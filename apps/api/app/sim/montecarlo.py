"""Monte Carlo over the stand-in chain (PRD §8): n draws (default 500), hypothesis drivers drawn from
Beta distributions centred on today's confidences, plus the mockup's gaussian parameter noise.
Seeded RNG → deterministic; cached by hash of (asset, levers, confidences, model_versions, n, seed)."""
from __future__ import annotations

import hashlib
import json
from typing import Optional

import numpy as np

from app.sim import core
from app.sim.models import model_versions
from app.sim.params import BETA_CONCENTRATION, MC_N_DEFAULT, MC_SEED

_CACHE: dict[str, dict] = {}
BINS = 28


def cache_key(cfg: dict, levers: dict, conf: dict, n: int, seed: int) -> str:
    body = {"asset": cfg.get("slug"), "params": cfg.get("model_params"), "levers": core.full_levers(cfg, levers),
            "conf": {k: round(v, 4) for k, v in sorted(conf.items())}, "versions": model_versions(), "n": n, "seed": seed}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def _q(a: np.ndarray, x: float) -> float:
    s = np.sort(a)
    return float(s[int(np.floor((len(s) - 1) * x))])


def _range(a: np.ndarray, nd: int = 3) -> dict:
    return {"p10": round(_q(a, 0.1), nd), "p50": round(_q(a, 0.5), nd), "p90": round(_q(a, 0.9), nd)}


def run(cfg: dict, levers: dict, conf: dict, n: int = MC_N_DEFAULT, seed: int = MC_SEED) -> dict:
    n = max(10, min(int(n or MC_N_DEFAULT), 5000))
    key = cache_key(cfg, levers, conf, n, seed)
    if key in _CACHE:
        return {**_CACHE[key], "cached": True}
    rng = np.random.default_rng(seed)
    base = core.drivers(cfg, conf)
    pk, rn, pt, rd = [], [], [], []
    for _ in range(n):
        p = {}
        for role, m in base.items():
            m = min(0.98, max(0.02, m))
            p[role] = float(rng.beta(m * BETA_CONCENTRATION, (1 - m) * BETA_CONCENTRATION))
        r = core.chain(cfg, levers, conf, rng, p_override=p)
        pk.append(r["business"]["peak"]); rn.append(r["business"]["rnpv"])
        pt.append(r["ptrs"]["ptrs"]); rd.append(r["feas"]["readout"])
    pk_a, rn_a, pt_a, rd_a = map(np.array, (pk, rn, pt, rd))
    lo, hi = float(pk_a.min()), float(pk_a.max())
    width = (hi - lo) / BINS if hi > lo else 1.0
    counts = np.zeros(BINS, dtype=int)
    for v in pk_a:
        counts[min(BINS - 1, int((v - lo) / (width + 1e-12)))] += 1
    hist = [{"x0": round(lo + i * width, 4), "x1": round(lo + (i + 1) * width, 4), "count": int(c)} for i, c in enumerate(counts)]
    out = {
        "n": n, "seed": seed,
        "peak": _range(pk_a), "rnpv": _range(rn_a), "ptrs": _range(pt_a), "readout": _range(rd_a, 1),
        "histogram": hist, "negative_share": round(float((rn_a < 0).mean()), 4),
        "unit": {"peak": "USD B", "rnpv": "USD B", "ptrs": "probability", "readout": "months"},
        "basis": "stand_in_assumption", "engine": "stand_in", "model_versions": model_versions(),
        "levers": core.full_levers(cfg, levers), "cache_key": key,
    }
    if len(_CACHE) > 256:
        _CACHE.clear()
    _CACHE[key] = out
    return {**out, "cached": False}
