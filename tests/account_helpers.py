"""Shared fixtures and helpers for the account (/me money, profile, password reset)
and certificate tests. Test modules bind the fixtures they use by name."""
from datetime import datetime

import pytest

PASSWORD = "Passw0rd!"


def _rows(db, model, **filters):
    db.session.expire_all()
    return model.query.filter_by(**filters).all()


# ----------------------------------------------------------------- enrollment / money
@pytest.fixture
def enroll(db, make_cohort):
    """``enroll(student_id, cohort=None, status="active")`` -> Enrollment."""
    from app.models import Enrollment

    def _make(student_id, cohort=None, status="active"):
        cohort = cohort or make_cohort()
        enr = Enrollment(cohort_id=cohort.id, student_id=student_id,
                         course_id=cohort.course_id, status=status)
        db.session.add(enr)
        db.session.commit()
        return enr

    return _make


@pytest.fixture
def make_ledger(db):
    from app.models import StudentLedger

    def _make(enrollment, due=1_000_000, paid=0, next_due=None):
        row = StudentLedger(student_id=enrollment.student_id, enrollment_id=enrollment.id,
                            total_due=due, total_paid=paid, balance=due - paid,
                            next_due_date=next_due)
        db.session.add(row)
        db.session.commit()
        return row

    return _make


@pytest.fixture
def make_invoice(db):
    from app.models import Invoice

    counter = {"n": 0}

    def _make(student_id, status="pending", amount=250_000, created_at=None, **fields):
        counter["n"] += 1
        inv = Invoice(provider="qpay", student_id=student_id, amount=amount, status=status,
                      sender_invoice_no=f"INV-{counter['n']}", qr_text="QR", qr_image="IMG",
                      provider_meta={"secret": "x"},
                      created_at=created_at or datetime(2026, 9, 1, 0, counter["n"]), **fields)
        db.session.add(inv)
        db.session.commit()
        return inv

    return _make


@pytest.fixture
def make_receipt(db):
    """``make_receipt(invoice, via_payment=False, temp=False)`` -> EBarimtReceipt."""
    from app.models import EBarimtReceipt, Payment

    counter = {"n": 0}

    def _make(invoice, via_payment=False, temp=False):
        counter["n"] += 1
        pay = Payment(invoice_id=invoice.id, provider="qpay",
                      provider_payment_id=f"P{counter['n']}", amount=invoice.amount,
                      raw={"secret": "x"})
        db.session.add(pay)
        db.session.flush()
        receipt = EBarimtReceipt(
            payment_id=pay.id, invoice_id=None if via_payment else invoice.id,
            total_amount=invoice.amount, vat_amount=10, is_temp_mode=temp,
            status="temp" if temp else "issued",
            ebarimt_id=None if temp else f"DDTD{counter['n']}",
            lottery=None if temp else "AB 12345678", qr_data=None if temp else "QRDATA",
            pos_no="POS", raw={"secret": "x"},
            issued_at=None if temp else datetime(2026, 9, 2),
        )
        db.session.add(receipt)
        db.session.commit()
        return receipt

    return _make


# ----------------------------------------------------------------- mail
@pytest.fixture
def outbox(app, monkeypatch):
    """Configure mail and capture every message ``app.mail.send_message`` is given."""
    from app.services.account import password_reset

    sent = []
    monkeypatch.setitem(app.config, "MAIL_HOST", "smtp.test")
    monkeypatch.setattr("app.mail.send_message", sent.append)
    # Reset mail goes out on a background thread; wait for it so asserts are not racy.
    deliver = password_reset._deliver
    monkeypatch.setattr(password_reset, "_deliver",
                        lambda message, account_id: deliver(message, account_id).join(5))
    return sent


def _code_from(message) -> str:
    body = message.get_content()
    return body.split("код: ")[1][:6]


# ----------------------------------------------------------------- learning content
@pytest.fixture
def make_lessons(db):
    """``make_lessons(course, n)`` -> [CourseLesson] under one module."""
    from app.models import CourseLesson, CourseTopic

    def _make(course, n=2):
        topic = CourseTopic(course_id=course.id, name_mn="Модуль", sort_order=1)
        db.session.add(topic)
        db.session.flush()
        lessons = [CourseLesson(topic_id=topic.id, name_mn=f"Хичээл {i}", sort_order=i)
                   for i in range(n)]
        db.session.add_all(lessons)
        db.session.commit()
        return lessons

    return _make


@pytest.fixture
def complete(db):
    from app.models import LessonProgress

    def _make(enrollment, lessons):
        for lesson in lessons:
            db.session.add(LessonProgress(enrollment_id=enrollment.id, lesson_id=lesson.id,
                                          completed=True, completed_at=datetime.utcnow()))
        db.session.commit()

    return _make


@pytest.fixture
def make_quiz(db):
    """``make_quiz(course, passed_by=None, required=True, questions=1)`` -> Exam."""
    from app.models import Exam, ExamQuestion, StudentExam

    def _make(course, passed_by=None, required=True, questions=1):
        exam = Exam(course_id=course.id, name_mn="Шалгалт", is_required=required)
        db.session.add(exam)
        db.session.flush()
        for i in range(questions):
            db.session.add(ExamQuestion(exam_id=exam.id, question=f"Q{i}"))
        if passed_by is not None:
            db.session.add(StudentExam(exam_id=exam.id, student_id=passed_by, is_passed=True,
                                       percent=100, completed_at=datetime.utcnow()))
        db.session.commit()
        return exam

    return _make


@pytest.fixture
def earned(make_student, make_course, make_cohort, enroll, make_lessons, complete,
           make_ledger):
    """A student who meets every requirement: returns (account, headers, course, enrollment)."""
    account, headers = make_student(last_name="Dorj")
    course = make_course(title_en="Leaders")
    enr = enroll(account.actor_id, make_cohort(course=course))
    complete(enr, make_lessons(course, 2))
    make_ledger(enr, due=1_000_000, paid=1_000_000)
    return account, headers, course, enr


# ----------------------------------------------------------------- S3
class FakeS3:
    def __init__(self):
        self.objects = {}
        self.fail = set()

    def upload_fileobj(self, fileobj, key, content_type=None):
        from app.storage import S3StorageError
        if "upload" in self.fail:
            raise S3StorageError("upload failed")
        self.objects[key] = (fileobj.read(), content_type)

    def presigned_url(self, key, expires=300):
        from app.storage import S3StorageError
        if "presign" in self.fail:
            raise S3StorageError("presign failed")
        return f"https://s3.test/{key}?expires={expires}"


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    for name in ("upload_fileobj", "presigned_url"):
        monkeypatch.setattr(f"app.services.certificates.issuing.{name}", getattr(fake, name))
    return fake


