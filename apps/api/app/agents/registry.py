"""Agent catalog -> connector calls built from ``Asset.watch_terms``.

``watch_terms`` = ``{own:[..], competitors:[..], literature:[..], standard?:[..], conditions?:[..]}``.
Entries may be plain strings or dicts (``{"term"|"intr"|"cond": ...}``).

Each fetch returns ``list[(RawItem, ctx)]`` where ``ctx`` carries routing hints for the
pipeline (``role`` for registry items, ``query`` used). Any ``SourceUnavailable`` propagates
so the pipeline records ``source_unreachable`` honestly.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.connectors import astellas_ir, ctgov, europepmc, openalex, openfda, pubmed
from app.connectors.http import RawItem, make_client

Fetched = list[tuple[RawItem, dict[str, Any]]]

SOURCE_NAMES = {
    "ctgov": "ClinicalTrials.gov",
    "pubmed": "PubMed",
    "europepmc": "Europe PMC",
    "openalex": "OpenAlex",
    "openfda": "openFDA",
    "astellas_ir": "Astellas IR",
}

AGENT_SOURCES = {
    "registry_watch": ["ctgov"],
    "literature": ["pubmed", "europepmc"],
    "research_graph": ["openalex"],
    "regulatory": ["openfda"],
    "astellas_ir": ["astellas_ir"],
}

MAX_TERMS = 10


def _term(e: Any) -> str | None:
    if isinstance(e, str):
        return e.strip() or None
    if isinstance(e, dict):
        return e.get("term") or e.get("intr") or e.get("name") or e.get("cond")
    return None


def terms(asset: Any, key: str) -> list[str]:
    wt = getattr(asset, "watch_terms", None) or {}
    out: list[str] = []
    for e in wt.get(key, []) or []:
        t = _term(e)
        if t and t not in out:
            out.append(t)
    return out[:MAX_TERMS]


def standard_terms(asset: Any) -> list[str]:
    return (terms(asset, "standard") + [t for t in terms(asset, "standard_of_care")
                                        if t not in terms(asset, "standard")])[:MAX_TERMS]


def condition_hints(asset: Any) -> list[str]:
    """Indication tokens used to keep registry hits on-indication."""
    wt = getattr(asset, "watch_terms", None) or {}
    if wt.get("conditions"):
        return [str(c).lower() for c in wt["conditions"]]
    ind = (getattr(asset, "indication", "") or "").lower()
    if "pancrea" in ind:
        return ["pancrea", "pdac"]
    if "lung" in ind:
        return ["lung", "nsclc"]
    if "gastr" in ind or "gej" in ind or "esophag" in ind:
        return ["gastric", "gastroesophageal", "gej", "stomach", "esophagogastric"]
    toks = [t for t in ind.replace("/", " ").split() if len(t) > 4]
    return toks[:2] or [ind]


def registry_condition(asset: Any) -> str:
    wt = getattr(asset, "watch_terms", None) or {}
    if wt.get("conditions"):
        return str(wt["conditions"][0])
    return getattr(asset, "indication", "") or ""


async def _registry_watch(asset: Any) -> Fetched:
    out: Fetched = []
    seen: set[str] = set()
    async with make_client() as c:
        for t in terms(asset, "own"):
            for it in await ctgov.search_studies(intr=t, client=c):
                if it.external_id not in seen:
                    seen.add(it.external_id)
                    out.append((it, {"query": t, "role_hint": "own", "own_term": t}))
        cond = registry_condition(asset)
        # Competitor trials on-indication. Standard-of-care drugs are not queried on the
        # registry (hundreds of chemo trials = noise); they are covered by `regulatory`.
        for role, key in (("competitor", "competitors"),):
            for t in terms(asset, key):
                for it in await ctgov.search_studies(intr=t, cond=cond or None, page_size=25,
                                                     max_pages=1, client=c):
                    if it.external_id not in seen:
                        seen.add(it.external_id)
                        out.append((it, {"query": t, "role_hint": role}))
    return out


async def _literature(asset: Any) -> Fetched:
    out: Fetched = []
    q = terms(asset, "literature") or terms(asset, "own")
    async with make_client() as c:
        for t in q:
            for it in await pubmed.search(t, client=c):
                out.append((it, {"query": t}))
            for it in await europepmc.search(t, client=c):
                out.append((it, {"query": t}))
    return _dedupe(out)


async def _research_graph(asset: Any) -> Fetched:
    out: Fetched = []
    q = terms(asset, "literature") or terms(asset, "own")
    async with make_client() as c:
        for t in q[:4]:
            for it in await openalex.search_works(t, client=c):
                out.append((it, {"query": t}))
    return _dedupe(out)


async def _regulatory(asset: Any) -> Fetched:
    out: Fetched = []
    async with make_client() as c:
        for role, q in (("competitor", terms(asset, "competitors")),
                        ("standard", standard_terms(asset))):
            for t in q:
                for it in await openfda.search_drug(t, client=c):
                    out.append((it, {"query": t, "role_hint": role}))
    return _dedupe(out)


async def _astellas_ir(asset: Any) -> Fetched:
    q = terms(asset, "own") + terms(asset, "ir")
    items = await astellas_ir.fetch(q or None)
    return [(it, {"query": ",".join(q), "role_hint": "own"}) for it in items]


def _dedupe(rows: Fetched) -> Fetched:
    seen: set[tuple[str, str]] = set()
    out: Fetched = []
    for it, ctx in rows:
        k = (it.source_key, it.external_id)
        if k not in seen:
            seen.add(k)
            out.append((it, ctx))
    return out


FETCHERS: dict[str, Callable[[Any], Awaitable[Fetched]]] = {
    "registry_watch": _registry_watch,
    "literature": _literature,
    "research_graph": _research_graph,
    "regulatory": _regulatory,
    "astellas_ir": _astellas_ir,
}


def is_runnable(agent_key: str) -> bool:
    return agent_key in FETCHERS


async def fetch_for(agent_key: str, asset: Any) -> Fetched:
    if agent_key not in FETCHERS:
        raise KeyError(f"agent {agent_key!r} has no connector fetcher")
    return await FETCHERS[agent_key](asset)
