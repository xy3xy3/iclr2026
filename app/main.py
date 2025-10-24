from typing import Any, Dict, List, Optional
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Query
from openai import OpenAI
import os

import gradio as gr
import psycopg
from pgvector.psycopg import register_vector, Vector

from .config import EMBED_DIM, EMBED_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL
from .db import ensure_schema, get_conn


def make_openai_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")
    if OPENAI_BASE_URL:
        return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    return OpenAI(api_key=OPENAI_API_KEY)


def embed_text(client: OpenAI, text: str) -> List[float]:
    text = text.replace("\n", " ")
    resp = client.embeddings.create(model=EMBED_MODEL, input=[text])
    return resp.data[0].embedding  # type: ignore


def combined_text(title: str, abstract: str) -> str:
    return f"Title: {title}\n\nAbstract: {abstract}"


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


@lru_cache(maxsize=512)
def embed_query_cached(text: str, model: str = EMBED_MODEL) -> List[float]:
    client = make_openai_client()
    t = text.replace("\n", " ")
    resp = client.embeddings.create(model=model, input=[t])
    return resp.data[0].embedding  # type: ignore


app = FastAPI(title="ICLR2026 Paper Search")


@app.on_event("startup")
def _on_startup() -> None:
    # Ensure schema exists at boot
    ensure_schema()


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

    # When selecting a row, update link textbox and the button's link (opens in new tab)
    out.select(fn=on_table_select, inputs=state_rows, outputs=[link_box, open_btn])


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
