"""The two 2026 Junior AI summer camps — finished runs on their real dates.

Unlike the running programmes these are laid out from ``first_day``, so every
class is in the past: all modules open, attendance complete, and the most
diligent students meet every certificate requirement (ready to be issued).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from .junior_summer import KIDS_ASSIGNMENTS, KIDS_MODULES, KIDS_QUIZZES
from .junior_summer_teens import TEEN_ASSIGNMENTS, TEEN_MODULES, TEEN_QUIZZES
from .spec import Programme

_SHARED = {
    "category": "bootcamp", "level": "junior", "format": "in_person",
    "duration_label": "11 хичээл · 44 академик цаг",
    "has_exam": False, "has_final_project": True, "final_project_type": "demo_day",
    "whats_included": ["11 хичээл × 180 минут", "Demo Day", "Гэрчилгээ"],
}

KIDS = Programme(
    key="summer-kids",
    login_prefix="jr10",
    course={
        **_SHARED, "slug": "junior-ai-summer-10-14", "capacity": 20, "age_min": 10,
        "age_max": 14, "target_audience": "10–14 насны хүүхдүүд",
        "title_mn": "10–14 Junior AI зуны сургалт", "title_en": "Junior AI Summer Camp 10–14",
        "tagline_mn": "Playground блок ба Teachable Machine-ээр AI бүтээе",
        "tagline_en": "Build AI with Playground blocks and Teachable Machine",
        "description_mn": ("Хөтөлбөрийн дугаар KD2606. AI ойлголт, алгоритм, компьютерийн "
                           "хараа, дуу, хэлний загварыг Playground орчинд блокоор бүтээж, "
                           "Demo Day-д төслөө танилцуулна."),
        "description_en": ("Programme KD2606: AI basics, algorithms, vision, sound and "
                           "language models built with blocks, ending at Demo Day."),
        "instructors": [{"name": "Ану Мөнхбаяр", "title": "Junior AI багш"}],
    },
    modules=KIDS_MODULES,
    teachers=[("jr10.teacher", "Ану", "Мөнхбаяр", "99160001",
               "Junior AI багш. Playground, Teachable Machine.")],
    students=[
        ("jr10.s01", "Төгс", "Батболд", "88060001", 2014, 0.98, "paid"),
        ("jr10.s02", "Мишээл", "Ганхуяг", "88060002", 2013, 0.96, "paid"),
        ("jr10.s03", "Тэмүүлэн", "Энхболд", "88060003", 2015, 0.92, "paid"),
        ("jr10.s04", "Хүсэл", "Отгонбаяр", "88060004", 2012, 0.88, "paid"),
        ("jr10.s05", "Бүжин", "Дашням", "88060005", 2014, 0.84, "overdue"),
        ("jr10.s06", "Эрхэс", "Батсайхан", "88060006", 2016, 0.78, "paid"),
        ("jr10.s07", "Анар", "Мөнхжаргал", "88060007", 2013, 0.72, "paid"),
        ("jr10.s08", "Ирмүүн", "Ганзориг", "88060008", 2015, 0.66, "paid"),
        ("jr10.s09", "Номиндарь", "Түвшинбаяр", "88060009", 2012, 0.58, "paid"),
        ("jr10.s10", "Ерөөл", "Баярмагнай", "88060010", 2016, 0.50, "overdue"),
    ],
    dropped=("jr10.s11", "Од", "Пүрэвсүрэн", "88060011", 2014, 0.20, "paid"),
    cohort={
        "name": "Junior AI 10–14 — Зун 2026", "capacity": 20,
        "meeting_days": ["tue", "thu", "sat"],
        "schedule_note": "Мягмар, Пүрэв, Бямба 09:00–12:00 (4 академик цаг).",
    },
    weekdays=(1, 3, 5), start_time="09:00", end_time="12:00",
    first_day=date(2026, 6, 16), current_lesson=10,
    price=Decimal("1200000"), installments=[(-5, Decimal("1"))],
    room="Room 201",
    quizzes=KIDS_QUIZZES, assignments=KIDS_ASSIGNMENTS, due_after_days=2,
    news=("Demo Day-д баяр хүргэе!", "Зуны сургалт амжилттай өндөрлөлөө."),
)

TEENS = Programme(
    key="summer-teens",
    login_prefix="jr14",
    course={
        **_SHARED, "slug": "junior-ai-summer-14-18", "capacity": 20, "age_min": 14,
        "age_max": 18, "target_audience": "14–18 насны сурагчид",
        "title_mn": "14–18 Junior AI зуны сургалт", "title_en": "Junior AI Summer Camp 14–18",
        "tagline_mn": "Python, өгөгдөл, машин сургалт — 11 хичээлд",
        "tagline_en": "Python, data and machine learning in 11 classes",
        "description_mn": ("Хөтөлбөрийн дугаар JN2606. Python, Pandas, өгөгдлийн дүрслэл, "
                           "scikit-learn-ээр ангилал, регресс, бүлэглэл хийж, capstone "
                           "төслөө Demo Day-д pitch хийнэ."),
        "description_en": ("Programme JN2606: Python, pandas, visualisation and scikit-learn, "
                           "ending with a capstone pitched at Demo Day."),
        "instructors": [{"name": "Билэгт Ганбат", "title": "Junior AI багш"}],
    },
    modules=TEEN_MODULES,
    teachers=[("jr14.teacher", "Билэгт", "Ганбат", "99170001",
               "Junior AI багш. Python, өгөгдлийн шинжилгээ, ML.")],
    students=[
        ("jr14.s01", "Амин-Эрдэнэ", "Цогтбаяр", "88070001", 2009, 0.98, "paid"),
        ("jr14.s02", "Сондор", "Мөнхсайхан", "88070002", 2010, 0.95, "paid"),
        ("jr14.s03", "Энэрэл", "Батжаргал", "88070003", 2008, 0.91, "paid"),
        ("jr14.s04", "Тэнүүн", "Ганболд", "88070004", 2011, 0.87, "paid"),
        ("jr14.s05", "Мөнгөншагай", "Эрдэнэбат", "88070005", 2009, 0.82, "paid"),
        ("jr14.s06", "Хангай", "Сүхбат", "88070006", 2010, 0.77, "overdue"),
        ("jr14.s07", "Ундрах", "Нямсүрэн", "88070007", 2012, 0.71, "paid"),
        ("jr14.s08", "Батмөнх", "Төмөрхуяг", "88070008", 2008, 0.64, "paid"),
        ("jr14.s09", "Сарангэрэл", "Болдбаатар", "88070009", 2011, 0.57, "overdue"),
        ("jr14.s10", "Жаргалсайхан", "Лхам", "88070010", 2010, 0.49, "paid"),
    ],
    dropped=("jr14.s11", "Цэлмэг", "Баттөмөр", "88070011", 2009, 0.20, "paid"),
    cohort={
        "name": "Junior AI 14–18 — Зун 2026", "capacity": 20,
        "meeting_days": ["mon", "wed", "fri"],
        "schedule_note": "Даваа, Лхагва, Баасан 14:00–17:00 (4 академик цаг).",
    },
    weekdays=(0, 2, 4), start_time="14:00", end_time="17:00",
    first_day=date(2026, 6, 15), current_lesson=10,
    price=Decimal("1200000"), installments=[(-5, Decimal("1"))],
    room="Room 202",
    quizzes=TEEN_QUIZZES, assignments=TEEN_ASSIGNMENTS, due_after_days=2,
    news=("Demo Day-д баяр хүргэе!", "Зуны сургалт амжилттай өндөрлөлөө."),
)
