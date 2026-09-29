"""Quizzes (contract §2.7): per-answer server grading for students, authoring for staff.

- :mod:`.attempts`  — student start/resume, answer, finish, read
- :mod:`.summary`   — the lesson-detail quiz summary and certificate eligibility
- :mod:`.authoring` — staff quiz CRUD (``course:edit``)
- :mod:`.questions` — staff question-set replacement and attempt review
- :mod:`.payloads`  — every JSON shape; the only place the answer key is gated

Other areas call :func:`quiz_summary_for_lesson` (learning) and
:func:`required_quizzes_passed` (certificates).
"""
from .summary import quiz_summary_for_lesson, required_quizzes_passed  # noqa: F401
