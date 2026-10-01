"""The 14-class "AI for your business" syllabus shared by Agentic AI and AI for Business.

Students build one system across the course: a brand and knowledge base, an n8n
content agent, an Admin Panel wired to Facebook, and a RAG Messenger chat —
demoed on the last day. Grouped into four modules so the path unlocks in steps.
"""
from __future__ import annotations

from .spec import Lesson

MODULES = [
    {"name_mn": "AI ба брэнд", "name_en": "AI & Your Brand", "lessons": [
        Lesson("AI гэж юу вэ?", "What is AI?",
               goal=("AI-ийн үндсэн ойлголт, чиг хандлага, бизнест бий болгож буй боломжуудыг "
                     "ойлгоно. Сургалтын төгсгөлд бүтээх Admin-аас удирддаг контент болон "
                     "Facebook чат системийн ерөнхий шийдэлтэй танилцана."),
               practice="Өөрийн ажлыг AI ашиглах өнцгөөс шинжлэх.",
               topics=("AI-ийн чиг хандлага", "Бизнесийн боломж", "Төгсгөлийн системийн шийдэл")),
        Lesson("Prompt Engineering", "Prompt engineering",
               goal="Чанартай үр дүн авах prompt боловсруулах аргачлалыг сурна.",
               practice=("Контент, чатын хариулт болон FAQ-д зориулсан 3 prompt-ыг туршиж, "
                         "сайжруулна."),
               topics=("Prompt-ийн бүтэц", "Контент prompt", "Чат / FAQ prompt")),
        Lesson("Брэндинг ба мэдлэгийн сан", "Branding and the knowledge base",
               goal=("Брэндийн үндсэн элементүүд болох нэр, лого, өнгө, фонт, өнгө аясыг "
                     "тодорхойлно."),
               practice=("AI ашиглан өөрийн брэндийг боловсруулж, Brand Book болон мэдлэгийн "
                         "сангийн бүтэц үүсгэнэ."),
               topics=("Нэр, лого", "Өнгө, фонт", "Өнгө аяс", "Brand Book")),
        Lesson("Poster, видео ба контент төлөвлөгөө", "Posters, video and a content plan",
               goal="Brand Book-д тулгуурлан контент бүтээж, мэдлэгийн санг дүүргэнэ.",
               practice=("5 poster, 1 богино видео бүтээж, 1 сарын контентын төлөвлөгөө "
                         "гаргана. Мэдлэгийн санг шаардлагатай агуулгаар дүүргэнэ."),
               topics=("Poster", "Богино видео", "Контент төлөвлөгөө")),
    ]},
    {"name_mn": "Automation ба AI агент", "name_en": "Automation & AI Agents", "lessons": [
        Lesson("Automation Workflow", "Automation workflows",
               goal=("Automation-ы ойлголт, n8n-ийн бүтэц (trigger, node, өгөгдөл "
                     "дамжуулах)-тэй танилцана. Бодит бизнест automation хэрхэн "
                     "ашиглагддаг талаар туршлагаасаа хуваалцана."),
               practice=("Google Sheets, Gmail зэрэг системийг холбож, анхны workflow-оо n8n "
                         "дээр бүтээнэ."),
               topics=("Trigger", "Node", "Өгөгдөл дамжуулах", "Google Sheets, Gmail")),
        Lesson("Контентын AI агент", "A content AI agent",
               goal=("AI агентын бүтэц, шийдвэр гаргах логикийг Mazaal AI-ийн бодит туршлага "
                     "дээр тайлбарлана."),
               practice=("Brand Book болон prompt санг ашиглан контентын ноорог үүсгэж, хүний "
                         "баталгаажуулалтаар дамжуулдаг AI агентыг n8n дээр бүтээнэ."),
               topics=("AI агентын бүтэц", "Human-in-the-loop", "n8n")),
        Lesson("Давтлага 1: Workshop (танхимаар, 2–3 цаг)", "Review 1: in-person workshop",
               goal=("1–6-р хичээлд дуусгаж амжаагүй ажлаа mentor-уудын тусламжтайгаар "
                     "гүйцээнэ. Brand Book, контент, AI агент, бүртгэл гэсэн 4 ширээнд "
                     "тухайн сэдвээр туслах mentor байна."),
               practice=("Facebook-тэй холбогдох Meta App үүсгэн туршигчаар нэмэгдэж, GitHub "
                         "болон hosting-д бүртгүүлнэ. Admin Panel-даа ямар цэс, мэдээлэл "
                         "байхыг цаасан дээр зурж ирнэ."),
               topics=("Brand Book ширээ", "Контент ширээ", "AI агент ширээ", "Бүртгэл ширээ")),
    ]},
    {"name_mn": "Admin Panel ба Facebook", "name_en": "Admin Panel & Facebook", "lessons": [
        Lesson("Vibe Coding: Admin Panel", "Vibe coding: the Admin Panel",
               goal="AI-ийн тусламжтайгаар код үүсгэж сурна.",
               practice=("Өөрийн брэндийн загвартай 4 цэстэй Admin Panel бүтээнэ: Контент, "
                         "Facebook, Чат, Захиалга."),
               topics=("Контент", "Facebook", "Чат", "Захиалга")),
        Lesson("Deployment", "Deployment",
               goal="Admin Panel-ыг интернэтэд байршуулж, системийн үндсэн ажиллагааг ажиллуулна.",
               practice="AI агентын үүсгэсэн нооргийг Admin-аас батлах үйлдлийг холбоно.",
               topics=("Hosting", "Ноорог батлах")),
        Lesson("Facebook холболт", "Connecting Facebook",
               goal="Facebook Page-ийн мэдээллийг системтэй холбоно.",
               practice=("Facebook Page-ийн пост, коммент болон хандалтын мэдээллийг системтэй "
                         "холбож, Admin Panel-д харуулна."),
               topics=("Пост", "Коммент", "Хандалтын мэдээлэл")),
        Lesson("Admin-аас контент удирдах", "Managing content from the Admin Panel",
               goal="Контентыг нэг газраас хянаж, нийтэлж, үр дүнг нь харна.",
               practice=("Admin Panel-аас контентын нооргийг хянаж, батлах, Facebook-т шууд "
                         "болон хуваарийн дагуу нийтлэх, нийтлэлийн үр дүнг буцаан харах "
                         "үйлдлүүдийг хэрэгжүүлнэ."),
               topics=("Ноорог батлах", "Шууд нийтлэх", "Хуваарьт нийтлэл", "Үр дүн")),
    ]},
    {"name_mn": "AI чат ба төгсөлт", "name_en": "AI Chat & Graduation", "lessons": [
        Lesson("Messenger AI чат ба Admin-аас удирдах", "Messenger AI chat, run from the Admin",
               goal="Байгууллагын мэдлэгийн сан дээр ажиллах RAG чат үүсгэнэ.",
               practice=("Яриаг Admin Panel-д бүртгэх, шаардлагатай үед хүн рүү шилжүүлэх, "
                         "захиалгын мэдээлэл авах үйлдлүүдийг холбоно."),
               topics=("RAG", "Хүн рүү шилжүүлэх", "Захиалга")),
        Lesson("Давтлага 2: Online (Zoom/Meet, 2–3 цаг)", "Review 2: online (Zoom/Meet)",
               goal="Оролцогч дэлгэцээ хуваалцан системээ эхнээс нь дуустал туршина.",
               practice=("Оролцогч бүр 3 минутын demo хийж, шаардлагатай бол нөөц бичлэг "
                         "бэлтгэнэ. Шаардлагатай тохиолдолд 15 минутын 1:1 зөвлөгөө өгнө."),
               topics=("Системийн тест", "3 минутын demo", "1:1 зөвлөгөө")),
        Lesson("Төгсөлтийн өдөр", "Graduation day",
               goal=("Брэнд, контент, AI агент, Admin Panel болон AI чатыг нэгтгэсэн нэгдсэн "
                     "системийн demo."),
               topics=("Demo", "Гэрчилгээ")),
    ]},
]

QUIZZES = {
    "Prompt engineering": ("Prompt Engineering — шалгах тест", "Prompt engineering — check", [
        ("Сайн prompt-д юу заавал байх ёстой вэ?", 1,
         ["Зөвхөн асуулт", "Үүрэг, контекст, хүссэн гаралтын хэлбэр",
          "Аль болох богино байх", "Англи хэл"], 1, None),
        ("FAQ-ийн хариултыг брэндийн өнгө аясаар гаргахын тулд?", 2,
         ["Brand Book-ийн өнгө аясыг prompt-д оруулах", "Model солих",
          "Урт асуулт бичих", "Юу ч хийх шаардлагагүй"], 0, None),
        ("AI-ийн гаргасан контентыг нийтлэхийн өмнө?", 1,
         ["Шууд нийтлэх", "Хүн хянаж батлах", "Устгах", "Орчуулах"], 1,
         "Тиймээс агент ноорог үүсгэж, хүн баталдаг."),
    ]),
    "Automation workflows": ("n8n Automation — шалгах тест", "n8n automation — check", [
        ("n8n workflow юугаар эхэлдэг вэ?", 1,
         ["Trigger", "Output", "Database", "Prompt"], 0, None),
        ("Node хооронд юу дамждаг вэ?", 1,
         ["Нууц үг", "Өгөгдөл (JSON item)", "Зураг л", "Юу ч биш"], 1, None),
        ("Google Sheets-д шинэ мөр нэмэгдэхэд Gmail илгээх нь?", 2,
         ["Sheets trigger → Gmail node", "Gmail trigger → Sheets node",
          "Зөвхөн AI node", "Боломжгүй"], 0, None),
    ]),
}

ASSIGNMENTS = {
    "Prompt engineering": ("3 prompt", "Контент, чатын хариулт, FAQ-ийн 3 prompt ба үр дүн."),
    "Branding and the knowledge base": (
        "Brand Book",
        "Нэр, лого, өнгө, фонт, өнгө аяс бүхий Brand Book ба мэдлэгийн сангийн бүтэц."),
    "Posters, video and a content plan": (
        "Контентын багц", "5 poster, 1 богино видео, 1 сарын контентын төлөвлөгөө."),
    "Automation workflows": ("Анхны n8n workflow", "Sheets/Gmail холбосон workflow-ийн бичлэг."),
    "A content AI agent": ("Контентын AI агент", "Ноорог үүсгэж, батлуулдаг агентын demo."),
    "Review 1: in-person workshop": (
        "Бэлтгэл ба Admin ноорог", "Meta App, GitHub, hosting бүртгэл ба Admin Panel-ийн зураг."),
    "Vibe coding: the Admin Panel": ("Admin Panel", "4 цэстэй Admin Panel-ийн дэлгэцийн зураг."),
    "Deployment": ("Байршуулсан систем", "Интернэтэд байршуулсан Admin Panel-ийн холбоос."),
    "Managing content from the Admin Panel": (
        "Контент нийтлэх", "Admin-аас батлаж Facebook-т нийтэлсэн постын холбоос."),
    "Messenger AI chat, run from the Admin": ("Messenger AI чат", "RAG чатын туршилтын бичлэг."),
    "Review 2: online (Zoom/Meet)": ("3 минутын demo", "Системийн 3 минутын demo бичлэг."),
}
