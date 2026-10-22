from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Scenario
from app.routers.deps import Who, get_session, who
from app.schemas import ScenarioCreate
from app.services import audit, events, views
from app.services.common import asset_cfg, conf_map, get_asset, require_writer
from app.sim import montecarlo
from app.sim.models import model_versions, run_all

router = APIRouter(tags=["scenarios"])


def scenario_view(s: Scenario) -> dict:
    return {"id": s.id, "name": s.name, "levers": s.levers, "hypothesis_snapshot": s.hypothesis_snapshot,
            "outputs": s.outputs, "model_versions": s.model_versions, "created_at": views.iso(s.created_at)}


@router.post("/assets/{slug}/scenarios")
def create_scenario(slug: str, body: ScenarioCreate, db: Session = Depends(get_session), w: Who = Depends(who)):
    a = get_asset(db, slug)
    require_writer(w.role)
    cfg, conf = asset_cfg(a), conf_map(db, a)
    run = run_all(cfg, body.levers, conf)
    mc = montecarlo.run(cfg, body.levers, conf, n=body.n)
    s = Scenario(asset_id=a.id, name=body.name, levers=run["levers"],
                 hypothesis_snapshot={k: round(v * 100, 2) for k, v in conf.items()},
                 outputs={"run": {k: {"kpis": run[k]["kpis"]} for k in ("demand", "ptrs", "access", "feasibility", "business")},
                          "montecarlo": {k: mc[k] for k in ("n", "peak", "rnpv", "ptrs", "readout", "negative_share")}},
                 model_versions=model_versions())
    db.add(s)
    db.flush()
    audit.record(db, w.actor, "scenario.saved", "scenario", s.id, {"name": s.name, "levers": s.levers}, asset_id=a.id)
    events.publish_on_commit(db, "audit", {"entity": "scenario", "id": s.id, "action": "scenario.saved"}, a.slug)
    db.commit()
    return scenario_view(s)


@router.get("/assets/{slug}/scenarios")
def list_scenarios(slug: str, db: Session = Depends(get_session)):
    a = get_asset(db, slug)
    return [scenario_view(s) for s in db.execute(select(Scenario).where(Scenario.asset_id == a.id)
                                                 .order_by(Scenario.created_at.desc())).scalars()]
