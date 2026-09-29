"""Validation of staff-authored learning content fields."""
from urllib.parse import urlparse

from ..errors import ServiceError


def text(data, key, *, max_len, required=False):
    """A trimmed string (or ``None``); ``<key>_required`` / ``<key>_too_long``."""
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise ServiceError(400, f"invalid_{key}")
    value = (value or "").strip() or None
    if required and value is None:
        raise ServiceError(400, f"{key}_required")
    if max_len and value and len(value) > max_len:
        raise ServiceError(400, f"{key}_too_long", max_length=max_len)
    return value


def integer(data, key, *, minimum=0, nullable=False):
    value = data.get(key)
    if value in (None, "") and nullable:
        return None
    if isinstance(value, bool):
        raise ServiceError(400, f"invalid_{key}")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ServiceError(400, f"invalid_{key}") from None
    if number < minimum:
        raise ServiceError(400, f"invalid_{key}")
    return number


def boolean(data, key):
    value = data.get(key)
    if not isinstance(value, bool):
        raise ServiceError(400, f"invalid_{key}")
    return value


def http_url(value, code="invalid_url"):
    if not isinstance(value, str) or not value.strip():
        raise ServiceError(400, code)
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or len(value) > 1000:
        raise ServiceError(400, code)
    return value


# ---------------------------------------------------------------- sections
def _loc(value, where, *, nullable=True):
    """A ``{"mn": str, "en": str|null}`` object, normalised to both keys."""
    if value is None and nullable:
        return None
    if (not isinstance(value, dict) or set(value) - {"mn", "en"}
            or not isinstance(value.get("mn"), str)
            or not isinstance(value.get("en"), (str, type(None)))):
        raise ServiceError(400, "invalid_sections", at=where)
    return {"mn": value["mn"], "en": value.get("en")}


def sections(value) -> list:
    """``[{title:{mn,en}, body:{mn,en}, bullets:[{mn,en}]}]`` — the shape the app renders."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ServiceError(400, "invalid_sections", at="sections")
    clean = []
    for i, section in enumerate(value):
        where = f"sections[{i}]"
        if not isinstance(section, dict) or set(section) - {"title", "body", "bullets"}:
            raise ServiceError(400, "invalid_sections", at=where)
        bullets = section.get("bullets") or []
        if not isinstance(bullets, list):
            raise ServiceError(400, "invalid_sections", at=f"{where}.bullets")
        clean.append({
            "title": _loc(section.get("title"), f"{where}.title"),
            "body": _loc(section.get("body"), f"{where}.body"),
            "bullets": [_loc(b, f"{where}.bullets[{j}]", nullable=False)
                        for j, b in enumerate(bullets)],
        })
    return clean
