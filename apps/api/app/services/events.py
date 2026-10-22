"""In-process async pub/sub bus for SSE.

- `publish(type, data, asset_slug=None)` — safe from sync code / any thread.
- `subscribe(asset_slug=None)` — async generator yielding event dicts
  `{type, data, asset, at}`; asset_slug=None receives everything; a subscriber for a
  specific asset also receives global (asset=None) events.
- `recent(asset_slug=None, limit=50)` — ring buffer of last events.
"""
from __future__ import annotations

import asyncio
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

_lock = threading.Lock()
_subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue, Optional[str]]] = []
_recent: deque = deque(maxlen=500)


def _matches(sub_asset: Optional[str], ev_asset: Optional[str]) -> bool:
    return sub_asset is None or ev_asset is None or sub_asset == ev_asset


def publish(type: str, data: dict | None = None, asset_slug: Optional[str] = None) -> dict:
    ev = {
        "type": type,
        "data": data or {},
        "asset": asset_slug,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        _recent.append(ev)
        subs = list(_subs)
    for loop, q, sub_asset in subs:
        if not _matches(sub_asset, asset_slug):
            continue
        try:
            loop.call_soon_threadsafe(q.put_nowait, ev)
        except RuntimeError:  # loop closed
            pass
    return ev


async def subscribe(asset_slug: Optional[str] = None) -> AsyncIterator[dict]:
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    entry = (loop, q, asset_slug)
    with _lock:
        _subs.append(entry)
    try:
        while True:
            yield await q.get()
    finally:
        with _lock:
            if entry in _subs:
                _subs.remove(entry)


def recent(asset_slug: Optional[str] = None, limit: int = 50) -> list[dict]:
    with _lock:
        items = [e for e in _recent if _matches(asset_slug, e["asset"])]
    return items[-limit:]


def subscriber_count() -> int:
    with _lock:
        return len(_subs)
