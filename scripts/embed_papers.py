import json
import os
from typing import Dict, List

import psycopg
from pgvector.psycopg import register_vector
from openai import OpenAI


DATA_PATH = os.getenv("DATA_PATH", os.path.join("data", "iclr2026.json"))
MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")


def dsn_from_env() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    port = int(os.getenv("POSTGRES_PORT", "5433"))
    db = os.getenv("POSTGRES_DB", "iclr2026")
    user = os.getenv("POSTGRES_USER", "iclr")
    pw = os.getenv("POSTGRES_PASSWORD", "iclrpass")
    return f"postgresql://{user}:{pw}@{host}:{port}/{db}"


def make_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def embed_texts(client: OpenAI, texts: List[str]) -> List[List[float]]:
    # OpenAI supports batching
    inputs = [t.replace("\n", " ") for t in texts]
    resp = client.embeddings.create(model=MODEL, input=inputs)
    return [d.embedding for d in resp.data]  # type: ignore


def ensure_schema(conn: psycopg.Connection) -> None:
    embed_dim = int(os.getenv("OPENAI_EMBED_DIM", "1536"))
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


def main() -> None:
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(f"Data file not found: {DATA_PATH}")

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        records: List[Dict[str, str]] = json.load(f)

    dsn = dsn_from_env()
    client = make_client()

    with psycopg.connect(dsn, autocommit=True) as conn:
        register_vector(conn)
        ensure_schema(conn)
        with conn.cursor() as cur:
            batch: List[Dict[str, str]] = []
            BATCH_SIZE = int(os.getenv("EMBED_BATCH", "64"))

            def flush_batch():
                if not batch:
                    return
                texts = [f"Title: {r['title']}\n\nAbstract: {r['abstract']}" for r in batch]
                embs = embed_texts(client, texts)
                for r, e in zip(batch, embs):
                    cur.execute(
                        """
                        INSERT INTO papers (title, abstract, link, embedding)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (link) DO UPDATE
                          SET title = EXCLUDED.title,
                              abstract = EXCLUDED.abstract,
                              embedding = EXCLUDED.embedding
                        """,
                        (r["title"], r["abstract"], r.get("link", ""), e),
                    )
                batch.clear()

            for r in records:
                if not r.get("title") or not r.get("abstract"):
                    continue
                batch.append(r)
                if len(batch) >= BATCH_SIZE:
                    flush_batch()
            flush_batch()

    print("Embedding upsert complete.")


if __name__ == "__main__":
    main()
