from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.models import Agent, AgentRun, Asset, AuditEvent
from app.routers.deps import get_session
from app.services import events as bus, views

router = APIRouter(tags=["events"])


def _message(e: AuditEvent) -> str:
    p = e.payload or {}
    bits = [e.action]
    for k in ("code", "key", "line", "version", "slug", "agent"):
        if k in p:
            bits.append(f"{k}={p[k]}")
    return " · ".join(str(b) for b in bits)


@router.get("/events/recent")
def recent(asset: Optional[str] = None, limit: int = 50, db: Session = Depends(get_session)):
    a = db.execute(select(Asset).where(Asset.slug == asset)).scalar_one_or_none() if asset else None
    q = select(AuditEvent)
    if a is not None:
        q = q.where((AuditEvent.asset_id == a.id) | (AuditEvent.asset_id.is_(None)))
    items = [{"id": e.id, "actor": e.actor, "action": e.action, "entity": e.entity, "entity_id": e.entity_id,
              "message": _message(e), "payload": e.payload, "created_at": views.iso(e.created_at), "kind": "audit"}
             for e in db.execute(q.order_by(AuditEvent.seq.desc()).limit(limit)).scalars()]
    rq = select(AgentRun, Agent).join(Agent, Agent.id == AgentRun.agent_id)
    if a is not None:
        rq = rq.where((AgentRun.asset_id == a.id) | (AgentRun.asset_id.is_(None)))
    for r, ag in db.execute(rq.order_by(AgentRun.started_at.desc()).limit(limit)).all():
        items.append({"id": r.id, "actor": f"agent:{ag.key}", "action": f"agent.run.{r.status}", "entity": "agent_run",
                      "entity_id": r.id, "message": r.summary or (f"{ag.name}: {r.status}" + (f" — {r.error}" if r.error else "")),
                      "payload": {"items_fetched": r.items_fetched, "signals_created": r.signals_created},
                      "created_at": views.iso(r.finished_at or r.started_at), "kind": "agent"})
    items.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return items[:limit]


@router.get("/events/stream")
async def stream(request: Request, asset: Optional[str] = None):
    async def gen():
        yield {"event": "audit", "data": json.dumps({"asset_slug": asset, "entity": "stream", "id": None,
                                                     "message": "connected"})}
        agen = bus.subscribe(asset)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(agen.__anext__(), timeout=15)
                except asyncio.TimeoutError:
                    continue
                yield {"event": ev["type"], "data": json.dumps({**ev["data"], "at": ev["at"]}, default=str)}
        finally:
            await agen.aclose()

    return EventSourceResponse(gen(), ping=15)
