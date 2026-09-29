"""Homework: assignments, versioned submissions, student uploads, teacher review.

Student side (contract §2.6, §2.8) in ``student`` / ``files``; the teacher/staff
side in ``authoring`` / ``review``; ``cleanup`` holds ``flask files cleanup``.
"""
from .student import assignment_for_lesson

__all__ = ["assignment_for_lesson"]
