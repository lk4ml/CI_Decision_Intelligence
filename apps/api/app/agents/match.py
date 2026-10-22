"""Match a fetched item against hypotheses by keyword overlap.

relevance buckets (PRD §7.4): 1.0 / 0.7 / 0.4; below the lowest bucket the hypothesis is not
matched. Pilot substitute for embedding similarity (no pgvector in the slice).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

STOPWORDS = set("""
a an the and or of in on for to with without by from at as is are be been being will would
should could can may might must shall than then that this these those it its into over under
vs versus per our we us their they them not no yes more most less least very such any all each
which who whom whose what when where why how also only both either neither if so do does did
patients patient trial trials study studies data team believe expect expected likely within
across among about after before during between least first line lines based use used using
""".split())


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9][a-z0-9\-\+\.]*[a-z0-9]|[a-z0-9]", (text or "").lower())
            if len(t) >= 4 and t not in STOPWORDS and not t.isdigit()}


@dataclass
class Match:
    hypothesis: Any
    relevance: float
    keyword_hits: list[str] = field(default_factory=list)
    token_hits: list[str] = field(default_factory=list)

    @property
    def code(self) -> str:
        return self.hypothesis.code


def _kw_hit(kw: str, low_text: str) -> bool:
    kw = (kw or "").strip().lower()
    if not kw:
        return False
    if len(kw) <= 4:
        return re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", low_text) is not None
    return kw in low_text


def score(hypothesis: Any, text: str) -> Optional[Match]:
    low = (text or "").lower()
    kws = [k for k in (getattr(hypothesis, "keywords", None) or []) if isinstance(k, str)]
    kw_hits = [k for k in kws if _kw_hit(k, low)]
    st = tokens(hypothesis.statement or "") | tokens(getattr(hypothesis, "change_trigger_text", "") or "")
    item_toks = tokens(text)
    t_hits = sorted(st & item_toks)
    ratio = len(t_hits) / len(st) if st else 0.0
    if len(kw_hits) >= 2 or (kw_hits and ratio >= 0.3):
        rel = 1.0
    elif kw_hits or ratio >= 0.4:
        rel = 0.7
    elif ratio >= 0.25 and len(t_hits) >= 2:
        rel = 0.4
    else:
        return None
    return Match(hypothesis=hypothesis, relevance=rel, keyword_hits=kw_hits, token_hits=t_hits)


def match(hypotheses: Iterable[Any], text: str, min_relevance: float = 0.4) -> list[Match]:
    out = []
    for h in hypotheses:
        m = score(h, text)
        if m and m.relevance >= min_relevance:
            out.append(m)
    out.sort(key=lambda m: (-m.relevance, m.code))
    return out
