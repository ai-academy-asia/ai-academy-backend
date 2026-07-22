"""Classroom domain logic (super_admin manages via the admin router)."""
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Classroom

from .errors import ServiceError

_WRITABLE = {
    "name", "center_name", "location", "capacity", "floor",
    "equipment", "is_active", "notes",
}


def _apply(classroom, data):
    for key in _WRITABLE:
        if key in data:
            setattr(classroom, key, data[key])


def get_or_404(classroom_id) -> Classroom:
    classroom = db.session.get(Classroom, classroom_id)
    if classroom is None:
        raise ServiceError(404, "not_found")
    return classroom


def list_classrooms(*, search=None, active=None):
    q = Classroom.query
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(Classroom.name.ilike(like), Classroom.center_name.ilike(like)))
    if active in ("true", "false"):
        q = q.filter(Classroom.is_active.is_(active == "true"))
    return q.order_by(Classroom.center_name.asc(), Classroom.name.asc()).all()


def _commit_or_conflict():
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ServiceError(409, "classroom_exists") from None  # same (center_name, name)


def create_classroom(data) -> Classroom:
    classroom = Classroom()
    _apply(classroom, data)
    if not classroom.name:
        raise ServiceError(400, "name_required")
    db.session.add(classroom)
    _commit_or_conflict()
    return classroom


def update_classroom(classroom, data) -> Classroom:
    _apply(classroom, data)
    if not classroom.name:
        raise ServiceError(400, "name_required")
    _commit_or_conflict()
    return classroom


def delete_classroom(classroom):
    db.session.delete(classroom)
    db.session.commit()
