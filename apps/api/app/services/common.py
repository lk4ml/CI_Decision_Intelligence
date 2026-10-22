"""Shared helpers for CORE services."""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, ConfidenceEvent, Hypothesis, Signal, SignalMove

ADMIN_ROLES = {"Asset lead", "Admin"}
READ_ONLY_ROLES = {"Reviewer"}
HCODE = re.compile(r"\bH\d+\b")


class Forbidden(Exception):
    pass


class Conflict(Exception):
    pass


class NotFound(Exception):
    pass


def get_asset(session: Session, slug_or_id: str) -> Asset:
    a = session.execute(select(Asset).where(Asset.slug == slug_or_id)).scalar_one_or_none()
    if a is None:
        a = session.get(Asset, slug_or_id)
    if a is None:
        raise NotFound(f"asset {slug_or_id!r} not found")
    return a


def hypotheses(session: Session, asset: Asset) -> list[Hypothesis]:
    rows = list(session.execute(select(Hypothesis).where(Hypothesis.asset_id == asset.id)).scalars())
    return sorted(rows, key=lambda h: (int(h.code[1:]) if h.code[1:].isdigit() else 999, h.code))


def conf_map(session: Session, asset: Asset) -> dict[str, float]:
    return {h.code: h.confidence / 100.0 for h in hypotheses(session, asset)}


def asset_cfg(asset: Asset) -> dict:
    return {"slug": asset.slug, "model_params": asset.model_params or {}, "lever_schema": asset.lever_schema or [],
            "current_levers": asset.current_levers or {}}


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def recompute_confidence(session: Session, h: Hypothesis) -> float:
    session.flush()
    total = sum(e.delta_applied for e in session.execute(
        select(ConfidenceEvent).where(ConfidenceEvent.hypothesis_id == h.id)).scalars())
    h.confidence = clamp(h.confidence_start + total, 5, 95)
    return h.confidence


def reverted_ids(session: Session, hypothesis_ids: Optional[list[str]] = None) -> set[str]:
    q = select(ConfidenceEvent.reverts_event_id).where(ConfidenceEvent.reverts_event_id.is_not(None))
    if hypothesis_ids is not None:
        q = q.where(ConfidenceEvent.hypothesis_id.in_(hypothesis_ids))
    return {r for (r,) in session.execute(q)}


def live_events(session: Session, hypothesis_ids: list[str]) -> list[ConfidenceEvent]:
    """Applied, not-reverted, non-compensating events for these hypotheses (newest first)."""
    if not hypothesis_ids:
        return []
    rev = reverted_ids(session, hypothesis_ids)
    rows = session.execute(select(ConfidenceEvent).where(ConfidenceEvent.hypothesis_id.in_(hypothesis_ids),
                                                         ConfidenceEvent.reverts_event_id.is_(None))
                           .order_by(ConfidenceEvent.created_at.desc())).scalars()
    return [e for e in rows if e.id not in rev]


def applied_signal_ids(session: Session, hypothesis_ids: list[str]) -> list[str]:
    out = []
    for e in live_events(session, hypothesis_ids):
        if e.signal_id and e.signal_id not in out:
            out.append(e.signal_id)
    return out


def role_owns_signal(session: Session, signal: Signal, role: Optional[str]) -> bool:
    if role is None or role in ADMIN_ROLES:
        return True
    if role in READ_ONLY_ROLES:
        return False
    for m in signal.moves:
        h = session.get(Hypothesis, m.hypothesis_id)
        if h and h.owner_role == role:
            return True
    return False


def require_writer(role: Optional[str]) -> None:
    if role in READ_ONLY_ROLES:
        raise Forbidden("Reviewer role is read-only")


def lever_label(asset: Asset, name: str, value) -> str:
    for item in asset.lever_schema or []:
        if item["name"] == name:
            if item.get("type") == "toggle":
                return "on" if value else "off"
            for o in item.get("options") or []:
                if str(o["value"]) == str(value):
                    return o["label"]
    return str(value)
