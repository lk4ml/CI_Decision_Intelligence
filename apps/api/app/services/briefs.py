"""Brief export: JSON snapshot + printable HTML (pilot substitute for PDF, Addendum A #13)."""
from __future__ import annotations

import html
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Asset, Brief, Pattern, Position, ProposedDecision, Scenario
from app.services import audit, events, views
from app.services.common import asset_cfg, conf_map, hypotheses
from app.sim import montecarlo
from app.sim.models import model_versions


def create(session: Session, asset: Asset, actor: str) -> Brief:
    n = session.execute(select(func.count(Brief.id)).where(Brief.asset_id == asset.id)).scalar_one()
    version = f"v0.{n + 1}"
    from app.services import positions as pos_svc

    vars_ = pos_svc.template_vars(session, asset)
    poss = [views.position_view(session, p, vars_) for p in
            session.execute(select(Position).where(Position.asset_id == asset.id)).scalars()]
    hyps = [views.hypothesis_view(session, h) for h in hypotheses(session, asset)]
    scen = [{"id": s.id, "name": s.name, "levers": s.levers,
             "montecarlo": {k: (s.outputs or {}).get("montecarlo", {}).get(k) for k in ("peak", "rnpv", "negative_share")}}
            for s in session.execute(select(Scenario).where(Scenario.asset_id == asset.id)
                                     .order_by(Scenario.created_at.desc())).scalars()]
    proposals = [views.proposal_view(session, asset, d) for d in session.execute(
        select(ProposedDecision).join(Pattern).where(Pattern.asset_id == asset.id,
                                                     ProposedDecision.cleared_at.is_(None))).scalars()]
    current_mc = montecarlo.run(asset_cfg(asset), {}, conf_map(session, asset))
    alternatives = [{"source": "pattern", "pattern": pr["pattern"]["title"], "label": o["label"], "levers": o["levers"],
                     "results": o["results"], "is_current": o["is_current"]} for pr in proposals for o in pr["options"]]
    alternatives += [{"source": "scenario", "label": s["name"], "levers": s["levers"], "results": s["montecarlo"]}
                     for s in scen]
    evidence = {}
    for h in hyps:
        for e in h["evidence"]:
            evidence.setdefault(e["signal_id"], {**{k: e[k] for k in ("signal_id", "title", "source_name", "source_url",
                                                                         "retrieved_at")}, "moves": []})
            evidence[e["signal_id"]]["moves"].append({"hypothesis_code": h["code"], "delta": e["delta"]})
    snapshot = {
        "asset": views.asset_brief(asset), "version": version, "exported_by": actor,
        "levers": asset.current_levers, "positions": poss, "hypotheses": hyps,
        "evidence": list(evidence.values()), "alternatives": alternatives, "scenarios": scen,
        "current_scenario": {k: current_mc[k] for k in ("peak", "rnpv", "negative_share", "n")},
        "what_would_change_our_mind": [{"code": h["code"], "statement": h["statement"], "position_line": h["position_line"],
                                        "owner_role": h["owner_role"], "change_trigger_text": h["change_trigger_text"],
                                        "confidence": h["confidence"], "threshold": h["threshold"]} for h in hyps],
        "model_versions": model_versions(), "engine": "stand_in",
        "note": "Model outputs are stand-in, illustrative values — not Astellas forecasts.",
    }
    b = Brief(asset_id=asset.id, version=version, snapshot=snapshot, exported_by=actor)
    session.add(b)
    session.flush()
    snapshot["audit_head_hash"] = audit.record(session, actor, "brief.exported", "brief", b.id, {"version": version},
                                               asset_id=asset.id).hash
    b.snapshot = dict(snapshot)
    events.publish_on_commit(session, "brief.exported", {"entity": "brief", "id": b.id, "version": version}, asset.slug)
    return b


def _e(x) -> str:
    return html.escape("" if x is None else str(x))


def render_html(b: Brief) -> str:
    s = b.snapshot or {}
    a = s.get("asset", {})
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>{_e(a.get('code'))} TPP {_e(b.version)}</title>",
           "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:32px auto;color:#111;line-height:1.45}"
           "h1{margin-bottom:0}table{border-collapse:collapse;width:100%;margin:8px 0 20px}td,th{border-bottom:1px solid #ddd;"
           "padding:6px;text-align:left;vertical-align:top;font-size:13px}.m{color:#666;font-size:12px}"
           "@media print{a{color:#111}}</style></head><body>",
           f"<h1>{_e(a.get('name'))} — {_e(a.get('indication'))}</h1>",
           f"<p class='m'>{_e(a.get('code'))} · {_e(a.get('biomarker'))} · {_e(a.get('phase'))} ({_e(a.get('phase_source'))}-provided)"
           f" · TPP {_e(b.version)} · exported by {_e(b.exported_by)} · {_e(views.iso(b.created_at))}</p>",
           f"<p class='m'>{_e(s.get('note'))}</p>",
           "<h2>Positions</h2><table><tr><th>Line</th><th>Statement</th><th>Owner</th><th>Status</th><th>Confidence</th></tr>"]
    for p in s.get("positions", []):
        hy = ", ".join(f"{h['code']} {h['confidence']:.0f}%" for h in p.get("hypotheses", []))
        out.append(f"<tr><td>{_e(p['line'])}</td><td>{_e(p['statement'])}<div class='m'>{_e(p.get('why'))}"
                   f"<br>Rests on: {_e(hy)}</div></td><td>{_e(p['owner_role'])}</td><td>{_e(p['status'])} v{_e(p['version'])}</td>"
                   f"<td>{_e(p.get('confidence'))}</td></tr>")
    out.append("</table><h2>Evidence</h2>")
    ev = s.get("evidence", [])
    if not ev:
        out.append("<p class='m'>No signals applied yet.</p>")
    else:
        out.append("<table><tr><th>Signal</th><th>Moves</th><th>Citation</th></tr>")
        for e in ev:
            mv = ", ".join(f"{m['hypothesis_code']} {m['delta']:+g}" for m in e["moves"])
            out.append(f"<tr><td>{_e(e['title'])}</td><td>{_e(mv)}</td><td>{_e(e.get('source_name'))}<br>"
                       f"<a href='{_e(e['source_url'])}'>{_e(e['source_url'])}</a><br><span class='m'>retrieved "
                       f"{_e(e['retrieved_at'])}</span></td></tr>")
        out.append("</table>")
    cs = s.get("current_scenario") or {}
    pk, rn = cs.get("peak") or {}, cs.get("rnpv") or {}
    out.append(f"<h2>Scenario range (stand-in)</h2><p>Peak P10/P50/P90: ${_e(pk.get('p10'))}B / ${_e(pk.get('p50'))}B / "
               f"${_e(pk.get('p90'))}B · rNPV P50 ${_e(rn.get('p50'))}B · {_e(cs.get('n'))} draws</p>")
    out.append("<h2>Alternatives considered</h2>")
    alts = s.get("alternatives", [])
    if not alts:
        out.append("<p class='m'>No fired patterns or saved scenarios.</p>")
    else:
        out.append("<table><tr><th>From</th><th>Option</th><th>Results</th></tr>")
        for o in alts:
            r = o.get("results") or {}
            out.append(f"<tr><td>{_e(o.get('pattern') or o['source'])}</td><td>{_e(o['label'])}"
                       f"{' (current)' if o.get('is_current') else ''}</td><td class='m'>{_e(r)}</td></tr>")
        out.append("</table>")
    out.append("<h2>What would change our mind</h2><table><tr><th>Hypothesis</th><th>Trigger</th><th>Confidence / threshold</th></tr>")
    for w in s.get("what_would_change_our_mind", []):
        out.append(f"<tr><td><b>{_e(w['code'])}</b> {_e(w['statement'])}<div class='m'>{_e(w['position_line'])} · "
                   f"{_e(w['owner_role'])}</div></td><td>{_e(w['change_trigger_text'])}</td>"
                   f"<td>{w['confidence']:.0f}% / {w['threshold']:.0f}%</td></tr>")
    out.append(f"</table><p class='m'>Audit head {_e(s.get('audit_head_hash'))} · models {_e(s.get('model_versions'))}</p>")
    out.append("</body></html>")
    return "".join(out)
