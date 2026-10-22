"""Extract structured facts from a fetched item (deterministic, schema-validated).

Output (``Facts``) drives matching and implication: ``event`` is the item kind used for
§7.4 base_strength, ``role`` is own/competitor/standard, plus facts (phase, n, endpoints,
dates, terms) taken verbatim from the source.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.connectors.ctgov import phase_rank
from app.connectors.http import RawItem

from .registry import condition_hints, standard_terms, terms

ENDPOINT_TERMS = ["overall survival", "progression-free survival", "objective response",
                  "ORR", "PFS", "OS", "DCR", "duration of response", "disease control",
                  "pathologic complete response", "safety", "tolerability", "dose-limiting"]
NEG_WORDS = ["failed", "did not meet", "did not improve", "no significant", "not significant",
             "terminated", "withdrawn", "suspended", "discontinued", "futility", "toxicity",
             "resistance", "worse", "inferior", "halted", "clinical hold"]
POS_WORDS = ["improved", "significant improvement", "statistically significant", "met its primary",
             "met the primary", "efficacy", "durable", "well tolerated", "manageable", "promising",
             "superior", "approved", "approval", "response rate", "encouraging", "antitumor activity"]
ADVANCE_STATUSES = {"Recruiting", "Active Not Recruiting", "Not Yet Recruiting",
                    "Enrolling By Invitation", "Completed"}
STOP_STATUSES = {"Terminated", "Withdrawn", "Suspended"}


class Facts(BaseModel):
    event: str
    role: str = "unknown"
    summary: str = ""
    phase: Optional[str] = None
    n: Optional[int] = None
    endpoints: list[str] = Field(default_factory=list)
    status: Optional[str] = None
    previous_status: Optional[str] = None
    primary_completion: Optional[str] = None
    previous_primary_completion: Optional[str] = None
    start_date: Optional[str] = None
    nct_ids: list[str] = Field(default_factory=list)
    terms_found: list[str] = Field(default_factory=list)
    polarity: int = 0  # +1 positive wording, -1 negative wording, 0 neutral
    on_indication: bool = True
    trial: Optional[dict[str, Any]] = None


def _found(text: str, words: list[str]) -> list[str]:
    low = text.lower()
    return [w for w in words if w and w.lower() in low]


def polarity(text: str) -> int:
    neg = len(_found(text, NEG_WORDS))
    pos = len(_found(text, POS_WORDS))
    return (pos > neg) - (neg > pos)


def _n(text: str) -> Optional[int]:
    m = re.search(r"\b[nN]\s*=\s*(\d{2,5})\b", text) or \
        re.search(r"\b(\d{2,5})\s+(?:patients|participants|subjects)\b", text)
    return int(m.group(1)) if m else None


def _phase_in_text(text: str) -> Optional[str]:
    m = re.search(r"\bphase\s*(1|2|3|I{1,3})(?:\s*/\s*(2|3|II|III))?\b", text, re.IGNORECASE)
    if not m:
        return None
    roman = {"I": "1", "II": "2", "III": "3"}
    a = roman.get(m.group(1).upper(), m.group(1))
    b = m.group(2)
    if b:
        return f"Phase {a}/{roman.get(b.upper(), b)}"
    return f"Phase {a}"


def _endpoints(text: str) -> list[str]:
    out = []
    for e in ENDPOINT_TERMS:
        if len(e) <= 3:
            if re.search(rf"\b{re.escape(e)}\b", text):
                out.append(e)
        elif e.lower() in text.lower():
            out.append(e)
    return out


def biomarker_hints(asset: Any) -> list[str]:
    bm = (getattr(asset, "biomarker", "") or "").lower()
    out = []
    if "g12d" in bm:
        out += ["g12d"]
    if "cldn18" in bm or "claudin" in bm:
        out += ["cldn18.2", "cldn 18.2", "cldn18", "claudin 18.2", "claudin18.2", "claudin-18.2"]
    if not out and bm:
        out = [bm.rstrip("+").strip()]
    return out


def trial_role(asset: Any, trial: dict[str, Any], ctx: dict[str, Any]) -> tuple[str, bool]:
    """Return (role, on_indication).

    own: an own watch term in title/interventions. competitor/standard: a matching watch term
    in title/interventions. Otherwise "context". On-indication requires the asset indication
    in conditions/title, or a basket ("solid tumor") trial that names the asset biomarker.
    """
    blob = " ".join([trial.get("title") or "", trial.get("official_title") or "",
                     " ".join(" ".join([i.get("name") or ""] + list(i.get("other_names") or []))
                              for i in trial.get("interventions") or [])]).lower()
    conds = " ".join(trial.get("conditions") or []).lower() + " " + \
        (trial.get("title") or "").lower() + " " + (trial.get("official_title") or "").lower()
    bm_blob = conds + " " + " ".join(trial.get("keywords") or []).lower()
    on_ind = any(h in conds for h in condition_hints(asset)) or (
        "solid tumo" in conds and any(b in bm_blob for b in biomarker_hints(asset)))
    if any(t.lower() in blob for t in terms(asset, "own")):
        return "own", on_ind
    if any(t.lower() in blob for t in terms(asset, "competitors")):
        return "competitor", on_ind
    if any(t.lower() in blob for t in standard_terms(asset)):
        return "standard", on_ind
    return "context", on_ind


def extract_trial(asset: Any, item: RawItem, ctx: dict[str, Any],
                  prev: Optional[dict[str, Any]]) -> Facts:
    t = item.data
    role, on_ind = trial_role(asset, t, ctx)
    rank = phase_rank(t.get("phase"))
    status = t.get("status")
    if prev is None:
        if rank >= 3 and status in ADVANCE_STATUSES:
            event = "phase3_start" if status != "Completed" else "trial_completed"
        else:
            event = "new_trial"
    else:
        if prev.get("status") != status and status == "Completed":
            event = "trial_completed"
        elif prev.get("status") != status and status in STOP_STATUSES:
            event = "trial_stopped"
        elif phase_rank(prev.get("phase")) < 3 <= rank:
            event = "phase3_start"
        elif prev.get("status") != status:
            event = "status_change"
        elif prev.get("primary_completion") != t.get("primary_completion"):
            event = "completion_moved"
        else:
            event = "trial_update"
    if status in STOP_STATUSES and event in ("new_trial", "trial_update"):
        event = "trial_stopped"
    pol = 1 if event in ("phase3_start", "trial_completed") else (-1 if event == "trial_stopped" else 0)
    parts = [f"{t.get('nct_id')} ({t.get('sponsor') or 'sponsor n/a'})"]
    if t.get("phase"):
        parts.append(t["phase"])
    if status:
        parts.append(status if not prev or prev.get("status") == status
                     else f"{prev.get('status')} -> {status}")
    return Facts(
        event=event, role=role, on_indication=on_ind,
        summary=", ".join(parts),
        phase=t.get("phase"), n=t.get("enrollment"),
        endpoints=[e.get("measure") for e in t.get("endpoints") or [] if e.get("type") == "primary"][:3],
        status=status, previous_status=(prev or {}).get("status"),
        primary_completion=t.get("primary_completion"),
        previous_primary_completion=(prev or {}).get("primary_completion"),
        start_date=t.get("start_date"), nct_ids=[t.get("nct_id")] if t.get("nct_id") else [],
        polarity=pol, trial=t,
    )


def extract_text_item(asset: Any, item: RawItem, ctx: dict[str, Any]) -> Facts:
    text = item.text or ""
    ph = _phase_in_text(text)
    kind = item.kind
    event = kind
    low = text.lower()
    results_words = any(w in low for w in ("results", "efficacy", "response", "survival", "outcome"))
    if kind in ("paper", "paper_trial", "congress_abstract", "preprint") and ph and results_words:
        r = phase_rank(ph)
        if r >= 3:
            event = "phase3_results"
        elif r == 2:
            event = "phase2_results"
    own = [t for t in terms(asset, "own") if t.lower() in low]
    comp = [t for t in terms(asset, "competitors") + standard_terms(asset) if t.lower() in low]
    role = ctx.get("role_hint") or ("own" if own else ("competitor" if comp else "context"))
    if kind == "company_ir":
        role = "own"
    nct = sorted(set(re.findall(r"NCT\d{8}", text)))
    return Facts(
        event=event, role=role, summary=item.title[:200], phase=ph, n=_n(text),
        endpoints=_endpoints(text), nct_ids=nct, terms_found=own + comp,
        polarity=polarity(text),
    )


def extract(asset: Any, item: RawItem, ctx: dict[str, Any],
            prev: Optional[dict[str, Any]] = None) -> Facts:
    if item.source_key == "ctgov":
        return extract_trial(asset, item, ctx, prev)
    return extract_text_item(asset, item, ctx)
