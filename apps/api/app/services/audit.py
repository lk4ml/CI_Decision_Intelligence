"""Append-only, hash-chained audit log.

`record(session, actor, action, entity, entity_id, payload, before=None, after=None)`
adds an AuditEvent to the session (caller commits). hash = sha256(prev_hash + canonical body).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, utcnow

GENESIS = "0" * 64


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))


def digest(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    return hashlib.sha256(_canon(obj).encode()).hexdigest()


def _last(session: Session) -> Optional[AuditEvent]:
    # include pending (unflushed) rows in this session
    pending = [o for o in session.new if isinstance(o, AuditEvent)]
    if pending:
        return max(pending, key=lambda e: e.seq)
    return session.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()


def record(
    session: Session,
    actor: str,
    action: str,
    entity: str,
    entity_id: Optional[str],
    payload: Any = None,
    before: Any = None,
    after: Any = None,
    asset_id: Optional[str] = None,
) -> AuditEvent:
    last = _last(session)
    prev_hash = last.hash if last else GENESIS
    seq = (last.seq + 1) if last else 1
    created = utcnow()
    before_hash, after_hash = digest(before), digest(after)
    body = {
        "seq": seq,
        "actor": actor,
        "action": action,
        "entity": entity,
        "entity_id": entity_id,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "payload": payload,
        "created_at": created.isoformat(),
    }
    h = hashlib.sha256((prev_hash + _canon(body)).encode()).hexdigest()
    ev = AuditEvent(
        seq=seq,
        actor=actor or "system",
        action=action,
        entity=entity,
        entity_id=entity_id,
        asset_id=asset_id,
        before_hash=before_hash,
        after_hash=after_hash,
        payload=payload,
        prev_hash=prev_hash,
        hash=h,
        created_at=created,
    )
    session.add(ev)
    return ev


def verify_chain(session: Session) -> bool:
    prev = GENESIS
    for ev in session.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars():
        body = {
            "seq": ev.seq,
            "actor": ev.actor,
            "action": ev.action,
            "entity": ev.entity,
            "entity_id": ev.entity_id,
            "before_hash": ev.before_hash,
            "after_hash": ev.after_hash,
            "payload": ev.payload,
            "created_at": ev.created_at.isoformat(),
        }
        if ev.prev_hash != prev:
            return False
        if hashlib.sha256((prev + _canon(body)).encode()).hexdigest() != ev.hash:
            return False
        prev = ev.hash
    return True
