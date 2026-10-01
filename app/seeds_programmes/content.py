"""Course, modules, lessons, materials and quizzes — everything that belongs to the course."""
from __future__ import annotations

from app.extensions import db
from app.models import (
    Course,
    CourseLesson,
    CourseTopic,
    Exam,
    ExamOption,
    ExamQuestion,
    LessonMaterial,
)


def create_course(spec, start, end) -> Course:
    course = Course(
        **spec.course, status="closed", start_date=start, end_date=end,
        duration_weeks=((end - start).days + 6) // 7, price_amount=spec.price,
        currency="MNT", discount_percent=0, has_attendance=True,
        attendance_method="qr_scan" if spec.in_person else "roll_call",
        curriculum=[{"mn": m["name_mn"], "en": m["name_en"]} for m in spec.modules],
    )
    db.session.add(course)
    db.session.flush()
    return course


def create_modules(spec, course) -> list[CourseLesson]:
    """All topics + lessons; returns the lessons in teaching order."""
    ordered = []
    for m_idx, module in enumerate(spec.modules, start=1):
        topic = CourseTopic(course_id=course.id, name_mn=module["name_mn"],
                            name_en=module["name_en"], sort_order=m_idx)
        db.session.add(topic)
        db.session.flush()
        for l_idx, item in enumerate(module["lessons"], start=1):
            kind = lesson_kind(spec, item)
            lesson = CourseLesson(
                topic_id=topic.id, name_mn=item.title_mn, name_en=item.title_en,
                type="recording", sort_order=l_idx,
                duration_seconds=_minutes(spec.start_time, spec.end_time) * 60,
                summary_mn=_summary(module["name_mn"], item, kind),
                summary_en=f"{item.title_en} — {module['name_en']}.",
                sections=_sections(item, kind),
                is_preview=(m_idx == 1 and l_idx == 1),
            )
            db.session.add(lesson)
            ordered.append(lesson)
    db.session.flush()
    return ordered


def add_materials(spec, lessons) -> None:
    for lesson in lessons:
        if lesson.name_en in spec.exam_titles:
            continue
        base = f"https://example.com/aiaa/{spec.key}"
        db.session.add(LessonMaterial(lesson_id=lesson.id, title="Слайд (PDF)", type="link",
                                      url=f"{base}/slides/{lesson.id}.pdf", sort_order=1))
        db.session.add(LessonMaterial(lesson_id=lesson.id, title="Дадлагын заавар",
                                      type="link", url=f"{base}/practice/{lesson.id}",
                                      sort_order=2))


def add_quizzes(spec, course, lessons) -> list[Exam]:
    exams = []
    for lesson in lessons:
        bank = spec.quizzes.get(lesson.name_en)
        if bank is None:
            continue
        name_mn, name_en, questions = bank
        exam = Exam(course_id=course.id, topic_id=lesson.topic_id, lesson_id=lesson.id,
                    name_mn=name_mn, name_en=name_en, pass_percent=70, max_attempts=2,
                    is_required=True)
        db.session.add(exam)
        db.session.flush()
        for q_idx, (text, points, options, correct, explanation) in enumerate(questions, 1):
            question = ExamQuestion(exam_id=exam.id, question=text, point=points,
                                    explanation=explanation, sort_order=q_idx)
            db.session.add(question)
            db.session.flush()
            for o_idx, answer in enumerate(options):
                db.session.add(ExamOption(question_id=question.id, answer=answer,
                                          is_correct=(o_idx == correct), sort_order=o_idx + 1))
        exams.append(exam)
    db.session.flush()
    return exams


def lesson_kind(spec, item) -> str:
    """exam | review | class — drives the summary and the lesson body."""
    if item.title_en in spec.exam_titles:
        return "exam"
    if item.title_en.lower().startswith(("review", "module review", "test review")):
        return "review"
    return "class"


def _minutes(start: str, end: str) -> int:
    (h1, m1), (h2, m2) = (map(int, start.split(":")), map(int, end.split(":")))
    return (h2 * 60 + m2) - (h1 * 60 + m1)


def _summary(module_mn, item, kind) -> str:
    if kind == "exam":
        return (f"«{module_mn}» модулийн шалгалт. Онлайн тест хийж, 70%-иас дээш "
                "оноо авбал тэнцэнэ. Хоёр удаа оролдох эрхтэй.")
    if item.goal:
        return item.goal + (f" Дадлага: {item.practice}" if item.practice else "")
    if kind == "review":
        return (f"«{module_mn}» модулийн өмнөх хичээлүүдийн давтлага: асуулт хариулт, "
                "дасгал ажил, алдаа засварлах.")
    return (f"{item.title_mn} — онол, live coding, дасгал. "
            "Хичээлийн бичлэг, слайд, notebook хавсаргав.")


def _bullet(text):
    return {"mn": text, "en": text}


def _sections(item, kind) -> list[dict]:
    """The lesson screen's structured body (title/body/bullets, mn+en)."""
    if kind == "exam":
        return [{
            "title": {"mn": "Шалгалтын заавар", "en": "Exam instructions"},
            "body": {"mn": "Хичээлийн цагт танхимд, өөрийн компьютероос өгнө.",
                     "en": "Taken in class, on your own laptop."},
            "bullets": [{"mn": "Тэнцэх босго: 70%", "en": "Pass mark: 70%"},
                        {"mn": "Оролдлого: 2 удаа", "en": "Attempts: 2"}],
        }]
    goal = item.goal or f"{item.title_mn} сэдвийг ойлгож, бие даан хэрэгжүүлэх."
    topics = item.topics or ("Онолын тайлбар", "Live coding", "Бие даалтын дасгал")
    out = [{
        "title": {"mn": "Хичээлийн зорилго", "en": "Goals"},
        "body": {"mn": goal, "en": f"Understand and apply: {item.title_en}."},
        "bullets": [_bullet(t) for t in topics],
    }]
    if item.practice:
        out.append({"title": {"mn": "Дадлага", "en": "Practice"},
                    "body": {"mn": item.practice, "en": item.practice}, "bullets": []})
    else:
        out.append({"title": {"mn": "Бэлтгэл", "en": "Before class"},
                    "body": {"mn": "Notebook-оо Google Colab дээр нээж бэлдээрэй.",
                             "en": "Open the notebook in Google Colab before class."},
                    "bullets": []})
    return out
