from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    CompanyCapability,
    CompanyCertification,
    CompanyExperience,
    CompanyProfile,
    NotificationPreference,
)
from app.schemas.company import (
    CapabilityInput,
    CertificationInput,
    CompanyInput,
    ExperienceInput,
)

CHILDREN = {"capabilities", "certifications", "experience"}


def create_company(engine: Engine, profile: CompanyInput) -> int:
    company = CompanyProfile(**profile.model_dump(exclude=CHILDREN))
    company.capabilities = [
        CompanyCapability(**item.model_dump(), name_key=item.name.casefold())
        for item in profile.capabilities
    ]
    company.certifications = [
        CompanyCertification(**item.model_dump()) for item in profile.certifications
    ]
    company.experience = [
        CompanyExperience(**item.model_dump()) for item in profile.experience
    ]
    with Session(engine) as session, session.begin():
        session.add(company)
        session.flush()
        session.add(NotificationPreference(company_id=company.id))
        return company.id


def load_company(session: Session, company_id: int) -> CompanyInput:
    company = session.scalar(
        select(CompanyProfile)
        .where(CompanyProfile.id == company_id)
        .options(
            selectinload(CompanyProfile.capabilities),
            selectinload(CompanyProfile.certifications),
            selectinload(CompanyProfile.experience),
        )
    )
    if company is None:
        raise ValueError("Company does not exist")
    data = {
        field: getattr(company, field)
        for field in CompanyInput.model_fields
        if field not in CHILDREN
    }
    for field, schema in (
        ("capabilities", CapabilityInput),
        ("certifications", CertificationInput),
        ("experience", ExperienceInput),
    ):
        data[field] = [
            schema(**{name: getattr(item, name) for name in schema.model_fields})
            for item in getattr(company, field)
        ]
    return CompanyInput(**data)


def show_company(engine: Engine, company_id: int) -> CompanyInput:
    with Session(engine) as session:
        return load_company(session, company_id)
