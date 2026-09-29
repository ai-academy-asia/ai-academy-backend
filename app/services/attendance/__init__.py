"""Class sessions, QR check-in and attendance (see the submodules).

``attendance_percent(enrollment)`` is the figure the refund rule will read.
"""
from .checkin import check_in, issue_qr, mark, session_attendance  # noqa: F401
from .sessions import (  # noqa: F401
    cohort_students,
    create_session,
    delete_session,
    generate_sessions,
    list_sessions,
    session_dict,
    update_session,
)
from .student import attendance_percent, my_attendance  # noqa: F401
