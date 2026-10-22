"""Agent pipeline tests on an in-memory DB with SYNTHETIC connector fixtures.

The DB holds configuration only (asset, hypotheses, agents, sources) - the same kind of
rows CORE's seed writes. All evidence comes through the (mocked) connectors.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import httpx
import pytest
from sqlalchemy import select

from app import db
from app.agents import guardrail, implication, match as match_mod
from app.agents.extract import Facts
from app.agents.pipeline import run_agent, run_agent_async
from app.connectors import http
from app.connectors.http import RawItem
from app.models import (Agent, AgentRun, Asset, AuditEvent, FetchedItem, Hypothesis, HypothesisAgent,
                        Signal, SignalMove, Source, Trial, UnmatchedItem)
from app.services import events

from fixtures.helpers import all_source_routes, route_transport


def _minimal_config(s):
    """Configuration-only seed used when CORE's seed is unavailable."""
    agents = {}
    for key, srcs in [("registry_watch", ["ctgov"]), ("literature", ["pubmed", "europepmc"]),
                      ("research_graph", ["openalex"]), ("regulatory", ["openfda"]),
                      ("astellas_ir", ["astellas_ir"])]:
        a = Agent(key=key, name=key.replace("_", " ").title(), category="always_on", reads="world",
                  cadence_minutes=360, status="running", source_keys=srcs)
        s.add(a)
        agents[key] = a
    for key, base in [("ctgov", "https://clinicaltrials.gov/api/v2"),
                      ("pubmed", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"),
                      ("europepmc", "https://www.ebi.ac.uk/europepmc/webservices/rest"),
                      ("openalex", "https://api.openalex.org"), ("openfda", "https://api.fda.gov"),
                      ("astellas_ir", "https://www.astellas.com/en/investors")]:
        s.add(Source(key=key, name=key, side="world", kind="x", base_url=base))
    asset = Asset(slug="asp3082-pdac", code="ASP3082-PDAC", name="Setidegrasib (ASP3082)",
                  indication="Pancreatic ductal adenocarcinoma", biomarker="KRAS G12D+",
                  phase="Phase 3 (started Apr 2026)", phase_source="user",
                  watch_terms={"own": ["ASP3082", "setidegrasib"], "competitors": ["daraxonrasib"],
                               "literature": ["KRAS G12D pancreatic cancer"],
                               "standard_of_care": ["gemcitabine"]})
    s.add(asset)
    s.flush()
    kw = dict(asset_id=asset.id, owner_role="Clinical", confidence_start=50, confidence=50, threshold=65)
    extra = {"position_line": "Comparator"} if hasattr(Hypothesis, "position_line") else {}
    h1 = Hypothesis(code="H7", category="Comparator",
                    statement="At least one competitor KRAS G12D-selective or pan-RAS agent will reach approval in PDAC before our pivotal reads out.",
                    keywords=["Phase 3", "competitor", "KRAS G12D", "pan-RAS", "approval"], **kw, **extra)
    h2 = Hypothesis(code="H8", category="Outcomes",
                    statement="Overall survival, not PFS alone, will be required as the primary endpoint for full approval in PDAC.",
                    keywords=["overall survival", "primary endpoint", "PFS"], **kw,
                    **({"position_line": "Outcomes"} if extra else {}))
    s.add_all([h1, h2])
    s.flush()
    for h in (h1, h2):
        for k in ("registry_watch", "literature", "regulatory", "astellas_ir", "research_graph"):
            s.add(HypothesisAgent(hypothesis_id=h.id, agent_id=agents[k].id))
    s.commit()


@pytest.fixture
def session(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db.configure("sqlite://")
    db.init_db()
    s = db.SessionLocal()
    _minimal_config(s)
    yield s
    s.close()


@pytest.fixture
def mocked():
    http.set_transport(route_transport(all_source_routes()))
    yield
    http.set_transport(None)


def test_registry_watch_end_to_end(session, mocked):
    run = run_agent(session, "registry_watch", "asp3082-pdac")
    assert run.status == "ok", run.error
    assert run.items_fetched == 2 and run.items_new == 2
    assert run.signals_created >= 1
    assert run.summary and "ClinicalTrials.gov" in run.summary
    sigs = list(session.execute(select(Signal)).scalars())
    assert sigs and all(s.source_url.startswith("https://clinicaltrials.gov/study/NCT") for s in sigs)
    for s in sigs:
        fi = session.get(FetchedItem, s.fetched_item_id)
        assert s.retrieved_at == fi.retrieved_at and s.source_url == fi.url
        assert s.review_status == "pending" and s.so_what_origin == "rules"
    moves = list(session.execute(select(SignalMove)).scalars())
    assert moves and all(-10 <= m.delta <= 10 and m.delta != 0 for m in moves)
    trials = {t.nct_id: t for t in session.execute(select(Trial)).scalars()}
    assert trials["NCT99990001"].role == "own" and trials["NCT99990002"].role == "competitor"
    asset = session.execute(select(Asset)).scalar_one()
    assert asset.phase_source == "registry"
    assert asset.registry_phase == "Phase 3"
    assert asset.registry_nct_ids == ["NCT99990001"]
    assert asset.registry_checked_at is not None
    assert asset.phase_discrepancy is None
    actions = [a.action for a in session.execute(select(AuditEvent)).scalars()]
    assert "signal.created" in actions and "agent.run" in actions and "asset.phase_reconciled" in actions
    src = session.execute(select(Source).where(Source.key == "ctgov")).scalar_one()
    assert src.last_status == "ok" and src.last_ok_at is not None
    types = [e["type"] for e in events.recent("asp3082-pdac")]
    assert "signal.created" in types and "agent.run" in types


def test_competitor_phase3_delta_formula(session, mocked):
    run_agent(session, "registry_watch", "asp3082-pdac")
    sig = session.execute(select(Signal).join(FetchedItem, FetchedItem.id == Signal.fetched_item_id)
                          .where(FetchedItem.external_id == "NCT99990002")).scalar_one()
    h7 = session.execute(select(Hypothesis).where(Hypothesis.code == "H7")).scalar_one()
    mv = session.execute(select(SignalMove).where(SignalMove.signal_id == sig.id,
                                                  SignalMove.hypothesis_id == h7.id)).scalar_one()
    # competitor Phase 3 start: base 1.0 x registry 1.0 x relevance 1.0 -> +10 for comparator-category H7
    assert mv.delta == 10
    assert sig.impact == "high"


def test_dedupe_on_second_run(session, mocked):
    r1 = run_agent(session, "registry_watch", "asp3082-pdac")
    n_sig = session.query(Signal).count()
    n_un = session.query(UnmatchedItem).count()
    r2 = run_agent(session, "registry_watch", "asp3082-pdac")
    assert r2.status == "ok" and r2.items_fetched == 2
    assert r2.items_new == 0 and r2.signals_created == 0
    assert session.query(Signal).count() == n_sig and session.query(UnmatchedItem).count() == n_un
    assert session.query(FetchedItem).count() == 2
    assert r1.id != r2.id


def test_source_unreachable_records_honestly(session):
    http.set_transport(route_transport({}, default_status=403))
    try:
        run = run_agent(session, "registry_watch", "asp3082-pdac")
    finally:
        http.set_transport(None)
    assert run.status == "source_unreachable"
    assert "403" in run.error and "clinicaltrials.gov" in run.error
    assert run.summary.startswith("ClinicalTrials.gov unreachable") and "403" in run.summary
    assert session.query(Signal).count() == 0
    assert session.query(Trial).count() == 0
    assert session.query(FetchedItem).count() == 0
    src = session.execute(select(Source).where(Source.key == "ctgov")).scalar_one()
    assert src.last_status == "source_unreachable" and "403" in src.last_error
    asset = session.execute(select(Asset)).scalar_one()
    assert asset.phase_source == "user"
    assert session.query(AgentRun).filter_by(status="source_unreachable").count() == 1
    ev = [e for e in events.recent("asp3082-pdac") if e["type"] == "agent.run"][-1]
    assert ev["data"]["status"] == "source_unreachable"


@pytest.mark.parametrize("agent_key", ["literature", "research_graph", "regulatory", "astellas_ir"])
def test_other_agents_run(session, mocked, agent_key):
    run = run_agent(session, agent_key, "asp3082-pdac")
    assert run.status == "ok", run.error
    assert run.items_fetched >= 1
    for s in session.execute(select(Signal)).scalars():
        fi = session.get(FetchedItem, s.fetched_item_id)
        assert s.source_url == fi.url and s.retrieved_at is not None
        assert guardrail.host_ok(s.source_url, fi.source_key, None)


def test_unmatched_no_hypothesis_match(session):
    def h(req):
        return httpx.Response(200, json={"studies": [{"protocolSection": {
            "identificationModule": {"nctId": "NCT99990077", "briefTitle": "Diet study in pancreatitis"},
            "statusModule": {"overallStatus": "RECRUITING"},
            "conditionsModule": {"conditions": ["Pancreatic exocrine insufficiency"]},
            "designModule": {"phases": ["NA"]}}}]})

    http.set_transport(httpx.MockTransport(h))
    try:
        run = run_agent(session, "registry_watch", "asp3082-pdac")
    finally:
        http.set_transport(None)
    assert run.status == "ok" and run.signals_created == 0
    reasons = [u.reason for u in session.execute(select(UnmatchedItem)).scalars()]
    assert reasons and reasons[0] == "no_hypothesis_match"
    assert session.execute(select(UnmatchedItem)).scalars().first().asset_id is not None


def test_run_agent_inside_running_loop(session, mocked):
    async def inner():
        return run_agent(session, "registry_watch", "asp3082-pdac")

    run = asyncio.run(inner())
    assert run.status == "ok"


def test_llm_so_what_with_unsourced_number_is_blocked_then_rules_fallback(session, mocked, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def fake_llm(item, facts, matches, client=None):
        return implication.LLMOut(so_what="Competitor reported 87% response in 999 patients.",
                                  moves=[implication.LLMMove(hypothesis_code=m.code, direction="support")
                                         for m in matches])

    monkeypatch.setattr(implication, "llm_implication", fake_llm)
    run = run_agent(session, "registry_watch", "asp3082-pdac")
    assert run.status == "ok"
    sigs = list(session.execute(select(Signal)).scalars())
    assert sigs and all(s.so_what_origin == "rules" for s in sigs)
    assert all("87%" not in (s.so_what or "") for s in sigs)


def test_llm_so_what_accepted_when_grounded(session, mocked, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def fake_llm(item, facts, matches, client=None):
        return implication.LLMOut(so_what="A competitor pan-RAS agent is in a registered Phase 3 in pancreatic cancer.",
                                  moves=[implication.LLMMove(hypothesis_code=m.code, direction="contradict")
                                         for m in matches])

    monkeypatch.setattr(implication, "llm_implication", fake_llm)
    run_agent(session, "registry_watch", "asp3082-pdac")
    sigs = list(session.execute(select(Signal)).scalars())
    assert sigs and all(s.so_what_origin == "llm" for s in sigs)
    # LLM sets only the sign; magnitude still from the formula
    assert all(m.delta < 0 for m in session.execute(select(SignalMove)).scalars())


# ------------------------------------------------------------------ guardrail units

class _FI:
    def __init__(self, url, retrieved_at, raw, structured=None):
        self.id = "fi-1"
        self.url, self.retrieved_at, self.raw, self.structured, self.title = url, retrieved_at, raw, structured, ""


def test_guardrail_rules():
    now = datetime(2026, 10, 22, 7, 0, 0)
    fi = _FI("https://clinicaltrials.gov/study/NCT99990001", now, {"text": "Phase 3, 450 patients NCT99990001"})
    ok = dict(source_url=fi.url, retrieved_at=now, fetched_item=fi, source_key="ctgov")
    assert guardrail.check(so_what="Own Phase 3 with 450 patients (NCT99990001) supports H7.", **ok) is None
    assert "missing source_url" in guardrail.check(**{**ok, "source_url": None}, so_what="x")
    assert "missing retrieved_at" in guardrail.check(**{**ok, "retrieved_at": None}, so_what="x")
    assert "no fetched_item" in guardrail.check(**{**ok, "fetched_item": None}, so_what="x")
    fi_ftp = _FI("ftp://clinicaltrials.gov/x", now, {})
    assert "scheme" in guardrail.check(**{**ok, "source_url": fi_ftp.url, "fetched_item": fi_ftp}, so_what="x")
    assert "differs" in guardrail.check(**{**ok, "source_url": "https://clinicaltrials.gov/other"}, so_what="x")
    fi_bad = _FI("https://evil.example.com/x", now, {})
    assert "host" in guardrail.check(**{**ok, "source_url": fi_bad.url, "fetched_item": fi_bad}, so_what="x")
    r = guardrail.check(so_what="Response rate 62% in NCT12345678.", **ok)
    assert r and "62" in r and "NCT12345678" in r


def test_match_buckets():
    class H:
        code, category = "H1", "Comparator"
        statement = "A competitor pan-RAS agent will reach approval in PDAC."
        change_trigger_text = ""
        keywords = ["pan-RAS", "approval"]

    m = match_mod.score(H, "pan-RAS inhibitor approval granted")
    assert m.relevance == 1.0
    assert match_mod.score(H, "pan-RAS chemistry").relevance == 0.7
    assert match_mod.score(H, "unrelated cardiology text") is None


def test_delta_formula_clamps():
    assert implication.compute_delta(1.0, 1.0, 1.0, +1) == 10
    assert implication.compute_delta(0.3, 0.5, 0.4, +1) == 1
    assert implication.compute_delta(0.8, 0.9, 0.7, -1) == -5


def test_core_seed_registry_watch_if_available(mocked, monkeypatch):
    """Runs against CORE's real configuration seed when it is importable."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    try:
        from app import seed as core_seed
        db.configure("sqlite://")
        db.init_db()
        s = db.SessionLocal()
        core_seed.seed(s)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"CORE seed not usable yet: {type(e).__name__}: {e}")
    try:
        assert s.query(Signal).count() == 0  # seed contains no evidence
        run = asyncio.run(run_agent_async(s, "registry_watch", "asp3082-pdac"))
        assert run.status == "ok", run.error
        assert s.query(Signal).filter(Signal.source_url.like("https://clinicaltrials.gov/study/%")).count() >= 1
    finally:
        s.close()
