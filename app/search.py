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


def embed_queries(texts: List[str], model: str = EMBED_MODEL) -> List[List[float]]:
    """Embed multiple queries in a single API call.

    Input texts are normalized by replacing newlines with spaces. Returns
    embeddings in the same order.
    """
    if not texts:
        return []
    client = make_openai_client()
    inputs = [t.replace("\n", " ") for t in texts]
    resp = client.embeddings.create(model=model, input=inputs)
    # resp.data is a list with .embedding for each input
    return [item.embedding for item in resp.data]  # type: ignore


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


def search_papers_vector_multi(queries: List[str], limit: int = 10) -> List[Dict[str, Any]]:
    """Vector search for multiple queries. Returns grouped results per query.

    Each result is {"query": str, "results": [ ... ]}. Limit applies per query.
    """
    if not queries:
        return []
    # Fast path for single query
    if len(queries) == 1:
        return [{"query": queries[0], "results": search_papers_vector(queries[0], limit)}]

    embs = embed_queries(queries, EMBED_MODEL)
    out: List[Dict[str, Any]] = []
    with get_conn() as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            for q, emb in zip(queries, embs):
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
                out.append({"query": q, "results": results})
    return out


def search_papers_keyword_multi(
    queries: List[str], limit: int = 10, fts_config: str = "english"
) -> List[Dict[str, Any]]:
    """Keyword/FTS search for multiple queries. Returns grouped results per query.

    For clarity and per-query limits, executes per-query rather than a single OR.
    """
    if not queries:
        return []
    out: List[Dict[str, Any]] = []
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
            for q in queries:
                cur.execute(sql, (q, q, limit))
                rows = cur.fetchall()
                results = [
                    {
                        "id": r[0],
                        "title": r[1],
                        "abstract": r[2],
                        "link": r[3],
                        "score": float(r[4]) if r[4] is not None else 0.0,
                    }
                    for r in rows
                ]
                out.append({"query": q, "results": results})
    return out


def search_papers_multi(queries: List[str], limit: int = 10, mode: str = "vector") -> List[Dict[str, Any]]:
    """Multi-query search helper.

    Returns a list of {"query": str, "results": [...]}, preserving input order.
    """
    # Normalize queries: strip and drop empties
    qnorm = [q.strip() for q in (queries or []) if isinstance(q, str) and q.strip()]
    if not qnorm:
        return []
    mode_norm = (mode or "vector").strip().lower()
    if mode_norm in ("kw", "keyword", "text", "fts"):
        return search_papers_keyword_multi(qnorm, limit)
    return search_papers_vector_multi(qnorm, limit)
