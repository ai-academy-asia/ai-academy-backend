"""Import all models here so Flask-Migrate/Alembic can autodetect them."""
from .auth_account import (  # noqa: F401
    ACTOR_STAFF,
    ACTOR_STUDENT,
    ACTOR_TEACHER,
    ACTOR_TYPES,
    AuthAccount,
)
from .classroom import Classroom  # noqa: F401
from .course import COURSE_LEVELS, COURSE_STATUSES, Course  # noqa: F401
from .refresh_token import RefreshToken  # noqa: F401
from .staff import STAFF_ROLES, Staff  # noqa: F401
from .student import Student  # noqa: F401
from .teacher import Teacher  # noqa: F401

# Maps an auth account's actor_type to its profile model.
PROFILE_MODEL_BY_ACTOR = {
    ACTOR_STUDENT: Student,
    ACTOR_TEACHER: Teacher,
    ACTOR_STAFF: Staff,
}


def get_profile_model(actor_type: str):
    """Return the profile model class for an actor_type, or None if unknown."""
    return PROFILE_MODEL_BY_ACTOR.get(actor_type)
