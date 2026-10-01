"""The two runs of the applied AI syllabus: Corporate Leaders (in person) and Online.

Same twelve classes, separate courses — each has its own price, cohort, teacher
and students, so either can be tested (or reset) without touching the other.
"""
from __future__ import annotations

from decimal import Decimal

from .applied_ai import ASSIGNMENTS, MODULES, QUIZZES
from .spec import Programme

_SHARED = {
    "category": "corporate", "level": "adult", "age_min": 18,
    "has_exam": False, "has_final_project": True, "final_project_type": "capstone",
    "whats_included": ["12 хичээл", "Дадлага бүрт mentor", "Capstone төсөл", "Гэрчилгээ"],
}

CORPORATE = Programme(
    key="corporate",
    login_prefix="corp",
    course={
        **_SHARED, "slug": "ai-corporate-leaders", "format": "in_person", "capacity": 20,
        "title_mn": "AI for Corporate Leaders", "title_en": "AI for Corporate Leaders",
        "tagline_mn": "Удирдах ажилтнуудад: AI-г ажилдаа нэвтрүүлж, өөрийн AI туслах бүтээх",
        "tagline_en": "For leaders: put AI to work and build your own AI assistant",
        "target_audience": "Байгууллагын удирдах ажилтан, менежерүүд",
        "duration_label": "12 долоо хоног",
        "description_mn": ("GenAI, prompt engineering, vibe coding, AI agent, RAG, n8n "
                           "автоматжуулалт, бүтээлч AI ба deployment — 12 хичээл, "
                           "Demo day-д төгсөлтийн төслөө танилцуулна."),
        "description_en": ("GenAI, prompting, vibe coding, AI agents, RAG, n8n automation, "
                           "creative AI and deployment in 12 classes, ending at Demo day."),
        "instructors": [{"name": "Оюунчимэг Баттулга", "title": "AI Solutions Lead"}],
    },
    modules=MODULES,
    teachers=[("corp.teacher", "Оюунчимэг", "Баттулга", "99120001",
               "AI Solutions Lead. Байгууллагад AI нэвтрүүлэх 6 жилийн туршлагатай.")],
    students=[
        ("corp.s01", "Ганбат", "Должин", "88020001", 1978, 0.97, "paid"),
        ("corp.s02", "Оюун-Эрдэнэ", "Цогт", "88020002", 1984, 0.94, "paid"),
        ("corp.s03", "Батхуяг", "Нэргүй", "88020003", 1975, 0.90, "paid"),
        ("corp.s04", "Сондор", "Жаргал", "88020004", 1986, 0.88, "on_track"),
        ("corp.s05", "Мөнхзул", "Алтангэрэл", "88020005", 1981, 0.84, "paid"),
        ("corp.s06", "Эрдэнэбат", "Гомбо", "88020006", 1972, 0.80, "on_track"),
        ("corp.s07", "Наранцэцэг", "Бат-Очир", "88020007", 1988, 0.76, "overdue"),
        ("corp.s08", "Төмөрбаатар", "Шаравдорж", "88020008", 1979, 0.70, "paid"),
        ("corp.s09", "Уранчимэг", "Дамдин", "88020009", 1990, 0.64, "on_track"),
        ("corp.s10", "Цолмон", "Энхбаяр", "88020010", 1983, 0.55, "overdue"),
    ],
    dropped=("corp.s11", "Баярсайхан", "Лувсан", "88020011", 1980, 0.30, "paid"),
    cohort={
        "name": "Corporate Leaders — 2026 намар", "capacity": 20, "meeting_days": ["thu"],
        "schedule_note": "Пүрэв гараг бүр 18:30–21:30, 12 долоо хоног.",
    },
    weekdays=(3,), start_time="18:30", end_time="21:30",
    current_lesson=7,                 # module 3, lesson 2 (n8n) — started 2026-08-06
    price=Decimal("4900000"),
    installments=[(-7, Decimal("0.5")), (35, Decimal("0.5"))],
    room="Executive Room 302",
    quizzes=QUIZZES, assignments=ASSIGNMENTS, due_after_days=6,
    news=("Demo day-ийн огноо", "Capstone Demo day 12 дахь хичээл дээр болно. Бэлдээрэй!"),
)

ONLINE = Programme(
    key="online",
    login_prefix="online",
    course={
        **_SHARED, "category": "online", "slug": "ai-applied-online", "format": "online",
        "capacity": 40,
        "title_mn": "Applied AI — Онлайн", "title_en": "Applied AI — Online",
        "tagline_mn": "Өглөөний 1.5 цагийн онлайн хичээлээр AI-г ажилдаа нэвтрүүл",
        "tagline_en": "Put AI to work in 90-minute online morning classes",
        "target_audience": "AI-г ажилдаа хэрэглэх хүсэлтэй насанд хүрэгчид",
        "duration_label": "6 долоо хоног",
        "description_mn": ("Corporate Leaders хөтөлбөрийн 12 хичээлийг онлайнаар, "
                           "долоо хоногт 2 удаа. Хичээл бүр бичлэгтэй."),
        "description_en": "The Corporate Leaders syllabus online, twice a week, recorded.",
        "instructors": [{"name": "Тэнгис Ганзориг", "title": "AI Engineer"}],
    },
    modules=MODULES,
    teachers=[("online.teacher", "Тэнгис", "Ганзориг", "99130001",
               "AI Engineer. Онлайн хичээл, AI agent, автоматжуулалт.")],
    students=[
        ("online.s01", "Хулан", "Ням-Очир", "88030001", 1995, 0.96, "paid"),
        ("online.s02", "Бат-Эрдэнэ", "Зориг", "88030002", 1990, 0.92, "paid"),
        ("online.s03", "Солонго", "Түвшин", "88030003", 1998, 0.88, "paid"),
        ("online.s04", "Амарбаясгалан", "Очир", "88030004", 1987, 0.82, "paid"),
        ("online.s05", "Гэрэлмаа", "Сэр-Од", "88030005", 1993, 0.78, "overdue"),
        ("online.s06", "Жавхлан", "Ганхуяг", "88030006", 2000, 0.72, "paid"),
        ("online.s07", "Энхтуяа", "Мягмар", "88030007", 1985, 0.66, "paid"),
        ("online.s08", "Дөлгөөн", "Батсүх", "88030008", 1996, 0.60, "overdue"),
        ("online.s09", "Мишээл", "Энх-Амгалан", "88030009", 2001, 0.52, "paid"),
        ("online.s10", "Ерөөлт", "Сүхээ", "88030010", 1992, 0.45, "paid"),
    ],
    dropped=("online.s11", "Хонгор", "Батжаргал", "88030011", 1994, 0.20, "paid"),
    cohort={
        "name": "Applied AI Online — 2026-09", "capacity": 40, "meeting_days": ["tue", "thu"],
        "schedule_note": "Мягмар, Пүрэв 07:30–09:00, Zoom. Бичлэг хичээлийн дараа орно.",
    },
    weekdays=(1, 3), start_time="07:30", end_time="09:00",
    current_lesson=3,                 # module 2, lesson 1
    price=Decimal("1490000"),
    installments=[(-3, Decimal("1"))],
    quizzes=QUIZZES, assignments=ASSIGNMENTS, due_after_days=4,
    news=("Zoom холбоос", "Хичээл бүрийн Zoom холбоос ангийн хуваарь дээр байна."),
)
