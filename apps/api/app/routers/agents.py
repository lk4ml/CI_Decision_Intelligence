from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, AgentRun, Hypothesis, HypothesisAgent
from app.routers.deps import Who, get_session, who
from app.schemas import AgentCreate, AgentPatch
from app.services import audit, events, views
from app.services.common import Forbidden, NotFound, get_asset, require_writer

router = APIRouter(tags=["agents"])


def _agent(db: Session, aid: str) -> Agent:
    a = db.get(Agent, aid) or db.execute(select(Agent).where(Agent.key == aid)).scalar_one_or_none()
    if a is None:
        raise NotFound(f"agent {aid} not found")
    return a


def _admin(w: Who):
    require_writer(w.role)
    if w.role not in ("Admin", "Asset lead"):
        raise Forbidden("Only Admin or Asset lead can manage agents")


@router.get("/agents")
def list_agents(db: Session = Depends(get_session)):
    return [views.agent_view(db, a) for a in db.execute(select(Agent).order_by(Agent.created_at)).scalars()]


@router.get("/agents/status")
def agents_status(db: Session = Depends(get_session)):
    agents = db.execute(select(Agent)).scalars().all()
    by = {}
    for cat in ("always_on", "daily", "on_event"):
        xs = [a for a in agents if a.category == cat]
        cad = sorted({a.cadence_minutes for a in xs if a.cadence_minutes})
        by[cat] = {"count": len(xs), "running": sum(1 for a in xs if a.status == "running"),
                   "supervised": sum(1 for a in xs if a.status == "supervised"),
                   "planned": sum(1 for a in xs if a.status == "planned"), "cadence_minutes": cad}
    nxt, scheduled = None, []
    try:
        from app.agents import scheduler

        n = scheduler.next_run_at()
        nxt = n.isoformat() if n else None
        sch = getattr(scheduler, "_scheduler", None)
        if sch is not None:
            scheduled = [{"id": j.id, "next_run_at": j.next_run_time.isoformat() if j.next_run_time else None}
                         for j in sch.get_jobs()]
    except ImportError:
        pass
    return {"by_category": by, "next_cycle_at": nxt, "agents_running": sum(1 for a in agents if a.status == "running"),
            "scheduled": scheduled}


@router.get("/agents/{aid}")
def get_agent(aid: str, db: Session = Depends(get_session)):
    a = _agent(db, aid)
    out = views.agent_view(db, a, detail=True)
    out["runs"] = [views.run_view(r, a.key) for r in db.execute(
        select(AgentRun).where(AgentRun.agent_id == a.id).order_by(AgentRun.started_at.desc()).limit(10)).scalars()]
    return out


@router.patch("/agents/{aid}")
def patch_agent(aid: str, body: AgentPatch, db: Session = Depends(get_session), w: Who = Depends(who)):
    _admin(w)
    a = _agent(db, aid)
    before = views.agent_view(db, a)
    ch = body.model_dump(exclude_unset=True)
    for k, v in ch.items():
        setattr(a, k, v)
    audit.record(db, w.actor, "agent.updated", "agent", a.id, {"key": a.key, "changes": ch}, before=before)
    events.publish_on_commit(db, "audit", {"entity": "agent", "id": a.id, "action": "agent.updated"}, None)
    db.commit()
    return views.agent_view(db, a)


@router.post("/agents")
def create_agent(body: AgentCreate, db: Session = Depends(get_session), w: Who = Depends(who)):
    require_writer(w.role)
    key = body.key or re.sub(r"[^a-z0-9]+", "_", body.name.lower()).strip("_")
    if db.execute(select(Agent).where(Agent.key == key)).scalar_one_or_none():
        raise HTTPException(409, f"agent {key} exists")
    a = Agent(key=key, name=body.name, category=body.category, reads=body.reads, cadence_minutes=body.cadence_minutes,
              status="supervised", description=body.description, source_keys=body.source_keys)
    db.add(a)
    db.flush()
    for hid in body.hypothesis_ids:
        if db.get(Hypothesis, hid):
            db.add(HypothesisAgent(hypothesis_id=hid, agent_id=a.id))
    audit.record(db, w.actor, "agent.created", "agent", a.id, {"key": key})
    events.publish_on_commit(db, "audit", {"entity": "agent", "id": a.id, "action": "agent.created"}, None)
    db.commit()
    return views.agent_view(db, a)


@router.post("/agents/{aid}/run")
def run_agent_ep(aid: str, asset: Optional[str] = None, db: Session = Depends(get_session), w: Who = Depends(who)):
    require_writer(w.role)
    a = _agent(db, aid)
    if asset:
        get_asset(db, asset)
    try:
        from app.agents.pipeline import run_agent
    except ImportError as e:
        raise HTTPException(503, f"Agent pipeline not available: {e}")
    try:
        run = run_agent(db, a.key, asset)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if isinstance(run, AgentRun):
        return views.run_view(run, a.key)
    return run
