"""Junior AI summer syllabi (2026-06-15 – 07-09, 11 classes × 180 min, 44 academic hours).

Two approved programmes: KD2606 for ages 10–14 (Playground blocks, Teachable
Machine) and JN2606 for ages 14–18 (Python, pandas, scikit-learn). Goals and
practice are the programme sheets' wording.
"""
from __future__ import annotations

from .spec import Lesson

KIDS_MODULES = [
    {"name_mn": "AI ойлголт ба Playground", "name_en": "AI Basics & Playground", "lessons": [
        Lesson("AI танилцуулга + Playground танилцуулга", "AI intro + Playground intro",
               goal=("AI гэж юу, өдөр тутамд хаана таарагддагийг ялгана. Playground орчны "
                     "блок, тайз, дүрийн зарчмыг ойлгоно."),
               practice=("5 AI жишээ олж ангилна. Playground-д дүрээ хөдөлгөж, «Сайн уу» "
                         "гэдэг бяцхан хэсэг үүсгэнэ."),
               topics=("AI гэж юу вэ", "Блок, тайз, дүр")),
        Lesson("Computer Vision + Algorithmic Thinking I",
               "Computer vision + algorithmic thinking I",
               goal=("Нүд vs камер хэрхэн «хардаг», пиксел/зураг танилтыг тайлбарлана. "
                     "Алгоритм = дараалсан алхам гэдгийг ойлгоно."),
               practice=("Пиксел торгоор компьютер юу хардгийг үзнэ. Өдөр тутмын үйлдлийг "
                         "цаасан дээр алхмаар алгоритм болгоно."),
               topics=("Пиксел", "Зураг таних", "Алгоритм")),
        Lesson("Audio recognition + Algorithmic Thinking II",
               "Audio recognition + algorithmic thinking II",
               goal=("Чимээ долгион болж дүрслэгддэг, компьютер дуу хоолойг хэрхэн таньдгийг "
                     "тайлбарлана. Нөхцөл салаа сэтгэлгээ нэмнэ."),
               practice=("Дуу хоолойгоо бичиж долгионыг ажиглана. Цаасан алгоритмаа "
                         "Playground блок руу шилжүүлж if-then нэмнэ."),
               topics=("Дууны долгион", "If-then")),
        Lesson("NLP үндэс + Dynamic Programming", "NLP basics + dynamic programming",
               goal=("Хүн ба машин үг/өгүүлбэрийг ойлгох ялгааг тайлбарлана. Нөхцөл, "
                     "давталт, хувьсагчийг кодод ашиглана."),
               practice=("Өгүүлбэрийг машин шиг үгээр задлана. Playground-д оноо тоолдог, "
                         "давталттай харилцан үйлдэл бүтээнэ."),
               topics=("Үг задлах", "Давталт", "Хувьсагч")),
        Lesson("What is Data? + Games", "What is data? + games",
               goal="Өгөгдлийн төрөл, цэвэр vs бохир өгөгдлийг ялгана. Тоглоомын логик зохионо.",
               practice=("Англи хэлээр жижиг өгөгдөл цуглуулж ангилна. Playground-д оноо, "
                         "дүрэмтэй бүрэн тоглоом бүтээнэ."),
               topics=("Өгөгдлийн төрөл", "Цэвэр / бохир өгөгдөл", "Тоглоомын логик")),
        Lesson("Machine Learning: Intro + Animations", "Machine learning: intro + animations",
               goal=("ML = жишээнээс хэв маяг сурах гэдгийг ойлгоно. Анимацийн зарчим "
                     "эзэмшинэ. Төгсгөлд 1-р модулийн 15 минутын давтлага."),
               practice=("«Машинд муур/нохой танихыг хэрхэн сургах вэ» хэлэлцэнэ. "
                         "Playground-д богино анимаци (түүх) бүтээнэ."),
               topics=("Жишээнээс сурах", "Анимаци", "Модулийн давтлага")),
    ]},
    {"name_mn": "AI загвар: хараа, сонсгол, хэл", "name_en": "AI Models: Vision, Sound, Language",
     "lessons": [
        Lesson("AI Ethics + Image Classification & Pose", "AI ethics + image classification & pose",
               goal=("Өрөөсгөл хандлага, нууцлал, шударга байдлыг хэлэлцэнэ. Зураг ангилал ба "
                     "поз танихын зарчмыг ойлгоно. Эхэнд «блок→AI блок гүүр» 20 минут."),
               practice=("«Энэ AI шударга уу?» хэлэлцүүлэг. Playground-ийн PoseBlocks-оор "
                         "хөдөлгөөн танилж, зураг ангиллын загвар (эсвэл TM импорт) ашиглана."),
               topics=("Шударга байдал", "Нууцлал", "PoseBlocks")),
        Lesson("Audio + Emotion танилт", "Audio + emotion recognition",
               goal=("Дуу ба нүүрний хувирлыг ML-ээр таних хэрэглээг гараар туршина. Загвар "
                     "сургах нийтлэг алхмыг тогтооно."),
               practice=("Teachable Machine-д дуу/нүүр загвар сургаад Playground-д импортлон "
                         "блокоор холбоно (алга таших, сэтгэл хөдлөлд хариу үзүүлэх)."),
               topics=("Teachable Machine", "Дуу таних", "Нүүрний хувирал")),
        Lesson("NLP Text Classification", "NLP text classification",
               goal=("Текст ангиллын ML хэрэглээг бүтээж, гурван мэдрэхүйн (хараа–сонсгол–хэл) "
                     "ажлыг нэгтгэн дүгнэнэ. Төгсгөлд 3-р модулийн 15 минутын давтлага."),
               practice=("Playground-ийн текст ангиллын блокоор эерэг/сөрөг өгүүлбэр таних "
                         "загвар бүтээж сургана. Гурван ML дасгалаа харьцуулна."),
               topics=("Текст ангилал", "Эерэг / сөрөг", "Харьцуулалт")),
    ]},
    {"name_mn": "Capstone ба Demo Day", "name_en": "Capstone & Demo Day", "lessons": [
        Lesson("Capstone 1", "Capstone 1",
               goal="Асуудлаа тодорхойлж, өгөгдлөө төлөвлөнө. Загвараа эхлүүлнэ.",
               practice=("Санаа сонгох, өгөгдөл цуглуулах төлөвлөгөө гаргана. Ёс зүйн хяналтын "
                         "жагсаалт бөглөж, Playground-д загвараа эхлүүлнэ."),
               topics=("Асуудал", "Өгөгдлийн төлөвлөгөө", "Ёс зүйн жагсаалт")),
        Lesson("Capstone 2 + Demo Day", "Capstone 2 + Demo Day",
               goal="Бүтээлээ эцэслэж, туршиж сайжруулах, бусдад танилцуулах чадвар эзэмшинэ.",
               practice=("Playground төслөө дуусгаж, дэмо/слайд бэлтгэнэ. Demo Day-д "
                         "танилцуулж харилцан үнэлгээ өгнө."),
               topics=("Demo", "Харилцан үнэлгээ")),
    ]},
]

KIDS_QUIZZES = {
    "Machine learning: intro + animations": ("1-р модулийн давтлага", "Module 1 review", [
        ("Алгоритм гэж юу вэ?", 1,
         ["Дараалсан алхмууд", "Компьютерийн нэр", "Зураг", "Тоглоом"], 0, None),
        ("Компьютер зургийг юугаар «хардаг» вэ?", 1,
         ["Үгээр", "Пикселээр", "Дуугаар", "Өнгөгүй"], 1, None),
        ("Машин сургалт гэж?", 2,
         ["Машиныг угаах", "Жишээнээс хэв маяг сурах", "Интернэт хайх", "Зураг зурах"], 1,
         "Олон муур, нохойн зураг үзүүлбэл машин ялгаж сурна."),
        ("Аль нь бохир өгөгдөл вэ?", 1,
         ["Зөв бичсэн нэрс", "Алдаатай, дутуу мөрүүд", "Тоонууд", "Огноо"], 1, None),
    ]),
}

KIDS_ASSIGNMENTS = {
    "AI intro + Playground intro": ("5 AI жишээ", "Өдөр тутамд тааралддаг 5 AI жишээ олж ангил."),
    "What is data? + games": ("Playground тоглоом", "Оноо, дүрэмтэй тоглоомынхоо холбоос."),
    "Machine learning: intro + animations": ("Анимаци түүх", "Playground анимацийн холбоос."),
    "Audio + emotion recognition": (
        "Teachable Machine загвар", "Дуу эсвэл нүүрний загвараа Playground-д холбосон бичлэг."),
    "NLP text classification": ("Текст ангилагч", "Эерэг/сөрөг өгүүлбэр таних загвар."),
    "Capstone 1": ("Capstone төлөвлөгөө", "Санаа, өгөгдлийн төлөвлөгөө, ёс зүйн жагсаалт."),
    "Capstone 2 + Demo Day": ("Capstone төсөл", "Playground төслийн холбоос ба слайд."),
}
