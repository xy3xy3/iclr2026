import json
import os
import socket
import asyncio
import random
import time
from typing import Dict, List, Set, Tuple, Optional

import psycopg
from pgvector.psycopg import register_vector, Vector
from openai import OpenAI, AsyncOpenAI
try:
    from openai import APIError, RateLimitError, APIConnectionError
except Exception:  # fallback for older clients
    APIError = Exception  # type: ignore
    RateLimitError = Exception  # type: ignore
    APIConnectionError = Exception  # type: ignore


DATA_PATH = os.getenv("DATA_PATH", os.path.join("data", "iclr2026.json"))
MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
EMBED_ONLY_MISSING = os.getenv("EMBED_ONLY_MISSING", "1").lower() in ("1", "true", "yes", "y")
EMBED_FORCE = os.getenv("EMBED_FORCE", "0").lower() in ("1", "true", "yes", "y")
EMBED_BATCH = int(os.getenv("EMBED_BATCH", "64"))
EMBED_CONCURRENCY = int(os.getenv("EMBED_CONCURRENCY", "1"))
EMBED_MAX_RETRIES = int(os.getenv("EMBED_MAX_RETRIES", "5"))
EMBED_BACKOFF_BASE = float(os.getenv("EMBED_BACKOFF_BASE", "1.5"))
EMBED_TASK_DELAY_MS = int(os.getenv("EMBED_TASK_DELAY_MS", "0"))  # delay between starting tasks
EMBED_LOG_FILE = os.getenv("EMBED_LOG_FILE", "")
EMBED_LOG_APPEND = os.getenv("EMBED_LOG_APPEND", "1").lower() in ("1", "true", "yes", "y")


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


def _is_resolvable(host: str) -> bool:
    try:
        # Try to resolve DNS / host
        socket.getaddrinfo(host, None)
        return True
    except Exception:
        return False


def _resolves_to_loopback(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
        for _, _, _, _, sockaddr in infos:
            ip = sockaddr[0]
            if ip.startswith("127.") or ip == "::1":
                return True
        return False
    except Exception:
        return False


def connect_with_fallback() -> psycopg.Connection:
    primary = dsn_from_env()
    try:
        return psycopg.connect(primary, autocommit=True)
    except psycopg.OperationalError as e:
        host = os.getenv("POSTGRES_HOST", "")
        port = os.getenv("POSTGRES_PORT", "")
        db = os.getenv("POSTGRES_DB", "iclr2026")
        user = os.getenv("POSTGRES_USER", "iclr")
        pw = os.getenv("POSTGRES_PASSWORD", "iclrpass")

        # Fallback rules aligned with app/db.py:
        # 1) host not resolvable -> 127.0.0.1:5433
        # 2) host == 'pgvector' -> 127.0.0.1:5433
        # 3) host resolves to loopback and port != 5433 -> 127.0.0.1:5433
        should_fallback = False
        if host and not _is_resolvable(host):
            should_fallback = True
        if host.lower() == "pgvector":
            should_fallback = True
        if _resolves_to_loopback(host or "127.0.0.1") and port not in ("", "5433"):
            should_fallback = True

        if should_fallback:
            fallback = f"postgresql://{user}:{pw}@127.0.0.1:5433/{db}"
            print(f"Warn: falling back to local DB {fallback}", flush=True)
            return psycopg.connect(fallback, autocommit=True)
        raise


def make_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def make_async_client() -> AsyncOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        return AsyncOpenAI(api_key=api_key, base_url=base_url)
    return AsyncOpenAI(api_key=api_key)


def embed_texts(client: OpenAI, texts: List[str]) -> List[List[float]]:
    # OpenAI supports batching
    inputs = [t.replace("\n", " ") for t in texts]
    resp = client.embeddings.create(model=MODEL, input=inputs)
    return [d.embedding for d in resp.data]  # type: ignore


async def embed_texts_async(client: AsyncOpenAI, texts: List[str]) -> List[List[float]]:
    inputs = [t.replace("\n", " ") for t in texts]
    resp = await client.embeddings.create(model=MODEL, input=inputs)
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

    client = make_client()

    # optional log file
    log_fp: Optional[object] = None
    def log(msg: str) -> None:
        print(msg, flush=True)
        if log_fp is not None:
            try:
                log_fp.write(msg + "\n")  # type: ignore[attr-defined]
                log_fp.flush()  # type: ignore[attr-defined]
            except Exception:
                pass

    if EMBED_LOG_FILE:
        try:
            d = os.path.dirname(EMBED_LOG_FILE)
            if d:
                os.makedirs(d, exist_ok=True)
            mode = "a" if EMBED_LOG_APPEND else "w"
            log_fp = open(EMBED_LOG_FILE, mode, encoding="utf-8")
            log(f"[log] writing progress to {EMBED_LOG_FILE} (append={EMBED_LOG_APPEND})")
        except Exception as e:
            print(f"Warn: cannot open EMBED_LOG_FILE '{EMBED_LOG_FILE}': {e}")

    started_at = time.perf_counter()

    with connect_with_fallback() as conn:
        ensure_schema(conn)
        # register after extension exists
        register_vector(conn)
        with conn.cursor() as cur:
            # 1) Upsert title/abstract/link; collect which links need embeddings
            #    If EMBED_FORCE=1 -> embed all; else if EMBED_ONLY_MISSING=1 -> embed only missing
            #    else -> embed all
            BATCH_SIZE = EMBED_BATCH

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

            total = len(to_embed)
            if total == 0:
                log("No records need embedding.")
                log("Embedding upsert complete.")
                return

            log(f"Embedding required for {total} records.")

            # 2) Embed and update only the necessary rows
            def chunks(lst, n):
                for i in range(0, len(lst), n):
                    yield lst[i : i + n]

            groups: List[List[Dict[str, str]]] = list(chunks(to_embed, BATCH_SIZE))

            done = 0
            if EMBED_CONCURRENCY <= 1:
                # Synchronous path
                for group in groups:
                    texts = [f"Title: {r['title']}\n\nAbstract: {r['abstract']}" for r in group]
                    embs = embed_texts(client, texts)
                    for r, e in zip(group, embs):
                        cur.execute("UPDATE papers SET embedding = %s WHERE link = %s", (Vector(e), r["link"]))
                    done += len(group)
                    pct = (done * 100.0) / max(1, total)
                    elapsed = time.perf_counter() - started_at
                    rate = (done / elapsed) if elapsed > 0 else 0.0
                    remaining = max(0, total - done)
                    eta = (remaining / rate) if rate > 0 else 0.0
                    eta_m = int(eta // 60)
                    eta_s = int(eta % 60)
                    log(f"Embed progress: {done}/{total} ({pct:.1f}%) | rate: {rate:.2f}/s | ETA: {eta_m:02d}:{eta_s:02d}")
            else:
                # Concurrent async path
                async_client = make_async_client()

                async def worker(g: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]], List[List[float]]]:
                    attempt = 0
                    while True:
                        try:
                            texts = [f"Title: {r['title']}\n\nAbstract: {r['abstract']}" for r in g]
                            embs = await embed_texts_async(async_client, texts)
                            return g, embs
                        except (RateLimitError, APIError, APIConnectionError, Exception) as e:  # broad retry
                            attempt += 1
                            if attempt > EMBED_MAX_RETRIES:
                                raise
                            delay = (EMBED_BACKOFF_BASE ** attempt) + random.uniform(0, 0.5)
                            await asyncio.sleep(delay)

                async def run_all():
                    sem = asyncio.Semaphore(EMBED_CONCURRENCY)

                    async def guarded(g):
                        async with sem:
                            if EMBED_TASK_DELAY_MS > 0:
                                await asyncio.sleep(EMBED_TASK_DELAY_MS / 1000.0)
                            return await worker(g)

                    tasks = [asyncio.create_task(guarded(g)) for g in groups]
                    nonlocal done
                    for task in asyncio.as_completed(tasks):
                        g, embs = await task
                        for r, e in zip(g, embs):
                            cur.execute("UPDATE papers SET embedding = %s WHERE link = %s", (Vector(e), r["link"]))
                        done += len(g)
                        pct = (done * 100.0) / max(1, total)
                        elapsed = time.perf_counter() - started_at
                        rate = (done / elapsed) if elapsed > 0 else 0.0
                        remaining = max(0, total - done)
                        eta = (remaining / rate) if rate > 0 else 0.0
                        eta_m = int(eta // 60)
                        eta_s = int(eta % 60)
                        log(f"Embed progress: {done}/{total} ({pct:.1f}%) | rate: {rate:.2f}/s | ETA: {eta_m:02d}:{eta_s:02d}")

                asyncio.run(run_all())
    log("Embedding upsert complete.")
    if log_fp is not None:
        try:
            log_fp.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
