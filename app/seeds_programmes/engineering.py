"""AI Engineering — the 8-month in-person ML Engineer track, mid-way through module 5."""
from __future__ import annotations

from decimal import Decimal

from .engineering_curriculum import EXAM_TITLES, MODULES
from .engineering_quizzes import QUIZZES
from .spec import Programme

# lesson title -> (title mn, instructions mn); due a week after the class.
ASSIGNMENTS = {
    "Working with lists": ("Жагсаалтын дасгал",
                           "10 бодлогыг list ашиглан бодож, notebook-оо GitHub-д оруулна."),
    "Working with files": ("Файлтай ажиллах мини төсөл",
                           "CSV файл уншиж, тайлан бичдэг скрипт бичих."),
    "Review pandas: EDA on full data mini project": (
        "EDA мини төсөл (Kaggle)", "Kaggle-ийн датасет сонгож бүрэн EDA хийж, дүгнэлт бич."),
    "Decision trees": ("Titanic — ангиллын загвар",
                       "Logistic regression ба decision tree-г харьцуулж, accuracy/F1 тайлагна."),
    "PCA (2)": ("PCA дасгал", "MNIST дээр PCA хийж, 2D дүрслэл гарга."),
    "Image classification": ("CNN зураг ангилал",
                             "PyTorch-оор CNN сургаж, validation accuracy ≥ 85% хүргэ."),
    "Building an LLM app and RAG": ("RAG чатбот",
                                    "Өөрийн баримт бичиг дээр RAG чатбот хийж demo бичлэг илгээ."),
    "Backend development: FastAPI, data management & ML integration": (
        "ML загварыг FastAPI-аар үйлчлэх", "Өмнөх загвараа /predict endpoint-оор гарга."),
    "Capstone start: project proposal": (
        "Capstone төслийн санал", "Асуудал, өгөгдөл, арга, хуваарийг 2 нүүрт багтаан бич."),
    "DevOps & deployment: Docker, CI/CD pipeline": (
        "Docker + CI/CD", "FastAPI сервисээ Docker-т хийж GitHub Actions pipeline тохируул."),
    "Capstone II: building seminar / office hours": (
        "Capstone — эцсийн хувилбар", "Ажилладаг demo, код, 10 минутын илтгэлийн слайд."),
}

ENGINEERING = Programme(
    key="engineering",
    login_prefix="eng",
    course={
        "slug": "ai-engineering", "category": "bootcamp", "level": "adult",
        "title_mn": "AI Инженерийн хөтөлбөр", "title_en": "AI Engineering Program",
        "tagline_mn": "Python-оос LLM, MLOps хүртэл — 8 сарын интенсив хөтөлбөр",
        "tagline_en": "From Python to LLMs and MLOps — an 8-month intensive",
        "target_audience": "Програмчлал, өгөгдлийн чиглэлээр карьер хийх насанд хүрэгчид",
        "age_min": 18, "duration_label": "8 сар", "format": "in_person", "capacity": 25,
        "description_mn": ("Python, өгөгдлийн шинжилгээ, машин сургалт, гүн сургалт, backend, "
                           "MLOps, Agentic AI-г хамарсан ML Engineer бэлтгэх хөтөлбөр. "
                           "Төгсөлтийн төсөлтэй."),
        "description_en": ("An ML Engineer track covering Python, data analysis, ML, deep "
                           "learning, backend, MLOps and agentic AI, ending in a capstone."),
        "prerequisites_mn": "Компьютерийн анхан шатны мэдлэг. Өөрийн зөөврийн компьютер.",
        "has_exam": True, "has_final_project": True, "final_project_type": "capstone",
        "whats_included": ["95 танхимын хичээл", "Хичээлийн бичлэг", "Mentor-ийн дэмжлэг",
                           "Төгсөлтийн гэрчилгээ"],
        "instructors": [{"name": "Батзориг Энхтайван", "title": "Lead ML Engineer"},
                        {"name": "Ганбаяр Түмэнжаргал", "title": "Backend Engineer"}],
    },
    modules=MODULES,
    teachers=[
        ("eng.teacher", "Батзориг", "Энхтайван", "99110001",
         "Lead ML Engineer. Python, ML, Deep Learning хичээлүүдийг заана."),
        ("eng.teacher2", "Ганбаяр", "Түмэнжаргал", "99110002",
         "Backend Engineer. FastAPI, SQL, DevOps хичээлүүдийг заана."),
    ],
    students=[
        ("eng.s01", "Тэмүүлэн", "Батбаяр", "88010001", 1998, 0.98, "paid"),
        ("eng.s02", "Номин", "Ганболд", "88010002", 2000, 0.95, "on_track"),
        ("eng.s03", "Анужин", "Мөнхбат", "88010003", 1996, 0.90, "paid"),
        ("eng.s04", "Билгүүн", "Отгонбаяр", "88010004", 2001, 0.85, "on_track"),
        ("eng.s05", "Сарнай", "Дорж", "88010005", 1999, 0.80, "overdue"),
        ("eng.s06", "Энхжин", "Пүрэвдорж", "88010006", 1995, 0.78, "on_track"),
        ("eng.s07", "Хүслэн", "Цэрэндорж", "88010007", 2002, 0.72, "on_track"),
        ("eng.s08", "Мөнх-Эрдэнэ", "Сүхбаатар", "88010008", 1993, 0.65, "overdue"),
        ("eng.s09", "Ариунаа", "Лхагва", "88010009", 1997, 0.58, "on_track"),
        ("eng.s10", "Төгөлдөр", "Нямдорж", "88010010", 2003, 0.50, "overdue"),
    ],
    dropped=("eng.s11", "Золбоо", "Баатар", "88010011", 2000, 0.30, "paid"),
    cohort={
        "name": "AI Engineering — Cohort 3", "capacity": 25,
        "meeting_days": ["mon", "wed", "fri"],
        "schedule_note": "Даваа, Лхагва, Баасан 19:00–21:30. Наадмын амралтаар хичээлгүй.",
    },
    weekdays=(0, 2, 4), start_time="19:00", end_time="21:30",
    current_lesson=78,                # module 5, lesson 8
    price=Decimal("9900000"),
    installments=[(-7, Decimal("0.3")), (75, Decimal("0.7") / 3),
                  (150, Decimal("0.7") / 3), (225, Decimal("0.7") / 3)],
    room="Engineering Lab 401",
    quizzes=QUIZZES, exam_titles=EXAM_TITLES, assignments=ASSIGNMENTS,
    news=("Модуль 5 эхэллээ", "Програм хангамж, MLOps ба Agentic AI модуль нээгдлээ."),
)
