"""JN2606 — Junior AI summer programme for ages 14–18 (Python, data, ML, capstone)."""
from __future__ import annotations

from .spec import Lesson

TEEN_MODULES = [
    {"name_mn": "AI ба Python-ийн үндэс", "name_en": "AI & Python Basics", "lessons": [
        Lesson("Нээлт + Хиймэл оюун ухаан гэж юу вэ?", "Opening: what is artificial intelligence?",
               goal=("AI-н үндсэн ойлголт, салбаруудыг тодорхойлж, бодит амьдрал дахь хэрэглээ "
                     "болон ёс зүйн асуудлыг жишээгээр тайлбарлаж, дэвшилтэт хэрэгслээр анхны "
                     "бүтээл хийж чадна."),
               practice="Орчин үеийн AI хэрэгслээр дуу, зураг, видео үүсгэх.",
               topics=("Салбарууд ба бодит жишээ", "Давуу ба сул тал, ёс зүй",
                       "Түүх ба өнөөгийн дүр зураг", "Тренд хэрэгслүүд")),
        Lesson("Computational Thinking ба Algorithmic Design + Python танилцуулга",
               "Computational thinking, algorithmic design + intro to Python",
               goal=("Бодлогыг алгоритмаар задлан блок схемээр илэрхийлж, Python-ы үндсэн "
                     "синтакс (хувьсагч, оролт/гаралт)-ыг ашиглан энгийн интерактив програм "
                     "бичиж чадна."),
               practice="Readiness Assessment. print(), input()-тэй интерактив програм бичих.",
               topics=("Блок схем, IPO загвар", "Арифметик, логик, харьцуулах оператор",
                       "Хувьсагч, төрөл хөрвүүлэх")),
        Lesson("Python: Нөхцөл + Давталт + Жагсаалт", "Python: conditions, loops and lists",
               goal=("Нөхцөл болон давталтын бүтцийг ашиглан логик урсгал зохион байгуулж, "
                     "жагсаалт зэрэг өгөгдлийн бүтцэд мэдээлэл хадгалан боловсруулж чадна."),
               practice=("БҮТЭЭЛ: Хоёр хэлний тоо таагч (MN/EN). "
                         "БҮТЭЭЛ: Pokémon simulator эсвэл түүнтэй адил."),
               topics=("if/elif/else, while, for", "range(), randint()", "list, tuple, set")),
        Lesson("Python: Функц + Толь бичиг (Dictionary)",
               "Python: functions and dictionaries",
               goal=("Давтагдах кодыг функц болгон бүтэцжүүлж, dictionary ашиглан өгөгдлийг "
                     "түлхүүр-утгаар зохион байгуулж, өмнөх ойлголтуудыг нэгтгэн санал болгогч "
                     "систем бүтээж чадна."),
               practice="БҮТЭЭЛ: Кино/тоглоом санал болгогч систем.",
               topics=("Функц, параметр, буцаах утга", "Dictionary",
                       "Жагсаалт, давталт, нөхцлийг хослуулах")),
    ]},
    {"name_mn": "Өгөгдөл ба машин сургалт", "name_en": "Data & Machine Learning", "lessons": [
        Lesson("Big Data танилцуулга + Pandas-аар өгөгдөл цэвэрлэх (+Python шалгалт)",
               "Intro to big data + cleaning data with pandas (+ Python test)",
               goal=("Өгөгдөл ба Big Data-н ялгааг тайлбарлаж, Pandas ашиглан жинхэнэ "
                     "өгөгдлийн багцыг шүүх, бүлэглэх, цэвэрлэх замаар утга учиртай мэдээлэл "
                     "гаргаж авч чадна."),
               practice="Python шалгалт. Жишиг өгөгдлийн багцыг цэвэрлэж судлах.",
               topics=("Big Data гэж юу вэ", "DataFrame: шүүх, бүлэглэх, эрэмбэлэх",
                       "Амьтны зураг, emoji, хүний үнэлгээний багц")),
        Lesson("Өгөгдлийн дүрслэл (Matplotlib & Seaborn) + Машин сургалтын танилцуулга",
               "Data visualisation (Matplotlib & Seaborn) + intro to ML",
               goal=("Өгөгдөлд тохирох графикийг сонгон дүрсэлж, дүрслэлээр дамжуулан дүгнэлт "
                     "хийж, машин сургалтын үндсэн төрлүүдийг жишээгээр ялган таньж чадна."),
               practice="Teachable Machine + симуляцийн систем.",
               topics=("Баганан, гистограм, шугаман, цэгэн, дугуй график",
                       "Аль графикийг хэзээ ашиглах", "ML-ийн төрлүүд")),
        Lesson("Хяналттай сургалт: Ангилал ба Регресс",
               "Supervised learning: classification and regression",
               goal=("Хяналттай сургалтын ангилал ба регрессийн ялгааг тайлбарлаж, scikit-learn "
                     "ашиглан энгийн таамаглах загвар сургаж, үр дүнг нь үнэлж чадна."),
               practice="БҮТЭЭЛ: Амьтны зураг ангилагч + таамаглагч.",
               topics=("Ангилал: амьтдыг ангилах", "Регресс: таамаглах",
                       "scikit-learn танилцуулга")),
        Lesson("Хяналтгүй сургалт: Бүлэглэл (Clustering) + Capstone танилцуулга",
               "Unsupervised learning: clustering + capstone intro",
               goal=("Хяналтгүй сургалтын бүлэглэлийн зарчмыг ойлгож, customer segmentation "
                     "зэрэг компаниудад өдөр тутам хийгддэг ажлыг хийж чаддаг болно."),
               practice="БҮТЭЭЛ: Customer Segmentation.",
               topics=("Clustering", "Сонирхлоор бүлэглэх", "Capstone танилцуулга")),
    ]},
    {"name_mn": "Capstone ба Demo Day", "name_en": "Capstone & Demo Day", "lessons": [
        Lesson("Зочин лекц: AI-н аялал + Capstone бүтээх өдөр 1",
               "Guest talk: a journey in AI + capstone build day 1",
               goal=("Их сургууль болон бодит салбар дахь AI-н хэрэглээ, судалгааны чиг "
                     "хандлагыг ойлгож, өөрийн суралцах ба карьерын зорилгоо төлөвлөж, "
                     "capstone төслийн санаа авч чадна."),
               practice="Capstone төслийн санааны brainstorm. Оюутнуудтай Q&A.",
               topics=("Принстоны 2 оюутны танилцуулга", "Их сургуульд AI-г хэрхэн судалдаг",
                       "Карьер, дадлага, тэтгэлэг")),
        Lesson("Capstone бүтээх өдөр 2 + Pitch бэлтгэл", "Capstone build day 2 + pitch prep",
               goal=("Сурсан AI ур чадвараа нэгтгэн ажиллах загвар бүхий capstone төсөл бүтээж, "
                     "түүнийгээ товч ойлгомжтой pitch болон demo хэлбэрээр илэрхийлэхэд бэлэн "
                     "болно. Тоглоом хийх."),
               practice="Pitch deck: 3 слайд + 5 минутын тайлбар. Demo бэлтгэх + peer feedback.",
               topics=("AI тоглоом, ангилагч, санал болгогч", "Dress rehearsal")),
        Lesson("Demo Day (Тайлангийн өдөр)", "Demo Day",
               goal="Бүтээлээ эцэслэж, туршиж сайжруулах, бусдад танилцуулах чадвар эзэмшинэ.",
               practice="5 минутын pitch + амьд demo. Эцэг эх, найз нөхөддөө бүтээлээ үзүүлэх.",
               topics=("Багш, mentor-уудаас feedback", "Гэрчилгээ, зураг")),
    ]},
]

TEEN_QUIZZES = {
    "Intro to big data + cleaning data with pandas (+ Python test)": (
        "Python шалгалт", "Python test", [
            ("`len([1, 2, 3])` юу буцаах вэ?", 1, ["2", "3", "4", "Алдаа"], 1, None),
            ("Аль нь давталт вэ?", 1, ["if", "for", "def", "print"], 1, None),
            ("`d = {'a': 1}` үед `d['a']`?", 1, ["'a'", "1", "None", "Алдаа"], 1, None),
            ("`randint(1, 6)` ямар утга өгөх вэ?", 2,
             ["Зөвхөн 1", "1-ээс 6 хүртэлх санамсаргүй бүхэл тоо", "0.5", "Үргэлж 6"], 1,
             None),
            ("Функцээс утга буцаах түлхүүр үг?", 1, ["print", "return", "yield", "give"], 1,
             None),
        ]),
}

TEEN_ASSIGNMENTS = {
    "Python: conditions, loops and lists": (
        "Тоо таагч + Pokémon simulator", "Хоёр БҮТЭЭЛ-ийн Colab холбоос."),
    "Python: functions and dictionaries": (
        "Санал болгогч систем", "Кино/тоглоом санал болгогч програмын холбоос."),
    "Supervised learning: classification and regression": (
        "Амьтны ангилагч", "scikit-learn ангилагч + таамаглагчийн notebook."),
    "Unsupervised learning: clustering + capstone intro": (
        "Customer Segmentation", "Бүлэглэлийн notebook ба 3 өгүүлбэрийн дүгнэлт."),
    "Capstone build day 2 + pitch prep": ("Pitch deck", "3 слайдтай pitch deck."),
    "Demo Day": ("Capstone төсөл", "Төслийн код, demo бичлэг."),
}
