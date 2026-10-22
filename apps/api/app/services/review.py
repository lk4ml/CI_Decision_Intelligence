"""Signal review: apply / dismiss / undo (PRD §5.6 G3, §7.4–7.5; Addendum A #4, #10, #11).

Append-only: apply writes ConfidenceEvents; undo writes compensating events (`reverts_event_id`).
confidence = clamp(start + Σ events, 5, 95). After each change: crossing → reopen, patterns.evaluate,
positions re-render, audit + SSE (published after commit).
"""
from __future__ import annotations

import math
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, ConfidenceEvent, Hypothesis, Signal
from app.services import audit, events, patterns, positions
from app.services.common import (ADMIN_ROLES, Conflict, Forbidden, Invalid, NotFound, clamp, live_events,
                                 recompute_confidence, require_writer, reverted_ids, role_owns_signal)


def _signal(session: Session, signal_id: str) -> Signal:
    s = session.get(Signal, signal_id)
    if s is None:
        raise NotFound(f"signal {signal_id} not found")
    return s


def _after_change(session: Session, asset: Asset, touched: list[Hypothesis], actor: str) -> dict:
    crossed = []
    for h in touched:
        recompute_confidence(session, h)
        if positions.update_crossing(session, asset, h, actor):
            crossed.append(h.code)
    pat = patterns.evaluate(session, asset, actor="system:patterns")
    positions.render_all(session, asset)
    for h in touched:
        events.publish_on_commit(session, "hypothesis.updated",
                                 {"entity": "hypothesis", "id": h.id, "code": h.code, "confidence": h.confidence},
                                 asset.slug)
    return {"crossed": crossed, **pat}


def apply(session: Session, signal_id: str, actor: str, role: Optional[str] = None,
          overrides: Optional[dict] = None, reason: Optional[str] = None) -> dict:
    s = _signal(session, signal_id)
    require_writer(role)
    if not role_owns_signal(session, s, role):
        raise Forbidden("You can apply only signals that move hypotheses you own")
    if s.review_status != "pending":
        raise Conflict(f"signal is {s.review_status}, not pending")
    overrides = overrides or {}
    asset = session.get(Asset, s.asset_id)
    move_codes = {session.get(Hypothesis, m.hypothesis_id).code: m for m in s.moves}
    for code, val in overrides.items():
        if code not in move_codes:
            raise Invalid(f"override for {code} but this signal does not move {code}")
        try:
            fval = float(val)
        except (TypeError, ValueError):
            raise Invalid(f"override for {code} is not a number")
        if not math.isfinite(fval):
            raise Invalid(f"override for {code} must be finite")
        if fval != move_codes[code].delta and not (reason and reason.strip()):
            raise Invalid("a reason is required when overriding a proposed move")
    touched, moves_out = [], []
    for m in s.moves:
        h = session.get(Hypothesis, m.hypothesis_id)
        applied = float(overrides.get(h.code, m.delta))
        applied = clamp(applied, -10, 10)
        ev = ConfidenceEvent(hypothesis_id=h.id, signal_id=s.id, delta_proposed=m.delta, delta_applied=applied,
                             actor=actor, reason=reason if h.code in overrides else (reason or "applied as proposed"))
        session.add(ev)
        touched.append(h)
        moves_out.append({"hypothesis_code": h.code, "delta_proposed": m.delta, "delta_applied": applied})
    s.review_status = "applied"
    s.reviewer = actor
    session.flush()
    before = {h.code: h.confidence for h in touched}
    result = _after_change(session, asset, touched, actor)
    after = {h.code: h.confidence for h in touched}
    audit.record(session, actor, "signal.applied", "signal", s.id,
                 {"moves": moves_out, "overrides": overrides, "reason": reason, "role": role, **result},
                 before=before, after=after, asset_id=asset.id)
    events.publish_on_commit(session, "signal.reviewed", {"entity": "signal", "id": s.id, "action": "applied", "moves": moves_out},
                             asset.slug)
    return {"signal_id": s.id, "review_status": s.review_status, "confidences": after, **result}


def dismiss(session: Session, signal_id: str, actor: str, role: Optional[str] = None,
            reason: Optional[str] = None) -> dict:
    s = _signal(session, signal_id)
    require_writer(role)
    if not role_owns_signal(session, s, role):
        raise Forbidden("You can dismiss only signals that move hypotheses you own")
    if s.review_status != "pending":
        raise Conflict(f"signal is {s.review_status}, not pending")
    asset = session.get(Asset, s.asset_id)
    s.review_status = "dismissed"
    s.reviewer = actor
    audit.record(session, actor, "signal.dismissed", "signal", s.id, {"reason": reason, "role": role},
                 asset_id=asset.id)
    events.publish_on_commit(session, "signal.reviewed", {"entity": "signal", "id": s.id, "action": "dismissed"}, asset.slug)
    return {"signal_id": s.id, "review_status": s.review_status}


def undo(session: Session, signal_id: str, actor: str, role: Optional[str] = None,
         reason: Optional[str] = None) -> dict:
    s = _signal(session, signal_id)
    require_writer(role)
    if not role_owns_signal(session, s, role):
        raise Forbidden("You can undo only signals that move hypotheses you own")
    if s.review_status == "pending":
        raise Conflict("signal is pending; nothing to undo")
    asset = session.get(Asset, s.asset_id)
    prev_status = s.review_status
    result: dict = {}
    if prev_status == "applied":
        rev = reverted_ids(session)
        originals = session.execute(select(ConfidenceEvent).where(ConfidenceEvent.signal_id == s.id,
                                                                   ConfidenceEvent.reverts_event_id.is_(None))).scalars()
        touched = {}
        for ev in originals:
            if ev.id in rev:
                continue
            session.add(ConfidenceEvent(hypothesis_id=ev.hypothesis_id, signal_id=s.id, delta_proposed=0,
                                        delta_applied=-ev.delta_applied, actor=actor, reason=reason or "undo",
                                        reverts_event_id=ev.id))
            touched[ev.hypothesis_id] = session.get(Hypothesis, ev.hypothesis_id)
        session.flush()
        result = _after_change(session, asset, list(touched.values()), actor)
        result["confidences"] = {h.code: h.confidence for h in touched.values()}
    s.review_status = "pending"
    s.reviewer = None
    audit.record(session, actor, "signal.undone", "signal", s.id, {"from": prev_status, "reason": reason, "role": role},
                 asset_id=asset.id)
    events.publish_on_commit(session, "signal.reviewed", {"entity": "signal", "id": s.id, "action": "undone"}, asset.slug)
    return {"signal_id": s.id, "review_status": s.review_status, **result}


def apply_all(session: Session, asset: Asset, actor: str, role: Optional[str] = None) -> dict:
    require_writer(role)
    pending = session.execute(select(Signal).where(Signal.asset_id == asset.id, Signal.review_status == "pending")
                              .order_by(Signal.retrieved_at)).scalars().all()
    applied, skipped = [], []
    for s in pending:
        if role_owns_signal(session, s, role):
            apply(session, s.id, actor, role)
            applied.append(s.id)
        else:
            skipped.append(s.id)
    return {"applied": applied, "skipped": skipped}
