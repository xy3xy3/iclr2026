from functools import lru_cache
from typing import Any, Dict, List

from openai import OpenAI
from pgvector.psycopg import register_vector, Vector

from .config import EMBED_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL
from .db import get_conn


def make_openai_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")
    if OPENAI_BASE_URL:
        return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    return OpenAI(api_key=OPENAI_API_KEY)


@lru_cache(maxsize=512)
def embed_query_cached(text: str, model: str = EMBED_MODEL) -> List[float]:
    client = make_openai_client()
    t = text.replace("\n", " ")
    resp = client.embeddings.create(model=model, input=[t])
    return resp.data[0].embedding  # type: ignore


def search_papers(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    emb = embed_query_cached(query, EMBED_MODEL)

    with get_conn() as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, abstract, link, (1 - (embedding <=> %s)) as score
                FROM papers
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (Vector(emb), Vector(emb), limit),
            )
            rows = cur.fetchall()
    results = [
        {
            "id": r[0],
            "title": r[1],
            "abstract": r[2],
            "link": r[3],
            "score": float(r[4]),
        }
        for r in rows
    ]
    return results

