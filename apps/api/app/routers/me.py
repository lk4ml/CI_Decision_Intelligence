from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ROLES, Agent, AgentRun, utcnow
from app.routers.deps import Who, get_session, who
from app.schemas import ROLE_DEFAULTS
from app.services import audit

router = APIRouter(tags=["me"])


@router.get("/me")
def me(w: Who = Depends(who)):
    return {"actor": w.actor, "role": w.role, "roles": ROLES, "defaults": ROLE_DEFAULTS.get(w.role, {}),
            "role_defaults": ROLE_DEFAULTS}


@router.get("/stats/landing")
def landing(db: Session = Depends(get_session)):
    since = utcnow() - timedelta(hours=1)
    runs = db.execute(select(AgentRun, Agent).join(Agent, Agent.id == AgentRun.agent_id)
                      .where(AgentRun.status == "ok", AgentRun.finished_at >= since)).all()
    srcs = {k for r, a in runs for k in (a.source_keys or [])}
    running = db.execute(select(func.count(Agent.id)).where(Agent.status == "running")).scalar_one()
    return {"sources_refreshed_1h": len(srcs), "agents_running": running}


@router.get("/audit/verify")
def audit_verify(db: Session = Depends(get_session)):
    return audit.verify(db)


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/config/public")
def config_public():
    return {"environment": "pilot", "notice": "Pilot build — model outputs are stand-in, illustrative values. "
                                                "Evidence comes only from live public sources."}
