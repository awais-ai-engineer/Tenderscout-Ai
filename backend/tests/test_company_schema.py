import json
import unittest
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from app.schemas.company import CompanyInput

FIXTURE = Path(__file__).parent / "fixtures" / "company_profile.json"


class CompanySchemaTests(unittest.TestCase):
    def test_valid_profile(self):
        profile = CompanyInput.model_validate_json(FIXTURE.read_bytes())
        self.assertEqual(profile.annual_revenue, Decimal("5000000.00"))
        self.assertEqual(len(profile.capabilities), 1)
        self.assertIsNone(profile.certifications[0].valid_until)

    def test_optional_values_and_completeness(self):
        profile = CompanyInput(name="Company")
        for field in (
            "country",
            "annual_revenue",
            "employee_count",
            "years_in_business",
        ):
            self.assertIsNone(getattr(profile, field))
        for field in ("capabilities", "certifications", "experience", "financials"):
            self.assertFalse(getattr(profile, field + "_complete"))

    def test_whitespace_and_duplicate_capabilities(self):
        profile = CompanyInput.model_validate_json(
            '{"name":"  Test  Company ",'
            '"capabilities":[{"name":" Cloud   migration "}]}'
        )
        self.assertEqual(profile.name, "Test Company")
        self.assertEqual(profile.capabilities[0].name, "Cloud migration")
        with self.assertRaises(ValidationError):
            CompanyInput.model_validate_json(
                json.dumps(
                    {
                        "name": "Test",
                        "capabilities": [
                            {"name": " Cloud migration"},
                            {"name": "CLOUD   MIGRATION"},
                        ],
                    }
                )
            )

    def test_invalid_inputs(self):
        cases = [
            {"employee_count": -1},
            {"annual_revenue": "-1"},
            {"years_in_business": -1},
            {"employee_count": True},
            {"employee_count": "8"},
            {"annual_revenue": "NaN"},
            {"annual_revenue": "1.001"},
            {"annual_revenue": "10000000000000000"},
            {"currency": "gbp"},
            {"currency": "POUNDS"},
            {"currency": "123"},
            {"website": "file:///secret"},
            {"website": "invalid"},
            {"website": "https://user:password@example.test"},
            {"capabilities_complete": "true"},
            {"extra": "private"},
            {"capabilities": [{"name": "Cloud", "extra": True}]},
            {"certifications": [{"name": "ISO 9001", "extra": True}]},
            {"experience": [{"title": "Project", "extra": True}]},
            {
                "certifications": [
                    {
                        "name": "ISO 9001",
                        "valid_from": "2026-01-02",
                        "valid_until": "2026-01-01",
                    }
                ]
            },
            {
                "experience": [
                    {
                        "title": "Project",
                        "started_at": "2026-01-02",
                        "completed_at": "2026-01-01",
                    }
                ]
            },
            {"experience": [{}]},
            {"name": ""},
            {"name": " "},
            {"name": "a" * 256},
            {"name": "private\x00value"},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValidationError):
                CompanyInput.model_validate_json(json.dumps({"name": "Test"} | case))

    def test_valid_dates_and_zero_are_not_replaced(self):
        profile = CompanyInput.model_validate_json(
            json.dumps(
                {
                    "name": "Test",
                    "years_in_business": 0,
                    "annual_revenue": "0",
                    "certifications": [
                        {"name": "ISO 9001", "valid_from": "2025-01-01"}
                    ],
                }
            )
        )
        self.assertEqual(profile.years_in_business, 0)
        self.assertEqual(profile.annual_revenue, 0)
        self.assertEqual(profile.certifications[0].valid_from.year, 2025)
