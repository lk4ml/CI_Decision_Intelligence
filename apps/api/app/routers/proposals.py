from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Pattern, ProposedDecision
from app.routers.deps import get_session
from app.services import views
from app.services.common import get_asset

router = APIRouter(tags=["proposals"])


@router.get("/assets/{slug}/proposals")
def proposals(slug: str, db: Session = Depends(get_session)):
    a = get_asset(db, slug)
    ds = db.execute(select(ProposedDecision).join(Pattern).where(Pattern.asset_id == a.id,
                                                                  ProposedDecision.cleared_at.is_(None))).scalars().all()
    ds = sorted(ds, key=lambda d: (d.framing != "take", -(d.total_movement or 0)))
    return [views.proposal_view(db, a, d) for d in ds]
