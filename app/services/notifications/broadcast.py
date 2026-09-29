"""Staff announcements: to a whole cohort, or to named accounts."""
from app.models import ACTOR_STUDENT, AuthAccount, Cohort, Enrollment
from app.services.errors import ServiceError
from app.services.params import get_by_id, parse_id

from .inbox import MAX_TITLE_LENGTH, notify


def _cohort_accounts(cohort_id) -> list:
    cohort = get_by_id(Cohort, cohort_id)
    if cohort is None:
        raise ServiceError(404, "cohort_not_found")
    student_ids = [
        e.student_id
        for e in Enrollment.query.filter_by(cohort_id=cohort.id, status="active").all()
    ]
    if not student_ids:
        return []
    return [
        a.id for a in AuthAccount.query.filter(
            AuthAccount.actor_type == ACTOR_STUDENT,
            AuthAccount.actor_id.in_(student_ids),
            AuthAccount.is_active.is_(True),
        ).all()
    ]


def _named_accounts(raw) -> list:
    if not isinstance(raw, list) or not raw:
        raise ServiceError(400, "invalid_account_ids")
    ids = {parse_id(v) for v in raw}
    if None in ids:
        raise ServiceError(400, "invalid_account_ids")
    found = {a.id for a in AuthAccount.query.filter(AuthAccount.id.in_(ids)).all()}
    missing = sorted(ids - found)
    if missing:
        raise ServiceError(400, "unknown_account_ids", account_ids=missing)
    return sorted(found)


def send_announcement(data) -> dict:
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ServiceError(400, "title_required")
    if len(title.strip()) > MAX_TITLE_LENGTH:
        raise ServiceError(400, "title_too_long", max_length=MAX_TITLE_LENGTH)
    body = data.get("body")
    if body is not None and not isinstance(body, str):
        raise ServiceError(400, "invalid_body")
    payload = data.get("data")
    if payload is not None and not isinstance(payload, dict):
        raise ServiceError(400, "invalid_data")
    if data.get("cohort_id") is not None:
        accounts = _cohort_accounts(data["cohort_id"])
        payload = {"cohort_id": parse_id(data["cohort_id"]), **(payload or {})}
    elif data.get("account_ids") is not None:
        accounts = _named_accounts(data["account_ids"])
    else:
        raise ServiceError(400, "recipients_required")
    sent = notify(accounts, kind="announcement", title=title.strip(), body=body, data=payload)
    return {"sent": sent}
