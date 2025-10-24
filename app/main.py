from typing import Any, Dict, List

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
import gradio as gr

from .db import ensure_schema
from .search import search_papers
from .mcp_server import mcp


# Create MCP ASGI app and combine lifespans so both our app init and MCP session
# manager run correctly in a single Uvicorn process.
mcp_app = mcp.http_app(path="/")


@asynccontextmanager
async def combined_lifespan(fastapi_app: FastAPI):
    # App startup (e.g., ensure DB schema)
    ensure_schema()
    # Run MCP lifespan nested so its resources/session manager initialize too
    async with mcp_app.lifespan(fastapi_app):
        yield


app = FastAPI(title="ICLR2026 Paper Search", lifespan=combined_lifespan)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/search")
def api_search(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50)) -> Dict[str, Any]:
    try:
        results = search_papers(q, limit)
    except Exception as e:
        raise HTTPException(500, f"search failed: {e}")
    return {"query": q, "results": results}


def gradio_interface(query: str, top_k: int):
    if not query.strip():
        return [], []
    rows = search_papers(query, top_k)
    table = [[r["score"], r["title"], r["link"], r["abstract"]] for r in rows]
    return table, table


def on_table_select(evt: gr.SelectData, rows: List[List[Any]]):
    # evt.index is typically (row, col)
    row_idx = 0
    try:
        idx = evt.index  # type: ignore[attr-defined]
        if isinstance(idx, (list, tuple)) and len(idx) >= 1:
            row_idx = int(idx[0])
        elif isinstance(idx, int):
            row_idx = idx
    except Exception:
        row_idx = 0

    link = ""
    try:
        if isinstance(rows, list) and 0 <= row_idx < len(rows):
            link = str(rows[row_idx][2])  # third column is link
    except Exception:
        link = ""

    return gr.update(value=link), gr.update(link=link)


with gr.Blocks(title="ICLR2026 Paper Search") as demo:
    gr.Markdown("# ICLR2026 Paper Semantic Search (pgvector)")
    with gr.Row():
        q = gr.Textbox(label="Query", placeholder="e.g., emotion classification in software engineering")
        k = gr.Slider(minimum=1, maximum=50, step=1, value=10, label="Top K")
    btn = gr.Button("Search")
    out = gr.Dataframe(
        headers=["score", "title", "link", "abstract"],
        datatype=["number", "str", "str", "str"],
        wrap=True,
        interactive=False,
        label="Results (score is similarity: higher is better)",
    )
    state_rows = gr.State([])
    with gr.Row():
        link_box = gr.Textbox(label="Link", interactive=False, show_copy_button=True)
        open_btn = gr.Button("Open Link", variant="secondary")

    # Search triggers table + state update
    btn.click(fn=gradio_interface, inputs=[q, k], outputs=[out, state_rows])

    # When selecting a row, update link textbox only
    out.select(fn=on_table_select, inputs=state_rows, outputs=[link_box])

    # Open the link in a new tab/window on click using JS
    open_btn.click(
        fn=None,
        inputs=link_box,
        outputs=None,
        _js="(link) => { if (link) window.open(link, '_blank', 'noopener'); }",
    )


# Mount Gradio at /gradio
try:
    from gradio import mount_gradio_app as _mount
except Exception:
    try:
        from gradio.routes import App  # type: ignore

        def _mount(fastapi_app: FastAPI, blocks: gr.Blocks, path: str = "/gradio"):
            fastapi_app.mount(path, App.create_app(blocks))
    except Exception:
        # Last-resort simple mounting (may not work on very old gradio)
        def _mount(fastapi_app: FastAPI, blocks: gr.Blocks, path: str = "/gradio"):
            fastapi_app.mount(path, gr.routes.App.create_app(blocks))  # type: ignore


_mount(app, demo, path="/gradio")

# Mount MCP routes under the same FastAPI app at /mcp
app.mount("/mcp", mcp_app)
