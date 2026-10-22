"""Implication agent: so-what + proposed confidence moves.

Rule-based by default. If ``ANTHROPIC_API_KEY`` is set, Claude (``claude-sonnet-5-5``) may
write the so-what and the support/contradict direction per matched hypothesis; its output is
Pydantic-validated and any failure falls back to rules. The LLM never sets numbers:

    delta = clamp(round(base_strength x reliability x relevance x 10), -10, 10) x sign
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.connectors.http import RawItem

from .extract import Facts
from .match import Match

LLM_MODEL = "claude-sonnet-5-5"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# §7.4 base_strength by extracted event kind
BASE_STRENGTH: dict[str, float] = {
    "phase3_start": 1.0,
    "trial_completed": 1.0,
    "approval": 1.0,
    "phase3_results": 1.0,
    "label_change": 0.8,
    "phase2_results": 0.8,
    "trial_stopped": 0.8,
    "paper_trial": 0.8,
    "congress_abstract": 0.7,
    "status_change": 0.6,
    "completion_moved": 0.6,
    "new_trial": 0.6,
    "paper": 0.6,
    "review": 0.6,
    "preprint": 0.6,
    "trial_update": 0.3,
    "regulatory_record": 0.3,
    "company_ir": 0.3,
}
# §7.4 reliability by source
RELIABILITY: dict[str, float] = {
    "ctgov": 1.0,
    "openfda": 1.0,
    "pubmed": 0.9,
    "europepmc": 0.9,
    "openalex": 0.8,
    "astellas_ir": 0.5,
}
EVENT_LABEL = {
    "phase3_start": "Phase 3 trial registered/started",
    "trial_completed": "trial reported completed",
    "approval": "recent FDA approval action",
    "phase3_results": "Phase 3 results reported",
    "label_change": "FDA label on record (check for change)",
    "phase2_results": "Phase 2 results reported",
    "trial_stopped": "trial stopped/terminated/withdrawn",
    "paper_trial": "clinical trial publication",
    "congress_abstract": "congress abstract",
    "status_change": "registry status changed",
    "completion_moved": "primary completion date moved",
    "new_trial": "new trial registered",
    "paper": "new publication",
    "review": "new review article",
    "preprint": "new preprint",
    "trial_update": "registry record updated",
    "regulatory_record": "FDA application record",
    "company_ir": "Astellas company disclosure",
}
COMPETITOR_WORDS = ("competitor", "competing", "rival", "another sponsor")
HIGH_IMPACT_EVENTS = {"phase3_start", "trial_completed", "approval", "phase3_results", "trial_stopped"}
EXCLUSIVITY = ("first-in-class", "first to", "only ", "lead", "ahead", "differentiat", "advantage", "unmet",
               "exclusiv", "best-in-class", "no approved", "no competitor", "uncontested", "window")


def base_strength(facts: Facts, item: RawItem) -> float:
    b = BASE_STRENGTH.get(facts.event, BASE_STRENGTH.get(item.kind, 0.3))
    if item.source_key == "openalex" and (item.data.get("cited_by_count") or 0) >= 20:
        b = max(b, 0.7)
    return b


def reliability(item: RawItem) -> float:
    r = RELIABILITY.get(item.source_key, 0.5)
    if item.kind == "preprint":
        r = min(r, 0.6)
    return r


def compute_delta(b: float, r: float, rel: float, sign: int) -> int:
    mag = round(b * r * rel * 10)
    return max(-10, min(10, mag * (1 if sign >= 0 else -1)))


def rule_sign(h: Any, facts: Facts) -> int:
    """+1 support / -1 contradict from role, event and hypothesis category/statement."""
    cat = (getattr(h, "category", "") or "").lower()
    stmt = (getattr(h, "statement", "") or "").lower()
    exclusive = any(w in stmt for w in EXCLUSIVITY)
    negative = facts.polarity < 0 or facts.event in ("trial_stopped",)
    role = facts.role
    about_competitors = any(w in stmt for w in COMPETITOR_WORDS)
    if role == "own":
        if about_competitors:
            # own progress makes a "competitor gets there first" belief less likely
            return 1 if negative else -1
        if facts.event == "completion_moved":
            new, old = facts.primary_completion or "", facts.previous_primary_completion or ""
            return -1 if new > old else 1
        return -1 if negative else 1
    if role in ("competitor", "standard"):
        if negative:  # competitor setback
            return 1 if (exclusive or cat == "business") else -1
        if cat == "comparator":
            return 1
        if cat == "business" or exclusive:
            return -1
        return 1
    # context literature
    return -1 if negative else 1


@dataclass
class ProposedMove:
    hypothesis: Any
    delta: int
    weight: float
    rationale: str


@dataclass
class Implication:
    so_what: str
    moves: list[ProposedMove] = field(default_factory=list)
    impact: str = "normal"
    origin: str = "rules"
    base_strength: float = 0.0
    reliability: float = 0.0


def rules_so_what(item: RawItem, facts: Facts, signs: dict[str, int]) -> str:
    label = EVENT_LABEL.get(facts.event, facts.event.replace("_", " "))
    who = {"own": "Own program", "competitor": "Competitor", "standard": "Standard of care",
           "context": "Field"}.get(facts.role, "Field")
    sup = [c for c, s in signs.items() if s > 0]
    con = [c for c, s in signs.items() if s < 0]
    tail = []
    if sup:
        tail.append("supports " + ", ".join(sup))
    if con:
        tail.append("cuts against " + ", ".join(con))
    head = f"{who}: {label}"
    if facts.summary and item.source_key == "ctgov":
        head += f" - {facts.summary}"
    return f"{head}. Proposed: {'; '.join(tail) or 'no move'} (pending review)."


# ---------------------------------------------------------------- LLM (optional)

class LLMMove(BaseModel):
    hypothesis_code: str
    direction: Literal["support", "contradict"]
    rationale: str = Field(default="", max_length=400)


class LLMOut(BaseModel):
    so_what: str = Field(min_length=10, max_length=600)
    moves: list[LLMMove] = Field(default_factory=list)


def _llm_prompt(item: RawItem, facts: Facts, matches: list[Match]) -> str:
    hyps = [{"code": m.code, "statement": m.hypothesis.statement,
             "category": getattr(m.hypothesis, "category", None)} for m in matches]
    return (
        "You are the Implication agent for a pharma decision-intelligence tool. Given ONE "
        "fetched source item and the team's hypotheses it matched, write a one-to-two sentence "
        "'so what' for the asset team and classify, per hypothesis, whether the item supports "
        "or contradicts it. Use ONLY facts in the item; do not introduce any number, date, "
        "trial ID or PMID that is not in the item. Do not output confidence numbers.\n\n"
        f"ITEM (source={item.source_key}, kind={item.kind}, role={facts.role}, event={facts.event}):\n"
        f"title: {item.title}\n"
        f"text: {item.text[:3500]}\n\n"
        f"HYPOTHESES: {json.dumps(hyps)}\n\n"
        'Respond with JSON only: {"so_what": str, "moves": [{"hypothesis_code": str, '
        '"direction": "support"|"contradict", "rationale": str}]}'
    )


def _parse_llm_json(text: str) -> LLMOut:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("no JSON object in LLM response")
    return LLMOut.model_validate_json(m.group(0))


async def llm_implication(item: RawItem, facts: Facts, matches: list[Match],
                          client: Optional[httpx.AsyncClient] = None) -> Optional[LLMOut]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not matches:
        return None
    body = {"model": LLM_MODEL, "max_tokens": 600,
            "messages": [{"role": "user", "content": _llm_prompt(item, facts, matches)}]}
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    own = client is None
    c = client or httpx.AsyncClient(timeout=30, trust_env=True,
                                    verify=os.environ.get("SSL_CERT_FILE")
                                    or os.environ.get("REQUESTS_CA_BUNDLE") or True)
    try:
        r = await c.post(ANTHROPIC_URL, json=body, headers=headers)
        r.raise_for_status()
        content = r.json().get("content") or []
        text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
        out = _parse_llm_json(text)
        codes = {m.code for m in matches}
        out.moves = [mv for mv in out.moves if mv.hypothesis_code in codes]
        return out
    except (httpx.HTTPError, ValueError, ValidationError, KeyError, TypeError):
        return None
    finally:
        if own:
            await c.aclose()


async def implicate(item: RawItem, facts: Facts, matches: list[Match],
                    use_llm: bool = True) -> Implication:
    b = base_strength(facts, item)
    r = reliability(item)
    signs = {m.code: rule_sign(m.hypothesis, facts) for m in matches}
    origin = "rules"
    so_what = None
    rationales: dict[str, str] = {}
    if use_llm:
        out = await llm_implication(item, facts, matches)
        if out is not None:
            origin = "llm"
            so_what = out.so_what.strip()
            for mv in out.moves:
                signs[mv.hypothesis_code] = 1 if mv.direction == "support" else -1
                rationales[mv.hypothesis_code] = mv.rationale
    moves: list[ProposedMove] = []
    for m in matches:
        d = compute_delta(b, r, m.relevance, signs[m.code])
        if d == 0:
            continue
        why = rationales.get(m.code) or (
            f"{EVENT_LABEL.get(facts.event, facts.event)}; "
            f"{'supports' if signs[m.code] > 0 else 'contradicts'} ({facts.role}); "
            f"strength {b} x reliability {r} x relevance {m.relevance}"
            + (f"; keywords: {', '.join(m.keyword_hits[:4])}" if m.keyword_hits else "")
        )
        moves.append(ProposedMove(hypothesis=m.hypothesis, delta=d, weight=m.relevance,
                                  rationale=why))
    if so_what is None:
        so_what = rules_so_what(item, facts, {mv.hypothesis.code: (1 if mv.delta > 0 else -1)
                                              for mv in moves})
    impact = "high" if (facts.event in HIGH_IMPACT_EVENTS and facts.role in ("own", "competitor")
                        ) or any(abs(mv.delta) >= 7 for mv in moves) else "normal"
    return Implication(so_what=so_what, moves=moves, impact=impact, origin=origin,
                       base_strength=b, reliability=r)
