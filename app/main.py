from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from openai import OpenAI
import os

import gradio as gr
import psycopg
from pgvector.psycopg import register_vector

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
    client = make_openai_client()
    emb = embed_text(client, query)

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
                (emb, emb, limit),
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


def gradio_interface(query: str, top_k: int) -> List[List[Any]]:
    if not query.strip():
        return []
    rows = search_papers(query, top_k)
    return [[r["score"], r["title"], r["link"], r["abstract"]] for r in rows]


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
    btn.click(fn=gradio_interface, inputs=[q, k], outputs=out)


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
