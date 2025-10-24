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
from app.search import search_papers


mcp = FastMCP("ICLR2026 Vector Search 🧠")


@mcp.tool
def paper_search(query: str, limit: int = 10, mode: str = "vector", ctx: Context | None = None) -> List[Dict[str, Any]]:
    """Search ICLR2026 papers with vector or keyword mode.

    Args:
        query: Natural language query.
        limit: Number of results to return (default 10).
        mode: "vector" (embedding similarity) or "keyword" (full-text search).

    Returns:
        A list of results: id, title, abstract, link, score.
    """
    # Ensure DB is ready before serving the search call
    ensure_schema()
    if ctx:
        # Small user-facing note in MCP clients
        ctx.info(f"Searching papers ({mode}) for: {query}")
    return search_papers(query, limit, mode)


@mcp.resource("paper://{paper_id}")
def paper_resource(paper_id: int) -> Dict[str, Any]:
    """Fetch a single paper's details by numeric id.

    URI format: paper://{paper_id}
    """
    ensure_schema()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, abstract, link FROM papers WHERE id = %s",
                (paper_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"error": f"paper id {paper_id} not found"}
            return {
                "id": row[0],
                "title": row[1],
                "abstract": row[2],
                "link": row[3],
            }


if __name__ == "__main__":
    # Run with STDIO by default; other transports can be chosen by args
    mcp.run()
