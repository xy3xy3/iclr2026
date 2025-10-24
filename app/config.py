import os
from typing import Optional


def env(key: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(key)
    return v if v not in (None, "") else default


DATABASE_URL = env(
    "DATABASE_URL",
    "postgresql://iclr:iclrpass@127.0.0.1:5432/iclr2026",
)

POSTGRES_HOST = env("POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = int(env("POSTGRES_PORT", "5432"))
POSTGRES_DB = env("POSTGRES_DB", "iclr2026")
POSTGRES_USER = env("POSTGRES_USER", "iclr")
POSTGRES_PASSWORD = env("POSTGRES_PASSWORD", "iclrpass")


def dsn_from_env() -> str:
    # Prefer explicit DATABASE_URL if provided
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    return (
        f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )


OPENAI_API_KEY = env("OPENAI_API_KEY")  # required
OPENAI_BASE_URL = env("OPENAI_BASE_URL")  # optional for compatible endpoints
EMBED_MODEL = env("OPENAI_EMBED_MODEL", "text-embedding-3-small")
EMBED_DIM = int(env("OPENAI_EMBED_DIM", "1536"))

