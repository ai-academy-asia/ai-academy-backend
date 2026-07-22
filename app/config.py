import os


def _build_database_url() -> str:
    """Return DATABASE_URL if set, otherwise assemble it from POSTGRES_* parts."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    user = os.getenv("POSTGRES_USER", "aiaa")
    password = os.getenv("POSTGRES_PASSWORD", "aiaa_dev_password")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    name = os.getenv("POSTGRES_DB", "aiaa")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    SQLALCHEMY_DATABASE_URI = _build_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # --- Auth / JWT ---
    # Falls back to SECRET_KEY if JWT_SECRET is not set separately.
    JWT_SECRET = os.getenv("JWT_SECRET") or SECRET_KEY
    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
    # Access-token lifetime in seconds. Kept short (1h) because refresh tokens
    # exist — a long-lived stateless access token would undermine the shorter
    # staff refresh window.
    JWT_ACCESS_TTL = int(os.getenv("JWT_ACCESS_TTL", str(60 * 60)))

    # --- Refresh tokens (DB-backed, opaque, rotated) ---
    # Learners (student/teacher) get a long refresh window; staff get a short
    # one because they can act on money data. Sliding window (each rotate resets
    # the clock). All in seconds.
    REFRESH_TTL_STUDENT = int(os.getenv("REFRESH_TTL_STUDENT", str(30 * 24 * 60 * 60)))
    REFRESH_TTL_TEACHER = int(os.getenv("REFRESH_TTL_TEACHER", str(30 * 24 * 60 * 60)))
    REFRESH_TTL_STAFF = int(os.getenv("REFRESH_TTL_STAFF", str(12 * 60 * 60)))

    # Minimum length enforced on password changes.
    PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "8"))

    # --- S3 (cert / contract template files) ---
    # boto3 uses its default credential chain (env keys, shared profile, or the
    # EC2 instance role in prod). Only the bucket/region need configuring here.
    AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
    S3_BUCKET = os.getenv("S3_BUCKET", "aiaa-templates-748560966884")
    S3_PREFIX = os.getenv("S3_PREFIX", "")  # optional key prefix
    # Max upload size for a template file (bytes). Default 15 MB.
    MAX_TEMPLATE_BYTES = int(os.getenv("MAX_TEMPLATE_BYTES", str(15 * 1024 * 1024)))
