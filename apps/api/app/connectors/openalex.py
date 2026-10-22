"""OpenAlex works search (citation/topic momentum)."""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

import httpx

from .http import RawItem, content_hash, get_json, now_utc

SOURCE_KEY = "openalex"
WORKS_URL = "https://api.openalex.org/works"


def abstract_from_index(inv: dict[str, list[int]] | None) -> str:
    if not inv:
        return ""
    pos: dict[int, str] = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def map_work(w: dict[str, Any]) -> dict[str, Any]:
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    authors, insts = [], []
    for a in w.get("authorships", []) or []:
        name = (a.get("author") or {}).get("display_name")
        if name:
            authors.append(name)
        for inst in a.get("institutions", []) or []:
            if inst.get("display_name") and inst["display_name"] not in insts:
                insts.append(inst["display_name"])
    topics = [t.get("display_name") for t in (w.get("topics") or w.get("concepts") or [])
              if t.get("display_name")]
    return {
        "openalex_id": w.get("id"),
        "doi": w.get("doi"),
        "title": (w.get("display_name") or w.get("title") or "").strip(),
        "publication_date": w.get("publication_date"),
        "type": w.get("type"),
        "venue": src.get("display_name"),
        "landing_page_url": loc.get("landing_page_url"),
        "cited_by_count": w.get("cited_by_count", 0),
        "authors": authors[:20],
        "institutions": insts[:20],
        "topics": topics[:10],
        "abstract": abstract_from_index(w.get("abstract_inverted_index")),
    }


def to_raw_item(w: dict[str, Any]) -> RawItem:
    d = map_work(w)
    url = d.get("doi") or d.get("landing_page_url") or d.get("openalex_id")
    ext = (d.get("openalex_id") or "").rsplit("/", 1)[-1]
    kind = "preprint" if d.get("type") == "preprint" else "paper"
    return RawItem(
        source_key=SOURCE_KEY,
        external_id=ext,
        url=url,
        title=d["title"],
        published_at=d.get("publication_date"),
        kind=kind,
        text=" ".join(x for x in [d["title"], d.get("venue") or "", " ".join(d["topics"]),
                                  d["abstract"]] if x),
        data=d,
        retrieved_at=now_utc(),
        content_hash=content_hash(d),
    )


async def search_works(term: str, days: int = 365, per_page: int = 25,
                       client: httpx.AsyncClient | None = None) -> list[RawItem]:
    since = (date.today() - timedelta(days=days)).isoformat()
    params: dict[str, Any] = {
        "search": term,
        "sort": "publication_date:desc",
        "filter": f"from_publication_date:{since}",
        "per-page": per_page,
    }
    mailto = os.environ.get("OPENALEX_MAILTO")
    if mailto:
        params["mailto"] = mailto
    payload = await get_json(SOURCE_KEY, WORKS_URL, params, client)
    return [to_raw_item(w) for w in payload.get("results", []) or [] if w.get("id")]
