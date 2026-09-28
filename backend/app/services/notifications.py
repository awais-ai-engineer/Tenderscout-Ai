import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from html import escape
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    Alert,
    DocumentVersion,
    NotificationPreference,
    SavedTender,
    Source,
    Tender,
    TenderAnalysis,
    TenderDocument,
    TenderMatch,
)


class EmailSender(Protocol):
    def send(self, to: str, subject: str, text: str, html: str) -> None: ...


class SmtpEmailSender:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, to: str, subject: str, text: str, html: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.smtp_from_email
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        with smtplib.SMTP(
            self.settings.smtp_host, self.settings.smtp_port, timeout=15
        ) as client:
            if self.settings.smtp_starttls:
                client.starttls()
            if self.settings.smtp_username:
                client.login(
                    self.settings.smtp_username,
                    self.settings.smtp_password.get_secret_value()
                    if self.settings.smtp_password
                    else "",
                )
            client.send_message(message)


def configured_sender(settings: Settings) -> EmailSender | None:
    if not settings.smtp_host or not settings.smtp_from_email:
        return None
    return SmtpEmailSender(settings)


def preference(session: Session, company_id: int) -> NotificationPreference | None:
    return session.get(NotificationPreference, company_id)


def create_match_alert(engine, match_id: int) -> tuple[int | None, bool]:
    with Session(engine) as session, session.begin():
        match = session.get(TenderMatch, match_id)
        if match is None:
            return None, False
        pref = session.get(NotificationPreference, match.company_id)
        if (
            pref is None
            or not pref.new_match_alerts
            or match.score is None
            or match.score < pref.minimum_match_score
            or match.eligibility_status == "ineligible"
        ):
            return None, False
        tender = session.scalar(
            select(Tender)
            .join(TenderDocument, TenderDocument.tender_id == Tender.id)
            .join(DocumentVersion, DocumentVersion.document_id == TenderDocument.id)
            .join(
                TenderAnalysis, TenderAnalysis.document_version_id == DocumentVersion.id
            )
            .where(TenderAnalysis.id == match.tender_analysis_id)
        )
        if tender is None:
            return None, False
        key = f"new_match:{match.company_id}:{tender.id}:{match.matcher_version}"
        existing = session.scalar(select(Alert).where(Alert.dedupe_key == key))
        if existing:
            return existing.id, False
        alert = Alert(
            company_id=match.company_id,
            tender_id=tender.id,
            match_id=match.id,
            type="new_match",
            title="New company match",
            message=f"{tender.title} has a company-fit score of {match.score}.",
            dedupe_key=key,
            delivery_status="pending" if pref.email_enabled else "unconfigured",
        )
        try:
            with session.begin_nested():
                session.add(alert)
                session.flush()
        except IntegrityError:
            existing = session.scalar(select(Alert).where(Alert.dedupe_key == key))
            return existing.id, False
        return alert.id, True


def create_update_alerts(
    engine, tender_id: int, revision_id: int, *, kind: str = "metadata"
) -> list[int]:
    created = []
    with Session(engine) as session, session.begin():
        tender = session.get(Tender, tender_id)
        if tender is None:
            return []
        company_ids = set(
            session.scalars(
                select(SavedTender.company_id).where(SavedTender.tender_id == tender_id)
            )
        )
        company_ids.update(
            session.scalars(
                select(TenderMatch.company_id)
                .join(TenderAnalysis)
                .join(DocumentVersion)
                .join(TenderDocument)
                .where(TenderDocument.tender_id == tender_id)
            )
        )
        for company_id in company_ids:
            pref = session.get(NotificationPreference, company_id)
            if not pref or not pref.tender_change_alerts:
                continue
            key = f"tender_updated:{company_id}:{tender_id}:{kind}:{revision_id}"
            if session.scalar(select(Alert.id).where(Alert.dedupe_key == key)):
                continue
            alert = Alert(
                company_id=company_id,
                tender_id=tender_id,
                type="tender_updated",
                title="Tender updated",
                message=f"{tender.title} has a recorded material change.",
                dedupe_key=key,
                delivery_status="pending" if pref.email_enabled else "unconfigured",
            )
            try:
                with session.begin_nested():
                    session.add(alert)
                    session.flush()
            except IntegrityError:
                continue
            created.append(alert.id)
    return created


def generate_deadline_alerts(
    engine, settings: Settings, now: datetime | None = None
) -> list[int]:
    now = now or datetime.now(UTC)
    created = []
    with Session(engine) as session, session.begin():
        for pref in session.scalars(
            select(NotificationPreference).where(
                NotificationPreference.deadline_reminders.is_(True)
            )
        ):
            tenders = list(
                session.scalars(
                    select(Tender).where(
                        Tender.deadline > now,
                        or_(
                            Tender.id.in_(
                                select(SavedTender.tender_id).where(
                                    SavedTender.company_id == pref.company_id
                                )
                            ),
                            Tender.id.in_(
                                select(TenderDocument.tender_id)
                                .join(DocumentVersion)
                                .join(TenderAnalysis)
                                .join(TenderMatch)
                                .where(TenderMatch.company_id == pref.company_id)
                            ),
                        ),
                    )
                )
            )
            for tender in tenders:
                remaining = tender.deadline.astimezone(UTC).date() - now.date()
                if remaining.days not in settings.deadline_reminder_days:
                    continue
                key = (
                    f"deadline_reminder:{pref.company_id}:{tender.id}:"
                    f"{tender.deadline.date()}:{remaining.days}"
                )
                if session.scalar(select(Alert.id).where(Alert.dedupe_key == key)):
                    continue
                alert = Alert(
                    company_id=pref.company_id,
                    tender_id=tender.id,
                    type="deadline_reminder",
                    title="Deadline approaching",
                    message=f"{tender.title} closes in {remaining.days} days.",
                    dedupe_key=key,
                    delivery_status="pending" if pref.email_enabled else "unconfigured",
                )
                try:
                    with session.begin_nested():
                        session.add(alert)
                        session.flush()
                except IntegrityError:
                    continue
                created.append(alert.id)
    return created


def deliver_alert(
    engine, alert_id: int, settings: Settings, sender: EmailSender | None = None
) -> bool:
    sender = sender or configured_sender(settings)
    with Session(engine) as session, session.begin():
        alert = session.scalar(
            select(Alert).where(Alert.id == alert_id).with_for_update()
        )
        if alert is None or alert.delivered_at is not None:
            return False
        pref = session.get(NotificationPreference, alert.company_id)
        if (
            not pref
            or not pref.email_enabled
            or not pref.notification_email
            or pref.delivery_mode != "instant"
            or sender is None
        ):
            if sender is None and pref and pref.email_enabled:
                alert.delivery_status = "unconfigured"
            return False
        tender = session.get(Tender, alert.tender_id)
        url = f"{settings.product_base_url.rstrip('/')}/tenders/{tender.id}"
        details = [alert.message]
        if alert.type == "new_match" and alert.match_id:
            match = session.get(TenderMatch, alert.match_id)
            source = session.get(Source, tender.source_id)
            deadline = (
                tender.deadline.isoformat() if tender.deadline else "Not provided"
            )
            details.extend(
                [
                    f"Organization: {tender.organization or 'Not provided'}",
                    f"Source: {source.name}",
                    f"Deadline: {deadline}",
                    f"Company fit: {match.score}/100",
                ]
            )
            reasons = (
                match.capability_matches
                + match.certification_matches
                + match.experience_matches
                + match.matched_requirements
            )
            details.extend(
                f"Why it matches: {reason.get('reason') or reason.get('requirement')}"
                for reason in reasons[:3]
            )
            details.extend(
                f"Needs review: {reason.get('reason') or reason.get('requirement')}"
                for reason in match.unknown_requirements[:2]
            )
        text = (
            f"{alert.title}\n\n" + "\n".join(details) + f"\n\nView opportunity: {url}"
        )
        to = pref.notification_email
        subject = (
            "New tender matching your company — TenderScout AI"
            if alert.type == "new_match"
            else f"{alert.title} — TenderScout AI"
        )
        html = (
            f"<h1>{escape(alert.title)}</h1>"
            + "".join(f"<p>{escape(line)}</p>" for line in details)
            + f'<p><a href="{url}">View opportunity</a></p>'
        )
        try:
            sender.send(to, subject, text, html)
        except Exception:
            if alert.delivered_at is None:
                alert.delivery_status = "failed"
            failed = True
        else:
            failed = False
            alert.delivery_status = "sent"
            alert.delivered_at = datetime.now(UTC)
    if failed:
        raise RuntimeError("Email delivery failed") from None
    return True


def send_digests(engine, settings: Settings, sender: EmailSender | None = None) -> int:
    sender = sender or configured_sender(settings)
    if sender is None:
        with Session(engine) as session, session.begin():
            for alert in session.scalars(
                select(Alert)
                .join(
                    NotificationPreference,
                    NotificationPreference.company_id == Alert.company_id,
                )
                .where(
                    NotificationPreference.email_enabled.is_(True),
                    NotificationPreference.delivery_mode == "daily_digest",
                    Alert.delivery_status.in_(("pending", "failed")),
                )
            ):
                alert.delivery_status = "unconfigured"
        return 0
    sent = 0
    with Session(engine) as session, session.begin():
        prefs = list(
            session.scalars(
                select(NotificationPreference)
                .where(
                    NotificationPreference.email_enabled.is_(True),
                    NotificationPreference.delivery_mode == "daily_digest",
                    NotificationPreference.notification_email.is_not(None),
                )
                .with_for_update()
            )
        )
        for pref in prefs:
            alerts = list(
                session.scalars(
                    select(Alert)
                    .where(
                        Alert.company_id == pref.company_id,
                        Alert.delivery_status.in_(
                            ("pending", "failed", "unconfigured")
                        ),
                    )
                    .order_by(Alert.created_at, Alert.id)
                )
            )
            if not alerts:
                continue
            lines = [
                f"- {a.title}: {a.message} "
                f"({settings.product_base_url.rstrip('/')}/tenders/{a.tender_id})"
                for a in alerts
            ]
            text = "TenderScout AI\nDaily Opportunity Brief\n\n" + "\n".join(lines)
            base_url = settings.product_base_url.rstrip("/")
            try:
                sender.send(
                    pref.notification_email,
                    "TenderScout AI — Daily Opportunity Brief",
                    text,
                    "<h1>Daily Opportunity Brief</h1><ul>"
                    + "".join(
                        f'<li><a href="{base_url}/tenders/{a.tender_id}">'
                        f"{escape(a.title)}: {escape(a.message)}</a></li>"
                        for a in alerts
                    )
                    + "</ul>",
                )
            except Exception:
                for alert in alerts:
                    alert.delivery_status = "failed"
                continue
            now = datetime.now(UTC)
            for alert in alerts:
                alert.delivery_status = "sent"
                alert.delivered_at = now
            sent += 1
    return sent
