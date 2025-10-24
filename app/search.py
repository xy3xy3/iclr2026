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


def search_papers_vector(query: str, limit: int = 10) -> List[Dict[str, Any]]:
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
    return [
        {
            "id": r[0],
            "title": r[1],
            "abstract": r[2],
            "link": r[3],
            "score": float(r[4]),
        }
        for r in rows
    ]


def search_papers_keyword(query: str, limit: int = 10, fts_config: str = "english") -> List[Dict[str, Any]]:
    # Keyword/FTS search over title + abstract using Postgres full-text search.
    # Uses websearch_to_tsquery for intuitive parsing, ranks by ts_rank_cd.
    with get_conn() as conn:
        with conn.cursor() as cur:
            sql = f"""
                SELECT
                    id,
                    title,
                    abstract,
                    link,
                    ts_rank_cd(
                        to_tsvector('{fts_config}', coalesce(title,'') || ' ' || coalesce(abstract,'')),
                        websearch_to_tsquery('{fts_config}', %s)
                    ) AS score
                FROM papers
                WHERE to_tsvector('{fts_config}', coalesce(title,'') || ' ' || coalesce(abstract,''))
                      @@ websearch_to_tsquery('{fts_config}', %s)
                ORDER BY score DESC
                LIMIT %s
            """
            cur.execute(sql, (query, query, limit))
            rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "title": r[1],
            "abstract": r[2],
            "link": r[3],
            "score": float(r[4]) if r[4] is not None else 0.0,
        }
        for r in rows
    ]


def search_papers(query: str, limit: int = 10, mode: str = "vector") -> List[Dict[str, Any]]:
    mode_norm = (mode or "vector").strip().lower()
    if mode_norm in ("kw", "keyword", "text", "fts"):
        return search_papers_keyword(query, limit)
    # default vector
    return search_papers_vector(query, limit)
