"""PubMed via NCBI E-utilities (esearch + esummary, efetch for abstracts)."""
from __future__ import annotations

import asyncio
import os
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from . import http as _http
from .http import RawItem, SourceUnavailable, content_hash, get_json, get_text, now_utc

SOURCE_KEY = "pubmed"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ESEARCH_URL = f"{EUTILS}/esearch.fcgi"
ESUMMARY_URL = f"{EUTILS}/esummary.fcgi"
EFETCH_URL = f"{EUTILS}/efetch.fcgi"
ARTICLE_URL = "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
NCBI_DELAY_S = 0.34  # <= 3 requests/second without an API key


def _common() -> dict[str, str]:
    p = {"tool": "zs_di"}
    email = os.environ.get("NCBI_EMAIL")
    if email:
        p["email"] = email
    key = os.environ.get("NCBI_API_KEY")
    if key:
        p["api_key"] = key
    return p


async def _pause() -> None:
    if _http._TRANSPORT_OVERRIDE is None:
        await asyncio.sleep(NCBI_DELAY_S)


def parse_abstracts(xml_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for art in root.iter("PubmedArticle"):
        pmid_el = art.find("./MedlineCitation/PMID")
        if pmid_el is None or not pmid_el.text:
            continue
        chunks = []
        for at in art.findall("./MedlineCitation/Article/Abstract/AbstractText"):
            txt = "".join(at.itertext()).strip()
            label = at.get("Label")
            if txt:
                chunks.append(f"{label}: {txt}" if label else txt)
        out[pmid_el.text.strip()] = " ".join(chunks)
    return out


def map_summary(rec: dict[str, Any], abstract: str = "") -> dict[str, Any]:
    ids = {a.get("idtype"): a.get("value") for a in rec.get("articleids", []) or []}
    return {
        "pmid": str(rec.get("uid")),
        "title": (rec.get("title") or "").strip(),
        "journal": rec.get("fulljournalname") or rec.get("source"),
        "pubdate": rec.get("pubdate"),
        "epubdate": rec.get("epubdate"),
        "sortpubdate": rec.get("sortpubdate"),
        "authors": [a.get("name") for a in rec.get("authors", []) or [] if a.get("name")],
        "doi": ids.get("doi"),
        "pmc": ids.get("pmc"),
        "pubtypes": rec.get("pubtype", []) or [],
        "abstract": abstract,
    }


def to_raw_item(d: dict[str, Any]) -> RawItem:
    text = " ".join(x for x in [d["title"], d.get("journal") or "", d.get("abstract") or ""] if x)
    kind = "paper"
    if any("Review" in p for p in d.get("pubtypes", [])):
        kind = "review"
    if any("Clinical Trial" in p for p in d.get("pubtypes", [])):
        kind = "paper_trial"
    return RawItem(
        source_key=SOURCE_KEY,
        external_id=d["pmid"],
        url=ARTICLE_URL.format(pmid=d["pmid"]),
        title=d["title"],
        published_at=d.get("sortpubdate") or d.get("pubdate"),
        kind=kind,
        text=text,
        data=d,
        retrieved_at=now_utc(),
        content_hash=content_hash(d),
    )


async def search(term: str, reldate_days: int = 365, retmax: int = 25,
                 client: httpx.AsyncClient | None = None) -> list[RawItem]:
    params = {"db": "pubmed", "term": term, "retmode": "json", "sort": "pub_date",
              "retmax": retmax, "datetype": "pdat", "reldate": reldate_days, **_common()}
    res = await get_json(SOURCE_KEY, ESEARCH_URL, params, client)
    ids = (res.get("esearchresult") or {}).get("idlist", []) or []
    if not ids:
        return []
    await _pause()
    summ = await get_json(SOURCE_KEY, ESUMMARY_URL,
                          {"db": "pubmed", "id": ",".join(ids), "retmode": "json", **_common()},
                          client)
    result = summ.get("result") or {}
    abstracts: dict[str, str] = {}
    await _pause()
    try:
        xml_text = await get_text(SOURCE_KEY, EFETCH_URL,
                                  {"db": "pubmed", "id": ",".join(ids), "retmode": "xml",
                                   **_common()}, client)
        abstracts = parse_abstracts(xml_text)
    except SourceUnavailable:
        abstracts = {}  # abstracts are optional enrichment; summaries are real data
    items = []
    for uid in result.get("uids", ids):
        rec = result.get(str(uid))
        if not rec or rec.get("error"):
            continue
        items.append(to_raw_item(map_summary(rec, abstracts.get(str(uid), ""))))
    return items
