"""Decision patterns engine (PRD §6) — simpleeval over H1..Hn (0–1), crossed_Hn, levers_<name>."""
from __future__ import annotations

from typing import Optional

from simpleeval import EvalWithCompoundTypes
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, Pattern, ProposedDecision, utcnow
from app.services import audit, events
from app.services.common import HCODE, applied_signal_ids, hypotheses


def names_for(session: Session, asset: Asset, levers: Optional[dict] = None) -> dict:
    names: dict = {}
    for h in hypotheses(session, asset):
        names[h.code] = h.confidence / 100.0
        names[f"crossed_{h.code}"] = bool(h.crossed)
    lv = dict(asset.current_levers or {})
    lv.update(levers or {})
    for k, v in lv.items():
        names[f"levers_{k}"] = v
    return names


def eval_trigger(expr: str, names: dict) -> bool:
    try:
        return bool(EvalWithCompoundTypes(names=names, functions={"abs": abs, "min": min, "max": max}).eval(expr))
    except Exception:
        return False


def _decision_meta(session: Session, asset: Asset, pattern: Pattern) -> tuple[list[str], list[str], str, float]:
    codes = sorted(set(HCODE.findall(pattern.trigger)), key=lambda c: int(c[1:]))
    hs = [h for h in hypotheses(session, asset) if h.code in codes]
    sig_ids = applied_signal_ids(session, [h.id for h in hs])
    framing = "take" if any(h.crossed for h in hs) else "frame"
    movement = round(sum(abs(h.confidence - h.confidence_start) for h in hs), 2)
    return codes, sig_ids, framing, movement


def open_decision(session: Session, pattern: Pattern) -> Optional[ProposedDecision]:
    return session.execute(select(ProposedDecision).where(ProposedDecision.pattern_id == pattern.id,
                                                          ProposedDecision.cleared_at.is_(None))
                           .order_by(ProposedDecision.fired_at.desc())).scalars().first()


def evaluate(session: Session, asset: Asset, actor: str = "system:patterns") -> dict:
    session.flush()
    names = names_for(session, asset)
    fired, cleared = [], []
    for p in session.execute(select(Pattern).where(Pattern.asset_id == asset.id)).scalars():
        now = eval_trigger(p.trigger, names)
        if now and not p.is_fired:
            p.is_fired = True
            codes, sig_ids, framing, movement = _decision_meta(session, asset, p)
            d = ProposedDecision(pattern_id=p.id, fired_at=utcnow(), hypothesis_codes=codes, signal_ids=sig_ids,
                                 framing=framing, total_movement=movement)
            session.add(d)
            session.flush()
            audit.record(session, actor, "pattern.fired", "pattern", p.id,
                         {"key": p.key, "trigger": p.trigger, "decision_id": d.id, "hypothesis_codes": codes},
                         asset_id=asset.id)
            events.publish_on_commit(session, "pattern.fired",
                                     {"entity": "pattern", "id": p.id, "key": p.key, "title": p.title,
                                      "decision_id": d.id}, asset.slug)
            fired.append(p.key)
        elif not now and p.is_fired:
            p.is_fired = False
            d = open_decision(session, p)
            if d:
                d.cleared_at = utcnow()
            audit.record(session, actor, "pattern.cleared", "pattern", p.id, {"key": p.key}, asset_id=asset.id)
            events.publish_on_commit(session, "pattern.cleared", {"entity": "pattern", "id": p.id, "key": p.key},
                                     asset.slug)
            cleared.append(p.key)
        elif now and p.is_fired:
            d = open_decision(session, p)
            if d:
                d.hypothesis_codes, d.signal_ids, d.framing, d.total_movement = _decision_meta(session, asset, p)
    session.flush()
    return {"fired": fired, "cleared": cleared}
