from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, Asset, HypothesisAgent, Pattern, Position, ProposedDecision, Signal, Trial, UnmatchedItem
from app.routers.deps import Who, get_session, who
from app.schemas import AssetCreate, LeversBody
from app.services import audit, events, patterns, positions as pos_svc, views
from app.services.common import ADMIN_ROLES, Forbidden, get_asset, hypotheses, require_writer
from app.sim import core
from app.sim.params import model_params_for

router = APIRouter(tags=["assets"])


@router.get("/assets")
def list_assets(db: Session = Depends(get_session)):
    return [views.asset_brief(a) for a in db.execute(select(Asset).order_by(Asset.created_at)).scalars()]


@router.post("/assets")
def onboard_asset(body: AssetCreate, db: Session = Depends(get_session), w: Who = Depends(who)):
    if w.role not in ("Asset lead", "Admin"):
        raise Forbidden("Only Asset lead or Admin can onboard assets")
    from app.seed import LEVERS_PDAC, create_positions, lever_defaults

    slug = body.slug or re.sub(r"[^a-z0-9]+", "-", body.code.lower()).strip("-")
    if db.execute(select(Asset).where(Asset.slug == slug)).scalar_one_or_none():
        raise HTTPException(409, f"asset {slug} exists")
    a = Asset(slug=slug, code=body.code, name=body.name, indication=body.indication, mechanism=body.mechanism,
              biomarker=body.biomarker, phase=body.phase, phase_source="user", governance_forum=body.governance_forum,
              governance_date=body.governance_date, descriptor=" · ".join(x for x in [body.mechanism, body.indication] if x),
              watch_terms={"own": [], "competitors": [], "literature": [], **body.watch_terms},
              lever_schema=LEVERS_PDAC, current_levers=lever_defaults(LEVERS_PDAC),
              model_params=model_params_for("generic"), registry_nct_ids=[])
    db.add(a)
    db.flush()
    create_positions(db, a, None)
    audit.record(db, w.actor, "asset.onboarded", "asset", a.id, {"slug": slug}, asset_id=a.id)
    events.publish_on_commit(db, "audit", {"entity": "asset", "id": a.id, "action": "asset.onboarded"}, slug)
    db.commit()
    return views.asset_full(db, a)


@router.get("/assets/{slug}")
def get_asset_ep(slug: str, db: Session = Depends(get_session)):
    return views.asset_full(db, get_asset(db, slug))


@router.get("/assets/{slug}/summary")
def asset_summary(slug: str, db: Session = Depends(get_session)):
    a = get_asset(db, slug)
    hs = sorted(hypotheses(db, a), key=lambda h: -abs(h.confidence - h.confidence_start))[:4]
    props = _open_decisions(db, a)
    return {"asset": views.asset_brief(a),
            "hypotheses": [{"code": h.code, "statement": h.statement, "confidence": h.confidence} for h in hs],
            "proposals": [{"id": d.id, "title": d.pattern.title, "framing": d.framing} for d in props[:3]]}


def _open_decisions(db: Session, a: Asset) -> list[ProposedDecision]:
    ds = db.execute(select(ProposedDecision).join(Pattern).where(Pattern.asset_id == a.id,
                                                                  ProposedDecision.cleared_at.is_(None))).scalars().all()
    return sorted(ds, key=lambda d: (d.framing != "take", -(d.total_movement or 0)))


@router.get("/assets/{slug}/brief")
def asset_brief_rows(slug: str, db: Session = Depends(get_session)):
    a = get_asset(db, slug)
    poss = {p.line: p for p in db.execute(select(Position).where(Position.asset_id == a.id)).scalars()}
    hs = hypotheses(db, a)
    n_agents = len(set(db.execute(select(HypothesisAgent.agent_id).where(
        HypothesisAgent.hypothesis_id.in_([h.id for h in hs]))).scalars())) if hs else 0
    wt = a.watch_terms or {}
    status = f"{a.phase or 'Phase not set'} ({'registry-verified' if a.phase_source == 'registry' else 'user-provided'})"
    if a.phase_discrepancy:
        status += f" · registry discrepancy: {a.phase_discrepancy}"
    v = pos_svc.template_vars(db, a)
    rows = [
        {"label": "Target population", "value": pos_svc.render(db, poss["Population"], v) if "Population" in poss else a.indication, "step": "positions"},
        {"label": "Mechanism", "value": a.mechanism or "—", "step": "asset"},
        {"label": "Program status", "value": status, "step": "asset"},
        {"label": "What it must show", "value": pos_svc.render(db, poss["Outcomes"], v) if "Outcomes" in poss else "—", "step": "simulate"},
        {"label": "Monitoring scope",
         "value": f"{len(hs)} hypotheses · {n_agents} agents attached · {len(wt.get('own', []))} own, "
                  f"{len(wt.get('competitors', []))} competitor and {len(wt.get('literature', []))} literature watch terms",
         "step": "hypotheses"},
    ]
    return {"rows": rows}


@router.get("/assets/{slug}/focus")
def focus(slug: str, db: Session = Depends(get_session)):
    a = get_asset(db, slug)
    ds = _open_decisions(db, a)
    if ds:
        d = ds[0]
        return {"kind": "pattern", "id": d.id, "title": d.pattern.title,
                "detail": f"{'Decision to take' if d.framing == 'take' else 'Decision to frame'}: {d.pattern.rationale} "
                          f"(trigger {d.pattern.trigger_text})", "link_step": "workbench"}
    s = db.execute(select(Signal).where(Signal.asset_id == a.id, Signal.review_status == "pending",
                                        Signal.impact == "high").order_by(Signal.retrieved_at.desc())).scalars().first()
    if s:
        return {"kind": "signal", "id": s.id, "title": s.title, "detail": s.so_what or "", "link_step": "signals"}
    return {"kind": "none", "title": "No open decision",
            "detail": "No pattern has fired and no high-impact signal is waiting.", "link_step": "hypotheses"}


@router.get("/assets/{slug}/trials")
def trials(slug: str, db: Session = Depends(get_session)):
    a = get_asset(db, slug)
    items = [views.trial_view(t) for t in db.execute(select(Trial).where(Trial.asset_id == a.id)
                                                     .order_by(Trial.role, Trial.start_date)).scalars()]
    cov = views.coverage(db, a, ["registry_watch"])
    lr = cov["last_run"]
    return {"items": items, "coverage": cov, "trials": items,
            "last_run": {"status": lr["status"], "finished_at": lr["finished_at"], "error": lr["error"]} if lr else None}


def _role_hyps(db, a, role):
    hs = hypotheses(db, a)
    if not role or role in ADMIN_ROLES or role == "Reviewer":
        return hs
    return [h for h in hs if h.owner_role == role]


@router.get("/assets/{slug}/changes")
def changes(slug: str, role: Optional[str] = None, db: Session = Depends(get_session)):
    a = get_asset(db, slug)
    mine = _role_hyps(db, a, role)
    mine_ids = {h.id for h in mine}
    pend = [s for s in db.execute(select(Signal).where(Signal.asset_id == a.id, Signal.review_status == "pending")
                                  .order_by(Signal.retrieved_at.desc())).scalars()
            if any(m.hypothesis_id in mine_ids for m in s.moves)]
    moved = [h for h in mine if abs(h.confidence - h.confidence_start) >= 8]
    ds = _open_decisions(db, a)
    reopened = db.execute(select(Position).where(Position.asset_id == a.id, Position.status == "reopened")).scalars().all()
    who_ = role or "the team"
    parts = [f"{len(pend)} signal{'s' if len(pend) != 1 else ''} waiting for {who_}"
             + (f" ({sum(1 for s in pend if s.impact == 'high')} high impact)" if pend else ""),
             f"{len(moved)} hypothes{'es' if len(moved) != 1 else 'is'} moved 8+ points",
             f"{len(ds)} decision{'s' if len(ds) != 1 else ''} proposed",
             f"{len(reopened)} position{'s' if len(reopened) != 1 else ''} reopened"]
    lede = "; ".join(parts) + "."
    if not pend and not moved and not ds and not reopened:
        lede = "Nothing has changed yet. Agents add signals as live sources report new items."
    return {"lede": lede, "role": role,
            "pending_signals": {"count": len(pend), "high_impact": sum(1 for s in pend if s.impact == "high"),
                                "items": [{"id": s.id, "title": s.title, "impact": s.impact} for s in pend]},
            "moved_hypotheses": {"count": len(moved), "items": [{"id": h.id, "code": h.code,
                                                                 "delta": round(h.confidence - h.confidence_start, 1)} for h in moved]},
            "fired_patterns": {"count": len(ds), "items": [{"id": d.id, "key": d.pattern.key, "title": d.pattern.title,
                                                            "framing": d.framing} for d in ds]},
            "reopened_positions": {"count": len(reopened), "items": [{"id": p.id, "line": p.line} for p in reopened]}}


@router.get("/assets/{slug}/digest")
def digest(slug: str, role: Optional[str] = None, db: Session = Depends(get_session)):
    c = changes(slug, role, db)
    a = get_asset(db, slug)
    lines = [f"Subject: {a.code} — what changed", "", c["lede"], ""]
    for s in c["pending_signals"]["items"]:
        lines.append(f"• [{s['impact']}] {s['title']}")
    for d in c["fired_patterns"]["items"]:
        lines.append(f"• Proposed: {d['title']} ({d['framing']})")
    for p in c["reopened_positions"]["items"]:
        lines.append(f"• Reopened: {p['line']}")
    text = "\n".join(lines)
    return {"role": role, "subject": lines[0][9:], "text": text,
            "html": "<div>" + "".join(f"<p>{l}</p>" for l in lines[2:] if l) + "</div>"}


@router.get("/assets/{slug}/levers")
def levers(slug: str, db: Session = Depends(get_session)):
    a = get_asset(db, slug)
    from app.seed import lever_defaults

    return {"schema": a.lever_schema or [], "defaults": lever_defaults(a.lever_schema or []),
            "current": core.full_levers(views_cfg(a), {})}


def views_cfg(a):
    from app.services.common import asset_cfg

    return asset_cfg(a)


@router.put("/assets/{slug}/levers")
def put_levers(slug: str, body: LeversBody, db: Session = Depends(get_session), w: Who = Depends(who)):
    a = get_asset(db, slug)
    require_writer(w.role)
    names = {i["name"]: i for i in a.lever_schema or []}
    for k, v in body.levers.items():
        if k not in names:
            raise HTTPException(422, f"unknown lever {k!r}")
        item = names[k]
        if item.get("type") == "select" and str(v) not in {str(o["value"]) for o in item.get("options") or []}:
            raise HTTPException(422, f"invalid value {v!r} for lever {k!r}")
    before = dict(a.current_levers or {})
    new = core.full_levers(views_cfg(a), body.levers)
    a.current_levers = new
    audit.record(db, w.actor, "levers.updated", "asset", a.id, {"levers": body.levers, "role": w.role},
                 before=before, after=new, asset_id=a.id)
    res = patterns.evaluate(db, a, actor=w.actor)
    pos_svc.render_all(db, a)
    events.publish_on_commit(db, "levers.updated", {"entity": "asset", "id": a.id, "levers": new}, a.slug)
    db.commit()
    return {"current": new, **res}


@router.get("/assets/{slug}/unmatched")
def unmatched(slug: str, db: Session = Depends(get_session)):
    a = get_asset(db, slug)
    from app.models import FetchedItem

    out = []
    for u in db.execute(select(UnmatchedItem).where(UnmatchedItem.asset_id == a.id)
                        .order_by(UnmatchedItem.created_at.desc()).limit(200)).scalars():
        fi = db.get(FetchedItem, u.fetched_item_id) if u.fetched_item_id else None
        out.append({"id": u.id, "reason": u.reason, "created_at": views.iso(u.created_at),
                    "item": {"id": fi.id, "source_key": fi.source_key, "external_id": fi.external_id, "url": fi.url,
                             "title": fi.title, "retrieved_at": views.iso(fi.retrieved_at)} if fi else None})
    return out
