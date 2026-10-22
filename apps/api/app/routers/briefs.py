from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Brief
from app.routers.deps import Who, get_session, who
from app.services import briefs, views
from app.services.common import NotFound, get_asset

router = APIRouter(tags=["briefs"])


class BriefBody(BaseModel):
    exported_by: Optional[str] = None


@router.post("/assets/{slug}/briefs")
def create_brief(slug: str, body: BriefBody = Body(default_factory=BriefBody), db: Session = Depends(get_session),
                 w: Who = Depends(who)):
    a = get_asset(db, slug)
    b = briefs.create(db, a, body.exported_by or w.actor)
    db.commit()
    return {"id": b.id, "version": b.version, "html_url": f"/api/v1/briefs/{b.id}.html"}


@router.get("/assets/{slug}/briefs")
def list_briefs(slug: str, db: Session = Depends(get_session)):
    a = get_asset(db, slug)
    return [{"id": b.id, "version": b.version, "exported_by": b.exported_by, "created_at": views.iso(b.created_at)}
            for b in db.execute(select(Brief).where(Brief.asset_id == a.id).order_by(Brief.created_at.desc())).scalars()]


def _brief(db, bid) -> Brief:
    b = db.get(Brief, bid)
    if b is None:
        raise NotFound(f"brief {bid} not found")
    return b


@router.get("/briefs/{bid}.html", response_class=HTMLResponse)
def brief_html(bid: str, db: Session = Depends(get_session)):
    return HTMLResponse(briefs.render_html(_brief(db, bid)))


@router.get("/briefs/{bid}")
def brief_json(bid: str, db: Session = Depends(get_session)):
    b = _brief(db, bid)
    return {"id": b.id, "asset_id": b.asset_id, "version": b.version, "exported_by": b.exported_by,
            "created_at": views.iso(b.created_at), "snapshot": b.snapshot}
