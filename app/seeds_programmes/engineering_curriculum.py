"""The AI Engineering programme's syllabus: six modules, one lesson per class session.

Lesson titles are the teaching team's list, lightly cleaned: typos fixed, staff
notes in brackets dropped, and a repeated title numbered so the app can tell the
two sessions apart.
"""
from __future__ import annotations

from .spec import Lesson

_RAW = [
    {
        "name_mn": "Python-ийн үндэс",
        "name_en": "Python Fundamentals",
        "lessons": [
            "Course intro",
            "Python syntax, variables, data types",
            "Exercises of fundamentals of Python",
            "Conditional statements",
            "Working with strings",
            "Loops and iteration",
            "Working with lists",
            "Review",
            "Sets and tuples",
            "Dictionaries",
            "Review",
            "Functions",
            "Review",
            "Working with files",
            "Exam",
        ],
    },
    {
        "name_mn": "Өгөгдлийн шинжилгээ ба статистик",
        "name_en": "Data Analysis & Statistics",
        "lessons": [
            "Introduction to pandas",
            "Pandas: working with columns",
            "Data wrangling and aggregation",
            "Visualization with Matplotlib and Seaborn",
            "AI Ethics",
            "Kaggle intro: data analysis on Kaggle",
            "Review pandas: EDA on full data mini project",
            "Foundations of statistics: sets, probability theory",
            "Distributions and causation",
            "Module review",
            "Module 1 Progress Test",
        ],
    },
    {
        "name_mn": "Машин сургалт",
        "name_en": "Machine Learning",
        "lessons": [
            "What is Machine Learning? Overview & workflow",
            "Linear regression (theory + code), polynomial and multiple regression",
            "Review: Machine Learning & linear regression",
            "Classification",
            "Classification: logistic regression",
            "Feature engineering & feature selection",
            "Decision trees",
            "Review: classification",
            "Review: supervised learning",
            "Review: supervised learning",
            "Unsupervised learning and K-Means",
            "Pandas merge and concatenation",
            "Pandas merge and concatenation",
            "Dimensionality reduction",
            "PCA",
            "PCA",
            "Review",
            "Module test",
        ],
    },
    {
        "name_mn": "Гүн сургалт: Computer Vision ба NLP",
        "name_en": "Deep Learning: Computer Vision & NLP",
        "lessons": [
            "Python OOP",
            "Fundamentals of deep learning",
            "Fundamentals of PyTorch and NumPy",
            "Fundamentals of PyTorch and NumPy",
            "PyTorch nn optimization",
            "Dataset and DataLoader",
            "PyTorch nn regression",
            "Fundamentals of computer vision",
            "CNNs: convolution, pooling, filters, CNNs in image classification",
            "Image classification",
            "Previous cohort's project showcase",
            "Preparing an object detection dataset",
            "Fundamentals of fine-tuning models: YOLO",
            "Image segmentation",
            "Image segmentation coding",
            "Intro to NLP and text preprocessing: tokenization, stopwords, stemming",
            "Intro to NLP and text preprocessing: tokenization, stopwords, stemming",
            "Large Language Models",
            "Large Language Model training",
            "Building an LLM app and RAG",
            "Test review",
            "Module Progress Test",
            "Deploying DL models",
            "Review: PyTorch",
            "Review: computer vision",
            "Transfer learning and fine-tuning models (SSD fine-tuning)",
            "Review: NLP, classification",
        ],
    },
    {
        "name_mn": "Програм хангамж, MLOps ба Agentic AI",
        "name_en": "Software Engineering, MLOps & Agentic AI",
        "lessons": [
            "Software development lifecycle & version control (prompt engineering)",
            "SQL basics: introduction & core commands",
            "SQL fundamentals: filtering, sorting & joins",
            "SQL databases: design & security",
            "Backend development: FastAPI, data management & ML integration",
            "Backend development: logging & security basics",
            "Testing: unit tests, API tests & Claude Code",
            "ML mini project",
            "Capstone start: project proposal",
            "DevOps & deployment: fundamentals of deployment",
            "DevOps & deployment: Docker, CI/CD pipeline",
            "Cloud computing: AWS",
            "ML on cloud: AWS SageMaker",
            "Agentic AI I",
            "Agentic AI II",
            "Agentic AI III",
            "MLOps & LLMOps",
            "AI governance and ethical AI",
        ],
    },
    {
        "name_mn": "Карьер ба төгсөлтийн төсөл",
        "name_en": "Career & Capstone",
        "lessons": [
            "Applied AI: modern AI tools",
            "Soft skills 1: technical interview prep (ML, Python, SQL)",
            "Soft skills 2: behavioral interviews & teamwork scenarios",
            "Final Exam (MLE)",
            "Capstone II: building seminar / office hours",
            "Capstone project presentations & graduation",
        ],
    },
]

# Lessons that are a graded test rather than a class; each gets a required quiz.
EXAM_TITLES = frozenset({"Exam", "Module 1 Progress Test", "Module test",
                         "Module Progress Test", "Final Exam (MLE)"})


def numbered_titles(titles: list[str]) -> list[str]:
    """['Review', 'PCA', 'PCA'] -> ['Review', 'PCA (1)', 'PCA (2)'] within one module."""
    totals: dict[str, int] = {}
    for title in titles:
        totals[title] = totals.get(title, 0) + 1
    seen: dict[str, int] = {}
    out = []
    for title in titles:
        if totals[title] == 1:
            out.append(title)
            continue
        seen[title] = seen.get(title, 0) + 1
        out.append(f"{title} ({seen[title]})")
    return out


MODULES = [
    {"name_mn": m["name_mn"], "name_en": m["name_en"],
     "lessons": [Lesson(title_mn=t, title_en=t) for t in numbered_titles(m["lessons"])]}
    for m in _RAW
]
