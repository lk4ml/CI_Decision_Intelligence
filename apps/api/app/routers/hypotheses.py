from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, Hypothesis, HypothesisAgent
from app.routers.deps import Who, get_session, who
from app.schemas import HypothesisCreate, HypothesisPatch
from app.services import audit, events, patterns, positions as pos_svc, views
from app.services.common import ADMIN_ROLES, Forbidden, NotFound, get_asset, hypotheses, require_writer

router = APIRouter(tags=["hypotheses"])


def _agent(db: Session, agent_id: str) -> Agent:
    a = db.get(Agent, agent_id) or db.execute(select(Agent).where(Agent.key == agent_id)).scalar_one_or_none()
    if a is None:
        raise NotFound(f"agent {agent_id} not found")
    return a


def _hyp(db: Session, hid: str) -> Hypothesis:
    h = db.get(Hypothesis, hid)
    if h is None:
        raise NotFound(f"hypothesis {hid} not found")
    return h


def _can_edit(w: Who, h_owner: str):
    require_writer(w.role)
    if w.role not in ADMIN_ROLES and w.role != h_owner:
        raise Forbidden(f"Only {h_owner}, Asset lead or Admin can change this hypothesis")


@router.get("/assets/{slug}/hypotheses")
def list_hypotheses(slug: str, db: Session = Depends(get_session)):
    a = get_asset(db, slug)
    return [views.hypothesis_view(db, h) for h in hypotheses(db, a)]


@router.post("/assets/{slug}/hypotheses")
def create_hypothesis(slug: str, body: HypothesisCreate, db: Session = Depends(get_session), w: Who = Depends(who)):
    a = get_asset(db, slug)
    _can_edit(w, body.owner_role)
    nums = [int(h.code[1:]) for h in hypotheses(db, a) if h.code[1:].isdigit()]
    code = f"H{(max(nums) if nums else 0) + 1}"
    h = Hypothesis(asset_id=a.id, code=code, statement=body.statement, category=body.category,
                   position_line=body.position_line, owner_role=body.owner_role,
                   confidence_start=body.confidence_start, confidence=body.confidence_start, threshold=body.threshold,
                   change_trigger_text=body.change_trigger_text, keywords=body.keywords)
    db.add(h)
    db.flush()
    agents = [_agent(db, i) for i in body.agent_ids]
    for ag in agents:
        db.add(HypothesisAgent(hypothesis_id=h.id, agent_id=ag.id))
    audit.record(db, w.actor, "hypothesis.created", "hypothesis", h.id,
                 {"code": code, "agents": [ag.key for ag in agents]}, after=views.hypothesis_view(db, h), asset_id=a.id)
    events.publish_on_commit(db, "hypothesis.updated", {"entity": "hypothesis", "id": h.id, "code": code,
                                                        "created": True}, a.slug)
    patterns.evaluate(db, a, actor=w.actor)
    db.commit()
    scheduled = []
    try:
        from app.agents import scheduler

        for ag in agents:
            r = scheduler.enqueue(ag.key, a.slug)
            scheduled.append({"agent_key": ag.key, "run_at": r.get("run_at"), **({"skipped": r["skipped"]} if r.get("skipped") else {})})
    except ImportError:
        scheduled = [{"agent_key": ag.key, "run_at": None, "skipped": "scheduler unavailable"} for ag in agents]
    warnings = [] if agents else ["No agent attached — this hypothesis will only move on manual review."]
    return {**views.hypothesis_view(db, h), "scheduled": scheduled, "warnings": warnings}


@router.patch("/hypotheses/{hid}")
def patch_hypothesis(hid: str, body: HypothesisPatch, db: Session = Depends(get_session), w: Who = Depends(who)):
    h = _hyp(db, hid)
    _can_edit(w, h.owner_role)
    a = h.asset
    before = views.hypothesis_view(db, h)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(h, k, v)
    db.flush()
    pos_svc.update_crossing(db, a, h, w.actor)
    audit.record(db, w.actor, "hypothesis.updated", "hypothesis", h.id, {"code": h.code, "changes": changes},
                 before=before, after=views.hypothesis_view(db, h), asset_id=a.id)
    patterns.evaluate(db, a, actor=w.actor)
    events.publish_on_commit(db, "hypothesis.updated", {"entity": "hypothesis", "id": h.id, "code": h.code}, a.slug)
    db.commit()
    return views.hypothesis_view(db, h)


@router.post("/hypotheses/{hid}/agents/{agent_id}")
def attach_agent(hid: str, agent_id: str, db: Session = Depends(get_session), w: Who = Depends(who)):
    h = _hyp(db, hid)
    _can_edit(w, h.owner_role)
    ag = _agent(db, agent_id)
    exists = db.execute(select(HypothesisAgent).where(HypothesisAgent.hypothesis_id == h.id,
                                                      HypothesisAgent.agent_id == ag.id)).scalar_one_or_none()
    if not exists:
        db.add(HypothesisAgent(hypothesis_id=h.id, agent_id=ag.id))
        audit.record(db, w.actor, "hypothesis.agent_attached", "hypothesis", h.id, {"agent": ag.key}, asset_id=h.asset_id)
        events.publish_on_commit(db, "hypothesis.updated", {"entity": "hypothesis", "id": h.id, "agent": ag.key}, h.asset.slug)
        db.commit()
    return views.hypothesis_view(db, h)


@router.delete("/hypotheses/{hid}/agents/{agent_id}")
def detach_agent(hid: str, agent_id: str, db: Session = Depends(get_session), w: Who = Depends(who)):
    h = _hyp(db, hid)
    _can_edit(w, h.owner_role)
    ag = _agent(db, agent_id)
    link = db.execute(select(HypothesisAgent).where(HypothesisAgent.hypothesis_id == h.id,
                                                    HypothesisAgent.agent_id == ag.id)).scalar_one_or_none()
    if link:
        db.delete(link)
        audit.record(db, w.actor, "hypothesis.agent_detached", "hypothesis", h.id, {"agent": ag.key}, asset_id=h.asset_id)
        events.publish_on_commit(db, "hypothesis.updated", {"entity": "hypothesis", "id": h.id, "agent": ag.key}, h.asset.slug)
        db.commit()
    return views.hypothesis_view(db, h)
