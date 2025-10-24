from contextlib import contextmanager
from typing import Iterator
import os
import socket

import psycopg
from pgvector.psycopg import register_vector

from .config import dsn_from_env, EMBED_DIM


def _is_resolvable(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
        return True
    except Exception:
        return False


def get_conn() -> psycopg.Connection:
    # Note: do not register pgvector here because the extension
    # may not exist yet; call register_vector after ensuring schema.
    dsn = dsn_from_env()
    try:
        return psycopg.connect(dsn, autocommit=True)
    except psycopg.OperationalError:
        host = os.getenv("POSTGRES_HOST")
        if host and not _is_resolvable(host):
            db = os.getenv("POSTGRES_DB", "iclr2026")
            user = os.getenv("POSTGRES_USER", "iclr")
            pw = os.getenv("POSTGRES_PASSWORD", "iclrpass")
            fallback = f"postgresql://{user}:{pw}@127.0.0.1:5433/{db}"
            print(f"Warn: host '{host}' not resolvable, trying local fallback {fallback}")
            return psycopg.connect(fallback, autocommit=True)
        raise


@contextmanager
def db() -> Iterator[psycopg.Connection]:
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


def ensure_schema() -> None:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS papers (
                    id BIGSERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    abstract TEXT NOT NULL,
                    link TEXT NOT NULL UNIQUE,
                    embedding VECTOR({int(EMBED_DIM)})
                )
                """
            )
            # Create ANN index (cosine). Note: requires ANALYZE after inserts for best perf
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE c.relname = 'papers_embedding_idx' AND n.nspname = 'public'
                    ) THEN
                        EXECUTE 'CREATE INDEX papers_embedding_idx ON papers USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)';
                    END IF;
                END$$;
                """
            )
