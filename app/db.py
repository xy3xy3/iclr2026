from contextlib import contextmanager
from typing import Iterator

import psycopg
from pgvector.psycopg import register_vector

from .config import dsn_from_env, EMBED_DIM


def get_conn() -> psycopg.Connection:
    # Note: do not register pgvector here because the extension
    # may not exist yet; call register_vector after ensuring schema.
    return psycopg.connect(dsn_from_env(), autocommit=True)


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
