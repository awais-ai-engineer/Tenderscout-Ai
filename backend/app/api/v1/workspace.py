from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.exceptions import RequestValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.product_support import Cursor, Database, Limit
from app.models import (
    Alert,
    CompanyProfile,
    DocumentVersion,
    NotificationPreference,
    SavedTender,
    Source,
    Tender,
    TenderAnalysis,
    TenderDocument,
    TenderMatch,
    TenderRevision,
)
from app.schemas import product as s
from app.services import queries

router = APIRouter()


@router.get("/saved", response_model=s.Page[s.SavedTenderItem], tags=["Saved Tenders"])
def saved_list(
    company_id: s.ID, db: Database, cursor: Cursor = None, limit: Limit = 20
):
    queries.require(db, CompanyProfile, company_id, "company")
    with Session(db) as session:
        rows = session.execute(
            select(SavedTender, Tender, Source)
            .join(Tender, Tender.id == SavedTender.tender_id)
            .join(Source, Source.id == Tender.source_id)
            .where(
                SavedTender.company_id == company_id,
                *([SavedTender.id < cursor] if cursor else []),
            )
            .order_by(SavedTender.id.desc())
            .limit(limit + 1)
        ).all()
        items = []
        for saved, tender, source in rows[:limit]:
            summary = dict(
                session.execute(queries.tender_query().where(Tender.id == tender.id))
                .mappings()
                .one()
            )
            changed = (
                session.scalar(
                    select(func.count(TenderRevision.id)).where(
                        TenderRevision.tender_id == tender.id,
                        TenderRevision.observed_at > saved.created_at,
                    )
                )
                > 0
            )
            items.append(
                {
                    "id": saved.id,
                    "company_id": company_id,
                    "tender": summary,
                    "saved_at": saved.created_at,
                    "updated_since_saved": changed,
                }
            )
        return {
            "items": items,
            "next_cursor": rows[limit - 1][0].id if len(rows) > limit else None,
        }


@router.post(
    "/saved/{tender_id}", response_model=s.SavedTenderResult, tags=["Saved Tenders"]
)
def save_tender(tender_id: s.ID, company_id: s.ID, db: Database):
    queries.require(db, CompanyProfile, company_id, "company")
    queries.require(db, Tender, tender_id, "tender")
    with Session(db) as session, session.begin():
        row = session.scalar(
            select(SavedTender).where(
                SavedTender.company_id == company_id, SavedTender.tender_id == tender_id
            )
        )
        if row is None:
            row = SavedTender(company_id=company_id, tender_id=tender_id)
            try:
                with session.begin_nested():
                    session.add(row)
                    session.flush()
            except IntegrityError:
                row = session.scalar(
                    select(SavedTender).where(
                        SavedTender.company_id == company_id,
                        SavedTender.tender_id == tender_id,
                    )
                )
        return {"saved": True, "id": row.id}


@router.delete(
    "/saved/{tender_id}", response_model=s.SavedTenderResult, tags=["Saved Tenders"]
)
def unsave_tender(tender_id: s.ID, company_id: s.ID, db: Database):
    queries.require(db, CompanyProfile, company_id, "company")
    with Session(db) as session, session.begin():
        row = session.scalar(
            select(SavedTender).where(
                SavedTender.company_id == company_id, SavedTender.tender_id == tender_id
            )
        )
        if row:
            session.delete(row)
        return {"saved": False}


@router.get(
    "/notification-preferences",
    response_model=s.NotificationPreferenceView,
    tags=["Alerts"],
)
def get_preferences(company_id: s.ID, db: Database):
    queries.require(db, CompanyProfile, company_id, "company")
    with Session(db) as session:
        row = session.get(NotificationPreference, company_id)
        return {"company_id": company_id} | (
            s.NotificationPreferenceInput().model_dump()
            if row is None
            else {
                name: getattr(row, name)
                for name in s.NotificationPreferenceInput.model_fields
            }
            | {"created_at": row.created_at, "updated_at": row.updated_at}
        )


@router.put(
    "/notification-preferences",
    response_model=s.NotificationPreferenceView,
    tags=["Alerts"],
)
def put_preferences(
    company_id: s.ID, body: s.NotificationPreferenceInput, db: Database
):
    queries.require(db, CompanyProfile, company_id, "company")
    if body.email_enabled and body.notification_email is None:
        raise RequestValidationError([])
    with Session(db) as session, session.begin():
        row = session.get(NotificationPreference, company_id)
        if row is None:
            row = NotificationPreference(company_id=company_id)
            session.add(row)
        for name, value in body.model_dump().items():
            setattr(row, name, value)
        session.flush()
        session.refresh(row)
        return {
            "company_id": company_id,
            **{
                name: getattr(row, name)
                for name in s.NotificationPreferenceInput.model_fields
            },
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }


@router.get("/alerts", response_model=s.Page[s.AlertItem], tags=["Alerts"])
def alert_list(
    company_id: s.ID,
    db: Database,
    unread_only: bool = False,
    cursor: Cursor = None,
    limit: Limit = 20,
):
    queries.require(db, CompanyProfile, company_id, "company")
    with Session(db) as session:
        q = (
            select(Alert, CompanyProfile.name, Tender.title)
            .join(CompanyProfile)
            .join(Tender)
            .where(Alert.company_id == company_id)
        )
        if unread_only:
            q = q.where(Alert.read_at.is_(None))
        if cursor:
            q = q.where(Alert.id < cursor)
        rows = session.execute(q.order_by(Alert.id.desc()).limit(limit + 1)).all()
        items = [
            {
                "id": a.id,
                "company_id": a.company_id,
                "company_name": company,
                "tender_id": a.tender_id,
                "tender_title": tender,
                "type": a.type,
                "title": a.title,
                "message": a.message,
                "created_at": a.created_at,
                "read_at": a.read_at,
            }
            for a, company, tender in rows[:limit]
        ]
        return {
            "items": items,
            "next_cursor": rows[limit - 1][0].id if len(rows) > limit else None,
        }


@router.patch("/alerts/{alert_id}/read", response_model=s.AlertItem, tags=["Alerts"])
def read_alert(alert_id: s.ID, company_id: s.ID, db: Database):
    with Session(db) as session, session.begin():
        row = session.scalar(
            select(Alert).where(Alert.id == alert_id, Alert.company_id == company_id)
        )
        if row is None:
            raise HTTPException(404)
        if row.read_at is None:
            row.read_at = datetime.now(UTC)
        company = session.get(CompanyProfile, row.company_id)
        tender = session.get(Tender, row.tender_id)
        return {
            "id": row.id,
            "company_id": row.company_id,
            "company_name": company.name,
            "tender_id": row.tender_id,
            "tender_title": tender.title,
            "type": row.type,
            "title": row.title,
            "message": row.message,
            "created_at": row.created_at,
            "read_at": row.read_at,
        }


@router.get("/matches", response_model=s.Page[s.MatchOpportunity], tags=["Matching"])
def opportunity_matches(
    company_id: s.ID, db: Database, cursor: Cursor = None, limit: Limit = 20
):
    queries.require(db, CompanyProfile, company_id, "company")
    with Session(db) as session:
        q = (
            select(TenderMatch, Tender, Source.slug)
            .join(TenderAnalysis, TenderAnalysis.id == TenderMatch.tender_analysis_id)
            .join(
                DocumentVersion,
                DocumentVersion.id == TenderAnalysis.document_version_id,
            )
            .join(TenderDocument, TenderDocument.id == DocumentVersion.document_id)
            .join(Tender, Tender.id == TenderDocument.tender_id)
            .join(Source, Source.id == Tender.source_id)
            .where(TenderMatch.company_id == company_id)
        )
        offset = cursor or 0
        rows = session.execute(
            q.order_by(TenderMatch.score.desc().nullslast(), TenderMatch.id.desc())
            .offset(offset)
            .limit(limit + 1)
        ).all()

        def reasons(values):
            return [
                str(value.get("reason") or value.get("requirement"))
                for value in values[:5]
            ]

        items = [
            {
                "match_id": m.id,
                "company_id": m.company_id,
                "analysis_id": m.tender_analysis_id,
                "eligibility_status": m.eligibility_status,
                "score": m.score,
                "coverage_ratio": m.coverage_ratio,
                "created_at": m.created_at,
                "tender_id": t.id,
                "tender_title": t.title,
                "organization": t.organization,
                "deadline": t.deadline,
                "source": source,
                "matched_reasons": reasons(
                    m.capability_matches
                    + m.certification_matches
                    + m.experience_matches
                    + m.matched_requirements
                ),
                "unknown_reasons": reasons(m.unknown_requirements),
            }
            for m, t, source in rows[:limit]
        ]
        return {
            "items": items,
            "next_cursor": offset + limit if len(rows) > limit else None,
        }
