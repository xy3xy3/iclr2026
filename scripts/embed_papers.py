import json
import os
from typing import Dict, List, Set

import psycopg
from pgvector.psycopg import register_vector
from openai import OpenAI


DATA_PATH = os.getenv("DATA_PATH", os.path.join("data", "iclr2026.json"))
MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
EMBED_ONLY_MISSING = os.getenv("EMBED_ONLY_MISSING", "1").lower() in ("1", "true", "yes", "y")
EMBED_FORCE = os.getenv("EMBED_FORCE", "0").lower() in ("1", "true", "yes", "y")


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
        ensure_schema(conn)
        # register after extension exists
        register_vector(conn)
        with conn.cursor() as cur:
            # 1) Upsert title/abstract/link; collect which links need embeddings
            #    If EMBED_FORCE=1 -> embed all; else if EMBED_ONLY_MISSING=1 -> embed only missing
            #    else -> embed all
            BATCH_SIZE = int(os.getenv("EMBED_BATCH", "64"))

            existing_with_emb: Set[str] = set()
            if not EMBED_FORCE and EMBED_ONLY_MISSING:
                cur.execute("SELECT link FROM papers WHERE embedding IS NOT NULL")
                existing_with_emb = {row[0] for row in cur.fetchall()}

            to_embed: List[Dict[str, str]] = []

            for r in records:
                title = (r.get("title") or "").strip()
                abstract = (r.get("abstract") or "").strip()
                link = (r.get("link") or "").strip()
                if not title or not abstract or not link:
                    continue
                # Upsert metadata without touching embedding
                cur.execute(
                    """
                    INSERT INTO papers (title, abstract, link)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (link) DO UPDATE
                      SET title = EXCLUDED.title,
                          abstract = EXCLUDED.abstract
                    """,
                    (title, abstract, link),
                )

                need = True
                if EMBED_FORCE:
                    need = True
                elif EMBED_ONLY_MISSING:
                    need = link not in existing_with_emb
                else:
                    need = True

                if need:
                    to_embed.append({"title": title, "abstract": abstract, "link": link})

            # 2) Embed and update only the necessary rows
            def chunks(lst, n):
                for i in range(0, len(lst), n):
                    yield lst[i : i + n]

            for group in chunks(to_embed, BATCH_SIZE):
                texts = [f"Title: {r['title']}\n\nAbstract: {r['abstract']}" for r in group]
                embs = embed_texts(client, texts)
                for r, e in zip(group, embs):
                    cur.execute(
                        "UPDATE papers SET embedding = %s WHERE link = %s",
                        (e, r["link"]),
                    )

    print("Embedding upsert complete.")


if __name__ == "__main__":
    main()
