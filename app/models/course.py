from datetime import datetime
from decimal import Decimal

from app.extensions import db

# Publication lifecycle. Only non-draft courses are visible to the public.
COURSE_STATUSES = ("draft", "open", "closed")
# Audience level shown as a badge on the site (Junior / Adult).
COURSE_LEVELS = ("junior", "adult")


class Course(db.Model):
    """A program / cohort shown on the public site (e.g. /summer-cohort).

    Bilingual (mn/en). Read is public (published only); write is staff with the
    ``course:edit`` permission. Two template files (certificate, contract) are
    uploaded to S3 — only their object keys + original filenames are stored here.
    """

    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)

    # --- classification / summary ---
    category = db.Column(db.String(80))          # e.g. "bootcamp", "online"
    level = db.Column(db.String(20))             # junior | adult
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)

    title_mn = db.Column(db.String(200), nullable=False)
    title_en = db.Column(db.String(200))
    tagline_mn = db.Column(db.String(300))
    tagline_en = db.Column(db.String(300))

    age_min = db.Column(db.Integer)
    age_max = db.Column(db.Integer)

    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    duration_weeks = db.Column(db.Integer)
    format = db.Column(db.String(20))            # online | in_person | hybrid

    price_amount = db.Column(db.Numeric(12, 2))
    currency = db.Column(db.String(3), default="MNT")
    discount_percent = db.Column(db.Integer, default=0)

    banner_image_url = db.Column(db.String(500))
    icon = db.Column(db.String(120))

    # --- detail ---
    description_mn = db.Column(db.Text)
    description_en = db.Column(db.Text)
    prerequisites_mn = db.Column(db.Text)
    prerequisites_en = db.Column(db.Text)
    capacity = db.Column(db.Integer)
    final_project_type = db.Column(db.String(60))
    curriculum = db.Column(db.JSON)              # list of modules/topics
    whats_included = db.Column(db.JSON)          # list of strings
    instructors = db.Column(db.JSON)             # list of {name, title?, ...}

    # --- uploaded template files (stored in S3; keys only here) ---
    cert_template_key = db.Column(db.String(500))
    cert_template_name = db.Column(db.String(255))
    contract_template_key = db.Column(db.String(500))
    contract_template_name = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # --- derived ---
    @property
    def is_public(self) -> bool:
        return self.status in ("open", "closed")

    @property
    def final_price_amount(self):
        if self.price_amount is None:
            return None
        pct = self.discount_percent or 0
        return (self.price_amount * (Decimal(100) - Decimal(pct)) / Decimal(100)).quantize(
            Decimal("0.01")
        )

    def _price(self, value):
        return None if value is None else float(value)

    def to_summary(self) -> dict:
        """Card/list view — the fields shown on the cohort grid."""
        return {
            "id": self.id,
            "slug": self.slug,
            "category": self.category,
            "level": self.level,
            "status": self.status,
            "title": {"mn": self.title_mn, "en": self.title_en},
            "tagline": {"mn": self.tagline_mn, "en": self.tagline_en},
            "age_min": self.age_min,
            "age_max": self.age_max,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "duration_weeks": self.duration_weeks,
            "format": self.format,
            "price_amount": self._price(self.price_amount),
            "currency": self.currency,
            "discount_percent": self.discount_percent,
            "final_price_amount": self._price(self.final_price_amount),
            "banner_image_url": self.banner_image_url,
            "icon": self.icon,
        }

    def to_detail(self) -> dict:
        """Full view — summary plus long-form content and file presence."""
        data = self.to_summary()
        data.update(
            {
                "description": {"mn": self.description_mn, "en": self.description_en},
                "prerequisites": {"mn": self.prerequisites_mn, "en": self.prerequisites_en},
                "capacity": self.capacity,
                "final_project_type": self.final_project_type,
                "curriculum": self.curriculum,
                "whats_included": self.whats_included,
                "instructors": self.instructors,
                "has_cert_template": self.cert_template_key is not None,
                "cert_template_name": self.cert_template_name,
                "has_contract_template": self.contract_template_key is not None,
                "contract_template_name": self.contract_template_name,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            }
        )
        return data

    def __repr__(self) -> str:
        return f"<Course {self.id} {self.slug!r} ({self.status})>"
