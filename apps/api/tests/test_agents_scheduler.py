"""Scheduler planning tests (no network, no timers)."""
from __future__ import annotations

import asyncio

from app import db
from app.agents import scheduler

from test_agents import _minimal_config


def _session():
    db.configure("sqlite://")
    db.init_db()
    s = db.SessionLocal()
    _minimal_config(s)
    return s


def test_pairs_from_hypothesis_agents():
    s = _session()
    try:
        plan = scheduler.pairs(s)
    finally:
        s.close()
    keys = {(k, a) for k, a, _ in plan}
    assert ("registry_watch", "asp3082-pdac") in keys
    assert len(keys) == 5 and all(c == 360 for _, _, c in plan)


def test_disabled_scheduler(monkeypatch):
    monkeypatch.setenv("DI_DISABLE_SCHEDULER", "1")
    assert scheduler.start(None) is None
    out = scheduler.enqueue("registry_watch", "asp3082-pdac")
    assert out["run_at"] is None and out["skipped"] == "scheduler disabled"
    assert scheduler.enqueue("implication", "asp3082-pdac")["skipped"] == "agent has no connector"


def test_start_schedules_jobs(monkeypatch):
    monkeypatch.delenv("DI_DISABLE_SCHEDULER", raising=False)
    _session().close()

    async def go():
        sch = scheduler.start(None)
        try:
            jobs = sch.get_jobs()
            assert {j.id for j in jobs} >= {"registry_watch:asp3082-pdac"}
            assert scheduler.next_run_at() is not None
            r = scheduler.enqueue("literature", "asp3082-pdac", delay_s=3600)
            assert r["run_at"]
        finally:
            scheduler.shutdown()

    asyncio.run(go())


def test_enqueue_registers_interval_and_reschedule(monkeypatch):
    monkeypatch.delenv("DI_DISABLE_SCHEDULER", raising=False)
    s = _session()
    s.close()

    async def go():
        sch = scheduler.start(None)
        try:
            sch.remove_job("literature:asp3082-pdac")
            scheduler.enqueue("literature", "asp3082-pdac", delay_s=3600)
            ids = {j.id for j in sch.get_jobs()}
            assert "literature:asp3082-pdac" in ids
            assert any(i.startswith("once:literature:asp3082-pdac") for i in ids)
            # agent set to planned -> reschedule drops its recurring jobs
            from app.models import Agent
            s2 = db.SessionLocal()
            s2.query(Agent).filter_by(key="literature").one().status = "planned"
            s2.commit(); s2.close()
            assert scheduler.reschedule("literature") == []
            assert "literature:asp3082-pdac" not in {j.id for j in sch.get_jobs()}
            assert scheduler.reschedule("registry_watch") == ["registry_watch:asp3082-pdac"]
        finally:
            scheduler.shutdown()

    asyncio.run(go())
