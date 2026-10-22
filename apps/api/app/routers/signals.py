from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Signal
from app.routers.deps import Who, get_session, who
from app.schemas import ApplyBody, ReasonBody
from app.services import review, views
from app.services.common import get_asset

router = APIRouter(tags=["signals"])


@router.get("/assets/{slug}/signals")
def list_signals(slug: str, status: Optional[str] = None, db: Session = Depends(get_session)):
    a = get_asset(db, slug)
    q = select(Signal).where(Signal.asset_id == a.id)
    if status:
        q = q.where(Signal.review_status == status)
    items = [views.signal_view(db, s) for s in db.execute(
        q.order_by(Signal.published_at.desc().nullslast(), Signal.retrieved_at.desc())).scalars()]
    return {"items": items, "coverage": views.coverage(db, a, views.FETCH_AGENTS)}


@router.post("/signals/{sid}/apply")
def apply_signal(sid: str, body: ApplyBody = Body(default_factory=ApplyBody), db: Session = Depends(get_session),
                 w: Who = Depends(who)):
    r = review.apply(db, sid, body.actor or w.actor, w.role, body.overrides, body.reason)
    db.commit()
    return {**r, "signal": views.signal_view(db, db.get(Signal, sid))}


@router.post("/signals/{sid}/dismiss")
def dismiss_signal(sid: str, body: ReasonBody = Body(default_factory=ReasonBody), db: Session = Depends(get_session),
                   w: Who = Depends(who)):
    r = review.dismiss(db, sid, body.actor or w.actor, w.role, body.reason)
    db.commit()
    return {**r, "signal": views.signal_view(db, db.get(Signal, sid))}


@router.post("/signals/{sid}/undo")
def undo_signal(sid: str, body: ReasonBody = Body(default_factory=ReasonBody), db: Session = Depends(get_session),
                w: Who = Depends(who)):
    r = review.undo(db, sid, body.actor or w.actor, w.role, body.reason)
    db.commit()
    return {**r, "signal": views.signal_view(db, db.get(Signal, sid))}


@router.post("/assets/{slug}/signals/apply-all")
def apply_all(slug: str, db: Session = Depends(get_session), w: Who = Depends(who)):
    a = get_asset(db, slug)
    r = review.apply_all(db, a, w.actor, w.role)
    db.commit()
    return r
