"""Parsing for ids and paging values that arrive as untrusted request input."""
from app.extensions import db

from .errors import ServiceError


def parse_id(value):
    """An id from a request body as an int, or ``None`` if it is not one.

    ``db.session.get`` hands the raw value to Postgres, which answers a string
    like ``"abc"`` with a DataError — a 500 for what is simply "no such row".
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_by_id(model, value):
    """``db.session.get`` for an id straight off a request: ``None`` unless it parses."""
    pk = parse_id(value)
    return db.session.get(model, pk) if pk is not None else None


def parse_limit(value, default=50, maximum=200) -> int:
    """A listing's ``?limit=``, clamped to 1..maximum. Garbage is a 400."""
    if value in (None, ""):
        return default
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        raise ServiceError(400, "invalid_limit") from None
