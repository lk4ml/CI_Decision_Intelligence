"""Positions: templated statements, derived confidence, reopen on threshold crossing, lock with snapshot."""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, Hypothesis, Position, PositionHistory, Scenario, utcnow
from app.services import audit, events
from app.services.common import (ADMIN_ROLES, Forbidden, NotFound, applied_signal_ids, asset_cfg, conf_map,
                                 hypotheses, lever_label)
from app.sim import core, montecarlo
from app.sim.models import model_versions


def position_hypotheses(session: Session, position: Position) -> list[Hypothesis]:
    return [h for h in hypotheses(session, position.asset) if h.position_line == position.line]


def confidence(session: Session, position: Position) -> Optional[float]:
    hs = position_hypotheses(session, position)
    if not hs:
        return None
    return round(sum(h.confidence for h in hs) / len(hs), 1)


def template_vars(session: Session, asset: Asset, levers: Optional[dict] = None) -> dict:
    cfg = asset_cfg(asset)
    r = core.chain(cfg, levers or {}, conf_map(session, asset), None)
    L = r["levers"]
    v = defaultdict(str)
    v.update({
        "line_label": lever_label(asset, "line", L.get("line")) if "line" in L else "",
        "regimen_label": {"mono": "monotherapy"}.get(L.get("regimen"), lever_label(asset, "regimen", L.get("regimen"))) if "regimen" in L else "",
        "comp_label": lever_label(asset, "comp", L.get("comp")),
        "cutoff_label": lever_label(asset, "cutoff", L.get("cutoff")) if "cutoff" in L else "",
        "ep_upper": str(L.get("ep", "")).upper(),
        "geo_label": lever_label(asset, "geo", L.get("geo")).lower() if L.get("geo") != "west" else "US + EU heavy",
        "dose_text": "a randomized two-dose cohort" if L.get("dose") else "a single Phase 2 dose",
        "combo_text": " and an anti-PD-1 backbone" if L.get("combo") else "",
        "patients": f"{round(r['demand']['on_drug']):,}",
        "testing_pct": round(r["demand"]["testing"] * 100),
        "ptrs_pct": round(r["ptrs"]["ptrs"] * 100),
        "us_net": f"{round(r['access']['net'] / 100) * 100:,}",
        "prem_pct": round(r["access"]["prem"] * 100),
        "readout_label": r["feas"]["readout_label"],
        "cost": r["feas"]["cost"],
        "peak": f"{r['business']['peak']:.2f}",
    })
    return v


def render(session: Session, position: Position, vars_: Optional[dict] = None) -> str:
    if not position.statement_template:
        return position.statement
    vars_ = vars_ if vars_ is not None else template_vars(session, position.asset)
    try:
        return position.statement_template.format_map(vars_)
    except Exception:
        return position.statement


def render_all(session: Session, asset: Asset) -> None:
    v = template_vars(session, asset)
    for p in session.execute(select(Position).where(Position.asset_id == asset.id)).scalars():
        if p.status != "locked":
            p.statement = render(session, p, v)


def reopen_line(session: Session, asset: Asset, line: str, hypothesis: Hypothesis, actor: str) -> list[Position]:
    out = []
    for p in session.execute(select(Position).where(Position.asset_id == asset.id, Position.line == line)).scalars():
        if p.status == "reopened":
            continue
        before = p.status
        p.status = "reopened"
        audit.record(session, actor, "position.reopened", "position", p.id,
                     {"line": line, "hypothesis": hypothesis.code, "from": before,
                      "confidence": hypothesis.confidence, "threshold": hypothesis.threshold},
                     before={"status": before}, after={"status": "reopened"}, asset_id=asset.id)
        events.publish_on_commit(session, "position.reopened",
                                 {"entity": "position", "id": p.id, "line": line, "hypothesis": hypothesis.code},
                                 asset.slug)
        out.append(p)
    return out


def update_crossing(session: Session, asset: Asset, h: Hypothesis, actor: str) -> bool:
    """Recompute crossed flag; on below→above transition reopen the line. Returns True if newly crossed."""
    now = h.confidence >= h.threshold
    if now and not h.crossed:
        h.crossed = True
        h.crossed_at = utcnow()
        audit.record(session, actor, "hypothesis.crossed", "hypothesis", h.id,
                     {"code": h.code, "confidence": h.confidence, "threshold": h.threshold}, asset_id=asset.id)
        events.publish_on_commit(session, "hypothesis.updated",
                                 {"entity": "hypothesis", "id": h.id, "code": h.code, "crossed": True}, asset.slug)
        reopen_line(session, asset, h.position_line, h, actor)
        return True
    if not now and h.crossed:
        h.crossed = False  # un-crossing does not un-reopen (Addendum A #4)
    return False


def scenario_summary(sc: Scenario) -> dict:
    mc = (sc.outputs or {}).get("montecarlo") or {}
    return {"id": sc.id, "name": sc.name, "peak": mc.get("peak"), "rnpv": mc.get("rnpv")}


def lock(session: Session, position: Position, actor: str, role: Optional[str], scenario_id: Optional[str] = None) -> PositionHistory:
    if role not in (position.owner_role, "Admin"):
        raise Forbidden(f"Only {position.owner_role} or Admin can lock the {position.line} position")
    asset = position.asset
    if scenario_id:
        sc = session.get(Scenario, scenario_id)
        if sc is None or sc.asset_id != asset.id:
            raise NotFound("scenario not found")
        scen = scenario_summary(sc)
    else:
        mc = montecarlo.run(asset_cfg(asset), {}, conf_map(session, asset))
        scen = {"id": None, "name": "current levers", "peak": mc["peak"], "rnpv": mc["rnpv"]}
    hs = position_hypotheses(session, position)
    statement = render(session, position)
    position.statement = statement
    position.version = (position.version or 0) + 1
    before = position.status
    position.status = "locked"
    snapshot = {
        "statement": statement,
        "levers": core.full_levers(asset_cfg(asset), {}),
        "hypotheses": [{"code": h.code, "confidence": h.confidence, "threshold": h.threshold} for h in hs],
        "signal_ids": applied_signal_ids(session, [h.id for h in hs]),
        "scenario": scen,
        "model_versions": model_versions(),
        "audit_head_hash": audit.head_hash(session),
    }
    hist = PositionHistory(position_id=position.id, version=position.version, snapshot=snapshot, locked_by=actor,
                           locked_at=utcnow())
    session.add(hist)
    session.flush()
    audit.record(session, actor, "position.locked", "position", position.id,
                 {"line": position.line, "version": position.version, "role": role, "history_id": hist.id},
                 before={"status": before}, after=snapshot, asset_id=asset.id)
    events.publish_on_commit(session, "position.locked",
                             {"entity": "position", "id": position.id, "line": position.line,
                              "version": position.version}, asset.slug)
    return hist
