"""The 12-class applied AI syllabus shared by Corporate Leaders and the Online run.

One class a session; the twelve are grouped into four modules of three so the
learning path unlocks in steps. Each class carries its goal and its hands-on
practice from the teaching plan.
"""
from __future__ import annotations

from .spec import Lesson

MODULES = [
    {"name_mn": "AI ба GenAI-ийн суурь", "name_en": "AI & GenAI Foundations", "lessons": [
        Lesson("AI танилцуулга: GenAI, Agentic AI, Machine Learning",
               "AI intro: GenAI, Agentic AI and Machine Learning",
               goal="GenAI, Agentic AI, Machine Learning-ийн ойлголтоо цэгцэлнэ.",
               practice="Capstone төслийн санаагаа гаргаж эхлэх.",
               topics=("GenAI", "Agentic AI", "Machine Learning", "Capstone санаа")),
        Lesson("GenAI ба LLM, Prompt engineering", "GenAI & LLMs, prompt engineering",
               goal="Prompt бичих чадвар, AI-ийн гаргалтыг хянах суурь.",
               practice=("Prompt бичих, дараагийн хичээлд зориулж хөгжүүлэлтийн орчноо "
                         "бэлдэх. Бэлэн AI Agent ашиглах (Claude AI, ChatGPT, "
                         "MS365 Copilot, Gemini)."),
               topics=("LLM гэж юу вэ", "Prompt engineering", "Vibe coding")),
        Lesson("Vibe coding (Automation)", "Vibe coding (automation)",
               goal="Систем хөгжүүлэлтийн нэгдсэн ойлголттой болох.",
               practice="Claude Code ашиглан vibe coding хийж энгийн динамик вебсайт хөгжүүлэх.",
               topics=("Claude Code", "Динамик вебсайт")),
    ]},
    {"name_mn": "AI-г ажилдаа нэгтгэх", "name_en": "AI at Work", "lessons": [
        Lesson("AI-г ажилдаа нэгтгэх: Use case тодорхойлох",
               "Bringing AI into your work: defining a use case",
               goal=("AI-г ажилдаа нэгтгэх суурь ойлголт авна. Бизнесийн болон системийн "
                     "шаардлага боловсруулах."),
               practice="Claude AI ашиглан туршилт хийх.",
               topics=("Work Automation Starter", "Workflow automation",
                       "AI Productivity Skill")),
        Lesson("API, AI model, API key, Database гэж юу вэ?",
               "What are APIs, AI models, API keys and databases?",
               goal="Систем хөгжүүлэх буюу автоматжуулалт хийх ойлголт авах.",
               practice="Claude AI ашиглан туршилт хийж, AI Agent хийх.",
               topics=("AI-тай систем хөгжүүлэлт", "AI model API key",
                       "Database яагаад хэрэгтэй вэ")),
        Lesson("Machine Learning-ийн суурь (Unsupervised learning)",
               "Machine learning basics (unsupervised learning)",
               goal="Өгөгдөлтэй бол хиймэл оюунтай системийг өөрөө бүтээх боломжтойг ойлгоно.",
               practice="Claude Code ашиглан машин сургалт хийж турших.",
               topics=("Unsupervised learning", "Кластерчлал")),
    ]},
    {"name_mn": "AI систем ба автоматжуулалт", "name_en": "AI Systems & Automation", "lessons": [
        Lesson("AI-ийн ёс зүй, МАБ; RAG ба Vector DB",
               "Ethical use of AI, data security; RAG and vector DBs",
               goal="AI систем хөгжүүлэхдээ DB ашиглахыг ойлгох.",
               practice="Claude Code ашиглан AI local model турших.",
               topics=("AI-ийн ёс зүй", "Мэдээллийн аюулгүй байдал", "RAG", "Vector DB")),
        Lesson("No-code автоматжуулалт ба AI Agent",
               "No-code automation and AI agents (bot, AI chat, AI assistant)",
               goal="Өөрийн AI туслах бүтээх чадвар.",
               practice="n8n туршиж AI Agent хийх. Capstone төслийн санаагаа боловсруулах.",
               topics=("Bot", "AI chat", "AI assistant", "n8n")),
        Lesson("Бүтээлч AI: зураг, дуу, видео", "Creativity AI: image, audio and video GenAI",
               goal=("Контент бүтээхэд AI платформ, model сонгох; prompt чухал гэдгийг "
                     "ойлгоно. Token зарцуулалт буюу credit гэж юу болохыг ойлгоно."),
               practice="1 минутаас дээш хугацаатай видео хийх.",
               topics=("Image GenAI", "Audio GenAI", "Video GenAI", "Token / credit")),
    ]},
    {"name_mn": "Deployment ба Capstone", "name_en": "Deployment & Capstone", "lessons": [
        Lesson("Cloud computing ба системийн deployment", "Cloud computing and system deployment",
               goal="Системээ, хийсэн автоматжуулалтаа хэрэглээнд оруулах чадвар суух.",
               practice=("Датанаас AI систем хөгжүүлж, шууд хэрэглээнд нэвтрүүлэх. "
                         "Claude Code ашиглана."),
               topics=("Cloud", "Deployment")),
        Lesson("Capstone төсөл: хөгжүүлэлт ба deployment",
               "Capstone project development and deployment",
               goal="Суралцагч өөрийн санаанаас сонгож ажиллана.",
               topics=("Mentor-ийн зөвлөгөө", "Deployment")),
        Lesson("Capstone төсөл — Demo day", "Capstone project — Demo day",
               goal="Бусдаас суралцах, мэдлэг мэдээллээ хуваалцах өдөр.",
               practice="Эцсийн төслөө танилцуулах.", topics=("Demo", "Санал хүсэлт")),
    ]},
]

QUIZZES = {
    "GenAI & LLMs, prompt engineering": ("Prompt engineering — шалгах тест",
                                         "Prompt engineering — check", [
        ("Сайн prompt-д юу заавал байх ёстой вэ?", 1,
         ["Зөвхөн асуулт", "Үүрэг, контекст, хүссэн гаралтын хэлбэр",
          "Аль болох богино байх", "Англи хэл"], 1, None),
        ("LLM «hallucination» гэж юу вэ?", 2,
         ["Хэт удаан хариулах", "Итгэлтэйгээр буруу мэдээлэл зохиох",
          "Хариулахаас татгалзах", "Зураг үүсгэх"], 1,
         "Тиймээс AI-ийн гаргалтыг заавал хянана."),
        ("Few-shot prompting гэж?", 1,
         ["Prompt-д жишээ хариултууд оруулах", "Олон удаа асуух",
          "Богино prompt", "Model солих"], 0, None),
        ("Нууц мэдээллийг нийтийн AI chat-д оруулах нь?", 2,
         ["Зүгээр", "Байгууллагын бодлогоор хориглосон бол эрсдэлтэй",
          "Үргэлж аюулгүй", "Зөвхөн англиар бол зүгээр"], 1, None),
    ]),
    "Ethical use of AI, data security; RAG and vector DBs": (
        "RAG ба AI ёс зүй — шалгах тест", "RAG & AI ethics — check", [
            ("RAG-ийн гол давуу тал?", 2,
             ["Model-ийг дахин сургах шаардлагагүйгээр өөрийн баримтаар хариулах",
              "Зураг үүсгэх", "Интернэтгүй ажиллах", "Үнэгүй болох"], 0, None),
            ("Vector DB юу хадгалдаг вэ?", 1,
             ["Нууц үг", "Текстийн embedding (тоон вектор)", "Видео", "Excel файл"], 1, None),
            ("Хувь хүний мэдээлэлтэй ажиллахад хамгийн түрүүнд?", 1,
             ["Зөвшөөрөл ба нууцлалыг хангах", "Хурдан ажиллуулах",
              "Бүгдийг нийтэд нээх", "Юу ч хийхгүй"], 0, None),
        ]),
}

ASSIGNMENTS = {
    "AI intro: GenAI, Agentic AI and Machine Learning": (
        "Capstone санаа", "Ажил дээрээ AI-аар шийдэж болох 3 асуудал бичиж, нэгийг сонго."),
    "GenAI & LLMs, prompt engineering": (
        "Prompt дасгал", "Өөрийн ажлын 5 даалгаварт prompt бичиж, 2 өөр AI-ийн хариуг харьцуул."),
    "Vibe coding (automation)": (
        "Динамик вебсайт", "Claude Code ашиглан хийсэн вебсайтынхаа холбоос, дэлгэцийн зураг."),
    "Bringing AI into your work: defining a use case": (
        "Use case тодорхойлолт", "Бизнесийн ба системийн шаардлагыг 1 нүүрт бич."),
    "What are APIs, AI models, API keys and databases?": (
        "Анхны AI Agent", "Claude AI ашиглан хийсэн agent-ийнхаа тайлбар ба туршилтын үр дүн."),
    "No-code automation and AI agents (bot, AI chat, AI assistant)": (
        "n8n AI туслах", "n8n дээр хийсэн workflow-ийн дэлгэцийн зураг, туршилтын бичлэг."),
    "Creativity AI: image, audio and video GenAI": (
        "1 минутын AI видео", "AI-аар хийсэн 1 минутаас дээш видеоны холбоос."),
    "Cloud computing and system deployment": (
        "Систем deploy хийх", "Хэрэглээнд гаргасан системийнхээ холбоос."),
    "Capstone project — Demo day": (
        "Capstone — эцсийн танилцуулга", "Demo-ийн холбоос, илтгэлийн слайд."),
}
