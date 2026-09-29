"""QR check-in and the teacher's attendance sheet.

The teacher's screen shows a QR that rotates: each ``issue_qr`` call mints a new
random token, stores only its SHA-256 (as refresh tokens are) and so voids the
previous one. A student scanning it is ``present``, or ``late`` more than
``LATE_AFTER_MINUTES`` after the session's local start time.
"""
import hashlib
import secrets

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import ATTENDANCE_STATUSES, Attendance, ClassSession, Enrollment
from app.services.errors import ServiceError
from app.timeutil import iso

from . import clock
from .sessions import roster, session_dict, session_for_teacher, student_name

QR_TTL_MINUTES = 5
LATE_AFTER_MINUTES = 15


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------- teacher: QR
def issue_qr(account, session_id) -> dict:
    session = session_for_teacher(account, session_id)
    if session.session_date != clock.local_today():
        raise ServiceError(409, "session_not_today")
    raw = secrets.token_urlsafe(24)
    session.qr_token_hash = _hash(raw)
    session.qr_expires_at = clock.plus_minutes(clock.now(), QR_TTL_MINUTES)
    db.session.commit()
    return {"token": raw, "expires_at": iso(session.qr_expires_at)}


# ----------------------------------------------------------------- student: scan
def _status_for(session) -> str:
    start = clock.local_start(session.session_date, session.start_time)
    if start is not None and clock.local_now() > clock.plus_minutes(start, LATE_AFTER_MINUTES):
        return "late"
    return "present"


def checkin_dict(record: Attendance) -> dict:
    return {
        "session_id": record.class_session_id,
        "status": record.status,
        "method": record.method,
        "checked_in_at": iso(record.checked_in_at),
    }


def check_in(student_id, token) -> tuple:
    """``(payload, created)`` — a repeat scan returns the first record untouched."""
    if not isinstance(token, str) or not token.strip():
        raise ServiceError(400, "token_required")
    session = ClassSession.query.filter_by(qr_token_hash=_hash(token.strip())).first()
    if session is None or session.qr_expires_at is None or session.qr_expires_at <= clock.now():
        raise ServiceError(400, "invalid_token")
    enrolled = Enrollment.query.filter_by(
        cohort_id=session.cohort_id, student_id=student_id, status="active"
    ).first()
    if enrolled is None:
        raise ServiceError(403, "not_enrolled")
    existing = Attendance.query.filter_by(
        class_session_id=session.id, student_id=student_id
    ).first()
    if existing is not None:
        return checkin_dict(existing), False
    record = Attendance(
        class_session_id=session.id, student_id=student_id, status=_status_for(session),
        method="qr", checked_in_at=clock.now(),
    )
    db.session.add(record)
    try:
        db.session.commit()
    except IntegrityError:  # a double-tap raced us; the first scan stands
        db.session.rollback()
        existing = Attendance.query.filter_by(
            class_session_id=session.id, student_id=student_id
        ).first()
        return checkin_dict(existing), False
    return checkin_dict(record), True


# ----------------------------------------------------------------- teacher: sheet
def session_attendance(account, session_id) -> dict:
    session = session_for_teacher(account, session_id)
    records = {
        a.student_id: a
        for a in Attendance.query.filter_by(class_session_id=session.id).all()
    }
    students, counts = [], dict.fromkeys(ATTENDANCE_STATUSES, 0)
    for _, student in roster(session.cohort_id):
        record = records.get(student.id)
        status = record.status if record else "absent"
        counts[status] = counts.get(status, 0) + 1
        students.append({
            "student_id": student.id,
            "name": student_name(student),
            "status": status,
            "method": record.method if record else None,
            "checked_in_at": iso(record.checked_in_at) if record else None,
        })
    return {"session": session_dict(session), "students": students, "counts": counts}


def mark(account, session_id, student_id, status) -> dict:
    session = session_for_teacher(account, session_id)
    if status not in ATTENDANCE_STATUSES:
        raise ServiceError(400, "invalid_status", allowed=list(ATTENDANCE_STATUSES))
    on_roster = Enrollment.query.filter_by(
        cohort_id=session.cohort_id, student_id=student_id, status="active"
    ).first()
    if on_roster is None:
        raise ServiceError(404, "student_not_found")
    record = Attendance.query.filter_by(
        class_session_id=session.id, student_id=student_id
    ).first()
    if record is None:
        record = Attendance(
            class_session_id=session.id, student_id=student_id, checked_in_at=clock.now()
        )
        db.session.add(record)
    record.status = status
    record.method = "manual"
    record.marked_by_teacher_id = account.actor_id if account.actor_type == "teacher" else None
    db.session.commit()
    return {"student_id": student_id, **checkin_dict(record)}
