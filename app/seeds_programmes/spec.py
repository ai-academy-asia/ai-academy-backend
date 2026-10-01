"""What a seeded programme is made of — one :class:`Programme` per course to seed.

The builders (content, people, activity, homework, money) read only this, so a
new programme is a new spec module, not new code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

EMAIL_DOMAIN = "test.ai-academy.asia"
PASSWORD = "Test1234!"


@dataclass(frozen=True)
class Lesson:
    title_mn: str
    title_en: str
    goal: str | None = None          # what the student walks away with
    practice: str | None = None      # the hands-on part of the class
    topics: tuple[str, ...] = ()     # bullet points under the goal


@dataclass(frozen=True)
class Programme:
    key: str                         # CLI name, also the login prefix ("eng" -> eng.s01@…)
    login_prefix: str
    course: dict                     # Course columns (title, format, level, …)
    modules: list                    # [{"name_mn", "name_en", "lessons": [Lesson]}]
    teachers: list                   # [(login, first, last, phone, bio)]
    # (login, first, last, phone, birth year, diligence 0..1, paid|on_track|overdue)
    students: list
    dropped: tuple | None            # one more student, enrolled then cancelled
    cohort: dict                     # Cohort columns (name, meeting_days, times, note)
    weekdays: tuple[int, ...]        # class days, Mon=0
    start_time: str
    end_time: str
    current_lesson: int              # 0-based: the latest class before "today"
    price: Decimal
    # (days from the first class, share of the price) per installment
    installments: list
    room: str | None = None          # classroom name; None = online (attendance by hand)
    quizzes: dict = field(default_factory=dict)       # lesson title_en -> bank
    exam_titles: frozenset = frozenset()              # lessons that ARE a test
    assignments: dict = field(default_factory=dict)   # lesson title_en -> (title, text)
    holidays: frozenset = frozenset({date(2026, 7, d) for d in range(10, 16)})
    due_after_days: int = 7
    news: tuple[str, str] | None = None               # one read announcement

    def email(self, login: str) -> str:
        return f"{login}@{EMAIL_DOMAIN}"

    @property
    def in_person(self) -> bool:
        return self.room is not None

    @property
    def email_pattern(self) -> str:
        return f"{self.login_prefix}.%@{EMAIL_DOMAIN}"

    @property
    def lesson_count(self) -> int:
        return sum(len(m["lessons"]) for m in self.modules)
