"""Course certificates: eligibility (§2.9), staff issuing, files, verification.

``certificate_status(student_id, course, enrollment)`` is the entry point the
learning service uses for the certificate summary on the module list.
"""
from .eligibility import certificate_status, is_eligible, requirements
from .issuing import (
    archive,
    get_certificate,
    issue,
    list_certificates,
    student_download,
    upload_file,
    verify,
)

__all__ = [
    "archive",
    "certificate_status",
    "get_certificate",
    "is_eligible",
    "issue",
    "list_certificates",
    "requirements",
    "student_download",
    "upload_file",
    "verify",
]
