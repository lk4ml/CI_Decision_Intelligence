"""Europe PMC REST search (abstracts, preprints, conference content)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx

from .http import RawItem, content_hash, get_json, now_utc

SOURCE_KEY = "europepmc"
SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ARTICLE_URL = "https://europepmc.org/article/{src}/{id}"


def item_url(r: dict[str, Any]) -> str:
    if r.get("doi"):
        return f"https://doi.org/{r['doi']}"
    if r.get("pmid"):
        return f"https://pubmed.ncbi.nlm.nih.gov/{r['pmid']}/"
    return ARTICLE_URL.format(src=r.get("source", "MED"), id=r.get("id"))


def classify(r: dict[str, Any]) -> str:
    src = r.get("source")
    types = [t.lower() for t in ((r.get("pubTypeList") or {}).get("pubType") or [])]
    if src == "PPR" or any("preprint" in t for t in types):
        return "preprint"
    if any("congress" in t or "conference" in t or "meeting" in t for t in types):
        return "congress_abstract"
    if any("review" in t for t in types):
        return "review"
    if any("clinical trial" in t for t in types):
        return "paper_trial"
    return "paper"


def map_result(r: dict[str, Any]) -> dict[str, Any]:
    journal = ((r.get("journalInfo") or {}).get("journal") or {}).get("title") \
        or (r.get("bookOrReportDetails") or {}).get("publisher")
    return {
        "id": r.get("id"),
        "source": r.get("source"),
        "pmid": r.get("pmid"),
        "pmcid": r.get("pmcid"),
        "doi": r.get("doi"),
        "title": (r.get("title") or "").strip(),
        "authors": r.get("authorString"),
        "journal": journal,
        "pub_year": r.get("pubYear"),
        "first_publication_date": r.get("firstPublicationDate"),
        "abstract": r.get("abstractText") or "",
        "pub_types": (r.get("pubTypeList") or {}).get("pubType") or [],
        "cited_by_count": r.get("citedByCount"),
    }


def to_raw_item(r: dict[str, Any]) -> RawItem:
    d = map_result(r)
    return RawItem(
        source_key=SOURCE_KEY,
        external_id=f"{d['source']}:{d['id']}",
        url=item_url(r),
        title=d["title"],
        published_at=d.get("first_publication_date") or d.get("pub_year"),
        kind=classify(r),
        text=" ".join(x for x in [d["title"], d.get("journal") or "", d["abstract"]] if x),
        data=d,
        retrieved_at=now_utc(),
        content_hash=content_hash(d),
    )


async def search(term: str, days: int = 365, page_size: int = 25,
                 client: httpx.AsyncClient | None = None) -> list[RawItem]:
    since = (date.today() - timedelta(days=days)).isoformat()
    until = date.today().isoformat()
    params = {
        "query": f"({term}) AND FIRST_PDATE:[{since} TO {until}]",
        "format": "json",
        "resultType": "core",
        "pageSize": page_size,
        "sort": "FIRST_PDATE desc",
    }
    payload = await get_json(SOURCE_KEY, SEARCH_URL, params, client)
    results = ((payload.get("resultList") or {}).get("result")) or []
    return [to_raw_item(r) for r in results if r.get("id") and r.get("title")]
