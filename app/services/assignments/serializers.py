"""JSON shapes for assignments, submissions and uploaded files (contract §2.6, §2.8)."""
from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models import LessonMaterial, StudentFile, Teacher
from app.timeutil import iso


def number(value):
    """A Numeric column as a JSON number: ``85`` rather than ``"85.00"``."""
    if value is None:
        return None
    value = Decimal(value)
    return int(value) if value == value.to_integral_value() else float(value)


def localised(mn, en):
    return {"mn": mn, "en": en}


def initials(first_name, last_name) -> str:
    return "".join(part[0] for part in (first_name, last_name) if part).upper()


def person_dict(profile) -> dict | None:
    if profile is None:
        return None
    name = " ".join(p for p in (profile.first_name, profile.last_name) if p)
    return {"id": profile.id, "name": name,
            "initials": initials(profile.first_name, profile.last_name)}


def mentor_dict(teacher_id) -> dict | None:
    teacher = db.session.get(Teacher, teacher_id) if teacher_id else None
    data = person_dict(teacher)
    if data is not None:
        data["role"] = "teacher"
    return data


def file_dict(student_file: StudentFile | None) -> dict | None:
    if student_file is None:
        return None
    return {"id": student_file.id, "file_name": student_file.file_name,
            "content_type": student_file.content_type,
            "size_bytes": student_file.size_bytes}



def material_dict(material_id) -> dict | None:
    """The §2.4 material object, in the learning service's shape."""
    material = db.session.get(LessonMaterial, material_id) if material_id else None
    if material is None:
        return None
    from app.services.learning import material_dict as shared

    return shared(material)


def feedback_dict(sub) -> dict | None:
    if sub.status != "reviewed":
        return None
    return {"message": sub.feedback, "created_at": iso(sub.graded_at),
            "mentor": mentor_dict(sub.graded_by_teacher_id)}


def submission_dict(sub) -> dict | None:
    if sub is None:
        return None
    student_file = db.session.get(StudentFile, sub.file_id) if sub.file_id else None
    return {
        "id": sub.id, "version": sub.version, "status": sub.status,
        "link": sub.submission_url, "description": sub.note,
        "file": file_dict(student_file),
        "submitted_at": iso(sub.submitted_at),
        "score": number(sub.score),
        "feedback": feedback_dict(sub),
    }


def assignment_dict(assignment, submission=None) -> dict:
    """The student's view: the assignment plus their latest submission."""
    instructions = None
    if assignment.instructions_mn or assignment.instructions_en:
        instructions = localised(assignment.instructions_mn, assignment.instructions_en)
    return {
        "id": assignment.id,
        "title": localised(assignment.title_mn, assignment.title_en),
        "instructions": instructions,
        "due_date": iso(assignment.due_date),
        "max_score": number(assignment.max_score),
        "attachment": material_dict(assignment.attachment_material_id),
        "submission": submission_dict(submission),
    }


def staff_assignment_dict(assignment, *, submitted_students=None) -> dict:
    """The authoring view: raw editable fields alongside the student shape."""
    data = assignment_dict(assignment)
    data.pop("submission")
    data.update({
        "cohort_id": assignment.cohort_id, "lesson_id": assignment.lesson_id,
        "teacher_id": assignment.teacher_id,
        "attachment_material_id": assignment.attachment_material_id,
        "title_mn": assignment.title_mn, "title_en": assignment.title_en,
        "instructions_mn": assignment.instructions_mn,
        "instructions_en": assignment.instructions_en,
        "is_active": assignment.is_active,
        "created_at": iso(assignment.created_at), "updated_at": iso(assignment.updated_at),
    })
    if submitted_students is not None:
        data["submitted_students"] = submitted_students
    return data
