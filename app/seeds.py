"""Turn the marketing site's hand-written programme cards into Course + Cohort rows.

The site shipped its catalogue as TypeScript literals (`spring-courses-data.ts`,
`summer-courses-data.ts`), exported verbatim to ``seeds/static-courses.json``.
Each entry there is one **run**: "Summer Bootcamp" appears eight times with
different days, times and age bands. Entries sharing (title, type, format, age)
are runs of the same programme, so seeding normalises them:

    23 static entries  ->  14 Course rows, 23 Cohorts

Idempotent — matched on the derived slug and the cohort's (date, start time), so
re-running updates rather than duplicating.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.extensions import db
from app.models import Cohort, CohortLegacySchedule, Course

SEED_FILE = Path(__file__).resolve().parent.parent / "seeds" / "static-courses.json"

# "Пу" is a typo for "Пү" in the source data; both mean Thursday.
_DAY_CODES = {"Да": "mon", "Мя": "tue", "Лх": "wed", "Пү": "thu", "Пу": "thu",
              "Ба": "fri", "Бя": "sat", "Ня": "sun"}
_LEVEL = {"junior-inclass": "junior", "junior-online": "junior",
          "adult": "adult", "corporate": "corporate"}
_FORMAT = {"Танхим": "in_person", "Онлайн": "online"}

# "09:00–12:00" and the compound "Пү 18:30–20:00 / Бя 14:00–17:00" (first wins).
_TIME_RE = re.compile(r"(\d{1,2}:\d{2})\s*[–\-—]\s*(\d{1,2}:\d{2})")
_AGE_RE = re.compile(r"(\d{1,2})\s*[–\-—]\s*(\d{1,2})")


def _slug(*parts: str) -> str:
    text = " ".join(p for p in parts if p)
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)


def _money(text: str) -> tuple[Decimal | None, str]:
    """('17,900,000₮') -> (17900000, 'MNT'); ('$1,600') -> (1600, 'USD')."""
    if not text:
        return None, "MNT"
    digits = re.sub(r"[^\d.]", "", text)
    if not digits:
        return None, "MNT"
    currency = "USD" if "$" in text else "MNT"
    return Decimal(digits), currency


def _percent(text: str) -> int:
    m = re.search(r"(\d+)", text or "")
    return int(m.group(1)) if m else 0


def _iso(text: str) -> date | None:
    """'2026/08/03' -> date. Blank strings are common and mean 'not set'."""
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _times(text: str) -> tuple[str | None, str | None]:
    m = _TIME_RE.search(text or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def _ages(text: str) -> tuple[int | None, int | None]:
    m = _AGE_RE.search(text or "")
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def load_entries(path: Path | None = None) -> list[dict]:
    data = json.loads((path or SEED_FILE).read_text(encoding="utf-8"))
    return data["courses"] if isinstance(data, dict) else data


def seed_courses(*, path: Path | None = None, publish: bool = False) -> dict:
    """Upsert the static catalogue. Returns a summary for the caller to print.

    ``publish`` marks the seeded courses ``published`` (and their cohorts
    ``open``) so they show up on ``/programmes`` immediately. Off by default:
    seeding prod should not silently put a programme on sale.
    """
    entries = load_entries(path)

    # Age band is part of the programme identity, not just a label: "Summer
    # Bootcamp 10–13" and "14–18" run at the same hour on the same day and are
    # separate classes with separate seats. Grouping without it silently merges
    # them and loses half the runs.
    groups: dict[tuple[str, str, str, str], list[dict]] = {}
    for e in entries:
        groups.setdefault(
            (e["title"], e["type"], e["format"], e.get("age") or ""), []
        ).append(e)

    summary = {"courses": 0, "cohorts": 0, "schedule_ids": 0, "updated": 0,
               "needs_mnt_price": []}

    for (title, type_, fmt, age), runs in groups.items():
        head = runs[0]
        slug = _slug(title, type_, age)
        # `mntPrice` is the MNT figure for `finalFee` — the price AFTER the
        # discount, not before it (301: fee $2,000, discount 50%, finalFee
        # $1,000, mntPrice ₮3,560,000 = $1,000 x 3,560). Storing it as the list
        # price and letting the discount apply again charges half.
        mnt_price, _ = _money(head.get("mntPrice"))
        discount = 0 if mnt_price is not None else _percent(head.get("discount", ""))
        if mnt_price is not None:
            amount, currency = mnt_price, "MNT"
        else:
            amount, currency = _money(head.get("fee"))
        age_min, age_max = _ages(head.get("age", ""))

        course = Course.query.filter_by(slug=slug).first()
        if course is None:
            course = Course(slug=slug)
            db.session.add(course)
            summary["courses"] += 1
        else:
            summary["updated"] += 1

        course.title_mn = title
        course.title_en = title
        course.level = _LEVEL.get(type_)
        course.format = _FORMAT.get(fmt)
        course.category = head.get("cohort")          # spring | summer
        course.target_audience = head.get("age")
        course.age_min, course.age_max = age_min, age_max
        course.duration_label = head.get("duration")
        course.price_amount = amount
        course.currency = currency
        course.discount_percent = discount
        course.whats_included = head.get("features") or []
        course.icon = head.get("badge")
        course.capacity = head.get("maxStudents")
        course.start_date = _iso(head.get("startDate"))
        course.end_date = _iso(head.get("endDate"))
        course.sort_order = head.get("num")
        course.legacy_course_id = head.get("backendCourseId")
        if publish:
            course.status = "published"
        elif not course.status:
            course.status = "draft"
        db.session.flush()

        if currency != "MNT":
            summary["needs_mnt_price"].append(f"{title} ({head.get('fee')})")

        for run in runs:
            start = _iso(run.get("startDate"))
            start_time, end_time = _times(run.get("time", ""))
            days = [_DAY_CODES[d] for d in run.get("activeDays", []) if d in _DAY_CODES]

            cohort = Cohort.query.filter_by(
                course_id=course.id, start_date=start, start_time=start_time
            ).first()
            if cohort is None:
                cohort = Cohort(course_id=course.id)
                db.session.add(cohort)
                summary["cohorts"] += 1

            label = " ".join(filter(None, [run.get("classType"), age]))
            cohort.name = f"{title} {start.isoformat() if start else ''} {label}".strip()
            cohort.start_date = start
            cohort.end_date = _iso(run.get("endDate"))
            cohort.capacity = run.get("maxStudents")
            cohort.meeting_days = days
            cohort.start_time, cohort.end_time = start_time, end_time
            cohort.schedule_note = run.get("time")   # keep the compound original
            cohort.legacy_schedule_id = run.get("backendScheduleId")
            cohort.legacy_course_id = run.get("backendCourseId")
            db.session.flush()   # need cohort.id for the schedule-id map
            summary["schedule_ids"] += _map_legacy_schedules(cohort, run)
            if publish:
                cohort.status = "open"
            elif not cohort.status:
                cohort.status = "draft"

    db.session.commit()
    return summary


# Which static field is which payment terms, and what share of the price it
# bills. The deposit share is per-course (`advancePaymentPercent`), defaulting
# to the site's own DEPOSIT_PERCENT.
DEFAULT_DEPOSIT_PERCENT = 30
_SCHEDULE_FIELDS = (
    ("backendScheduleId", "full", False),
    ("depositScheduleId", "deposit", True),
    ("promoScheduleId", "promo", False),
    ("promoDepositScheduleId", "promo_deposit", True),
)


def _map_legacy_schedules(cohort: Cohort, run: dict) -> int:
    """Point every legacy schedule id this run published at ``cohort``.

    The site posts whichever id matches the terms the buyer chose, and all of
    them are the same seat in the same class — so they resolve to one cohort and
    differ only in what fraction of the price they charge.
    """
    deposit = int(run.get("advancePaymentPercent") or DEFAULT_DEPOSIT_PERCENT)
    written = 0
    for field, kind, is_deposit in _SCHEDULE_FIELDS:
        legacy_id = run.get(field)
        if not legacy_id:
            continue
        row = db.session.get(CohortLegacySchedule, int(legacy_id))
        if row is None:
            row = CohortLegacySchedule(legacy_schedule_id=int(legacy_id))
            db.session.add(row)
        row.cohort_id = cohort.id
        row.kind = kind
        row.charge_percent = deposit if is_deposit else 100
        written += 1
    return written
