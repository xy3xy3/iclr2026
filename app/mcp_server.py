from typing import Any, Dict, List

from fastmcp import FastMCP, Context

# Ensure project root is on sys.path so `app` package is importable
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Reuse existing app logic and configuration
from app.db import ensure_schema, get_conn
from app.search import search_papers_multi


mcp = FastMCP("ICLR2026 Vector Search 🧠")


@mcp.tool
def paper_search(
    queries: List[str],
    limit: int = 10,
    mode: str = "vector",
    ctx: Context | None = None,
) -> List[Dict[str, Any]]:
    """Search ICLR2026 papers with vector or keyword mode.

    Args:
        queries: List of natural language queries (1-32 items).
        limit: Per-query number of results to return (default 10).
        mode: "vector" (embedding similarity) or "keyword" (full-text search).

    Returns:
        - vector 模式：返回列表，元素为 {"query": str, "results": [ {id, title, abstract, link, score} ]}
        - keyword 模式：返回扁平列表 [ {id, title, abstract, link, score} ]，
          其中总条数为 len(queries) × limit（合并 OR 检索）
    """
    ensure_schema()
    if not isinstance(queries, list) or len(queries) == 0:
        return []
    # Enforce max 32 queries for safety
    queries = [q for q in (queries or []) if isinstance(q, str) and q.strip()][:32]
    if ctx:
        ctx.info(f"Searching papers ({mode}) for {len(queries)} queries, limit={limit}")
    return search_papers_multi(queries, limit, mode)


@mcp.tool
def paper_details(paper_ids: List[int]) -> List[Dict[str, Any]]:
    """Fetch details for a list of paper IDs.

    Args:
        paper_ids: List of numeric IDs.

    Returns:
        List of paper dicts ordered to match the input IDs when found.
    """
    ensure_schema()
    # Normalize and cap list size for safety
    ids = [int(x) for x in (paper_ids or [])][:256]
    if not ids:
        return []
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Use = ANY(%s) so psycopg adapts Python list to SQL array
            cur.execute(
                "SELECT id, title, abstract, link FROM papers WHERE id = ANY(%s)",
                (ids,),
            )
            rows = cur.fetchall()
    by_id: Dict[int, Dict[str, Any]] = {
        int(r[0]): {"id": r[0], "title": r[1], "abstract": r[2], "link": r[3]}
        for r in rows
    }
    # Preserve requested order; skip IDs not found
    return [by_id[i] for i in ids if i in by_id]


if __name__ == "__main__":
    # Run with STDIO by default; other transports can be chosen by args
    mcp.run()
