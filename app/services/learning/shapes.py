"""JSON shapes of the learning surface (contract §2.1–2.5), shared by student and staff views."""
from app.timeutil import iso


def loc(mn, en):
    """A localised ``{"mn", "en"}`` object."""
    return {"mn": mn, "en": en}


def module_ref(topic, order) -> dict:
    return {"id": topic.id, "order": order, "title": loc(topic.name_mn, topic.name_en)}


def material_dict(material) -> dict:
    """§2.4 material object. Links carry their ``url``; files are fetched via /download."""
    data = {
        "id": material.id,
        "title": material.title,
        "type": material.type,
        "file_name": material.file_name,
        "content_type": material.content_type,
        "size_bytes": material.size_bytes,
    }
    if material.type == "link":
        data["url"] = material.url
    return data


def author_dict(profile) -> dict:
    """Display name + ready-to-render initials ("Болд Батаа" -> "ББ")."""
    if profile is None:
        return {"name": None, "initials": None}
    parts = [p.strip() for p in (profile.first_name, profile.last_name) if p and p.strip()]
    return {
        "name": " ".join(parts) or None,
        "initials": "".join(p[0] for p in parts).upper() or None,
    }


def note_dict(note, profile) -> dict:
    """§2.5 note object."""
    return {
        "id": note.id,
        "content": note.content,
        "created_at": iso(note.created_at),
        "updated_at": iso(note.updated_at),
        "author": author_dict(profile),
    }


# ---------------------------------------------------------------- staff views
def staff_module_dict(topic, lesson_count=None) -> dict:
    return {
        "id": topic.id,
        "course_id": topic.course_id,
        "name_mn": topic.name_mn,
        "name_en": topic.name_en,
        "sort_order": topic.sort_order,
        "lesson_count": len(topic.lessons) if lesson_count is None else lesson_count,
        "created_at": iso(topic.created_at),
        "updated_at": iso(topic.updated_at),
    }


def staff_lesson_dict(lesson) -> dict:
    return {
        "id": lesson.id,
        "module_id": lesson.topic_id,
        "name_mn": lesson.name_mn,
        "name_en": lesson.name_en,
        "type": lesson.type,
        "classroom_embed_url": lesson.classroom_embed_url,
        "duration_seconds": lesson.duration_seconds,
        "summary_mn": lesson.summary_mn,
        "summary_en": lesson.summary_en,
        "sections": lesson.sections or [],
        "is_preview": lesson.is_preview,
        "sort_order": lesson.sort_order,
        "created_at": iso(lesson.created_at),
        "updated_at": iso(lesson.updated_at),
    }


def staff_material_dict(material) -> dict:
    data = material_dict(material)
    data.update({
        "lesson_id": material.lesson_id,
        "cohort_id": material.cohort_id,
        "url": material.url,
        "sort_order": material.sort_order,
        "created_at": iso(material.created_at),
    })
    return data
