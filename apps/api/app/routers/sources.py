from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, Source
from app.routers.deps import get_session
from app.services import views
from app.services.common import NotFound

router = APIRouter(tags=["sources"])


def source_view(db: Session, s: Source) -> dict:
    agents = [a for a in db.execute(select(Agent)).scalars() if s.key in (a.source_keys or [])]
    return {"id": s.id, "key": s.key, "name": s.name, "side": s.side, "kind": s.kind, "base_url": s.base_url,
            "access_level": s.access_level, "license_notes": s.license_notes, "last_fetch_at": views.iso(s.last_fetch_at),
            "last_status": s.last_status, "last_error": s.last_error, "last_ok_at": views.iso(s.last_ok_at),
            "agent_keys": [a.key for a in agents], "agents": [views.agent_brief(a) for a in agents]}


@router.get("/sources")
def list_sources(db: Session = Depends(get_session)):
    return [source_view(db, s) for s in db.execute(select(Source).order_by(Source.side.desc(), Source.key)).scalars()]


@router.get("/sources/{key}")
def get_source(key: str, db: Session = Depends(get_session)):
    s = db.execute(select(Source).where(Source.key == key)).scalar_one_or_none() or db.get(Source, key)
    if s is None:
        raise NotFound(f"source {key} not found")
    return source_view(db, s)
