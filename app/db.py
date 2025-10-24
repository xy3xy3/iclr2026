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


def _resolves_to_loopback(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
        for family, _, _, _, sockaddr in infos:
            ip = sockaddr[0]
            # IPv4 loopback
            if ip.startswith("127."):
                return True
            # IPv6 loopback
            if ip == "::1":
                return True
        return False
    except Exception:
        return False


def get_conn() -> psycopg.Connection:
    # Note: do not register pgvector here because the extension
    # may not exist yet; call register_vector after ensuring schema.
    dsn = dsn_from_env()
    try:
        return psycopg.connect(dsn, autocommit=True)
    except psycopg.OperationalError:
        host = os.getenv("POSTGRES_HOST", "")
        port = os.getenv("POSTGRES_PORT", "")
        dbname = os.getenv("POSTGRES_DB", "iclr2026")
        user = os.getenv("POSTGRES_USER", "iclr")
        pw = os.getenv("POSTGRES_PASSWORD", "iclrpass")

        # Fallback rules:
        # 1) host not resolvable -> fallback to 127.0.0.1:5433
        # 2) host == 'pgvector' -> fallback to 127.0.0.1:5433
        # 3) host resolves to loopback and port != 5433 -> try 127.0.0.1:5433
        should_fallback = False
        if host and not _is_resolvable(host):
            should_fallback = True
        if host.lower() == "pgvector":
            should_fallback = True
        if _resolves_to_loopback(host or "127.0.0.1") and port not in ("", "5433"):
            should_fallback = True

        if should_fallback:
            fallback = f"postgresql://{user}:{pw}@127.0.0.1:5433/{dbname}"
            print(f"Warn: falling back to local DB {fallback}")
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
            # Create FTS GIN index over title+abstract for keyword search
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE c.relname = 'papers_fts_idx' AND n.nspname = 'public'
                    ) THEN
                        EXECUTE 'CREATE INDEX papers_fts_idx ON papers USING GIN (
                            to_tsvector(''english'', coalesce(title,'''') || '' '' || coalesce(abstract,''''))
                        )';
                    END IF;
                END$$;
                """
            )
