from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Position, PositionHistory
from app.routers.deps import Who, get_session, who
from app.schemas import LockBody
from app.services import positions as pos_svc, views
from app.services.common import NotFound, get_asset

router = APIRouter(tags=["positions"])

ORDER = ["Population", "Intervention", "Comparator", "Outcomes", "Price & access", "Timeline"]


@router.get("/assets/{slug}/positions")
def list_positions(slug: str, db: Session = Depends(get_session)):
    a = get_asset(db, slug)
    v = pos_svc.template_vars(db, a)
    ps = db.execute(select(Position).where(Position.asset_id == a.id)).scalars().all()
    ps = sorted(ps, key=lambda p: ORDER.index(p.line) if p.line in ORDER else 99)
    return [views.position_view(db, p, v) for p in ps]


def _pos(db, pid) -> Position:
    p = db.get(Position, pid)
    if p is None:
        raise NotFound(f"position {pid} not found")
    return p


@router.post("/positions/{pid}/lock")
def lock(pid: str, body: LockBody = Body(default_factory=LockBody), db: Session = Depends(get_session),
         w: Who = Depends(who)):
    p = _pos(db, pid)
    hist = pos_svc.lock(db, p, w.actor, w.role, body.scenario_id)
    db.commit()
    return {**views.position_view(db, p), "history": history_view(hist)}


def history_view(h: PositionHistory) -> dict:
    return {"id": h.id, "version": h.version, "snapshot": h.snapshot, "locked_by": h.locked_by,
            "locked_at": views.iso(h.locked_at)}


@router.get("/positions/{pid}/history")
def history(pid: str, db: Session = Depends(get_session)):
    p = _pos(db, pid)
    return [history_view(h) for h in db.execute(select(PositionHistory).where(PositionHistory.position_id == p.id)
                                                .order_by(PositionHistory.version.desc())).scalars()]
