import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal

from app.ai.schemas import TenderAnalysisOutput

CHANGESET_VERSION = "v1"
METADATA_PREVIEW_CHARS = 240
MODIFIED_PAIR_MIN_SIMILARITY = Decimal("0.75")
MIN_MEANINGFUL_TOKENS = 3
BUSINESS_FIELDS = (
    "external_id",
    "title",
    "organization",
    "description",
    "source_url",
    "category",
    "location",
    "published_at",
    "deadline",
    "source_content_hash",
)
VALUE_CATEGORIES = (
    "eligibility_requirements",
    "required_documents",
    "technical_requirements",
    "financial_requirements",
    "submission_instructions",
    "risks_or_ambiguities",
)


def utc_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def canonical_datetime(value: datetime) -> str:
    return utc_datetime(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_snapshot(values: dict) -> dict:
    return {
        name: canonical_datetime(values[name])
        if isinstance(values[name], datetime)
        else values[name]
        for name in BUSINESS_FIELDS
    }


def snapshot_hash(values: dict) -> str:
    serialized = json.dumps(
        canonical_snapshot(values),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def metadata_diff(old: dict, new: dict) -> list[dict]:
    old, new = canonical_snapshot(old), canonical_snapshot(new)
    changes = []
    for name in BUSINESS_FIELDS:
        before, after = old[name], new[name]
        if before == after:
            continue
        change = {
            "field": name,
            "change_type": "added"
            if before is None
            else "removed"
            if after is None
            else "modified",
        }
        if name == "description" or any(
            isinstance(value, str) and len(value) > METADATA_PREVIEW_CHARS
            for value in (before, after)
        ):
            for prefix, value in (("old", before), ("new", after)):
                change[prefix + "_hash"] = (
                    hashlib.sha256(value.encode("utf-8")).hexdigest()
                    if value is not None
                    else None
                )
                change[prefix + "_preview"] = (
                    value[:METADATA_PREVIEW_CHARS] if value is not None else None
                )
        else:
            change.update(old=before, new=after)
        changes.append(change)
    return changes


def normalized(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def lexical_tokens(value: str) -> set[str]:
    # Keep complete numbers, currency and negation; word pairs anchor short phrases.
    tokens = re.findall(r"\d+(?:[,.]\d+)*|[^\W\d_]+|[£€$%+-]", normalized(value))
    if len({token for token in tokens if token.isalpha()}) < MIN_MEANINGFUL_TOKENS:
        return set()
    return set(tokens) | {
        f"{left} {right}"
        for left, right in zip(tokens, tokens[1:])
        if left.isalpha() and right.isalpha()
    }


def change_record(
    category: str, old: dict | None, new: dict | None, basis: str, review: bool = False
) -> dict:
    return {
        "category": category,
        "change_type": "added"
        if old is None
        else "removed"
        if new is None
        else "modified",
        "old": old,
        "new": new,
        "match_basis": basis,
        "requires_review": review,
    }


def comparable_item(item: dict, key: str) -> dict:
    return item | {key: normalized(item[key])}


def keyed_pairs(
    old: list[dict],
    new: list[dict],
    key: str,
    remaining_old: set[int],
    remaining_new: set[int],
    *,
    unique_only: bool = False,
):
    keys = sorted({normalized(old[index].get(key)) for index in remaining_old} - {""})
    pairs = []
    for value in keys:
        left = [
            index
            for index in sorted(remaining_old)
            if normalized(old[index].get(key)) == value
        ]
        right = [
            index
            for index in sorted(remaining_new)
            if normalized(new[index].get(key)) == value
        ]
        ambiguous = len(left) > 1 or len(right) > 1
        # Pair identical payloads first so reordering repeated keys is not a change.
        for i in left[:]:
            j = next(
                (
                    j
                    for j in right
                    if comparable_item(old[i], key) == comparable_item(new[j], key)
                ),
                None,
            )
            if j is not None:
                pairs.append((i, j, False))
                left.remove(i)
                right.remove(j)
        if not unique_only or not ambiguous:
            pairs.extend((i, j, ambiguous) for i, j in zip(left, right))
    for i, j, _ in pairs:
        remaining_old.remove(i)
        remaining_new.remove(j)
    return pairs


def list_diff(
    category: str, old: list[dict], new: list[dict], key: str, *, lexical: bool = False
) -> list[dict]:
    remaining_old, remaining_new = set(range(len(old))), set(range(len(new)))
    changes = []
    for i, j, ambiguous in keyed_pairs(old, new, key, remaining_old, remaining_new):
        if comparable_item(old[i], key) != comparable_item(new[j], key):
            changes.append(
                change_record(category, old[i], new[j], "normalized_key", ambiguous)
            )
    if lexical:
        before = {i: lexical_tokens(old[i][key]) for i in remaining_old}
        after = {j: lexical_tokens(new[j][key]) for j in remaining_new}
        candidates = []
        for i, a in before.items():
            for j, b in after.items():
                if a and b:
                    similarity = Decimal(len(a & b)) / len(a | b)
                    if similarity >= MODIFIED_PAIR_MIN_SIMILARITY:
                        candidates.append((-similarity, i, j))
        for _, i, j in sorted(candidates):
            if i in remaining_old and j in remaining_new:
                changes.append(
                    change_record(category, old[i], new[j], "lexical_similarity", True)
                )
                remaining_old.remove(i)
                remaining_new.remove(j)
    changes.extend(
        change_record(category, old[i], None, "unpaired") for i in sorted(remaining_old)
    )
    changes.extend(
        change_record(category, None, new[j], "unpaired") for j in sorted(remaining_new)
    )
    return changes


def contact_diff(old: list[dict], new: list[dict]) -> list[dict]:
    remaining_old, remaining_new = set(range(len(old))), set(range(len(new)))
    changes = []
    for i in sorted(remaining_old):
        j = next((j for j in sorted(remaining_new) if old[i] == new[j]), None)
        if j is not None:
            remaining_old.remove(i)
            remaining_new.remove(j)
    for key in ("email", "identity"):

        def keyed(items):
            if key == "email":
                return items
            return [
                item
                | {
                    "identity": json.dumps(
                        [normalized(item["name"]), normalized(item["organization"])]
                    )
                    if item["name"] and item["organization"]
                    else ""
                }
                for item in items
            ]

        before, after = keyed(old), keyed(new)
        for i, j, _ in keyed_pairs(
            before, after, key, remaining_old, remaining_new, unique_only=True
        ):
            if old[i] != new[j]:
                changes.append(
                    change_record(
                        "contact_information", old[i], new[j], "normalized_key"
                    )
                )
    changes.extend(
        change_record("contact_information", old[i], None, "unpaired")
        for i in sorted(remaining_old)
    )
    changes.extend(
        change_record("contact_information", None, new[j], "unpaired")
        for j in sorted(remaining_new)
    )
    return changes


def analysis_diff(old: TenderAnalysisOutput, new: TenderAnalysisOutput) -> list[dict]:
    before, after = old.model_dump(), new.model_dump()
    changes = []
    if (
        normalized(old.summary) != normalized(new.summary)
        or old.summary_evidence != new.summary_evidence
    ):
        changes.append(
            change_record(
                "summary",
                {"summary": old.summary, "summary_evidence": old.summary_evidence},
                {"summary": new.summary, "summary_evidence": new.summary_evidence},
                "summary",
                True,
            )
        )
    for category in VALUE_CATEGORIES:
        changes.extend(
            list_diff(
                category, before[category], after[category], "value", lexical=True
            )
        )
    for category, key in (
        ("important_dates", "label"),
        ("evaluation_criteria", "criterion"),
    ):
        changes.extend(list_diff(category, before[category], after[category], key))
    changes.extend(
        contact_diff(before["contact_information"], after["contact_information"])
    )
    return changes


def category_counts(changes: list[dict]) -> dict[str, int]:
    return dict(sorted(Counter(change["category"] for change in changes).items()))
