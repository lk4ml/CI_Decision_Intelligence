"""Serializers producing the response shapes in docs/ARCHITECTURE.md."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (Agent, AgentRun, Asset, ConfidenceEvent, Hypothesis, HypothesisAgent, Pattern, Position,
                        ProposedDecision, Signal, SignalMove, Trial, utcnow)
from app.services import positions as pos_svc
from app.services.common import asset_cfg, conf_map, hypotheses, live_events
from app.sim import core
from app.sim.models import option_results

FETCH_AGENTS = ["registry_watch", "literature", "research_graph", "regulatory", "astellas_ir"]


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() + ("Z" if dt and dt.tzinfo is None else "") if dt else None


def asset_brief(a: Asset) -> dict:
    return {"id": a.id, "slug": a.slug, "code": a.code, "name": a.name, "indication": a.indication,
            "biomarker": a.biomarker, "phase": a.phase, "phase_source": a.phase_source}


def asset_full(session: Session, a: Asset) -> dict:
    hs = hypotheses(session, a)
    pending = session.execute(select(func.count(Signal.id)).where(Signal.asset_id == a.id,
                                                                  Signal.review_status == "pending")).scalar_one()
    proposals = session.execute(select(func.count(ProposedDecision.id)).join(Pattern).where(
        Pattern.asset_id == a.id, ProposedDecision.cleared_at.is_(None))).scalar_one()
    locked = session.execute(select(func.count(Position.id)).where(Position.asset_id == a.id,
                                                                   Position.status == "locked")).scalar_one()
    return {**asset_brief(a), "mechanism": a.mechanism, "decision_type": a.decision_type,
            "governance_forum": a.governance_forum, "governance_date": a.governance_date, "descriptor": a.descriptor,
            "watch_terms": a.watch_terms, "registry_phase": a.registry_phase, "registry_nct_ids": a.registry_nct_ids or [],
            "registry_checked_at": iso(a.registry_checked_at), "phase_discrepancy": a.phase_discrepancy,
            "current_levers": a.current_levers, "created_at": iso(a.created_at),
            "counts": {"hypotheses": len(hs), "pending_signals": pending, "proposals": proposals,
                       "locked_positions": locked}}


def run_view(r: Optional[AgentRun], agent_key: Optional[str] = None) -> Optional[dict]:
    if r is None:
        return None
    return {"id": r.id, "agent_key": agent_key, "agent_id": r.agent_id, "asset_id": r.asset_id, "status": r.status,
            "started_at": iso(r.started_at), "finished_at": iso(r.finished_at), "items_fetched": r.items_fetched,
            "items_new": r.items_new, "signals_created": r.signals_created, "blocked": r.blocked, "error": r.error,
            "summary": r.summary}


def latest_run(session: Session, agent: Agent, asset: Optional[Asset] = None) -> Optional[AgentRun]:
    q = select(AgentRun).where(AgentRun.agent_id == agent.id)
    if asset is not None:
        q = q.where((AgentRun.asset_id == asset.id) | (AgentRun.asset_id.is_(None)))
    return session.execute(q.order_by(AgentRun.started_at.desc()).limit(1)).scalar_one_or_none()


def coverage(session: Session, asset: Asset, agent_keys: list[str]) -> dict:
    runs = []
    for k in agent_keys:
        ag = session.execute(select(Agent).where(Agent.key == k)).scalar_one_or_none()
        if ag is None:
            continue
        r = latest_run(session, ag, asset)
        if r is not None:
            runs.append((k, r))
    if not runs:
        return {"status": "never_run", "last_run": None}
    status = "ok" if all(r.status in ("ok", "running") for _, r in runs) else "source_unreachable"
    k, r = max(runs, key=lambda kr: kr[1].started_at)
    bad = [(k2, r2) for k2, r2 in runs if r2.status not in ("ok", "running")]
    if bad:
        k, r = max(bad, key=lambda kr: kr[1].started_at)
    return {"status": status,
            "last_run": {"agent_key": k, "status": r.status, "finished_at": iso(r.finished_at), "error": r.error}}


def trial_view(t: Trial) -> dict:
    return {c: (iso(getattr(t, c)) if isinstance(getattr(t, c), datetime) else getattr(t, c)) for c in
            ["id", "nct_id", "title", "sponsor", "phase", "status", "start_date", "primary_completion", "enrollment",
             "conditions", "interventions", "endpoints", "role", "source_url", "retrieved_at"]}


def agent_brief(a: Agent) -> dict:
    return {"id": a.id, "key": a.key, "name": a.name, "cadence_minutes": a.cadence_minutes, "status": a.status}


def agent_view(session: Session, a: Agent, detail: bool = False) -> dict:
    r = latest_run(session, a)
    out = {**agent_brief(a), "category": a.category, "reads": a.reads, "description": a.description,
           "source_keys": a.source_keys or [], "last_run_at": iso(a.last_run_at), "last_run": run_view(r, a.key),
           "summary": (r.summary if r and r.summary else ("Not yet run" if r is None else f"Last run: {r.status}"))}
    links = session.execute(select(HypothesisAgent.hypothesis_id).where(HypothesisAgent.agent_id == a.id)).scalars().all()
    out["hypothesis_ids"] = list(links)
    if detail:
        out["hypotheses"] = [{"id": h.id, "code": h.code, "asset_id": h.asset_id, "statement": h.statement}
                             for h in (session.get(Hypothesis, i) for i in links) if h]
        out["governance_notes"] = (
            "Supervised: every proposed move requires owner review (PRD §7.6)." if a.status == "supervised" else
            "Proposals require review; promotion to auto-apply routine moves needs 8-week precision ≥80% (PRD §7.6).")
    return out


def hypothesis_view(session: Session, h: Hypothesis) -> dict:
    evs = live_events(session, [h.id])
    week_ago = utcnow() - timedelta(days=7)
    all_evs = session.execute(select(ConfidenceEvent).where(ConfidenceEvent.hypothesis_id == h.id)).scalars().all()
    week_delta = sum(e.delta_applied for e in all_evs if e.created_at >= week_ago)
    agents = [agent_brief(a) for a in session.execute(
        select(Agent).join(HypothesisAgent, HypothesisAgent.agent_id == Agent.id).where(
            HypothesisAgent.hypothesis_id == h.id)).scalars()]
    evidence = []
    for e in evs:
        if not e.signal_id:
            continue
        s = session.get(Signal, e.signal_id)
        evidence.append({"signal_id": s.id, "title": s.title, "delta": e.delta_applied, "source_name": s.source_name,
                         "source_url": s.source_url, "retrieved_at": iso(s.retrieved_at), "applied_at": iso(e.created_at),
                         "actor": e.actor, "reason": e.reason})
    return {"id": h.id, "code": h.code, "statement": h.statement, "category": h.category,
            "position_line": h.position_line, "owner_role": h.owner_role, "confidence": h.confidence,
            "confidence_start": h.confidence_start, "threshold": h.threshold, "crossed": h.crossed,
            "crossed_at": iso(h.crossed_at), "change_trigger_text": h.change_trigger_text, "keywords": h.keywords or [],
            "for_count": sum(1 for e in evs if e.delta_applied > 0),
            "against_count": sum(1 for e in evs if e.delta_applied < 0),
            "week_delta": week_delta, "agents": agents, "evidence": evidence}


def signal_view(session: Session, s: Signal) -> dict:
    moves = []
    for m in s.moves:
        h = session.get(Hypothesis, m.hypothesis_id)
        moves.append({"hypothesis_id": h.id, "hypothesis_code": h.code, "delta": m.delta, "weight": m.weight,
                      "rationale": m.rationale, "owner_role": h.owner_role})
    ag = s.agent
    return {"id": s.id, "title": s.title, "so_what": s.so_what, "so_what_origin": s.so_what_origin,
            "impact": s.impact, "agent": {"key": ag.key, "name": ag.name, "reads": ag.reads} if ag else None,
            "source_name": s.source_name, "source_url": s.source_url, "retrieved_at": iso(s.retrieved_at),
            "published_at": iso(s.published_at), "review_status": s.review_status, "reviewer": s.reviewer,
            "fetched_item_id": s.fetched_item_id, "created_at": iso(s.created_at), "moves": moves}


def position_view(session: Session, p: Position, vars_: Optional[dict] = None) -> dict:
    hs = pos_svc.position_hypotheses(session, p)
    statement = p.statement if p.status == "locked" else pos_svc.render(session, p, vars_)
    return {"id": p.id, "line": p.line, "statement": statement, "statement_template": p.statement_template,
            "why": p.why, "owner_role": p.owner_role, "contributor_roles": p.contributor_roles or [], "status": p.status,
            "version": p.version, "confidence": pos_svc.confidence(session, p),
            "hypotheses": [{"id": h.id, "code": h.code, "confidence": h.confidence, "threshold": h.threshold,
                            "crossed": h.crossed, "owner_role": h.owner_role} for h in hs]}


def pattern_view(p: Pattern) -> dict:
    return {"id": p.id, "key": p.key, "title": p.title, "position_line": p.position_line, "trigger": p.trigger,
            "trigger_text": p.trigger_text, "rationale": p.rationale, "options": p.options, "is_fired": p.is_fired}


def proposal_view(session: Session, asset: Asset, d: ProposedDecision) -> dict:
    p = d.pattern
    cfg = asset_cfg(asset)
    conf = conf_map(session, asset)
    current = core.full_levers(cfg, {})
    hs = [h for h in hypotheses(session, asset) if h.code in (d.hypothesis_codes or [])]
    sigs = [session.get(Signal, i) for i in (d.signal_ids or [])]
    hyp_ids = {h.id: h.code for h in hs}
    sig_out = []
    for s in sigs:
        if s is None:
            continue
        sv = signal_view(session, s)
        sv["moves"] = [m for m in sv["moves"] if m["hypothesis_id"] in hyp_ids]
        sig_out.append(sv)
    options = []
    for o in p.options or []:
        lv = {**current, o["lever"]: o["value"]}
        lv = core.full_levers(cfg, lv)
        options.append({"label": o["label"], "lever": o["lever"], "value": o["value"], "levers": lv,
                        "is_current": str(current.get(o["lever"])) == str(lv.get(o["lever"])),
                        "results": option_results(cfg, lv, conf)})
    return {"id": d.id, "fired_at": iso(d.fired_at), "framing": d.framing, "total_movement": d.total_movement,
            "pattern": {"id": p.id, "key": p.key, "title": p.title, "position_line": p.position_line,
                        "trigger": p.trigger, "trigger_text": p.trigger_text, "rationale": p.rationale},
            "hypotheses": [{"id": h.id, "code": h.code, "statement": h.statement, "confidence": h.confidence,
                            "confidence_start": h.confidence_start, "threshold": h.threshold, "crossed": h.crossed,
                            "owner_role": h.owner_role, "change_trigger_text": h.change_trigger_text} for h in hs],
            "signals": sig_out, "options": options}
