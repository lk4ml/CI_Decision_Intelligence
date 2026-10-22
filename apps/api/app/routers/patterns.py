from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Pattern
from app.routers.deps import get_session
from app.services import views
from app.services.common import get_asset

router = APIRouter(tags=["patterns"])


@router.get("/assets/{slug}/patterns")
def asset_patterns(slug: str, db: Session = Depends(get_session)):
    a = get_asset(db, slug)
    return [views.pattern_view(p) for p in db.execute(select(Pattern).where(Pattern.asset_id == a.id)
                                                     .order_by(Pattern.created_at)).scalars()]


@router.get("/patterns")
def patterns_q(asset: Optional[str] = None, db: Session = Depends(get_session)):
    if not asset:
        raise HTTPException(422, "asset query parameter required")
    return asset_patterns(asset, db)
