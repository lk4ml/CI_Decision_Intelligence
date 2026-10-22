"""Agent scheduler (APScheduler AsyncIOScheduler).

- ``start(app)``: schedules each distinct (agent, asset) pair from HypothesisAgent where the
  agent has ``cadence_minutes`` and ``status != "planned"`` and a connector fetcher. First run
  30s after startup (staggered). Disabled with env ``DI_DISABLE_SCHEDULER=1``.
- ``enqueue(agent_key, asset_slug)``: immediate one-off run (used by POST /hypotheses);
  returns ``{agent_key, asset_slug, run_at}``.
- ``run_all_now()``: synchronous run of every schedulable pair.
- ``shutdown()``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select

from app import db
from app.models import Agent, Asset, Hypothesis, HypothesisAgent

from . import registry
from .pipeline import run_agent

log = logging.getLogger("di.scheduler")
FIRST_RUN_DELAY_S = 30
STAGGER_S = 5
ENQUEUE_DELAY_S = 2

_scheduler = None


def disabled() -> bool:
    return os.environ.get("DI_DISABLE_SCHEDULER", "").strip() in ("1", "true", "yes")


def pairs(session) -> list[tuple[str, str, int]]:
    """Distinct (agent_key, asset_slug, cadence_minutes) for schedulable agents."""
    q = (select(Agent.key, Asset.slug, Agent.cadence_minutes, Agent.status)
         .join(HypothesisAgent, HypothesisAgent.agent_id == Agent.id)
         .join(Hypothesis, Hypothesis.id == HypothesisAgent.hypothesis_id)
         .join(Asset, Asset.id == Hypothesis.asset_id)
         .distinct())
    out = []
    for key, slug, cadence, status in session.execute(q).all():
        if cadence and status != "planned" and registry.is_runnable(key):
            out.append((key, slug, int(cadence)))
    return sorted(set(out))


def _run_sync(agent_key: str, asset_slug: str) -> Optional[str]:
    s = db.SessionLocal()
    try:
        run = run_agent(s, agent_key, asset_slug)
        return run.status
    except Exception:  # noqa: BLE001
        log.exception("agent run failed: %s %s", agent_key, asset_slug)
        return None
    finally:
        s.close()


async def _job(agent_key: str, asset_slug: str) -> None:
    await asyncio.to_thread(_run_sync, agent_key, asset_slug)


def start(app: Any = None) -> Any:
    global _scheduler
    if disabled():
        log.info("scheduler disabled (DI_DISABLE_SCHEDULER=1)")
        return None
    if _scheduler is not None:
        return _scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    sch = AsyncIOScheduler(timezone="UTC")
    s = db.SessionLocal()
    try:
        plan = pairs(s)
    finally:
        s.close()
    now = datetime.now(timezone.utc)
    for i, (key, slug, cadence) in enumerate(plan):
        sch.add_job(_job, "interval", minutes=cadence, args=[key, slug],
                    id=f"{key}:{slug}", replace_existing=True, max_instances=1, coalesce=True,
                    next_run_time=now + timedelta(seconds=FIRST_RUN_DELAY_S + i * STAGGER_S))
    sch.start()
    _scheduler = sch
    if app is not None:
        try:
            app.state.scheduler = sch
        except AttributeError:
            pass
    log.info("scheduler started with %d (agent, asset) jobs", len(plan))
    return sch


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass
        _scheduler = None


def next_run_at() -> Optional[datetime]:
    if _scheduler is None:
        return None
    times = [j.next_run_time for j in _scheduler.get_jobs() if j.next_run_time]
    return min(times) if times else None


def enqueue(agent_key: str, asset_slug: str, delay_s: int = ENQUEUE_DELAY_S) -> dict:
    """Schedule an immediate one-off run; works with or without the scheduler running."""
    run_at = datetime.now(timezone.utc) + timedelta(seconds=delay_s)
    if not registry.is_runnable(agent_key):
        return {"agent_key": agent_key, "asset_slug": asset_slug, "run_at": None,
                "skipped": "agent has no connector"}
    if _scheduler is not None:
        _scheduler.add_job(_job, "date", run_date=run_at, args=[agent_key, asset_slug],
                           id=f"once:{agent_key}:{asset_slug}:{run_at.timestamp()}")
    elif not disabled():
        t = threading.Timer(delay_s, _run_sync, args=[agent_key, asset_slug])
        t.daemon = True
        t.start()
    else:
        return {"agent_key": agent_key, "asset_slug": asset_slug, "run_at": None,
                "skipped": "scheduler disabled"}
    return {"agent_key": agent_key, "asset_slug": asset_slug, "run_at": run_at.isoformat()}


def run_all_now() -> list[dict]:
    s = db.SessionLocal()
    try:
        plan = pairs(s)
    finally:
        s.close()
    return [{"agent_key": k, "asset_slug": a, "status": _run_sync(k, a)} for k, a, _ in plan]
