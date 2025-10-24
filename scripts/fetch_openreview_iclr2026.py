import asyncio
import json
import math
import os
import random
import sys
from typing import Any, Dict, List, Optional

import httpx
from email.utils import parsedate_to_datetime


API_BASE = "https://api2.openreview.net/notes"
FORUM_BASE = "https://openreview.net/forum?id="

# Tunables
PAGE_SIZE = int(os.getenv("OPENREVIEW_PAGE_SIZE", "100"))  # per-request limit
CONCURRENCY = int(os.getenv("OPENREVIEW_CONCURRENCY", "3"))  # concurrent page fetches
TIMEOUT = float(os.getenv("OPENREVIEW_TIMEOUT", "30"))  # seconds per request
RPS = float(os.getenv("OPENREVIEW_RPS", "1"))  # requests per second (global)
MAX_RETRIES = int(os.getenv("OPENREVIEW_MAX_RETRIES", "6"))
BACKOFF_BASE = float(os.getenv("OPENREVIEW_BACKOFF_BASE", "1.5"))

DOMAIN = "ICLR.cc/2026/Conference"
VENUEID = f"{DOMAIN}/Submission"


def note_to_record(note: Dict[str, Any]) -> Dict[str, str]:
    content = note.get("content", {})

    def get_value(field: str) -> str:
        v = content.get(field)
        if isinstance(v, dict):
            return v.get("value", "") or ""
        return v or ""

    title = get_value("title")
    abstract = get_value("abstract")
    forum = note.get("forum") or note.get("id")
    link = FORUM_BASE + str(forum) if forum else ""
    return {
        "title": title,
        "abstract": abstract,
        "link": link,
    }


class AsyncIntervalLimiter:
    def __init__(self, rps: float):
        self.interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self):
        if self.interval <= 0:
            return
        async with self._lock:
            now = asyncio.get_event_loop().time()
            wait = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.interval
        if wait > 0:
            await asyncio.sleep(wait)


async def fetch_page(
    client: httpx.AsyncClient,
    offset: int,
    limit: int,
    limiter: Optional[AsyncIntervalLimiter] = None,
) -> Dict[str, Any]:
    params = {
        "content.venueid": VENUEID,
        "domain": DOMAIN,
        "limit": str(limit),
        "offset": str(offset),
    }

    attempt = 0
    while True:
        if limiter is not None:
            await limiter.wait()
        try:
            r = await client.get(API_BASE, params=params)
            if r.status_code == 429:
                # Respect Retry-After header when present
                retry_after = r.headers.get("Retry-After")
                delay = None
                if retry_after:
                    try:
                        # It can be seconds or HTTP date
                        if retry_after.isdigit():
                            delay = float(retry_after)
                        else:
                            dt = parsedate_to_datetime(retry_after)
                            delay = max(0.0, (dt.timestamp() - asyncio.get_event_loop().time()))
                    except Exception:
                        delay = None
                if delay is None:
                    # exponential backoff with jitter
                    delay = (BACKOFF_BASE ** attempt) + random.uniform(0, 0.5)
                attempt += 1
                if attempt > MAX_RETRIES:
                    r.raise_for_status()
                await asyncio.sleep(delay)
                continue

            if 500 <= r.status_code < 600:
                attempt += 1
                if attempt > MAX_RETRIES:
                    r.raise_for_status()
                delay = (BACKOFF_BASE ** attempt) + random.uniform(0, 0.5)
                await asyncio.sleep(delay)
                continue

            r.raise_for_status()
            return r.json()
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
            attempt += 1
            if attempt > MAX_RETRIES:
                raise
            delay = (BACKOFF_BASE ** attempt) + random.uniform(0, 0.5)
            await asyncio.sleep(delay)


async def gather_all_notes() -> List[Dict[str, Any]]:
    headers = {
        "accept": "application/json,text/*;q=0.99",
        "referer": "https://openreview.net/",
        "user-agent": "TrendLLM-fetch/1.0"
    }

    limits = httpx.Limits(max_keepalive_connections=CONCURRENCY, max_connections=CONCURRENCY)
    timeout = httpx.Timeout(TIMEOUT)
    async with httpx.AsyncClient(headers=headers, timeout=timeout, limits=limits) as client:
        limiter = AsyncIntervalLimiter(RPS)
        # Initial call to get total count and first page
        first = await fetch_page(client, offset=0, limit=PAGE_SIZE, limiter=limiter)
        notes = first.get("notes", [])
        total = int(first.get("count", len(notes)))

        # Optional cap for testing
        max_notes_env = os.getenv("OPENREVIEW_MAX_NOTES")
        if max_notes_env:
            try:
                cap = int(max_notes_env)
                total = min(total, max(0, cap))
            except ValueError:
                pass

        # Initial progress log
        if total > 0:
            current = min(total, len(notes))
            pct = (current * 100.0) / total
            print(f"Fetch progress: {current}/{total} ({pct:.1f}%)")

        if total <= len(notes):
            return notes

        # Prepare remaining page fetches
        remaining = total - len(notes)
        # next offsets start at len(notes)
        page_indices = list(range(len(notes), total, PAGE_SIZE))

        semaphore = asyncio.Semaphore(CONCURRENCY)

        async def fetch_with_sem(offset: int) -> List[Dict[str, Any]]:
            async with semaphore:
                data = await fetch_page(client, offset=offset, limit=PAGE_SIZE, limiter=limiter)
                return data.get("notes", [])

        tasks = [asyncio.create_task(fetch_with_sem(o)) for o in page_indices]
        for task in asyncio.as_completed(tasks):
            try:
                page_notes = await task
                notes.extend(page_notes)
                if total > 0:
                    current = min(total, len(notes))
                    pct = (current * 100.0) / total
                    print(f"Fetch progress: {current}/{total} ({pct:.1f}%)")
            except Exception as e:
                # Best-effort: log and continue
                print(f"Warn: page fetch failed: {e}")

        return notes


async def main() -> None:
    print("Fetching OpenReview ICLR 2026 submissions...")
    notes = await gather_all_notes()
    print(f"Fetched notes: {len(notes)}")

    # Filtering progress
    records: List[Dict[str, str]] = []
    n_total = len(notes)
    for i, n in enumerate(notes, start=1):
        rec = note_to_record(n)
        records.append(rec)
        if n_total > 0 and (i == n_total or i % max(1, n_total // 20) == 0):  # ~5% steps
            pct = (i * 100.0) / n_total
            print(f"Filter progress: {i}/{n_total} ({pct:.1f}%)")

    # Ensure output directory
    out_dir = os.path.join("data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "iclr2026.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(records)} records to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())