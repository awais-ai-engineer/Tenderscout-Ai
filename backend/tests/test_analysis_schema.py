import hashlib
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.ai.schemas import TenderAnalysisOutput
from app.services.analysis import TRUNCATION_MARKER, check_evidence, prepare_text

FIXTURES = Path(__file__).parent / "fixtures"


class AnalysisSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads((FIXTURES / "analysis_response.json").read_text())
        self.source = (FIXTURES / "analysis_source.txt").read_text()

    def test_valid_schema_and_all_evidence(self) -> None:
        output = TenderAnalysisOutput.model_validate(self.payload)
        check_evidence(output, prepare_text(self.source, 60000))
        self.assertEqual(len(output.evidence_snippets()), 10)
        self.assertEqual(
            output.important_dates[0].date, "30 October 2026 at 12:00 UK time"
        )

    def test_empty_categories_and_absent_summary_are_valid(self) -> None:
        payload = {
            key: []
            for key in self.payload
            if key not in {"summary", "summary_evidence"}
        }
        output = TenderAnalysisOutput.model_validate(payload)
        self.assertIsNone(output.summary)
        self.assertEqual(output.evidence_snippets(), [])

    def test_extra_root_and_nested_fields_rejected(self) -> None:
        for value in (
            self.payload | {"score": 90},
            self.payload
            | {
                "eligibility_requirements": [
                    {"value": "Claim", "evidence": "Quote", "unknown": True}
                ]
            },
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                TenderAnalysisOutput.model_validate(value)

    def test_malformed_criteria_dates_and_contacts_rejected(self) -> None:
        for field, value in (
            ("evaluation_criteria", ["price"]),
            (
                "evaluation_criteria",
                [self.payload["evaluation_criteria"][0] | {"weighting": 60}],
            ),
            (
                "important_dates",
                [self.payload["important_dates"][0] | {"date": {"day": 30}}],
            ),
            (
                "contact_information",
                [self.payload["contact_information"][0] | {"phone": 1234}],
            ),
            (
                "contact_information",
                [
                    {
                        "name": None,
                        "organization": None,
                        "email": None,
                        "phone": None,
                        "role": None,
                        "evidence": "Quote",
                    }
                ],
            ),
            ("required_documents", "declaration"),
        ):
            with (
                self.subTest(field=field, value=value),
                self.assertRaises(ValidationError),
            ):
                TenderAnalysisOutput.model_validate(self.payload | {field: value})

    def test_evidence_is_required_nonempty_and_bounded(self) -> None:
        for item in (
            {"value": "Claim"},
            {"value": "Claim", "evidence": " "},
            {"value": "Claim", "evidence": "x" * 401},
            {"value": 1, "evidence": "Quote"},
        ):
            with self.subTest(item=item), self.assertRaises(ValidationError):
                TenderAnalysisOutput.model_validate(
                    self.payload | {"required_documents": [item]}
                )

    def test_summary_requires_supporting_evidence(self) -> None:
        for change in ({"summary_evidence": []}, {"summary": None}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                TenderAnalysisOutput.model_validate(self.payload | change)

    def test_missing_category_is_not_silently_treated_as_empty(self) -> None:
        del self.payload["financial_requirements"]
        with self.assertRaises(ValidationError):
            TenderAnalysisOutput.model_validate(self.payload)

    def test_fabricated_evidence_is_rejected(self) -> None:
        self.payload["required_documents"][0]["evidence"] = (
            "Submit a security clearance."
        )
        with self.assertRaisesRegex(ValueError, "Evidence not found"):
            check_evidence(
                TenderAnalysisOutput.model_validate(self.payload),
                prepare_text(self.source, 60000),
            )

    def test_evidence_matching_allows_only_whitespace_differences(self) -> None:
        self.payload["required_documents"][0]["evidence"] = (
            "Submit a\n signed  declaration."
        )
        check_evidence(
            TenderAnalysisOutput.model_validate(self.payload),
            prepare_text(self.source, 60000),
        )


class AnalysisInputTests(unittest.TestCase):
    def test_short_text_unchanged_and_hash_is_exact_utf8_text(self) -> None:
        text = "Price: £100.\n\nNext paragraph."
        prepared = prepare_text(text, 1000)
        self.assertEqual(prepared.text, text)
        self.assertEqual(
            prepared.input_hash, hashlib.sha256(text.encode("utf-8")).hexdigest()
        )
        self.assertFalse(prepared.truncated)
        self.assertNotIn(text, repr(prepared))

    def test_normalization_is_deterministic(self) -> None:
        first = prepare_text("  First\x00\r\n\r\nSecond\rThird  ", 1000)
        second = prepare_text("First\n\nSecond\nThird", 1000)
        self.assertEqual(first, second)

    def test_head_and_tail_truncation_includes_marker_within_limit(self) -> None:
        text = "BEGIN " + "x" * 2000 + " END"
        first = prepare_text(text, 200)
        self.assertEqual(first, prepare_text(text, 200))
        self.assertEqual(len(first.text), 200)
        self.assertTrue(first.truncated)
        self.assertTrue(first.text.startswith("BEGIN "))
        self.assertTrue(first.text.endswith(" END"))
        self.assertIn(TRUNCATION_MARKER, first.text)
        self.assertEqual(
            first.input_hash, hashlib.sha256(first.text.encode()).hexdigest()
        )

    def test_different_prepared_text_changes_hash(self) -> None:
        self.assertNotEqual(
            prepare_text("one", 128).input_hash, prepare_text("two", 128).input_hash
        )

    def test_truncation_boundary_and_minimum_limit(self) -> None:
        self.assertFalse(prepare_text("x" * 128, 128).truncated)
        self.assertTrue(prepare_text("x" * 129, 128).truncated)
        with self.assertRaises(ValueError):
            prepare_text("text", 127)

    def test_removed_text_and_marker_cannot_be_used_as_evidence(self) -> None:
        payload = json.loads((FIXTURES / "analysis_response.json").read_text())
        payload = {
            key: [] for key in payload if key not in {"summary", "summary_evidence"}
        }
        prepared = prepare_text(
            "start " + "x" * 500 + "OMITTED EVIDENCE" + "y" * 500 + " end", 128
        )
        for evidence in ("OMITTED EVIDENCE", "[TRUNCATED BY TENDERSCOUT]", "x y"):
            payload["required_documents"] = [{"value": "Claim", "evidence": evidence}]
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                check_evidence(TenderAnalysisOutput.model_validate(payload), prepared)
