"""Homework with submissions, the installment plan with its payments, and notifications."""
from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from app.extensions import db
from app.models import (
    Assignment,
    AssignmentSubmission,
    AuthAccount,
    Invoice,
    Notification,
    Payment,
    PaymentInstallment,
)
from app.services.payments.ledger import recompute_ledger

from .activity import utc_at

FEEDBACK = ["Сайн байна, кодоо илүү цэвэрхэн функцэд хуваагаарай.",
            "Маш сайн! Дүгнэлт хэсэг тодорхой байна.",
            "Validation хэсэг дутуу байна, дараагийн удаа анхаараарай.",
            "Ажил бүрэн. README нэмбэл илүү дээр."]


def create_assignments(spec, cohort, lessons, dates_by_lesson) -> list[Assignment]:
    """Set by the cohort's teacher — the one who can review them through the API."""
    by_title = {lesson.name_en: lesson for lesson in lessons}
    out = []
    for title, (title_mn, instructions) in spec.assignments.items():
        lesson = by_title[title]
        due = dates_by_lesson[lesson.id] + timedelta(days=spec.due_after_days)
        out.append(Assignment(
            cohort_id=cohort.id, lesson_id=lesson.id, teacher_id=cohort.teacher_id,
            title_mn=title_mn, title_en=title, instructions_mn=instructions,
            due_date=due, max_score=Decimal(100),
        ))
    db.session.add_all(out)
    db.session.flush()
    return out


def record_submissions(spec, assignments, dates_by_lesson, enrolled, today) -> None:
    """Past-due work is graded except the newest one (left for the teacher to review)."""
    past_due = [a for a in assignments if a.due_date < today]
    awaiting_review = past_due[-1].id if past_due else None
    for a in assignments:
        opened = dates_by_lesson[a.lesson_id]
        if opened >= today:
            continue
        for idx, (_, student, diligence, _) in enumerate(enrolled):
            rng = random.Random(f"hw-{a.id}-{idx}")
            if a.due_date >= today and diligence < 0.85:
                continue                     # still open: only the keen have handed in
            if rng.random() > diligence:
                continue
            versions = 2 if rng.random() < 0.2 else 1
            repo = f"https://github.com/aiaa-{spec.login_prefix}-s{idx + 1:02d}/hw-{a.id}"
            for version in range(1, versions + 1):
                when = utc_at(min(opened + timedelta(days=2 + 2 * version), today), "22:00")
                sub = AssignmentSubmission(
                    assignment_id=a.id, student_id=student.id, version=version,
                    submission_url=repo,
                    note="Хийсэн ажлаа илгээв." if version == 1 else "Засварласан хувилбар.",
                    submitted_at=when,
                )
                if version == versions and a.due_date < today and a.id != awaiting_review:
                    sub.status = "reviewed"
                    sub.score = Decimal(min(100, int(55 + 45 * diligence + rng.randint(-8, 8))))
                    sub.feedback = rng.choice(FEEDBACK)
                    sub.graded_by_teacher_id = a.teacher_id
                    sub.graded_at = when + timedelta(days=2)
                db.session.add(sub)


def payment_plan(spec, start) -> list[tuple]:
    """[(due date, amount)]; the last installment absorbs rounding so the sum is the price."""
    plan = [(start + timedelta(days=days), (spec.price * share).quantize(Decimal(1)))
            for days, share in spec.installments]
    last_due, _ = plan[-1]
    plan[-1] = (last_due, spec.price - sum(amount for _, amount in plan[:-1]))
    return plan


def record_money(spec, enrolled, start, today) -> None:
    """paid = everything settled · on_track = what is due · overdue = only the deposit
    (nothing at all on a single-payment plan)."""
    plan = payment_plan(spec, start)
    for enrollment, student, _, profile in enrolled:
        for seq, (due, amount) in enumerate(plan, start=1):
            inst = PaymentInstallment(enrollment_id=enrollment.id, student_id=student.id,
                                      seq=seq, due_date=due, amount=amount)
            db.session.add(inst)
            db.session.flush()
            settled = (profile == "paid" or (profile == "on_track" and due <= today)
                       or (profile == "overdue" and seq == 1 and len(plan) > 1))
            if settled:
                _pay(spec, enrollment, student, inst, due - timedelta(days=1))
            elif due < today:
                inst.status = "overdue"
        db.session.flush()
        recompute_ledger(enrollment.id)


def _pay(spec, enrollment, student, inst, day) -> None:
    paid_at = utc_at(day, "14:00")
    invoice = Invoice(provider="qpay", enrollment_id=enrollment.id, student_id=student.id,
                      installment_id=inst.id, amount=inst.amount, status="paid",
                      sender_invoice_no=f"SEED-{spec.key.upper()}-{enrollment.id}-{inst.seq}",
                      description=f"{spec.course['title_en']} — {inst.seq}-р төлөлт",
                      paid_at=paid_at)
    db.session.add(invoice)
    db.session.flush()
    db.session.add(Payment(invoice_id=invoice.id, provider="qpay", amount=inst.amount,
                           provider_payment_id=f"SEED-PAY-{invoice.id}", status="paid",
                           method="qr", paid_at=paid_at))
    inst.status, inst.paid_at = "paid", paid_at


def notify(spec, enrolled, assignments, today) -> None:
    current = next((a for a in assignments if a.due_date >= today), None)
    for _, student, _, profile in enrolled:
        account = AuthAccount.query.filter_by(actor_type="student", actor_id=student.id).one()
        if current is not None:
            db.session.add(Notification(
                account_id=account.id, kind="assignment", title="Шинэ даалгавар",
                body=f"«{current.title_mn}» — {current.due_date:%m/%d} хүртэл илгээнэ үү.",
                data={"assignment_id": current.id},
            ))
        if spec.news:
            db.session.add(Notification(
                account_id=account.id, kind="general", title=spec.news[0], body=spec.news[1],
                read_at=utc_at(today - timedelta(days=3), "09:00"),
            ))
        if profile == "overdue":
            db.session.add(Notification(
                account_id=account.id, kind="payment", title="Төлбөрийн сануулга",
                body="Хугацаа хэтэрсэн төлбөр байна. Аппаас төлнө үү.",
            ))
