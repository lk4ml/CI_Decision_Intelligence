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

# Exact landing hosts per source (no suffix matching).
SOURCE_HOSTS: dict[str, frozenset[str]] = {
    "ctgov": frozenset({"clinicaltrials.gov", "www.clinicaltrials.gov"}),
    "pubmed": frozenset({"pubmed.ncbi.nlm.nih.gov"}),
    "europepmc": frozenset({"europepmc.org", "www.europepmc.org"}),
    "openalex": frozenset({"openalex.org"}),
    "openfda": frozenset({"dailymed.nlm.nih.gov", "www.accessdata.fda.gov", "api.fda.gov"}),
    "astellas_ir": frozenset({"www.astellas.com", "astellas.com"}),
}

_NUM = re.compile(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)?")
_NCT_LIKE = re.compile(r"NCT[\s-]?\d{7,9}(?!\d)", re.IGNORECASE)
_PMID = re.compile(r"PMID[:\s]*(\d+)", re.IGNORECASE)
_HCODE = re.compile(r"\bH\d+\b")
NUMBER_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy "
    "eighty ninety hundred thousand million billion dozen half quarter percent"
).split()
_NUM_WORD = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", re.IGNORECASE)


def host_ok(url: str, source_key: str, source_base_url: Optional[str] = None) -> bool:
    """Exact host match against SOURCE_HOSTS (source_base_url is ignored by design)."""
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host in SOURCE_HOSTS.get(source_key, frozenset())


def _norm_num(s: str) -> str:
    s = s.replace(",", "")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def unsupported_claims(text: str, haystack: str) -> list[str]:
    """Numbers (digits or words) / NCT-like IDs / PMIDs in ``text`` absent from the source."""
    text = _HCODE.sub(" ", text or "")
    hay_low = haystack.lower()
    hay_ids = {re.sub(r"[\s-]", "", m).upper() for m in _NCT_LIKE.findall(haystack)}
    bad: list[str] = []
    for nct in _NCT_LIKE.findall(text):
        if re.sub(r"[\s-]", "", nct).upper() not in hay_ids:
            bad.append(nct)
    for pm in _PMID.findall(text):
        if pm not in haystack:
            bad.append(f"PMID {pm}")
    rest = _PMID.sub(" ", _NCT_LIKE.sub(" ", text))
    hay_nums = {_norm_num(n) for n in _NUM.findall(haystack)}
    for n in _NUM.findall(rest):
        if _norm_num(n) not in hay_nums:
            bad.append(n)
    for w in _NUM_WORD.findall(rest):
        if not re.search(rf"\b{w.lower()}\b", hay_low):
            bad.append(w)
    return bad


def haystack_of(fetched_item: Any) -> str:
    """Source text only: raw title, text and data. Never url/retrieved_at/content_hash."""
    raw = fetched_item.raw or {}
    return json.dumps([raw.get("title"), raw.get("text"), raw.get("data")],
                      default=str, ensure_ascii=False)


def check(*, source_url: Optional[str], retrieved_at: Any, so_what: str,
          fetched_item: Any, source_key: str, source_base_url: Optional[str] = None,
          extra_texts: Optional[list[str]] = None) -> Optional[str]:
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
    if not host_ok(source_url, source_key):
        return f"guardrail: url host {urlparse(source_url).hostname} does not match source {source_key}"
    hay = haystack_of(fetched_item)
    bad: list[str] = []
    for t in [so_what] + list(extra_texts or []):
        bad += unsupported_claims(t, hay)
    if bad:
        return "guardrail: text contains claims not in source: " + ", ".join(sorted(set(bad))[:8])
    return None
