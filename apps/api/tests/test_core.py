"""CORE tests: seed integrity, review → confidence → threshold → reopen → pattern, undo, lock auth,
guardrail invariants, sim determinism, Monte Carlo shape, contract endpoint sweep.

Signals are created directly via the ORM with obviously synthetic test URLs (never loaded by the app)."""
from __future__ import annotations

import os
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

os.environ["DI_DISABLE_SCHEDULER"] = "1"

from app import db  # noqa: E402
from app.models import (Asset, AuditEvent, FetchedItem, Hypothesis, Pattern, Position, ProposedDecision,  # noqa: E402
                        Signal, SignalMove, Trial)

ASSETS = ["asp3082-pdac", "asp3082-nsclc", "asp2138-gc"]
API = "/api/v1"
H_ADMIN = {"X-Actor": "user:Admin", "X-Role": "Admin"}
H_OPS = {"X-Actor": "user:Operations", "X-Role": "Operations"}
H_CLIN = {"X-Actor": "user:Clinical", "X-Role": "Clinical"}
H_REV = {"X-Actor": "user:Reviewer", "X-Role": "Reviewer"}


@pytest.fixture
def client():
    db.configure("sqlite://")
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def session(client):
    s = db.SessionLocal()
    yield s
    s.close()


_n = [0]


def make_signal(s, slug, moves: dict[str, int], impact="normal") -> str:
    _n[0] += 1
    a = s.execute(select(Asset).where(Asset.slug == slug)).scalar_one()
    url = f"https://example.test/fixture/{_n[0]}"
    now = datetime(2026, 10, 1, 12, 0, 0)
    fi = FetchedItem(source_key="ctgov", external_id=f"TEST-{_n[0]}", url=url, title="synthetic test item",
                     retrieved_at=now)
    s.add(fi)
    s.flush()
    sig = Signal(asset_id=a.id, title=f"Synthetic test signal {_n[0]}", so_what="test", source_name="test fixture",
                 source_url=url, retrieved_at=now, impact=impact, fetched_item_id=fi.id)
    s.add(sig)
    s.flush()
    for code, d in moves.items():
        h = s.execute(select(Hypothesis).where(Hypothesis.asset_id == a.id, Hypothesis.code == code)).scalar_one()
        s.add(SignalMove(signal_id=sig.id, hypothesis_id=h.id, delta=d, weight=1.0, rationale="test"))
    s.commit()
    return sig.id


def hyp(c, slug, code):
    return next(h for h in c.get(f"{API}/assets/{slug}/hypotheses").json() if h["code"] == code)


def pos(c, slug, line):
    return next(p for p in c.get(f"{API}/assets/{slug}/positions").json() if p["line"] == line)


# ---------------------------------------------------------------- seed
def test_seed_integrity(client, session):
    assets = session.execute(select(Asset)).scalars().all()
    assert sorted(a.slug for a in assets) == sorted(ASSETS)
    assert session.query(Signal).count() == 0
    assert session.query(Trial).count() == 0
    assert session.query(FetchedItem).count() == 0
    for a in assets:
        hs = session.execute(select(Hypothesis).where(Hypothesis.asset_id == a.id)).scalars().all()
        assert 8 <= len(hs) <= 10
        for h in hs:
            assert 40 <= h.confidence_start <= 60
            assert h.threshold > h.confidence_start and h.keywords and h.change_trigger_text
            assert h.category in ("Population", "Intervention", "Comparator", "Outcomes", "Business")
        assert session.query(Position).filter(Position.asset_id == a.id).count() == 6
        pats = session.execute(select(Pattern).where(Pattern.asset_id == a.id)).scalars().all()
        assert 4 <= len(pats) <= 6 and not any(p.is_fired for p in pats)
        assert a.watch_terms["own"] and a.watch_terms["competitors"] and a.model_params["bindings"]
        assert all(v["basis"] in ("stand_in_assumption", "sourced") for v in a.model_params["inputs"].values())
    # idempotent
    from app.seed import seed

    seed(session)
    assert session.query(Asset).count() == 3


def test_kras_assets_do_not_reuse_cldn_hypotheses(client, session):
    for slug in ("asp3082-pdac", "asp3082-nsclc"):
        a = session.execute(select(Asset).where(Asset.slug == slug)).scalar_one()
        text = " ".join(h.statement for h in a.hypotheses)
        assert "CLDN18.2" not in text and "zolbetuximab" not in text
        assert "cutoff" not in {i["name"] for i in a.lever_schema}


# ---------------------------------------------------------------- review flow
def test_apply_threshold_reopen_pattern_and_undo(client, session):
    slug = "asp3082-pdac"
    s1 = make_signal(session, slug, {"H10": 8})
    s2 = make_signal(session, slug, {"H10": 8}, impact="high")
    r = client.post(f"{API}/signals/{s1}/apply", json={}, headers=H_OPS)
    assert r.status_code == 200, r.text
    assert hyp(client, slug, "H10")["confidence"] == 58
    assert pos(client, slug, "Timeline")["status"] == "provisional"
    r = client.post(f"{API}/signals/{s2}/apply", json={"reason": "two signals"}, headers=H_OPS)
    assert r.status_code == 200
    body = r.json()
    assert body["crossed"] == ["H10"] and "footprint" in body["fired"]
    h = hyp(client, slug, "H10")
    assert h["confidence"] == 66 and h["crossed"] and h["for_count"] == 2 and len(h["evidence"]) == 2
    assert pos(client, slug, "Timeline")["status"] == "reopened"
    props = client.get(f"{API}/assets/{slug}/proposals").json()
    assert [p["pattern"]["key"] for p in props] == ["footprint"]
    p = props[0]
    assert p["framing"] == "take" and len(p["signals"]) == 2
    assert any(o["is_current"] for o in p["options"]) and all("levers" in o for o in p["options"])
    # explore parity: option results == /models/run for the same levers
    o = p["options"][1]
    run = client.post(f"{API}/models/run", json={"asset": slug, "levers": o["levers"]}).json()
    assert run["feasibility"]["kpis"][1]["value"] == o["results"]["readout"]
    assert client.get(f"{API}/assets/{slug}/changes", params={"role": "Operations"}).json()["fired_patterns"]["count"] == 1
    assert client.get(f"{API}/assets/{slug}/focus").json()["kind"] == "pattern"
    # 409s
    assert client.post(f"{API}/signals/{s2}/apply", json={}, headers=H_OPS).status_code == 409
    # undo restores confidence; pattern clears; reopened stays (Addendum A #4)
    r = client.post(f"{API}/signals/{s2}/undo", json={}, headers=H_OPS)
    assert r.status_code == 200
    h = hyp(client, slug, "H10")
    assert h["confidence"] == 58 and not h["crossed"] and len(h["evidence"]) == 1
    assert client.get(f"{API}/assets/{slug}/proposals").json() == []
    assert pos(client, slug, "Timeline")["status"] == "reopened"
    assert client.post(f"{API}/signals/{s2}/undo", json={}, headers=H_OPS).status_code == 409
    # append-only: compensating event exists, audit chain verifies
    assert client.get(f"{API}/audit/verify").json()["ok"] is True
    session.expire_all()
    acts = [e.action for e in session.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars()]
    assert "pattern.fired" in acts and "pattern.cleared" in acts and "position.reopened" in acts


def test_overrides_dismiss_and_role_enforcement(client, session):
    slug = "asp2138-gc"
    sid = make_signal(session, slug, {"H10": 9})
    assert client.post(f"{API}/signals/{sid}/apply", json={}, headers=H_CLIN).status_code == 403
    assert client.post(f"{API}/signals/{sid}/apply", json={}, headers=H_REV).status_code == 403
    r = client.post(f"{API}/signals/{sid}/apply", json={"overrides": {"H10": 3}, "reason": "weaker"}, headers=H_ADMIN)
    assert r.status_code == 200
    assert hyp(client, slug, "H10")["confidence"] == 58
    sid2 = make_signal(session, slug, {"H6": 5})
    assert client.post(f"{API}/signals/{sid2}/dismiss", json={}, headers=H_CLIN).status_code == 200
    assert client.post(f"{API}/signals/{sid2}/dismiss", json={}, headers=H_CLIN).status_code == 409
    assert client.post(f"{API}/signals/{sid2}/undo", json={}, headers=H_CLIN).json()["review_status"] == "pending"
    # apply-all scoped to role
    make_signal(session, slug, {"H2": 4})
    r = client.post(f"{API}/assets/{slug}/signals/apply-all", headers=H_CLIN).json()
    assert len(r["applied"]) == 1 and len(r["skipped"]) == 1


def test_threshold_patch_and_levers_put(client):
    slug = "asp2138-gc"
    h = hyp(client, slug, "H3")
    r = client.patch(f"{API}/hypotheses/{h['id']}", json={"threshold": 60}, headers=H_CLIN)
    assert r.status_code == 200 and r.json()["crossed"]
    assert pos(client, slug, "Intervention")["status"] == "reopened"
    r = client.put(f"{API}/assets/{slug}/levers", json={"levers": {"cutoff": "1"}}, headers=H_ADMIN)
    assert r.status_code == 200 and r.json()["current"]["cutoff"] == "1"
    assert client.get(f"{API}/assets/{slug}/levers").json()["current"]["cutoff"] == "1"
    assert "≥1%" in pos(client, slug, "Population")["statement"]
    assert client.put(f"{API}/assets/{slug}/levers", json={"levers": {"cutoff": "33"}}, headers=H_ADMIN).status_code == 422


# ---------------------------------------------------------------- positions
def test_lock_requires_owner_or_admin(client):
    slug = "asp3082-nsclc"
    p = pos(client, slug, "Population")
    assert p["owner_role"] == "Asset lead"
    assert client.post(f"{API}/positions/{p['id']}/lock", json={}, headers=H_CLIN).status_code == 403
    r = client.post(f"{API}/positions/{p['id']}/lock", json={}, headers={"X-Actor": "u", "X-Role": "Asset lead"})
    assert r.status_code == 200 and r.json()["status"] == "locked" and r.json()["version"] == 1
    t = pos(client, slug, "Timeline")
    r = client.post(f"{API}/positions/{t['id']}/lock", json={}, headers=H_ADMIN)
    assert r.status_code == 200
    hist = client.get(f"{API}/positions/{p['id']}/history").json()
    snap = hist[0]["snapshot"]
    assert set(snap) >= {"statement", "levers", "hypotheses", "signal_ids", "scenario", "model_versions", "audit_head_hash"}
    assert set(snap["scenario"]["peak"]) == {"p10", "p50", "p90"}


def test_lock_then_crossing_reopens_and_keeps_history(client, session):
    slug = "asp3082-pdac"
    t = pos(client, slug, "Timeline")
    client.post(f"{API}/positions/{t['id']}/lock", json={}, headers=H_OPS)
    sid = make_signal(session, slug, {"H10": 10})
    sid2 = make_signal(session, slug, {"H10": 6})
    client.post(f"{API}/signals/{sid}/apply", json={}, headers=H_OPS)
    client.post(f"{API}/signals/{sid2}/apply", json={}, headers=H_OPS)
    assert pos(client, slug, "Timeline")["status"] == "reopened"
    assert len(client.get(f"{API}/positions/{t['id']}/history").json()) == 1


# ---------------------------------------------------------------- guardrail invariants
def test_signal_without_source_url_cannot_be_inserted(client, session):
    a = session.execute(select(Asset)).scalars().first()
    fi = FetchedItem(source_key="ctgov", external_id="X-1", url="https://example.test/x", retrieved_at=datetime.now())
    session.add(fi)
    session.flush()
    session.add(Signal(asset_id=a.id, title="no url", source_url=None, retrieved_at=datetime.now(), fetched_item_id=fi.id))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    session.add(Signal(asset_id=a.id, title="no retrieval", source_url="https://example.test/x", retrieved_at=None,
                       fetched_item_id=fi.id))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    session.add(Signal(asset_id=a.id, title="no item", source_url="https://example.test/x", retrieved_at=datetime.now()))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


# ---------------------------------------------------------------- sim
def test_sim_determinism_and_interface(client):
    for slug in ASSETS:
        a = client.post(f"{API}/models/run", json={"asset": slug, "levers": {}}).json()
        b = client.post(f"{API}/models/run", json={"asset": slug, "levers": {}}).json()
        assert a == b
        for k in ("demand", "ptrs", "access", "feasibility", "business"):
            m = a[k]
            assert m["engine"] == "stand_in" and m["version"] and m["reading"] and "Stand-in" in m["reading"]
            assert m["assumptions"] and all("basis" in x for x in m["assumptions"])
            assert all(set(kp) >= {"label", "value", "unit", "basis"} for kp in m["kpis"])
        assert a["demand"]["series"]["pools"]
    reg = client.get(f"{API}/models/registry").json()
    assert len(reg) == 5 and all(r["engine"] == "stand_in" for r in reg)


def test_levers_change_outputs(client):
    base = client.post(f"{API}/models/run", json={"asset": "asp2138-gc", "levers": {}}).json()
    broad = client.post(f"{API}/models/run", json={"asset": "asp2138-gc", "levers": {"cutoff": "1"}}).json()
    assert broad["demand"]["kpis"][0]["value"] != base["demand"]["kpis"][0]["value"]


def test_montecarlo_shape_and_determinism(client):
    r1 = client.post(f"{API}/models/montecarlo", json={"asset": "asp3082-pdac", "levers": {}, "n": 500}).json()
    r2 = client.post(f"{API}/models/montecarlo", json={"asset": "asp3082-pdac", "levers": {}, "n": 500}).json()
    assert r1["n"] == 500 and r2["cached"] is True
    for k in ("peak", "rnpv"):
        assert set(r1[k]) == {"p10", "p50", "p90"} and r1[k]["p10"] <= r1[k]["p50"] <= r1[k]["p90"]
        assert r1[k] == r2[k]
    assert sum(b["count"] for b in r1["histogram"]) == 500
    assert 0 <= r1["negative_share"] <= 1
    from app.sim import montecarlo
    montecarlo._CACHE.clear()
    r3 = client.post(f"{API}/models/montecarlo", json={"asset": "asp3082-pdac", "levers": {}, "n": 500}).json()
    assert r3["peak"] == r1["peak"] and r3["cached"] is False


# ---------------------------------------------------------------- endpoint sweep
def test_every_contract_endpoint_200(client, session):
    for path in ["/health", "/assets", "/agents", "/agents/status", "/sources", "/sources/ctgov", "/models/registry",
                 "/events/recent", "/stats/landing", "/me", "/audit/verify", "/patterns?asset=asp2138-gc"]:
        r = client.get(API + path)
        assert r.status_code == 200, (path, r.text)
    assert client.get("/health").json() == {"ok": True}
    agents = client.get(f"{API}/agents").json()
    assert all("last_run" in a and a["summary"] == "Not yet run" for a in agents)
    assert client.get(f"{API}/agents/{agents[0]['id']}").status_code == 200
    for slug in ASSETS:
        for sub in ["", "/brief", "/focus", "/trials", "/changes?role=Clinical", "/hypotheses", "/signals",
                    "/signals?status=pending", "/proposals", "/patterns", "/levers", "/scenarios", "/positions",
                    "/unmatched", "/digest?role=Clinical", "/summary", "/briefs"]:
            r = client.get(f"{API}/assets/{slug}{sub}")
            assert r.status_code == 200, (slug, sub, r.text)
        tr = client.get(f"{API}/assets/{slug}/trials").json()
        assert tr["items"] == [] and tr["coverage"]["status"] == "never_run" and tr["last_run"] is None
        sg = client.get(f"{API}/assets/{slug}/signals").json()
        assert sg["items"] == [] and sg["coverage"]["status"] == "never_run"
        assert client.post(f"{API}/models/run", json={"asset": slug, "levers": {}}).status_code == 200
        r = client.post(f"{API}/assets/{slug}/scenarios", json={"name": "base", "n": 100}, headers=H_ADMIN)
        assert r.status_code == 200
        r = client.post(f"{API}/assets/{slug}/briefs", json={"exported_by": "user:Admin"}, headers=H_ADMIN)
        assert r.status_code == 200
        bid = r.json()["id"]
        assert r.json()["version"] == "v0.1"
        assert client.get(f"{API}/briefs/{bid}").status_code == 200
        html = client.get(f"{API}/briefs/{bid}.html")
        assert html.status_code == 200 and "What would change our mind" in html.text
    # hypothesis register + agent attach
    ag = next(a for a in agents if a["key"] == "literature")
    r = client.post(f"{API}/assets/asp3082-pdac/hypotheses", headers=H_CLIN, json={
        "statement": "A test hypothesis statement that is long enough.", "category": "Outcomes", "owner_role": "Clinical",
        "confidence_start": 50, "threshold": 70, "change_trigger_text": "x", "keywords": ["x"], "agent_ids": [ag["id"]]})
    assert r.status_code == 200, r.text
    assert r.json()["code"] == "H11" and r.json()["scheduled"][0]["agent_key"] == "literature"
    bad = client.post(f"{API}/assets/asp3082-pdac/hypotheses", headers=H_CLIN, json={
        "statement": "too short", "category": "Outcomes", "owner_role": "Clinical", "confidence_start": 50, "threshold": 40})
    assert bad.status_code == 422
    hid = r.json()["id"]
    rg = next(a for a in agents if a["key"] == "registry_watch")
    assert client.post(f"{API}/hypotheses/{hid}/agents/{rg['id']}", headers=H_CLIN).status_code == 200
    assert client.delete(f"{API}/hypotheses/{hid}/agents/{rg['id']}", headers=H_CLIN).status_code == 200
    assert client.patch(f"{API}/agents/{rg['id']}", json={"cadence_minutes": 120}, headers=H_ADMIN).json()["cadence_minutes"] == 120
    r = client.post(f"{API}/agents", json={"name": "Test draft agent", "category": "daily"}, headers=H_ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "supervised"
    r = client.post(f"{API}/assets", json={"code": "NEW-1", "name": "New", "indication": "Test"}, headers=H_ADMIN)
    assert r.status_code == 200 and r.json()["counts"]["hypotheses"] == 0
    assert len(client.get(f"{API}/assets/new-1/positions").json()) == 6
    assert client.get(f"{API}/assets/nope").status_code == 404
    rec = client.get(f"{API}/events/recent").json()
    assert rec and set(rec[0]) >= {"actor", "action", "entity", "message", "created_at"}
    assert client.get(f"{API}/audit/verify").json()["ok"] is True


def test_audit_chain_tamper_detected(client, session):
    from app.services import audit

    assert audit.verify(session)["ok"]
    ev = session.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars().first()
    ev.payload = {"tampered": True}
    session.commit()
    assert audit.verify(session)["ok"] is False


def test_events_bus_publish_from_sync():
    import asyncio

    from app.services import events

    async def go():
        agen = events.subscribe("asp2138-gc")
        task = asyncio.ensure_future(agen.__anext__())
        await asyncio.sleep(0)
        events.publish("audit", {"entity": "x", "id": "1"}, "asp2138-gc")
        ev = await asyncio.wait_for(task, 2)
        await agen.aclose()
        return ev

    ev = asyncio.run(go())
    assert ev["type"] == "audit" and ev["data"]["asset_slug"] == "asp2138-gc"
