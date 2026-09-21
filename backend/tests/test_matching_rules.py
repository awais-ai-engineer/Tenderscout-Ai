import json
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app.ai.schemas import EvidenceItem, TenderAnalysisOutput
from app.schemas.company import CompanyInput
from app.services.matching import compute_match
from app.services.matching_rules import alignment, hard_comparison

AS_OF = date(2026, 1, 1)


def profile(**changes):
    return CompanyInput.model_validate_json(json.dumps({"name": "Synthetic"} | changes))


def item(text):
    return EvidenceItem(value=text, evidence=text)


def analysis(**fields):
    values = {
        field: []
        for field in TenderAnalysisOutput.model_fields
        if field not in {"summary", "summary_evidence"}
    }
    values.update(
        {
            field: [item(text).model_dump() for text in texts]
            for field, texts in fields.items()
        }
    )
    return TenderAnalysisOutput.model_validate(values)


class MatchingRuleTests(unittest.TestCase):
    def compare(self, text, **facts):
        return hard_comparison(item(text), profile(**facts), AS_OF)

    def test_certification_presence_absence_and_completeness(self):
        for facts, status in [
            ({"certifications": [{"name": "ISO-27001:2022"}]}, "matched"),
            ({}, "unknown"),
            ({"certifications_complete": True}, "unmatched"),
            ({"certifications": [{"name": "ISO 9001"}]}, "unknown"),
        ]:
            with self.subTest(facts=facts):
                compared = self.compare("Supplier must hold ISO 27001", **facts)
                self.assertEqual(compared["status"], status)
                self.assertEqual(
                    compared["tender_evidence"], "Supplier must hold ISO 27001"
                )

    def test_iso_family_normalization(self):
        for name in ("ISO 9001", "ISO-9001", "ISO9001:2015"):
            self.assertEqual(
                self.compare(
                    "Supplier must hold ISO 9001", certifications=[{"name": name}]
                )["status"],
                "matched",
            )
        self.assertEqual(
            self.compare(
                "Supplier must hold ISO 9001", certifications=[{"name": "ISO 90010"}]
            )["status"],
            "unknown",
        )

    def test_no_inferred_certification_validity(self):
        text = "Supplier must hold valid ISO 27001"
        for dates, status in [
            ({}, "unknown"),
            ({"valid_from": "2025-01-01"}, "unknown"),
            ({"valid_from": "2025-01-01", "valid_until": "2026-01-01"}, "matched"),
            ({"valid_until": "2025-01-01"}, "unmatched"),
            ({"valid_from": "2027-01-01"}, "unmatched"),
        ]:
            with self.subTest(dates=dates):
                self.assertEqual(
                    self.compare(
                        text,
                        certifications_complete=True,
                        certifications=[{"name": "ISO 27001"} | dates],
                    )["status"],
                    status,
                )
        self.assertEqual(
            self.compare(
                text,
                certifications=[{"name": "ISO 27001", "valid_until": "2025-01-01"}],
            )["status"],
            "unknown",
        )

    def test_years(self):
        for wording in (
            "at least 5 years experience",
            "minimum 5 years in business",
            "Supplier must have at least 5 years of experience.",
        ):
            for years, status in ((8, "matched"), (2, "unmatched"), (None, "unknown")):
                with self.subTest(wording=wording, years=years):
                    self.assertEqual(
                        self.compare(wording, years_in_business=years)["status"], status
                    )

    def test_supplier_country_and_delivery(self):
        for country, status in (
            ("UK", "matched"),
            ("United Kingdom", "matched"),
            ("Pakistan", "unmatched"),
            (None, "unknown"),
        ):
            self.assertEqual(
                self.compare("Supplier must be established in UK", country=country)[
                    "status"
                ],
                status,
            )
        result = compute_match(
            profile(country="Pakistan"),
            analysis(eligibility_requirements=["Delivery location is UK"]),
            AS_OF,
        )
        self.assertEqual(result["eligibility_status"], "uncertain")
        self.assertEqual(result["hard_blockers"], [])

    def test_financial_safe_same_currency_only(self):
        for text in (
            "minimum annual turnover of £2,000,000",
            "Annual turnover must be at least GBP 2,000,000.",
        ):
            for revenue, currency, status in (
                ("5000000", "GBP", "matched"),
                ("1000000", "GBP", "unmatched"),
                ("5000000", "USD", "unknown"),
                (None, "GBP", "unknown"),
                ("5000000", None, "unknown"),
            ):
                with self.subTest(text=text, revenue=revenue, currency=currency):
                    self.assertEqual(
                        self.compare(text, annual_revenue=revenue, currency=currency)[
                            "status"
                        ],
                        status,
                    )
        self.assertEqual(
            self.compare(
                "minimum annual turnover of GBP 2,000,000", financials_complete=True
            )["status"],
            "unknown",
        )

    def test_complex_or_negative_clauses_are_unknown(self):
        for text in (
            "Supplier must hold ISO 27001 or equivalent",
            "Supplier need not hold ISO 27001",
            "Supplier must not be established in UK",
            "minimum annual turnover of GBP 2,000,000 averaged over three years",
            "minimum annual turnover of $2,000,000",
            "minimum annual turnover of GBP 20,00,000",
            "at least 5 years experience in cloud migration",
            "at least 5 years experience or equivalent resources",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    self.compare(
                        text,
                        years_in_business=0,
                        certifications_complete=True,
                        annual_revenue="0",
                        currency="GBP",
                        country="Pakistan",
                    )["status"],
                    "unknown",
                )

    def test_capability_alignment_and_unknowns(self):
        company = profile(capabilities=[{"name": "Azure cloud migration"}])
        matched = alignment(item("cloud migration services"), company)
        self.assertEqual(matched["status"], "matched")
        self.assertIn("threshold 0.6", matched["reason"])
        self.assertEqual(matched["company_fact"]["name"], "Azure cloud migration")
        self.assertEqual(
            alignment(item("penetration testing"), company)["status"], "unknown"
        )
        self.assertEqual(
            alignment(
                item("penetration testing"),
                profile(
                    capabilities=[{"name": "software development"}],
                    capabilities_complete=True,
                ),
            )["status"],
            "unmatched",
        )

    def test_experience_alignment_is_not_project_success(self):
        company = profile(
            experience=[
                {
                    "title": "Government cloud migration",
                    "client": "Synthetic ministry",
                    "country": "UK",
                }
            ]
        )
        matched = alignment(item("government cloud migration experience"), company)
        self.assertEqual(matched["status"], "matched")
        self.assertEqual(matched["category"], "experience")
        self.assertIn("success", matched["reason"])
        self.assertEqual(
            alignment(item("bridge construction experience"), company)["status"],
            "unknown",
        )
        self.assertEqual(
            alignment(
                item("bridge construction experience"),
                profile(experience_complete=True),
            )["status"],
            "unmatched",
        )

    def test_numeric_technical_constraints_cannot_match_lexically(self):
        for text in (
            "laptops with 16 GB RAM",
            "cloud migration must be completed",
            "software without external dependencies",
        ):
            matched = alignment(item(text), profile(capabilities=[{"name": text}]))
            self.assertEqual(matched["status"], "unknown")
            self.assertTrue(matched["hard_requirement"])

    def test_document_inventory_is_unknown_even_with_certificate(self):
        compared = compute_match(
            profile(
                certifications=[{"name": "ISO 27001"}], certifications_complete=True
            ),
            analysis(
                required_documents=[
                    "ISO 27001 certificate",
                    "Audited accounts",
                    "Insurance certificate",
                ]
            ),
            AS_OF,
        )
        self.assertEqual(len(compared["unknown_requirements"]), 3)
        self.assertFalse(compared["hard_blockers"])

    def test_eligibility_statuses_and_empty_analysis(self):
        for company, expected in (
            (profile(years_in_business=8), "eligible"),
            (profile(years_in_business=2), "ineligible"),
            (profile(), "uncertain"),
        ):
            matched = compute_match(
                company,
                analysis(eligibility_requirements=["minimum 5 years in business"]),
                AS_OF,
            )
            self.assertEqual(matched["eligibility_status"], expected)
        self.assertEqual(
            compute_match(profile(), analysis(), AS_OF)["eligibility_status"],
            "uncertain",
        )

    def test_score_deterministic_offline_and_unknown_not_failure(self):
        data = analysis(
            technical_requirements=["cloud migration", "penetration testing"]
        )
        sparse = profile(capabilities=[{"name": "cloud migration"}])
        with patch(
            "socket.socket.connect", side_effect=AssertionError("Network forbidden")
        ):
            first = compute_match(sparse, data, AS_OF)
            self.assertEqual(first, compute_match(sparse, data, AS_OF))
        self.assertEqual(first["score"], 100)
        self.assertEqual(first["coverage_ratio"], Decimal("0.5"))
        complete = compute_match(
            profile(
                capabilities=[{"name": "cloud migration"}], capabilities_complete=True
            ),
            data,
            AS_OF,
        )
        self.assertEqual(complete["score"], 50)
        self.assertEqual(complete["coverage_ratio"], 1)

    def test_matched_greater_than_unmatched_same_coverage(self):
        data = analysis(technical_requirements=["cloud migration"])
        results = [
            compute_match(company, data, AS_OF)
            for company in (
                profile(capabilities=[{"name": "cloud migration"}]),
                profile(capabilities_complete=True),
                profile(),
            )
        ]
        self.assertGreater(results[0]["score"], results[1]["score"])
        self.assertEqual(results[0]["coverage_ratio"], results[1]["coverage_ratio"])
        self.assertIsNone(results[2]["score"])
        for compared in results:
            if compared["score"] is not None:
                self.assertTrue(0 <= compared["score"] <= 100)
            self.assertTrue(0 <= compared["coverage_ratio"] <= 1)

    def test_blocker_preserves_positive_alignment_and_evidence(self):
        data = analysis(
            eligibility_requirements=["minimum 5 years in business"],
            technical_requirements=["cloud migration"],
            risks_or_ambiguities=["Contract scope is unclear"],
        )
        compared = compute_match(
            profile(years_in_business=2, capabilities=[{"name": "cloud migration"}]),
            data,
            AS_OF,
        )
        self.assertEqual(compared["eligibility_status"], "ineligible")
        self.assertEqual(compared["score"], 100)
        self.assertEqual(len(compared["hard_blockers"]), 1)
        self.assertEqual(
            compared["risks"][0]["tender_evidence"], "Contract scope is unclear"
        )
        for key in ("matched_requirements", "unmatched_requirements", "hard_blockers"):
            for entry in compared[key]:
                self.assertIn(entry["tender_evidence"], data.evidence_snippets())
                self.assertTrue(entry["reason"])

    def test_unparsed_hard_requirement_prevents_eligible(self):
        compared = compute_match(
            profile(years_in_business=8),
            analysis(
                eligibility_requirements=[
                    "minimum 5 years in business",
                    "Security clearance required",
                ]
            ),
            AS_OF,
        )
        self.assertEqual(compared["eligibility_status"], "uncertain")

    def test_evidence_not_ai_paraphrase_controls_blocker(self):
        data = analysis(eligibility_requirements=["Delivery location is UK"])
        data.eligibility_requirements[0].value = "Supplier must be established in UK"
        self.assertFalse(
            compute_match(profile(country="Pakistan"), data, AS_OF)["hard_blockers"]
        )

    def test_unrecognized_country_does_not_create_blocker(self):
        self.assertEqual(
            self.compare(
                "Supplier must be established in UK", country="England (UK office)"
            )["status"],
            "unknown",
        )

    def test_negative_company_text_does_not_match_positive_requirement(self):
        compared = alignment(
            item("cloud migration"),
            profile(
                capabilities=[{"name": "No cloud migration"}],
                capabilities_complete=True,
            ),
        )
        self.assertEqual(compared["status"], "unknown")

    def test_mandatory_technical_requirement_prevents_false_eligibility(self):
        compared = compute_match(
            profile(years_in_business=8, capabilities=[{"name": "security clearance"}]),
            analysis(
                eligibility_requirements=["minimum 5 years in business"],
                technical_requirements=["security clearance required"],
            ),
            AS_OF,
        )
        self.assertEqual(compared["eligibility_status"], "uncertain")

    def test_country_and_complete_certificate_absence_create_blockers(self):
        compared = compute_match(
            profile(country="Pakistan", certifications_complete=True),
            analysis(
                eligibility_requirements=[
                    "Supplier must be established in UK",
                    "Supplier must hold ISO 27001",
                ]
            ),
            AS_OF,
        )
        self.assertEqual(compared["eligibility_status"], "ineligible")
        self.assertEqual(len(compared["hard_blockers"]), 2)
