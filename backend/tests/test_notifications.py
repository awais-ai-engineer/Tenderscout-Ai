import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    Alert,
    Base,
    CompanyProfile,
    NotificationPreference,
    SavedTender,
    Source,
    Tender,
)
from app.services.notifications import (
    deliver_alert,
    generate_deadline_alerts,
    send_digests,
)


class FakeSender:
    def __init__(self, error=False):
        self.error = error
        self.messages = []

    def send(self, to, subject, text, html):
        if self.error:
            raise RuntimeError("provider secret")
        self.messages.append((to, subject, text, html))


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.now = datetime(2026, 1, 1, 12, tzinfo=UTC)
        with Session(self.engine) as session, session.begin():
            source = Source(
                name="Source", slug="source", base_url="https://example.test"
            )
            company = CompanyProfile(name="Company")
            session.add_all([source, company])
            session.flush()
            tender = Tender(
                source_id=source.id,
                title="Opportunity",
                source_url="https://example.test/1",
                deadline=self.now + timedelta(days=7),
                first_seen_at=self.now,
                last_seen_at=self.now,
            )
            session.add(tender)
            session.flush()
            session.add_all(
                [
                    SavedTender(company_id=company.id, tender_id=tender.id),
                    NotificationPreference(
                        company_id=company.id,
                        email_enabled=True,
                        notification_email="alerts@example.com",
                        delivery_mode="daily_digest",
                    ),
                ]
            )
            self.company_id, self.tender_id = company.id, tender.id
        self.settings = Settings(_env_file=None, postgres_password="test")

    def test_deadline_alert_is_deduplicated_and_digest_delivers_once(self):
        first = generate_deadline_alerts(self.engine, self.settings, self.now)
        second = generate_deadline_alerts(self.engine, self.settings, self.now)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        sender = FakeSender()
        self.assertEqual(send_digests(self.engine, self.settings, sender), 1)
        self.assertEqual(send_digests(self.engine, self.settings, sender), 0)
        self.assertEqual(len(sender.messages), 1)
        with Session(self.engine) as session:
            alert = session.scalar(select(Alert))
            self.assertEqual(alert.delivery_status, "sent")
            self.assertIsNotNone(alert.delivered_at)

    def test_digest_failure_keeps_durable_alert(self):
        generate_deadline_alerts(self.engine, self.settings, self.now)
        self.assertEqual(send_digests(self.engine, self.settings, FakeSender(True)), 0)
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(Alert)).delivery_status, "failed")

    def test_unconfigured_digest_remains_available_for_later_delivery(self):
        generate_deadline_alerts(self.engine, self.settings, self.now)
        self.assertEqual(send_digests(self.engine, self.settings), 0)
        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(select(Alert)).delivery_status, "unconfigured"
            )
        sender = FakeSender()
        self.assertEqual(send_digests(self.engine, self.settings, sender), 1)

    def test_instant_delivery_sanitizes_failure_and_does_not_repeat_success(self):
        with Session(self.engine) as session, session.begin():
            pref = session.get(NotificationPreference, self.company_id)
            pref.delivery_mode = "instant"
            alert = Alert(
                company_id=self.company_id,
                tender_id=self.tender_id,
                type="tender_updated",
                title="Tender updated",
                message="A real change occurred.",
                dedupe_key="instant-test",
                delivery_status="pending",
            )
            session.add(alert)
            session.flush()
            alert_id = alert.id
        with self.assertRaisesRegex(RuntimeError, "Email delivery failed"):
            deliver_alert(self.engine, alert_id, self.settings, FakeSender(True))
        with Session(self.engine) as session:
            self.assertEqual(session.get(Alert, alert_id).delivery_status, "failed")
        sender = FakeSender()
        self.assertTrue(deliver_alert(self.engine, alert_id, self.settings, sender))
        self.assertFalse(deliver_alert(self.engine, alert_id, self.settings, sender))
        self.assertEqual(len(sender.messages), 1)
