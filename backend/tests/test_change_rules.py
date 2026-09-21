import unittest
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

from change_fixtures import contact, item, output

from app.services.change_rules import (
    BUSINESS_FIELDS,
    METADATA_PREVIEW_CHARS,
    analysis_diff,
    lexical_tokens,
    metadata_diff,
    snapshot_hash,
)


class MetadataRuleTests(unittest.TestCase):
    def state(self, **values):
        return (
            dict.fromkeys(BUSINESS_FIELDS)
            | {"title": "Synthetic", "source_url": "https://example.test"}
            | values
        )

    def test_canonical_hash_ignores_bookkeeping_and_normalizes_offsets(self):
        first = self.state(deadline=datetime(2026, 10, 10, 12, tzinfo=UTC))
        second = self.state(
            deadline=datetime(2026, 10, 10, 17, tzinfo=timezone(timedelta(hours=5)))
        )
        self.assertEqual(
            snapshot_hash(first),
            snapshot_hash(second | {"last_seen_at": "ignored", "id": 42}),
        )
        self.assertNotEqual(
            snapshot_hash(first),
            snapshot_hash(first | {"source_content_hash": "b" * 64}),
        )
        self.assertEqual(len(snapshot_hash(first)), 64)
        self.assertEqual(metadata_diff(first, second), [])

    def test_metadata_add_remove_modify_and_bounded_description(self):
        old = self.state(category="Services", description="A" * 5000)
        new = self.state(
            title="Changed",
            category=None,
            organization="Authority A",
            description="B" * 6000,
        )
        changes = {change["field"]: change for change in metadata_diff(old, new)}
        self.assertEqual(changes["title"]["change_type"], "modified")
        self.assertEqual(changes["organization"]["change_type"], "added")
        self.assertEqual(changes["category"]["change_type"], "removed")
        self.assertEqual(
            len(changes["description"]["old_preview"]), METADATA_PREVIEW_CHARS
        )
        self.assertNotIn("old", changes["description"])
        self.assertNotEqual(
            changes["description"]["old_hash"], changes["description"]["new_hash"]
        )

    def test_deadline_json_is_canonical_utc(self):
        changes = metadata_diff(
            self.state(deadline=datetime(2026, 10, 10, tzinfo=UTC)),
            self.state(deadline=datetime(2026, 10, 17, tzinfo=UTC)),
        )
        self.assertEqual(changes[0]["old"], "2026-10-10T00:00:00.000000Z")
        self.assertEqual(changes[0]["new"], "2026-10-17T00:00:00.000000Z")


class AnalysisRuleTests(unittest.TestCase):
    def test_added_and_removed_requirements_and_no_cross_category_pairing(self):
        old = output(eligibility_requirements=[item("ISO 27001 certification")])
        new = output(
            eligibility_requirements=[item("Public liability insurance")],
            required_documents=[item("Signed declaration")],
            risks_or_ambiguities=[item("Scope remains uncertain")],
        )
        changes = analysis_diff(old, new)
        self.assertEqual(
            [change["change_type"] for change in changes],
            ["removed", "added", "added", "added"],
        )
        shifted = analysis_diff(
            old, output(required_documents=old.eligibility_requirements)
        )
        self.assertEqual(
            [change["change_type"] for change in shifted], ["removed", "added"]
        )

    def test_financial_threshold_is_reviewable_lexical_modified_candidate(self):
        old = item(
            "Minimum annual turnover £2,000,000",
            "minimum annual turnover of £2,000,000",
        )
        new = item(
            "Minimum annual turnover £3,000,000",
            "minimum annual turnover of £3,000,000",
        )
        before, after = (
            output(financial_requirements=[old]),
            output(financial_requirements=[new]),
        )
        changes = analysis_diff(before, after)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["change_type"], "modified")
        self.assertEqual(changes[0]["match_basis"], "lexical_similarity")
        self.assertTrue(changes[0]["requires_review"])
        self.assertEqual(changes[0]["old"], old)
        self.assertEqual(changes[0]["new"], new)
        a, b = lexical_tokens(old["value"]), lexical_tokens(new["value"])
        self.assertEqual(Decimal(len(a & b)) / len(a | b), Decimal("0.75"))

    def test_numbers_currencies_and_negation_survive_tokenization(self):
        tokens = lexical_tokens("Supplier must not exceed £2,000,000 or USD 3.50")
        for token in ("not", "£", "2,000,000", "usd", "3.50"):
            self.assertIn(token, tokens)
        self.assertEqual(lexical_tokens("ISO 27001"), set())

    def test_technical_rewrite_and_deterministic_tie_break(self):
        prefix = (
            "Supplier must provide fully managed secure cloud hosting services "
            "including monitoring support and "
        )
        old = [
            item(prefix + "daily encrypted backups", "Old first"),
            item(prefix + "daily encrypted backups", "Old second"),
        ]
        new = [
            item(prefix + "weekly encrypted backups", "New first"),
            item(prefix + "weekly encrypted backups", "New second"),
        ]
        before, after = (
            output(technical_requirements=old),
            output(technical_requirements=new),
        )
        changes = analysis_diff(before, after)
        self.assertEqual(changes, analysis_diff(before, after))
        self.assertEqual(len(changes), 2)
        self.assertEqual(
            [change["old"]["evidence"] for change in changes],
            ["Old first", "Old second"],
        )
        self.assertEqual(
            [change["new"]["evidence"] for change in changes],
            ["New first", "New second"],
        )
        self.assertTrue(all(change["requires_review"] for change in changes))

    def test_evidence_only_change_preserves_exact_quotes(self):
        old = output(
            eligibility_requirements=[item("ISO 27001 required", "Old  quotation.")]
        )
        new = output(
            eligibility_requirements=[item("iso   27001 REQUIRED", "New quotation.")]
        )
        change = analysis_diff(old, new)[0]
        self.assertEqual(change["change_type"], "modified")
        self.assertEqual(change["match_basis"], "normalized_key")
        self.assertEqual(change["old"]["evidence"], "Old  quotation.")
        self.assertEqual(change["new"]["evidence"], "New quotation.")

    def test_reordering_and_normalized_value_only_changes_are_unchanged(self):
        old = output(
            required_documents=[
                item("Document A", "First quote"),
                item("Document A", "Second quote"),
            ]
        )
        new = output(
            required_documents=[
                item("document  a", "Second quote"),
                item("Document A", "First quote"),
            ]
        )
        self.assertEqual(analysis_diff(old, new), [])

    def test_dates_keep_uncertain_source_wording_and_notes(self):
        old = {
            "label": "Submission deadline",
            "date": "around 10 October",
            "notes": None,
            "evidence": "Old deadline",
        }
        new = {
            "label": "submission DEADLINE",
            "date": "17 October (provisional)",
            "notes": "Check portal",
            "evidence": "New deadline",
        }
        change = analysis_diff(
            output(important_dates=[old]), output(important_dates=[new])
        )[0]
        self.assertEqual(change["change_type"], "modified")
        self.assertEqual(change["new"]["date"], "17 October (provisional)")
        self.assertEqual(change["old"]["evidence"], "Old deadline")

    def test_evaluation_weight_changes(self):
        old = {
            "criterion": "Quality",
            "weighting": "60%",
            "notes": None,
            "evidence": "Quality 60%",
        }
        new = old | {"weighting": "70%", "evidence": "Quality 70%"}
        change = analysis_diff(
            output(evaluation_criteria=[old]), output(evaluation_criteria=[new])
        )[0]
        self.assertEqual(change["old"]["weighting"], "60%")
        self.assertEqual(change["new"]["weighting"], "70%")
        self.assertFalse(change["requires_review"])

    def test_contact_email_change_uses_unique_name_and_organization(self):
        old = contact(
            name="Synthetic Person", organization="Authority", email="old@example.test"
        )
        new = old | {"email": "new@example.test", "evidence": "New contact"}
        changes = analysis_diff(
            output(contact_information=[old]), output(contact_information=[new])
        )
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["change_type"], "modified")
        self.assertEqual(changes[0]["new"]["email"], "new@example.test")

    def test_contacts_without_stable_identity_are_not_forced_pairs(self):
        old = contact(phone="123", role="Helpdesk")
        new = contact(phone="456", role="Helpdesk")
        changes = analysis_diff(
            output(contact_information=[old]), output(contact_information=[new])
        )
        self.assertEqual(
            [change["change_type"] for change in changes], ["removed", "added"]
        )
        self.assertEqual(
            analysis_diff(
                output(contact_information=[old]), output(contact_information=[old])
            ),
            [],
        )

    def test_summary_changes_and_evidence_only_changes(self):
        first = output(summary="Summary A", summary_evidence=["Source A"])
        for changed in (
            output(summary="Summary B", summary_evidence=["Source B"]),
            output(summary="Summary A", summary_evidence=["Source revised"]),
        ):
            change = analysis_diff(first, changed)[0]
            self.assertEqual(change["category"], "summary")
            self.assertTrue(change["requires_review"])
            self.assertEqual(change["old"]["summary_evidence"], ["Source A"])
