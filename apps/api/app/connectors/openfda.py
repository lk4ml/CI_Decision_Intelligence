"""openFDA drug label + Drugs@FDA connector."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from .http import RawItem, SourceUnavailable, content_hash, get_json, now_utc

SOURCE_KEY = "openfda"
BASE = "https://api.fda.gov"
LABEL_URL = f"{BASE}/drug/label.json"
DRUGSFDA_URL = f"{BASE}/drug/drugsfda.json"
DAILYMED_URL = "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={setid}"
DRUGSFDA_PAGE = ("https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm"
                 "?event=overview.process&ApplNo={appl}")
RECENT_DAYS = 365


def _search_expr(name: str) -> str:
    n = name.replace('"', "")
    return f'openfda.generic_name:"{n}" OR openfda.brand_name:"{n}"'


async def _query(url: str, search: str, limit: int, client) -> list[dict[str, Any]]:
    try:
        payload = await get_json(SOURCE_KEY, url, {"search": search, "limit": limit}, client)
    except SourceUnavailable as e:
        # openFDA answers 404 {"error":{"code":"NOT_FOUND"}} when nothing matches.
        if e.detail.startswith("HTTP 404") and "NOT_FOUND" in e.detail:
            return []
        raise
    return payload.get("results", []) or []


def _first(v: Any) -> Any:
    return v[0] if isinstance(v, list) and v else v


def _fmt_date(s: str | None) -> str | None:
    if s and len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def map_label(r: dict[str, Any]) -> dict[str, Any]:
    of = r.get("openfda") or {}
    return {
        "id": r.get("id"),
        "set_id": r.get("set_id"),
        "version": r.get("version"),
        "effective_time": _fmt_date(r.get("effective_time")),
        "brand_name": _first(of.get("brand_name")),
        "generic_name": _first(of.get("generic_name")),
        "manufacturer": _first(of.get("manufacturer_name")),
        "application_number": _first(of.get("application_number")),
        "indications_and_usage": " ".join(r.get("indications_and_usage") or [])[:4000],
        "boxed_warning": " ".join(r.get("boxed_warning") or [])[:1500],
    }


def label_item(r: dict[str, Any]) -> RawItem | None:
    d = map_label(r)
    if not d.get("set_id"):
        return None
    title = f"FDA label: {d.get('brand_name') or d.get('generic_name')} " \
            f"(effective {d.get('effective_time')})"
    return RawItem(
        source_key=SOURCE_KEY,
        external_id=f"label:{d['set_id']}",
        url=DAILYMED_URL.format(setid=d["set_id"]),
        title=title,
        published_at=d.get("effective_time"),
        kind="label_change",
        text=" ".join(x for x in [title, d.get("generic_name") or "", d.get("manufacturer") or "",
                                  d["indications_and_usage"], d["boxed_warning"]] if x),
        data=d,
        retrieved_at=now_utc(),
        content_hash=content_hash(d),
    )


def map_application(r: dict[str, Any]) -> dict[str, Any]:
    of = r.get("openfda") or {}
    subs = sorted(r.get("submissions", []) or [],
                  key=lambda s: s.get("submission_status_date") or "", reverse=True)
    products = r.get("products", []) or []
    return {
        "application_number": r.get("application_number"),
        "sponsor": r.get("sponsor_name"),
        "brand_name": _first(of.get("brand_name")) or _first([p.get("brand_name") for p in products]),
        "generic_name": _first(of.get("generic_name")),
        "products": [{"brand_name": p.get("brand_name"),
                      "active_ingredients": p.get("active_ingredients"),
                      "marketing_status": p.get("marketing_status")} for p in products],
        "submissions": [{"type": s.get("submission_type"), "number": s.get("submission_number"),
                         "status": s.get("submission_status"),
                         "status_date": _fmt_date(s.get("submission_status_date")),
                         "class": s.get("submission_class_code_description")
                         or s.get("submission_class_code")} for s in subs],
    }


def application_item(r: dict[str, Any]) -> RawItem | None:
    d = map_application(r)
    appl = d.get("application_number")
    if not appl:
        return None
    latest = d["submissions"][0] if d["submissions"] else {}
    cutoff = (date.today() - timedelta(days=RECENT_DAYS)).isoformat()
    recent_ap = latest.get("status") == "AP" and (latest.get("status_date") or "") >= cutoff
    kind = "approval" if recent_ap else "regulatory_record"
    name = d.get("brand_name") or d.get("generic_name") or appl
    title = (f"FDA {latest.get('type', '')} {latest.get('status', '')} for {name} ({appl})"
             f" on {latest.get('status_date')}" if latest else f"FDA application {appl} ({name})")
    digits = "".join(ch for ch in appl if ch.isdigit())
    return RawItem(
        source_key=SOURCE_KEY,
        external_id=f"appl:{appl}",
        url=DRUGSFDA_PAGE.format(appl=digits) if digits else
        f"{DRUGSFDA_URL}?search=application_number:{quote(appl)}",
        title=title,
        published_at=latest.get("status_date"),
        kind=kind,
        text=" ".join(x for x in [title, d.get("sponsor") or "", d.get("generic_name") or "",
                                  str(latest.get("class") or "")] if x),
        data=d,
        retrieved_at=now_utc(),
        content_hash=content_hash(d),
    )


async def search_drug(name: str, limit: int = 5,
                      client: httpx.AsyncClient | None = None) -> list[RawItem]:
    expr = _search_expr(name)
    items: list[RawItem] = []
    for r in await _query(LABEL_URL, expr, limit, client):
        it = label_item(r)
        if it:
            items.append(it)
    for r in await _query(DRUGSFDA_URL, expr, limit, client):
        it = application_item(r)
        if it:
            items.append(it)
    return items
