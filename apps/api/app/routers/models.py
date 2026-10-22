from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.routers.deps import get_session
from app.schemas import ModelRunBody, MonteCarloBody
from app.services.common import asset_cfg, conf_map, get_asset
from app.sim import core, montecarlo
from app.sim.models import registry, run_all

router = APIRouter(tags=["models"])


def _conf(db, a, overrides):
    c = conf_map(db, a)
    for k, v in (overrides or {}).items():
        c[k] = float(v) / 100.0
    return c


@router.post("/models/run")
def models_run(body: ModelRunBody, db: Session = Depends(get_session)):
    a = get_asset(db, body.asset)
    return run_all(asset_cfg(a), body.levers, _conf(db, a, body.hypotheses))


@router.post("/models/montecarlo")
def models_mc(body: MonteCarloBody, db: Session = Depends(get_session)):
    a = get_asset(db, body.asset)
    return montecarlo.run(asset_cfg(a), body.levers, _conf(db, a, body.hypotheses), n=body.n)


@router.post("/models/evaluate")
def models_evaluate(body: ModelRunBody, db: Session = Depends(get_session)):
    from app.sim.models import option_results

    a = get_asset(db, body.asset)
    return option_results(asset_cfg(a), body.levers, _conf(db, a, body.hypotheses))


@router.post("/models/demand/pools")
def demand_pools(body: ModelRunBody, db: Session = Depends(get_session)):
    a = get_asset(db, body.asset)
    r = core.chain(asset_cfg(a), body.levers, _conf(db, a, body.hypotheses), None)
    return {"pools": r["demand"]["pools"], "basis": "stand_in_assumption"}


@router.get("/models/registry")
def models_registry():
    return registry()
