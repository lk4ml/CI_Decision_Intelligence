"""Always-on pipeline (PRD §7.2): fetch -> change detection -> extract -> match ->
implication -> guardrail -> persist Signal(+SignalMoves, pending) -> audit + SSE.

Hard rules: no fabricated evidence. On ``SourceUnavailable`` the run is recorded as
``status="source_unreachable"`` with the error, the Source row is updated, and nothing else
is written.
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.ctgov import phase_rank
from app.connectors.http import RawItem, SourceUnavailable
from app.models import (
    Agent,
    AgentRun,
    Asset,
    FetchedItem,
    Hypothesis,
    HypothesisAgent,
    Signal,
    SignalMove,
    Source,
    Trial,
    UnmatchedItem,
    utcnow,
)
from app.services import audit, events

from . import guardrail, registry
from .extract import Facts, extract
from .implication import Implication, implicate, llm_enabled
from .match import match

ACTOR_PREFIX = "agent:"
_RUN_LOCK = threading.Lock()  # serialise runs (SQLite, single process)


def _naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _parse_date(s: Any) -> Optional[datetime]:
    """Best-effort parse of source dates ('2026-04-15', '2026/09/15 00:00', '2026-04', '2026 Sep')."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip().replace("/", "-")
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    parts = s.replace(",", " ").split()
    head = parts[0] if parts else ""
    try:
        if len(head) == 10:
            return datetime.strptime(head, "%Y-%m-%d")
        if len(head) == 7:
            return datetime.strptime(head, "%Y-%m")
        if len(head) == 4 and head.isdigit():
            month = _MONTHS.get(parts[1][:3].lower(), 1) if len(parts) > 1 else 1
            return datetime(int(head), month, 1)
    except ValueError:
        return None
    return None


def _hypotheses_for(session: Session, agent: Agent, asset: Asset) -> list[Hypothesis]:
    all_h = list(session.execute(select(Hypothesis).where(Hypothesis.asset_id == asset.id)).scalars())
    linked = set(session.execute(
        select(HypothesisAgent.hypothesis_id).where(HypothesisAgent.agent_id == agent.id)
    ).scalars())
    scoped = [h for h in all_h if h.id in linked]
    return scoped or all_h


def _update_sources(session: Session, keys: list[str], status: str, error: Optional[str]) -> None:
    now = utcnow()
    for k in keys:
        src = session.execute(select(Source).where(Source.key == k)).scalar_one_or_none()
        if not src:
            continue
        src.last_fetch_at = now
        src.last_status = status
        if status == "ok":
            src.last_ok_at = now
            src.last_error = None
        else:
            src.last_error = error


def _already_processed(session: Session, fi: FetchedItem, asset: Asset) -> bool:
    s = session.execute(select(Signal.id).where(Signal.fetched_item_id == fi.id,
                                                Signal.asset_id == asset.id).limit(1)).first()
    if s:
        return True
    u = session.execute(select(UnmatchedItem.id).where(UnmatchedItem.fetched_item_id == fi.id,
                                                       UnmatchedItem.asset_id == asset.id).limit(1)).first()
    return bool(u)


def _upsert_fetched(session: Session, item: RawItem) -> tuple[FetchedItem, bool, Optional[dict]]:
    """Return (row, changed, previous_data)."""
    fi = session.execute(select(FetchedItem).where(
        FetchedItem.source_key == item.source_key, FetchedItem.external_id == item.external_id
    )).scalar_one_or_none()
    if fi is None:
        fi = FetchedItem(source_key=item.source_key, external_id=item.external_id, url=item.url,
                         title=item.title, content_hash=item.content_hash, raw=item.to_dict(),
                         retrieved_at=_naive(item.retrieved_at))
        session.add(fi)
        session.flush()
        return fi, True, None
    if fi.content_hash == item.content_hash:
        return fi, False, (fi.raw or {}).get("data")
    prev = (fi.raw or {}).get("data")
    fi.url, fi.title, fi.content_hash = item.url, item.title, item.content_hash
    fi.raw = item.to_dict()
    fi.retrieved_at = _naive(item.retrieved_at)
    session.flush()
    return fi, True, prev


def _upsert_trial(session: Session, asset: Asset, facts: Facts, fi: FetchedItem) -> Optional[dict]:
    """Upsert Trial row; return the previous trial snapshot for this asset (or None)."""
    t = facts.trial or {}
    if not t.get("nct_id") or facts.role not in ("own", "competitor", "standard"):
        return None  # "context" trials are matched but not listed as asset trials
    row = session.execute(select(Trial).where(Trial.asset_id == asset.id,
                                              Trial.nct_id == t["nct_id"])).scalar_one_or_none()
    prev = None
    if row is None:
        row = Trial(asset_id=asset.id, nct_id=t["nct_id"], source_url=fi.url,
                    retrieved_at=fi.retrieved_at)
        session.add(row)
    else:
        prev = {"status": row.status, "phase": row.phase,
                "primary_completion": row.primary_completion}
    row.title, row.sponsor, row.phase, row.status = t.get("title"), t.get("sponsor"), t.get("phase"), t.get("status")
    row.start_date, row.primary_completion = t.get("start_date"), t.get("primary_completion")
    row.enrollment = t.get("enrollment")
    row.conditions, row.interventions, row.endpoints = (t.get("conditions") or [],
                                                        t.get("interventions") or [],
                                                        t.get("endpoints") or [])
    row.role = facts.role if facts.role in ("own", "competitor", "standard") else "competitor"
    row.source_url, row.retrieved_at = fi.url, fi.retrieved_at
    return prev


def _reconcile_phase(session: Session, asset: Asset, own_trials: list[dict]) -> Optional[dict]:
    """Registry reconciliation (Addendum A #12). Returns change payload or None."""
    before = {"phase_source": asset.phase_source, "registry_phase": asset.registry_phase,
              "phase_discrepancy": asset.phase_discrepancy}
    asset.registry_checked_at = utcnow()
    if not own_trials:
        asset.phase_discrepancy = ("No own on-indication trial found on ClinicalTrials.gov for "
                                   "watch terms" if asset.phase else None)
        return None if before["phase_discrepancy"] == asset.phase_discrepancy else {"before": before}
    best = max(own_trials, key=lambda t: phase_rank(t.get("phase")))
    rank = phase_rank(best.get("phase"))
    asset.registry_phase = best.get("phase")
    asset.registry_nct_ids = sorted({t["nct_id"] for t in own_trials if t.get("nct_id")})
    user_rank = phase_rank(asset.phase)
    if rank >= 3:
        asset.phase_source = "registry"
    if user_rank and rank and user_rank != rank:
        asset.phase_discrepancy = (f"User-provided '{asset.phase}' vs registry '{best.get('phase')}' "
                                   f"({best.get('nct_id')})")
    else:
        asset.phase_discrepancy = None
    after = {"phase_source": asset.phase_source, "registry_phase": asset.registry_phase,
             "phase_discrepancy": asset.phase_discrepancy}
    return {"before": before, "after": after} if after != before else None


def _unmatched(session: Session, fi: FetchedItem, asset: Asset, reason: str) -> None:
    session.add(UnmatchedItem(fetched_item_id=fi.id, asset_id=asset.id, reason=reason))


def _summary(agent: Agent, asset: Optional[Asset], run: AgentRun, src_names: str,
             failed: Optional[dict] = None, llm_used: int = 0) -> str:
    who = asset.code if asset else "all assets"
    llm = (f"LLM used for {llm_used} so-what(s)" if llm_used else
           ("LLM enabled, not used" if llm_enabled() else "LLM off (rules only)"))
    if run.status == "source_unreachable":
        detail = (run.error or "").split("): ", 1)[-1]
        return f"{src_names} unreachable for {who} - {detail}. No data substituted."
    if run.status == "error":
        return f"Run failed for {who}: {run.error}"
    failed = failed or {}
    ok_names = " / ".join(registry.SOURCE_NAMES.get(k, k)
                          for k in registry.AGENT_SOURCES.get(agent.key, []) if k not in failed) or src_names
    text = (f"Checked {run.items_fetched} {ok_names} records for {who}: {run.items_new} new/changed, "
            f"{run.signals_created} signals proposed, {run.blocked} blocked by guardrail; {llm}")
    if failed:
        text += ". Unreachable: " + "; ".join(
            f"{registry.SOURCE_NAMES.get(k, k)} ({e.detail})" for k, e in failed.items()
        ) + " - no data substituted"
    return text


@dataclass
class _Plan:
    item: RawItem
    ctx: dict
    pre: Optional[Facts] = None          # ctgov role/on-indication (for Trial upsert)
    facts: Optional[Facts] = None
    new_for_asset: bool = False
    reason: Optional[str] = None         # unmatched reason decided before implication
    matches: list = field(default_factory=list)
    imp: Optional[Implication] = None
    rules_imp: Optional[Implication] = None


def _plan_reads(session: Session, agent: Agent, asset: Asset,
                rows: list[tuple[RawItem, dict]]) -> tuple[list[_Plan], list[dict]]:
    """Phase 1 (DB reads only, no network): change detection, extract, match."""
    hyps = _hypotheses_for(session, agent, asset)
    plans: list[_Plan] = []
    own_trials: list[dict] = []
    for item, ctx in rows:
        p = _Plan(item=item, ctx=ctx)
        fi = session.execute(select(FetchedItem).where(
            FetchedItem.source_key == item.source_key,
            FetchedItem.external_id == item.external_id)).scalar_one_or_none()
        changed = fi is None or fi.content_hash != item.content_hash
        prev_data = (fi.raw or {}).get("data") if fi is not None else None
        p.new_for_asset = changed or not _already_processed(session, fi, asset)
        trial_prev = None
        if item.source_key == "ctgov":
            p.pre = extract(asset, item, ctx, None)
            if p.pre.role == "own" and p.pre.on_indication:
                own_trials.append(item.data)
            row = session.execute(select(Trial).where(
                Trial.asset_id == asset.id, Trial.nct_id == item.external_id)).scalar_one_or_none()
            if row is not None:
                trial_prev = {"status": row.status, "phase": row.phase,
                              "primary_completion": row.primary_completion}
        if p.new_for_asset:
            if item.source_key == "ctgov":
                p.facts = extract(asset, item, ctx, trial_prev if trial_prev is not None else
                                  (prev_data if changed and prev_data else None))
                if not p.facts.on_indication:
                    p.reason = "off_indication"
            else:
                p.facts = extract(asset, item, ctx, None)
            if p.reason is None:
                p.matches = match(hyps, " ".join([item.title or "", item.text or ""]))
                if not p.matches:
                    p.reason = "no_hypothesis_match"
        plans.append(p)
    return plans, own_trials


async def _plan_implications(plans: list[_Plan]) -> None:
    """Phase 2 (network/LLM, no DB access)."""
    for p in plans:
        if p.new_for_asset and p.reason is None:
            p.imp = await implicate(p.item, p.facts, p.matches)
            if p.imp.origin == "llm":
                p.rules_imp = await implicate(p.item, p.facts, p.matches, use_llm=False)
            if not p.imp.moves:
                p.reason = "no_move_proposed"


def _write(session: Session, agent: Agent, asset: Asset, run: AgentRun, plans: list[_Plan],
           own_trials: list[dict]) -> tuple[list[str], int]:
    """Phase 3 (one short write transaction; caller commits)."""
    sources = {s.key: s for s in session.execute(select(Source)).scalars()}
    signal_ids: list[str] = []
    llm_used = 0
    for p in plans:
        item = p.item
        fi, _changed, _prev = _upsert_fetched(session, item)
        if p.pre is not None and p.pre.on_indication:
            _upsert_trial(session, asset, p.pre, fi)
        if not p.new_for_asset:
            continue
        run.items_new += 1
        fi.structured = p.facts.model_dump(exclude={"trial"}) if p.facts else None
        if p.reason:
            _unmatched(session, fi, asset, p.reason)
            continue
        src = sources.get(item.source_key)
        imp = p.imp

        def _check(i: Implication) -> Optional[str]:
            return guardrail.check(source_url=item.url, retrieved_at=_naive(item.retrieved_at),
                                   so_what=i.so_what, fetched_item=fi, source_key=item.source_key,
                                   extra_texts=i.llm_texts())

        reason = _check(imp)
        if reason and imp.origin == "llm" and p.rules_imp is not None:
            reason2 = _check(p.rules_imp)
            if reason2 is None:
                imp, reason = p.rules_imp, None  # LLM text rejected; rules text is sourced
            else:
                reason = f"{reason}; rules fallback: {reason2}"
        if reason:
            run.blocked += 1
            _unmatched(session, fi, asset, reason)
            continue
        if imp.origin == "llm":
            llm_used += 1
        sig = Signal(asset_id=asset.id, agent_id=agent.id, title=(item.title or item.external_id)[:500],
                     so_what=imp.so_what,
                     source_name=src.name if src else registry.SOURCE_NAMES.get(item.source_key, item.source_key),
                     source_url=fi.url, retrieved_at=fi.retrieved_at,
                     published_at=_parse_date(item.published_at), impact=imp.impact,
                     review_status="pending", fetched_item_id=fi.id, so_what_origin=imp.origin)
        session.add(sig)
        session.flush()
        for mv in imp.moves:
            session.add(SignalMove(signal_id=sig.id, hypothesis_id=mv.hypothesis.id, delta=mv.delta,
                                   weight=mv.weight, rationale=mv.rationale))
        run.signals_created += 1
        signal_ids.append(sig.id)
        audit.record(session, ACTOR_PREFIX + agent.key, "signal.created", "signal", sig.id,
                     payload={"title": sig.title, "source_url": sig.source_url,
                              "retrieved_at": sig.retrieved_at.isoformat(),
                              "fetched_item_id": fi.id, "so_what_origin": imp.origin,
                              "llm_disagrees": [m.hypothesis.code for m in imp.moves if m.llm_disagrees],
                              "moves": [{"hypothesis_code": m.hypothesis.code, "delta": m.delta}
                                        for m in imp.moves]},
                     after={"signal_id": sig.id, "review_status": "pending"}, asset_id=asset.id)
    if agent.key == "registry_watch":
        change = _reconcile_phase(session, asset, own_trials)
        if change:
            audit.record(session, ACTOR_PREFIX + agent.key, "asset.phase_reconciled", "asset",
                         asset.id, payload=change, asset_id=asset.id)
    return signal_ids, llm_used


async def _run_one(session: Session, agent: Agent, asset: Asset) -> AgentRun:
    started = utcnow()
    run = AgentRun(agent_id=agent.id, asset_id=asset.id, started_at=started, status="running",
                   items_fetched=0, items_new=0, signals_created=0, blocked=0)
    src_keys = registry.AGENT_SOURCES.get(agent.key, list(agent.source_keys or []))
    src_names = " / ".join(registry.SOURCE_NAMES.get(k, k) for k in src_keys) or agent.name
    signal_ids: list[str] = []
    failed: dict[str, SourceUnavailable] = {}
    llm_used = 0
    try:
        # 1) network fetch - no DB writes open
        rows, failed = await registry.fetch_for(agent.key, asset)
        run.items_fetched = len(rows)
        # 2) reads + extract + match, then end the read transaction
        plans, own_trials = _plan_reads(session, agent, asset, rows)
        session.commit()
        # 3) implication (may call the LLM) - no DB access
        await _plan_implications(plans)
        # 4) single short write transaction
        session.add(run)
        signal_ids, llm_used = _write(session, agent, asset, run, plans, own_trials)
        run.status = "ok"  # at least one source answered
        _update_sources(session, [k for k in src_keys if k not in failed], "ok", None)
        for k, e in failed.items():
            _update_sources(session, [k], "source_unreachable", str(e))
        if failed:
            run.error = "; ".join(str(e) for e in failed.values())
    except SourceUnavailable as e:
        session.rollback()  # nothing partial; record the outage honestly
        session.add(run)
        run.status = "source_unreachable"
        all_failed = getattr(e, "failed_sources", None) or {e.source_key: e}
        run.error = "; ".join(str(x) for x in all_failed.values())
        run.items_fetched = run.items_new = run.signals_created = run.blocked = 0
        signal_ids = []
        for k, x in all_failed.items():
            _update_sources(session, [k] if k in src_keys else src_keys, "source_unreachable", str(x))
    except KeyError as e:
        session.rollback()
        session.add(run)
        run.status = "error"
        run.error = f"agent not runnable: {e}"
    except Exception as e:  # noqa: BLE001
        session.rollback()
        session.add(run)
        run.status = "error"
        run.error = f"{type(e).__name__}: {e}"
        run.items_fetched = run.items_new = run.signals_created = run.blocked = 0
        signal_ids = []
    session.add(run)
    run.finished_at = utcnow()
    run.summary = _summary(agent, asset, run, src_names, failed, llm_used)
    agent.last_run_at = run.finished_at
    session.add(agent)
    session.flush()
    audit.record(session, ACTOR_PREFIX + agent.key, "agent.run", "agent_run", run.id,
                 payload={"agent_key": agent.key, "asset": asset.slug, "status": run.status,
                          "items_fetched": run.items_fetched, "items_new": run.items_new,
                          "signals_created": run.signals_created, "blocked": run.blocked,
                          "llm_used": llm_used, "error": run.error}, asset_id=asset.id)
    session.commit()
    for sid in signal_ids:
        sig = session.get(Signal, sid)
        events.publish("signal.created", {"asset_slug": asset.slug, "entity": "signal", "id": sid,
                                          "title": sig.title if sig else None,
                                          "agent_key": agent.key,
                                          "impact": sig.impact if sig else None}, asset.slug)
    events.publish("agent.run", {"asset_slug": asset.slug, "entity": "agent_run", "id": run.id,
                                 "agent_key": agent.key, "status": run.status,
                                 "summary": run.summary, "signals_created": run.signals_created,
                                 "error": run.error}, asset.slug)
    return run


async def run_agent_async(session: Session, agent_key: str, asset_slug: Optional[str]) -> AgentRun:
    """Run one agent for one asset (or every asset if ``asset_slug`` is None; returns last run)."""
    agent = session.execute(select(Agent).where(Agent.key == agent_key)).scalar_one_or_none()
    if agent is None:
        raise ValueError(f"unknown agent {agent_key!r}")
    if asset_slug:
        asset = session.execute(select(Asset).where(Asset.slug == asset_slug)).scalar_one_or_none()
        if asset is None:
            raise ValueError(f"unknown asset {asset_slug!r}")
        assets = [asset]
    else:
        assets = list(session.execute(select(Asset).order_by(Asset.slug)).scalars())
    last: Optional[AgentRun] = None
    for a in assets:
        last = await _run_one(session, agent, a)
    if last is None:
        raise ValueError("no assets configured")
    return last


def run_agent(session: Session, agent_key: str, asset_slug: Optional[str]) -> AgentRun:
    """Sync wrapper, safe from FastAPI sync endpoints and from threads with a running loop."""
    with _RUN_LOCK:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(run_agent_async(session, agent_key, asset_slug))
        box: dict[str, Any] = {}

        def _target() -> None:
            try:
                box["run"] = asyncio.run(run_agent_async(session, agent_key, asset_slug))
            except BaseException as e:  # noqa: BLE001
                box["err"] = e

        t = threading.Thread(target=_target, name=f"agent-{agent_key}", daemon=True)
        t.start()
        t.join()
        if "err" in box:
            raise box["err"]
        return box["run"]
