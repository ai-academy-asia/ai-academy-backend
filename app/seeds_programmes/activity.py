"""The cohort's calendar and what students did in it: attendance, progress, quiz attempts.

The calendar is anchored on *today*: one class per lesson on the programme's
weekdays, laid out so the latest past class is ``spec.current_lesson``. Which
modules are open or still locked by their first class date is therefore the same
whatever day the seed runs.
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from app.extensions import db
from app.models import (
    Attendance,
    ClassSession,
    LessonProgress,
    StudentExam,
    StudentExamAnswer,
)
from app.services.quizzes.attempts import grade

UB_OFFSET = timedelta(hours=8)          # Asia/Ulaanbaatar, no DST


def _class_days(spec, start: date, step: int):
    day = start
    while True:
        if day.weekday() in spec.weekdays and day not in spec.holidays:
            yield day
        day += timedelta(days=step)


def calendar(spec, today: date) -> list[date]:
    """One class date per lesson; the current lesson falls on the last class before today."""
    back = _class_days(spec, today - timedelta(days=1), -1)
    past = [next(back) for _ in range(spec.current_lesson + 1)][::-1]
    ahead = _class_days(spec, today, 1)
    future = [next(ahead) for _ in range(spec.lesson_count - len(past))]
    return past + future


def utc_at(day: date, hhmm: str, minutes: int = 0) -> datetime:
    """A local UB wall-clock time as the naive UTC the database stores."""
    local = datetime.combine(day, time.fromisoformat(hhmm)) + timedelta(minutes=minutes)
    return local - UB_OFFSET


def create_sessions(spec, cohort, lessons, dates) -> list[ClassSession]:
    sessions = []
    for lesson, day in zip(lessons, dates):
        session = ClassSession(cohort_id=cohort.id, topic_id=lesson.topic_id,
                               session_date=day, start_time=spec.start_time,
                               end_time=spec.end_time)
        db.session.add(session)
        sessions.append(session)
    db.session.flush()
    return sessions


def record_attendance(spec, sessions, enrolled, teacher, today) -> None:
    for idx, (_, student, diligence, _) in enumerate(enrolled):
        rng = random.Random(f"att-{idx}")
        for session in sessions:
            if session.session_date >= today:
                break
            roll = rng.random()
            if roll < diligence:
                status, late = "present", rng.randint(0, 9)
            elif roll < diligence + 0.08:
                status, late = "late", rng.randint(15, 40)
            elif roll < diligence + 0.12:
                status, late = "excused", 0
            else:
                status, late = "absent", 0
            if status == "absent":
                continue                     # no row = not checked in
            manual = not spec.in_person or status == "excused" or rng.random() < 0.1
            db.session.add(Attendance(
                class_session_id=session.id, student_id=student.id, status=status,
                method="manual" if manual else "qr",
                marked_by_teacher_id=teacher.id if manual else None,
                checked_in_at=utc_at(session.session_date, spec.start_time, late),
            ))


def record_progress(lessons, dates, enrolled, today) -> None:
    """Completed lessons per student, and the enrollment's progress percent."""
    for idx, (enrollment, _, diligence, _) in enumerate(enrolled):
        rng = random.Random(f"prog-{idx}")
        done = 0
        for lesson, day in zip(lessons, dates):
            if day >= today:
                break
            if rng.random() > diligence + 0.05:
                continue
            watched = utc_at(day + timedelta(days=rng.randint(0, 3)), "21:00", rng.randint(0, 120))
            db.session.add(LessonProgress(enrollment_id=enrollment.id, lesson_id=lesson.id,
                                          completed=True, watched_at=watched,
                                          completed_at=watched))
            done += 1
        enrollment.progress_pct = done * 100 // len(lessons)


def record_quiz_attempts(spec, exams, dates_by_lesson, enrolled, today) -> None:
    """Past tests: one attempt each; a retake for the diligent ones who failed."""
    for exam in exams:
        day = dates_by_lesson[exam.lesson_id]
        if day >= today:
            continue
        for idx, (_, student, diligence, _) in enumerate(enrolled):
            rng = random.Random(f"quiz-{exam.id}-{idx}")
            attempt = _attempt(exam, student, rng, diligence, utc_at(day, spec.start_time, 20))
            if not attempt.is_passed and diligence >= 0.6:
                _attempt(exam, student, rng, min(diligence + 0.15, 1.0),
                         utc_at(day + timedelta(days=2), "20:00"))


def _attempt(exam, student, rng, skill, started) -> StudentExam:
    attempt = StudentExam(exam_id=exam.id, student_id=student.id, started_at=started)
    db.session.add(attempt)
    db.session.flush()
    answers = {}
    for n, question in enumerate(exam.questions):
        options = list(question.options)
        right = next(o for o in options if o.is_correct)
        wrong = [o for o in options if not o.is_correct]
        pick = right if rng.random() < skill else rng.choice(wrong)
        answer = StudentExamAnswer(student_exam_id=attempt.id, question_id=question.id,
                                   option_id=pick.id, is_correct=pick.is_correct,
                                   answered_at=started + timedelta(minutes=2 * n + 1))
        db.session.add(answer)
        answers[question.id] = answer
    grade(attempt, exam, answers)
    attempt.completed_at = started + timedelta(minutes=2 * len(answers) + 3)
    return attempt
