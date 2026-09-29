"""Course learning: the student's path through modules and lessons, materials,
notes and progress (docs/course_learning_api_contract_v1.md §2.1–2.5), plus the
staff authoring of that content.

Other areas rely on :func:`course_progress` and :func:`material_dict`.
"""
from .path import course_progress
from .shapes import material_dict

__all__ = ["course_progress", "material_dict"]
