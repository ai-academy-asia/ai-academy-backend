"""Account-provisioning helpers, shared by the CLI and (later) the
enrollment/checkout flow that auto-creates student accounts after payment."""
from app.extensions import db
from app.models import (
    ACTOR_STAFF,
    ACTOR_STUDENT,
    ACTOR_TEACHER,
    AuthAccount,
    Staff,
    Student,
    Teacher,
)


class AccountError(Exception):
    """Raised on a provisioning problem (e.g. duplicate email)."""


def email_exists(email: str) -> bool:
    return AuthAccount.get_by_email(email) is not None


def _provision(profile, *, email, password, actor_type, role, must_change_password):
    """Create a profile row + its auth account in one transaction.

    ``profile`` is an unsaved Student/Teacher/Staff instance; its id is assigned
    by the flush before the account is linked to it. Returns (account, profile).
    """
    email = AuthAccount.normalize_email(email)
    if not email:
        raise AccountError("email_required")
    if email_exists(email):
        raise AccountError("email_taken")

    db.session.add(profile)
    db.session.flush()  # assign profile.id

    account = AuthAccount(
        email=email,
        actor_type=actor_type,
        actor_id=profile.id,
        role=role,
        must_change_password=must_change_password,
    )
    account.set_password(password)
    db.session.add(account)
    db.session.commit()
    return account, profile


def create_student_account(*, email, password, first_name, last_name=None,
                           phone=None, must_change_password=True):
    profile = Student(first_name=first_name, last_name=last_name, phone=phone)
    return _provision(
        profile, email=email, password=password, actor_type=ACTOR_STUDENT,
        role=ACTOR_STUDENT, must_change_password=must_change_password,
    )


def create_teacher_account(*, email, password, first_name, last_name=None,
                           phone=None, must_change_password=True):
    profile = Teacher(first_name=first_name, last_name=last_name, phone=phone)
    return _provision(
        profile, email=email, password=password, actor_type=ACTOR_TEACHER,
        role=ACTOR_TEACHER, must_change_password=must_change_password,
    )


def create_staff_account(*, email, password, first_name, last_name=None,
                         phone=None, role="super_admin", must_change_password=True):
    """Create a Staff profile + auth account. The staff role doubles as the
    account's RBAC role."""
    profile = Staff(first_name=first_name, last_name=last_name, phone=phone, role=role)
    return _provision(
        profile, email=email, password=password, actor_type=ACTOR_STAFF,
        role=role, must_change_password=must_change_password,
    )
