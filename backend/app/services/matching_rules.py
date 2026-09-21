import re
from datetime import date
from decimal import Decimal

from app.ai.schemas import EvidenceItem
from app.schemas.company import CompanyInput

MIN_TOKEN_OVERLAP = Decimal("0.6")
STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "for",
        "in",
        "to",
        "and",
        "with",
        "services",
        "service",
        "experience",
        "previous",
        "relevant",
    ]
)
ISO = r"iso[ -]?(\d{4,5})(?::\d{4})?"
SUBJECT = (
    r"(?:(?:the )?(?:supplier|suppliers|bidder|bidders) "
    r"(?:must|shall) (?:have |hold )?)?"
)
MONEY = r"(?P<amount>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)"
TURNOVER = re.compile(
    r"(?:minimum annual turnover of |annual turnover (?:must be )?(?:of )?at least )"
    r"(?P<currency>£|GBP|USD|EUR)\s*" + MONEY,
    re.IGNORECASE,
)


def normalized(value: str) -> str:
    return " ".join(value.casefold().split()).rstrip(".")


def result(
    item: EvidenceItem,
    status: str = "unknown",
    fact: object = None,
    reason: str = "No safe deterministic comparison is available.",
    *,
    hard: bool = True,
    category: str = "eligibility",
) -> dict:
    return {
        "requirement": item.value,
        "status": status,
        "company_fact": fact,
        "reason": reason,
        "tender_evidence": item.evidence,
        "hard_requirement": hard,
        "category": category,
    }


def certification(
    item: EvidenceItem, profile: CompanyInput, as_of: date
) -> dict | None:
    text = normalized(item.evidence)
    match = re.fullmatch(
        r"(?:(?:the )?(?:supplier|suppliers|bidder|bidders) (?:must|shall) hold |"
        r"must hold |required certification: )(?P<valid>valid |current )?"
        + ISO
        + r"(?: certification)?",
        text,
    )
    if not match:
        return None
    family = match[2]
    certificates = [
        cert
        for cert in profile.certifications
        if (found := re.fullmatch(ISO, normalized(cert.name))) and found[1] == family
    ]
    facts = [cert.model_dump(mode="json") for cert in certificates]
    if not certificates:
        return result(
            item,
            "unmatched" if profile.certifications_complete else "unknown",
            {
                "certifications_complete": profile.certifications_complete,
                "certification_names": [cert.name for cert in profile.certifications],
            },
            "Required family is absent from the asserted complete list."
            if profile.certifications_complete
            else "Certification list is incomplete.",
            category="certification",
        )
    if not match["valid"]:
        return result(
            item,
            "matched",
            facts,
            "Company asserts this certification family; validity is not established.",
            category="certification",
        )
    if any(
        cert.valid_from
        and cert.valid_until
        and cert.valid_from <= as_of <= cert.valid_until
        for cert in certificates
    ):
        return result(
            item,
            "matched",
            facts,
            f"Asserted validity dates cover analysis date {as_of}; "
            "no external verification.",
            category="certification",
        )
    invalid = all(
        (cert.valid_from and cert.valid_from > as_of)
        or (cert.valid_until and cert.valid_until < as_of)
        for cert in certificates
    )
    return result(
        item,
        "unmatched" if invalid and profile.certifications_complete else "unknown",
        facts,
        f"Validity on analysis date {as_of} is unmet or not established; "
        "both dates are required to establish validity.",
        category="certification",
    )


def country_key(value: str) -> str:
    text = normalized(value)
    return {"uk": "united kingdom", "gb": "united kingdom", "pk": "pakistan"}.get(
        text, text
    )


def hard_comparison(item: EvidenceItem, profile: CompanyInput, as_of: date) -> dict:
    cert = certification(item, profile, as_of)
    if cert is not None:
        return cert
    text = normalized(item.evidence)
    years = re.fullmatch(
        SUBJECT + r"(?:at least |minimum )(\d{1,3}) years(?: of)? "
        r"(?:experience|in business)",
        text,
    )
    if years:
        actual = profile.years_in_business
        return result(
            item,
            "unknown"
            if actual is None
            else "matched"
            if actual >= int(years[1])
            else "unmatched",
            {"years_in_business": actual},
            f"Compare asserted years in business with minimum {years[1]}; "
            "does not establish specialist project experience.",
        )
    country = re.fullmatch(
        r"(?:the )?supplier(?:s)? (?:must|shall) be established in "
        r"(?:the )?(uk|united kingdom|pakistan|gb)(?: only)?",
        text,
    )
    if country:
        actual = profile.country
        known = actual is not None and country_key(actual) in {
            "united kingdom",
            "pakistan",
        }
        return result(
            item,
            "unknown"
            if not known
            else "matched"
            if country_key(actual) == country_key(country[1])
            else "unmatched",
            {"country": actual},
            "Compare recognized UK/Pakistan company country with supplier rule; "
            "other names need review. Delivery location is not used.",
        )
    financial = TURNOVER.fullmatch(item.evidence.strip().rstrip("."))
    if financial:
        currency = financial["currency"].upper().replace("£", "GBP")
        minimum = Decimal(financial["amount"].replace(",", ""))
        actual = profile.annual_revenue
        comparable = actual is not None and profile.currency == currency
        return result(
            item,
            "unknown"
            if not comparable
            else "matched"
            if actual >= minimum
            else "unmatched",
            {
                "annual_revenue": str(actual) if actual is not None else None,
                "currency": profile.currency,
            },
            f"Minimum annual turnover {minimum} {currency}; compare only known, "
            "same-currency annual revenue. No currency conversion.",
            category="financial",
        )
    return result(item)


def tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z]+", value.casefold())) - STOP_WORDS


def alignment(item: EvidenceItem, profile: CompanyInput) -> dict:
    experience = "experience" in tokens_raw(item.evidence)
    category = "experience" if experience else "capability"
    records = profile.experience if experience else profile.capabilities
    complete = (
        profile.experience_complete if experience else profile.capabilities_complete
    )
    # Lexical overlap cannot establish numeric, conditional or negative obligations.
    unsafe = re.search(
        r"\d|\b(?:must|shall|required|mandatory|no|not|without|unless|or|if|"
        r"except|only|minimum|least|maximum)\b",
        item.evidence,
        re.IGNORECASE,
    )
    if unsafe:
        return result(
            item,
            reason="This constraint requires review beyond lexical alignment.",
            hard=True,
            category=category,
        )
    required = tokens(item.evidence)
    if len(required) < 2:
        return result(
            item,
            reason="Too few specific tokens for lexical comparison.",
            hard=False,
            category=category,
        )
    best, best_overlap = None, Decimal(0)
    ambiguous = False
    for record in records:
        fields = (
            ("title", "description", "country", "client")
            if experience
            else ("name", "description")
        )
        candidate = " ".join(getattr(record, field) or "" for field in fields)
        if re.search(r"\b(?:no|not|without|never|lack|lacks)\b", candidate, re.I):
            ambiguous = True
            continue
        overlap = Decimal(len(required & tokens(candidate))) / len(required)
        if overlap > best_overlap:
            best, best_overlap = record, overlap
    matched = best_overlap >= MIN_TOKEN_OVERLAP
    return result(
        item,
        "matched"
        if matched
        else "unmatched"
        if complete and not ambiguous
        else "unknown",
        best.model_dump(mode="json")
        if best is not None
        else {"list_complete": complete},
        f"Lexical {category} alignment: {best_overlap:.3f} of requirement tokens; "
        f"threshold {MIN_TOKEN_OVERLAP}. "
        + (
            "Alignment only; quality, scope and success are not established."
            if matched
            else "No alignment found; ambiguous facts need review and a gap "
            "requires an asserted complete list."
        ),
        hard=False,
        category=category,
    )


def tokens_raw(value: str) -> set[str]:
    return set(re.findall(r"[a-z]+", value.casefold()))
