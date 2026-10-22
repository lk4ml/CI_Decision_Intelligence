"""Guardrail agent: blocks unsourced / unverifiable claims before a Signal is written.

Checks (ARCHITECTURE Hard rule 2 + Addendum A #5):
- the signal is tied to a FetchedItem; source_url and retrieved_at are present and equal the
  FetchedItem's values
- source_url is http(s) and its host matches the Source's host (base_url or known landing host)
- so_what introduces no number / NCT ID / PMID absent from the fetched raw + structured data
Returns ``None`` when OK, otherwise a reason string for ``UnmatchedItem``.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urlparse

SOURCE_HOSTS: dict[str, tuple[str, ...]] = {
    "ctgov": ("clinicaltrials.gov",),
    "pubmed": ("pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov"),
    "europepmc": ("europepmc.org", "ebi.ac.uk"),
    "openalex": ("openalex.org",),
    "openfda": ("fda.gov", "dailymed.nlm.nih.gov"),
    "astellas_ir": ("astellas.com",),
}

_NUM = re.compile(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)?")
_NCT = re.compile(r"NCT\d{8}", re.IGNORECASE)
_PMID = re.compile(r"PMID[:\s]*(\d+)", re.IGNORECASE)
_HCODE = re.compile(r"\bH\d+\b")


def host_ok(url: str, source_key: str, source_base_url: Optional[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    allowed = list(SOURCE_HOSTS.get(source_key, ()))
    if source_base_url:
        bh = (urlparse(source_base_url).hostname or "").lower()
        if bh:
            allowed.append(bh)
            allowed.append(".".join(bh.split(".")[-2:]))
    return any(host == a or host.endswith("." + a) for a in allowed if a)


def _norm_num(s: str) -> str:
    s = s.replace(",", "")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def unsupported_claims(so_what: str, haystack: str) -> list[str]:
    """Numbers / NCT IDs / PMIDs in so_what that the source does not contain."""
    text = _HCODE.sub(" ", so_what or "")
    hay_up = haystack.upper()
    bad: list[str] = []
    for nct in _NCT.findall(text):
        if nct.upper() not in hay_up:
            bad.append(nct)
    for pm in _PMID.findall(text):
        if pm not in haystack:
            bad.append(f"PMID {pm}")
    text_wo_ids = _NCT.sub(" ", text)
    hay_nums = {_norm_num(n) for n in _NUM.findall(haystack)}
    for n in _NUM.findall(text_wo_ids):
        if _norm_num(n) not in hay_nums:
            bad.append(n)
    return bad


def haystack_of(fetched_item: Any) -> str:
    return json.dumps([fetched_item.raw, fetched_item.structured, fetched_item.title,
                       fetched_item.url], default=str, ensure_ascii=False)


def check(*, source_url: Optional[str], retrieved_at: Any, so_what: str,
          fetched_item: Any, source_key: str, source_base_url: Optional[str] = None
          ) -> Optional[str]:
    if fetched_item is None or not getattr(fetched_item, "id", None):
        return "guardrail: no fetched_item provenance"
    if not source_url:
        return "guardrail: missing source_url"
    if retrieved_at is None:
        return "guardrail: missing retrieved_at"
    scheme = urlparse(source_url).scheme.lower()
    if scheme not in ("http", "https"):
        return f"guardrail: source_url scheme not http(s): {scheme or 'none'}"
    if source_url != fetched_item.url:
        return "guardrail: source_url differs from fetched item url"
    if retrieved_at != fetched_item.retrieved_at:
        return "guardrail: retrieved_at differs from fetched item"
    if not host_ok(source_url, source_key, source_base_url):
        return f"guardrail: url host {urlparse(source_url).hostname} does not match source {source_key}"
    bad = unsupported_claims(so_what, haystack_of(fetched_item))
    if bad:
        return "guardrail: so_what contains claims not in source: " + ", ".join(sorted(set(bad))[:8])
    return None
