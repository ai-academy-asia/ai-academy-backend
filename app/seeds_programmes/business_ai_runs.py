"""The two runs of the 14-class business syllabus: Agentic AI and AI for Business.

Same classes, separate courses — each with its own schedule, price, room,
teacher and students, so either can be tested (or reset) without the other.
"""
from __future__ import annotations

from decimal import Decimal

from .business_ai import ASSIGNMENTS, MODULES, QUIZZES
from .spec import Programme

_SHARED = {
    "level": "adult", "age_min": 18, "format": "hybrid", "duration_label": "14 хичээл",
    "has_exam": False, "has_final_project": True, "final_project_type": "demo",
    "whats_included": ["14 хичээл", "Танхимын workshop + онлайн давтлага",
                       "Ажилладаг Admin Panel + AI чат", "Гэрчилгээ"],
    "prerequisites_mn": "Өөрийн зөөврийн компьютер, Facebook Page.",
}

AGENTIC = Programme(
    key="agentic",
    login_prefix="agentic",
    course={
        **_SHARED, "slug": "agentic-ai", "category": "bootcamp", "capacity": 24,
        "title_mn": "Agentic AI", "title_en": "Agentic AI",
        "tagline_mn": "n8n AI агент, Admin Panel, Messenger AI чат — өөрийн системээ бүтээ",
        "tagline_en": "Build your own system: n8n AI agents, an Admin Panel, a Messenger AI chat",
        "target_audience": "AI агентаар ажлаа автоматжуулах хүсэлтэй хүмүүс",
        "description_mn": ("Брэнд, мэдлэгийн сангаас эхлээд контентын AI агент, Admin Panel, "
                           "Facebook холболт, RAG чат хүртэл нэгдсэн систем бүтээнэ."),
        "description_en": ("From brand and knowledge base to a content agent, an Admin Panel, "
                           "Facebook and a RAG chat — one working system."),
        "instructors": [{"name": "Мөнхтулга Эрдэнэ", "title": "AI Automation Engineer"}],
    },
    modules=MODULES,
    teachers=[("agentic.teacher", "Мөнхтулга", "Эрдэнэ", "99140001",
               "AI Automation Engineer. n8n, AI агент, Facebook интеграци.")],
    students=[
        ("agentic.s01", "Анударь", "Болд", "88040001", 1997, 0.96, "paid"),
        ("agentic.s02", "Тэмүүжин", "Ганзориг", "88040002", 1994, 0.92, "paid"),
        ("agentic.s03", "Маралмаа", "Цэцэг", "88040003", 1999, 0.88, "on_track"),
        ("agentic.s04", "Баясгалан", "Мөнх", "88040004", 1991, 0.84, "paid"),
        ("agentic.s05", "Нандин-Эрдэнэ", "Жамц", "88040005", 2001, 0.80, "on_track"),
        ("agentic.s06", "Өлзий", "Түмэн", "88040006", 1989, 0.74, "overdue"),
        ("agentic.s07", "Халиун", "Дашдорж", "88040007", 1996, 0.70, "on_track"),
        ("agentic.s08", "Сүх-Очир", "Баасан", "88040008", 1993, 0.62, "paid"),
        ("agentic.s09", "Есүй", "Ганбаатар", "88040009", 2002, 0.56, "overdue"),
        ("agentic.s10", "Мөнгөнцэцэг", "Пүрэв", "88040010", 1986, 0.48, "on_track"),
    ],
    dropped=("agentic.s11", "Тэлмүүн", "Ариунболд", "88040011", 1998, 0.25, "paid"),
    cohort={
        "name": "Agentic AI — 2026 намар", "capacity": 24, "meeting_days": ["tue", "thu"],
        "schedule_note": ("Мягмар, Пүрэв 19:00–21:00. Давтлага 1 танхимд, "
                          "Давтлага 2 Zoom/Meet-ээр."),
    },
    weekdays=(1, 3), start_time="19:00", end_time="21:00",
    current_lesson=8,                 # module 3, lesson 2 (Deployment)
    price=Decimal("2900000"),
    installments=[(-7, Decimal("0.5")), (21, Decimal("0.5"))],
    room="Room 303",
    quizzes=QUIZZES, assignments=ASSIGNMENTS, due_after_days=5,
    news=("Давтлага 2 онлайн", "13 дахь хичээл Zoom/Meet-ээр болно. Холбоос хуваарь дээр."),
)

BUSINESS = Programme(
    key="business",
    login_prefix="biz",
    course={
        **_SHARED, "slug": "ai-for-business", "category": "corporate", "capacity": 20,
        "title_mn": "AI for Business", "title_en": "AI for Business",
        "tagline_mn": "Бизнесээ AI-аар: брэнд, контент, автомат нийтлэл, AI чат",
        "tagline_en": "Your business on AI: brand, content, automated posting, AI chat",
        "target_audience": "Бизнес эрхлэгч, маркетинг, борлуулалтын ажилтнууд",
        "description_mn": ("Бизнес эрхлэгчдэд зориулсан 14 хичээл: брэнд ба контентоо AI-аар "
                           "бүтээж, Facebook-оо Admin Panel-аас удирдаж, Messenger-т AI чат "
                           "ажиллуулна."),
        "description_en": ("14 classes for business owners: AI-made brand and content, Facebook "
                           "run from an Admin Panel, and an AI chat on Messenger."),
        "instructors": [{"name": "Одгэрэл Наранбаатар", "title": "AI Business Consultant"}],
    },
    modules=MODULES,
    teachers=[("biz.teacher", "Одгэрэл", "Наранбаатар", "99150001",
               "AI Business Consultant. Жижиг, дунд бизнест AI нэвтрүүлэх зөвлөх.")],
    students=[
        ("biz.s01", "Энхбаяр", "Гантулга", "88050001", 1982, 0.95, "paid"),
        ("biz.s02", "Сэлэнгэ", "Батмөнх", "88050002", 1988, 0.91, "paid"),
        ("biz.s03", "Чинзориг", "Должинсүрэн", "88050003", 1979, 0.87, "paid"),
        ("biz.s04", "Оюунбилэг", "Нацаг", "88050004", 1990, 0.83, "overdue"),
        ("biz.s05", "Бямбадорж", "Содном", "88050005", 1985, 0.78, "paid"),
        ("biz.s06", "Ундрал", "Хишиг", "88050006", 1993, 0.73, "paid"),
        ("biz.s07", "Гантөмөр", "Лувсанжав", "88050007", 1976, 0.67, "paid"),
        ("biz.s08", "Нарантуяа", "Сэржмядаг", "88050008", 1984, 0.60, "overdue"),
        ("biz.s09", "Батзаяа", "Отгон", "88050009", 1995, 0.54, "paid"),
        ("biz.s10", "Алтанхуяг", "Бүрэн", "88050010", 1980, 0.46, "paid"),
    ],
    dropped=("biz.s11", "Зоригт", "Санжаа", "88050011", 1987, 0.20, "paid"),
    cohort={
        "name": "AI for Business — 2026-09", "capacity": 20, "meeting_days": ["sat"],
        "schedule_note": "Бямба гараг бүр 10:00–13:00. Давтлага 2 Zoom/Meet-ээр.",
    },
    weekdays=(5,), start_time="10:00", end_time="13:00",
    current_lesson=4,                 # module 2, lesson 1 (n8n)
    price=Decimal("1990000"),
    installments=[(-5, Decimal("1"))],
    room="Room 304",
    quizzes=QUIZZES, assignments=ASSIGNMENTS, due_after_days=6,
    news=("Brand Book-оо бэлдээрэй", "Контентын AI агент хичээлд Brand Book хэрэгтэй."),
)
