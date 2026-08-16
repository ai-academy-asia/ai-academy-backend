"""One place that decides what a timestamp means on the way out.

Everything is **stored** in UTC (`datetime.utcnow()`, naive). That is the right
thing to keep in the database, but a naive ``2026-08-16T14:03:08`` on the wire is
read as *local* time by a browser (`new Date(...)` on a string without an offset
uses the viewer's zone), so a receipt issued at 22:03 in Ulaanbaatar showed up as
14:03 — eight hours out, and a seat hold looked expired the moment it was made.

So: JSON carries the offset (:func:`iso`), and anything a person reads as a wall
clock — receipt emails — is converted to Mongolian time first (:func:`local`).
Mongolia has not observed DST since 2016, but ``ZoneInfo`` is used rather than a
hardcoded +08:00 so that a future change is a tzdata update, not a bug hunt.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Ulaanbaatar")


def utcnow() -> datetime:
    """The clock every stored timestamp is written from."""
    return datetime.utcnow()


def iso(value: datetime | date | None) -> str | None:
    """ISO-8601 for an API payload: datetimes carry a zone, dates stay bare.

    A ``date`` is a calendar day, not an instant — stamping it with an offset
    would turn "starts on the 6th" into an instant that is the 5th somewhere.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()
    return value.isoformat()


def local(value: datetime | None) -> datetime | None:
    """A stored UTC timestamp as Mongolian wall-clock time, for human text."""
    if value is None:
        return None
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(LOCAL_TZ)
