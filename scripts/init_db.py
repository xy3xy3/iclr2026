import os
import socket
import psycopg
from pgvector.psycopg import register_vector


def dsn_from_env() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    db = os.getenv("POSTGRES_DB", "iclr2026")
    user = os.getenv("POSTGRES_USER", "iclr")
    pw = os.getenv("POSTGRES_PASSWORD", "iclrpass")
    return f"postgresql://{user}:{pw}@{host}:{port}/{db}"


def _is_resolvable(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
        return True
    except Exception:
        return False


def connect_with_fallback() -> psycopg.Connection:
    primary = dsn_from_env()
    try:
        return psycopg.connect(primary, autocommit=True)
    except psycopg.OperationalError:
        host = os.getenv("POSTGRES_HOST")
        if host and not _is_resolvable(host):
            db = os.getenv("POSTGRES_DB", "iclr2026")
            user = os.getenv("POSTGRES_USER", "iclr")
            pw = os.getenv("POSTGRES_PASSWORD", "iclrpass")
            fallback = f"postgresql://{user}:{pw}@127.0.0.1:5432/{db}"
            print(f"Warn: host '{host}' not resolvable, trying local fallback {fallback}")
            return psycopg.connect(fallback, autocommit=True)
        raise


def main() -> None:
    embed_dim = int(os.getenv("OPENAI_EMBED_DIM", "1536"))
    with connect_with_fallback() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS papers (
                    id BIGSERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    abstract TEXT NOT NULL,
                    link TEXT NOT NULL UNIQUE,
                    embedding VECTOR({embed_dim})
                )
                """
            )
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
        # Register type adapters after ensuring extension exists
        register_vector(conn)
    print("DB schema ensured (extension/table/index)")


if __name__ == "__main__":
    main()
