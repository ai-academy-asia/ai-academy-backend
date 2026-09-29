"""The one time source for sessions and check-in — tests patch :func:`now`.

Stored timestamps are naive UTC; the session calendar (dates, "HH:MM") is
Asia/Ulaanbaatar wall-clock time, so "today" and "late" are judged locally.
"""
from datetime import datetime, time, timedelta

from app import timeutil


def now() -> datetime:
    """Naive UTC, like every stored timestamp."""
    return timeutil.utcnow()


def local_now() -> datetime:
    """The current Ulaanbaatar wall-clock time (zone-aware)."""
    return timeutil.local(now())


def local_today():
    return local_now().date()


def local_start(session_date, start_time: str):
    """A session's start as a zone-aware Ulaanbaatar datetime, or ``None``."""
    if not start_time:
        return None
    hours, minutes = (int(part) for part in start_time.split(":"))
    return datetime.combine(session_date, time(hours, minutes), tzinfo=timeutil.LOCAL_TZ)


def plus_minutes(value: datetime, minutes: int) -> datetime:
    return value + timedelta(minutes=minutes)
