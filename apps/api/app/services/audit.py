"""Append-only, hash-chained audit log (Addendum A #11).

`record(session, actor, action, entity, entity_id, payload, before=None, after=None, asset_id=None)`
adds an AuditEvent to the session (caller commits).
hash = sha256(canonical JSON (sorted keys) of the event body + prev_hash). Writes are serialised by a
process-wide lock so the chain cannot fork within one process.
"""
from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent, utcnow

GENESIS = "0" * 64
# Plain Lock (not RLock): it may be released from a different thread than the acquirer (agent runs
# share the request session across threads). Re-entrancy is tracked per session in session.info.
_LOCK = threading.Lock()
_HELD = "_audit_lock_held"
LOCK_TIMEOUT_S = 30


def _acquire(session: Session) -> None:
    if session.info.get(_HELD):
        return
    if not _LOCK.acquire(timeout=LOCK_TIMEOUT_S):
        raise RuntimeError("audit chain lock timeout")
    session.info[_HELD] = True


def _release(session: Session) -> None:
    if session.info.pop(_HELD, False):
        try:
            _LOCK.release()
        except RuntimeError:
            pass


def _install_hooks() -> None:
    from sqlalchemy import event as sa_event

    @sa_event.listens_for(Session, "after_transaction_end")
    def _end(sess, trans):  # pragma: no cover - trivial
        if trans.parent is None:
            _release(sess)

    @sa_event.listens_for(Session, "after_commit")
    def _commit(sess):  # pragma: no cover - trivial
        _release(sess)

    @sa_event.listens_for(Session, "after_rollback")
    def _rollback(sess):  # pragma: no cover - trivial
        _release(sess)


_install_hooks()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))


def digest(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def _body(ev: AuditEvent) -> dict:
    return {
        "seq": ev.seq,
        "ts": ev.ts.isoformat(),
        "actor": ev.actor,
        "action": ev.action,
        "entity": ev.entity,
        "entity_id": ev.entity_id,
        "asset_id": ev.asset_id,
        "before_hash": ev.before_hash,
        "after_hash": ev.after_hash,
        "payload": json.loads(canonical(ev.payload)) if ev.payload is not None else None,
    }


def compute_hash(ev: AuditEvent, prev_hash: str) -> str:
    return hashlib.sha256((canonical(_body(ev)) + prev_hash).encode()).hexdigest()


def _last(session: Session) -> Optional[AuditEvent]:
    pending = [o for o in session.new if isinstance(o, AuditEvent)]
    if pending:
        return max(pending, key=lambda e: e.seq)
    return session.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()


def head_hash(session: Session) -> str:
    last = _last(session)
    return last.hash if last else GENESIS


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
    # The lock is held from here until this session commits/rolls back, so concurrent in-process
    # writers cannot read the same head and fork the chain (seq is also UNIQUE as a backstop).
    _acquire(session)
    if True:
        last = _last(session)
        prev_hash = last.hash if last else GENESIS
        seq = (last.seq + 1) if last else 1
        now = utcnow()
        ev = AuditEvent(
            seq=seq,
            ts=now,
            created_at=now,
            actor=actor or "system",
            action=action,
            entity=entity,
            entity_id=entity_id,
            asset_id=asset_id,
            before_hash=digest(before),
            after_hash=digest(after),
            payload=json.loads(canonical(payload)) if payload is not None else None,
            prev_hash=prev_hash,
            hash="",
        )
        ev.hash = compute_hash(ev, prev_hash)
        session.add(ev)
        session.flush()
        return ev


def verify(session: Session) -> dict:
    prev = GENESIS
    n = 0
    ok = True
    for ev in session.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars():
        n += 1
        if ev.prev_hash != prev or compute_hash(ev, prev) != ev.hash:
            ok = False
            break
        prev = ev.hash
    length = session.execute(select(func.count(AuditEvent.id))).scalar_one()
    return {"ok": ok, "length": length, "head_hash": head_hash(session)}


def verify_chain(session: Session) -> bool:
    return verify(session)["ok"]
