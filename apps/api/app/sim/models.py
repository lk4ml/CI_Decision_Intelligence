"""Five stand-in models behind a common interface (PRD §8).

Every output: {name, version, engine:"stand_in", kpis:[{label,value,unit,basis}], series, reading, assumptions}.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np

from app.sim import core
from app.sim.params import MODEL_VERSION

STAND_IN_NOTE = "Stand-in model with illustrative parameters — not an Astellas forecast."


def _pct(x: float) -> int:
    return int(round(x * 100))


def _assumptions(cfg: dict, names: list[str], drivers: dict, roles: list[str]) -> list[dict]:
    raw = (cfg.get("model_params") or {}).get("inputs") or {}
    b = (cfg.get("model_params") or {}).get("bindings") or {}
    out = []
    for n in names:
        if n in raw:
            v = raw[n]
            out.append({"name": n, "value": v.get("value"), "unit": v.get("unit", ""),
                        "basis": v.get("basis", "stand_in_assumption"), "source_url": v.get("source_url")})
    for r in roles:
        out.append({"name": f"driver:{r}", "value": round(drivers.get(r, 0.5), 3), "unit": "confidence fraction",
                    "basis": "hypothesis_confidence", "hypothesis_code": b.get(r)})
    return out


def _kpi(label, value, unit, basis):
    return {"label": label, "value": value, "unit": unit, "basis": basis}


@dataclass
class Model:
    name: str
    key: str
    reads: str
    returns: str
    version: str = MODEL_VERSION
    engine: str = "stand_in"
    inputs: tuple = ()
    roles: tuple = ()
    fmt: Optional[Callable[[dict, dict, dict], dict]] = None

    def run(self, cfg: dict, levers: dict, conf: dict, rng: Optional[np.random.Generator] = None,
            raw: Optional[dict] = None) -> dict:
        r = raw or core.chain(cfg, levers, conf, rng)
        basis = core.basis_of(cfg, list(self.inputs))
        out = self.fmt(cfg, r, {"basis": basis})
        out.update({
            "name": self.name, "key": self.key, "version": self.version, "engine": self.engine,
            "assumptions": _assumptions(cfg, list(self.inputs), r["drivers"], list(self.roles)),
            "note": STAND_IN_NOTE,
        })
        out["reading"] = out["reading"] + " " + STAND_IN_NOTE
        return out


def _fmt_demand(cfg, r, m):
    d = r["demand"]; L = r["levers"]; b = m["basis"]
    pop_lever = f"cutoff ≥{L['cutoff']}%" if "cutoff" in L else f"{L.get('line')} {L.get('regimen', '')}".strip()
    return {
        "kpis": [
            _kpi("Patients on drug at peak", round(d["on_drug"]), "patients/yr", b),
            _kpi("Peak share of treated", round(d["share"], 3), "fraction", b),
            _kpi("Testing rate assumed", round(d["testing"], 3), "fraction", b),
        ],
        "series": {"funnel": [{"label": k, "value": round(v)} for k, v in d["funnel"]], "pools": d["pools"]},
        "reading": (f"At {pop_lever}, about {round(d['on_drug']):,} patients a year are on drug at peak share "
                    f"({_pct(d['share'])}%). Testing uptake ({_pct(d['testing'])}%) is read from the testing hypothesis "
                    f"and competitor-first confidence ({_pct(r['drivers']['comp_first'])}%) erodes share."),
    }


def _fmt_ptrs(cfg, r, m):
    t = r["ptrs"]; b = m["basis"]
    return {
        "kpis": [_kpi("Probability of technical & regulatory success", round(t["ptrs"], 3), "probability", b),
                 _kpi("Sample size", r["feas"]["n"], "patients", b)],
        "series": {"buildup": [{"label": k, "value": round(v, 3)} for k, v in t["items"]]},
        "reading": (f"PTRS {_pct(t['ptrs'])}% built from a stand-in base rate plus design increments. "
                    + ("The dose-optimization cohort is included. " if r["levers"].get("dose") else
                       f"No dose cohort while dose-expectation confidence is {_pct(r['drivers']['dose'])}%. ")
                    + f"Comparator-shift confidence {_pct(r['drivers']['soc_shift'])}% prices the control-arm choice."),
    }


def _fmt_access(cfg, r, m):
    a = r["access"]; b = m["basis"]
    return {
        "kpis": [_kpi("US net price, monthly", round(a["net"]), "USD/month", b),
                 _kpi("Premium vs reference", round(a["prem"], 3), "fraction", b),
                 _kpi("EU reimbursement", a["hta_months"], "months", b),
                 _kpi("Medicare negotiation year", a["negotiation_year"], "year", b)],
        "series": {"markets": [
            {"market": "United States", "net_month": round(a["net"]), "gtn": round(a["gtn"], 3)},
            {"market": "EU (JCA then national)", "net_month": round(a["eu"]), "hta_months": a["hta_months"],
             "germany": a["gba"], "england": a["nice"]},
            {"market": "Japan", "net_month": round(a["jp"])},
        ]},
        "reading": (f"{_pct(a['prem_ok'])}% of the asked premium is defensible given payer-premium confidence "
                    f"{_pct(r['drivers']['prem'])}% and a {r['levers'].get('ep', 'pfs').upper()} primary endpoint."),
    }


def _fmt_feas(cfg, r, m):
    f = r["feas"]; b = m["basis"]
    total_sites = sum(c[1] for c in f["countries"]) or 1
    return {
        "kpis": [_kpi("Enrollment", round(f["enroll"]), "months", b),
                 _kpi("Primary readout", f["readout"], "months from FPI", b),
                 _kpi("Primary readout (quarter)", f["readout_label"], "quarter", b),
                 _kpi("Screen failure", round(f["screen_fail"], 3), "fraction", b),
                 _kpi("Program cost", f["cost"], "USD M", b)],
        "series": {"countries": [
            {"country": c[0], "sites": c[1], "competing_index": c[2],
             "pts_site_month": round(f["rate"] / total_sites * f["drag"][i], 3), "drag": round(1 - f["drag"][i], 3)}
            for i, c in enumerate(f["countries"])]},
        "reading": (f"Readout ~{f['readout']} months from first patient ({f['readout_label']}). Site-competition "
                    f"confidence {_pct(r['drivers']['site'])}% applies a {round(35 * r['drivers']['site'])}% drag to Asia-Pacific sites."),
    }


def _fmt_business(cfg, r, m):
    bz = r["business"]; b = m["basis"]
    return {
        "kpis": [_kpi("Peak sales (deterministic)", round(bz["peak"], 3), "USD B", b),
                 _kpi("Risk-adjusted NPV (deterministic)", round(bz["rnpv"], 3), "USD B", b),
                 _kpi("PTRS", round(r["ptrs"]["ptrs"], 3), "probability", b)],
        "series": {},
        "reading": (f"Peak ~${bz['peak']:.2f}B and rNPV ~${bz['rnpv']:.2f}B on today's confidences; run Monte Carlo "
                    f"for the P10/P50/P90 spread."),
    }


MODELS: list[Model] = [
    Model("Population & demand", "demand", "Population lever, footprint · testing, competitor-first, differentiation",
          "Funnel, patients on drug, share, patient pools",
          inputs=("incident", "advanced_frac", "her2neg", "testing_floor", "testing_span", "biomarker_prev", "prev_by_cutoff",
                  "line_reach", "treated_1l", "share_base", "share_by_cutoff", "regimen_share"),
          roles=("testing", "comp_first", "diff", "early_line", "combo"), fmt=_fmt_demand),
    Model("Probability of success", "ptrs", "Population lever, endpoint, comparator, dose · dose, comparator-shift, competitor-first, OS-requirement",
          "PTRS with itemised increments",
          inputs=("ptrs_base", "ptrs_line", "cutoff_ptrs"), roles=("dose", "soc_shift", "comp_first", "os_req", "diff", "combo"),
          fmt=_fmt_ptrs),
    Model("Price & access", "access", "Population lever, endpoint · differentiation, payer premium",
          "Net price by market, GTN, HTA timing, negotiation year",
          inputs=("ref_price_month", "premium_base", "premium_by_cutoff", "gtn", "gtn_by_cutoff", "eu_ratio", "jp_ratio",
                  "ira_years", "launch_year"), roles=("diff", "prem"), fmt=_fmt_access),
    Model("Feasibility", "feasibility", "Population lever, footprint, dose, endpoint · site competition",
          "Enrollment months, readout, screen failure, cost, country table",
          inputs=("sample_size", "sample_by_cutoff", "rate_per_site", "rate_by_cutoff", "screen_fail", "screen_fail_by_cutoff",
                  "readout_add", "activation_months", "cost_per_patient_k", "fpi"), roles=("site",), fmt=_fmt_feas),
    Model("Business case", "business", "All of the above", "Peak, rNPV, P10/P50/P90, share of negative scenarios",
          inputs=("months_on_therapy", "region_split", "compliance", "npv_multiple", "effective_years"), roles=(),
          fmt=_fmt_business),
]
BY_KEY = {m.key: m for m in MODELS}


def registry() -> list[dict]:
    return [{"name": m.name, "key": m.key, "reads": m.reads, "returns": m.returns, "engine": m.engine,
             "version": m.version} for m in MODELS]


def model_versions() -> dict:
    return {m.key: m.version for m in MODELS}


def run_all(cfg: dict, levers: dict, conf: dict) -> dict:
    """Deterministic (rng=None) run of all five models for one lever set."""
    raw = core.chain(cfg, levers, conf, None)
    out = {m.key: m.run(cfg, levers, conf, raw=raw) for m in MODELS}
    out["levers"] = raw["levers"]
    out["model_versions"] = model_versions()
    return out


def option_results(cfg: dict, levers: dict, conf: dict) -> dict:
    """Compact results used by proposal option tables — same deterministic chain as /models/run."""
    r = core.chain(cfg, levers, conf, None)
    return {"patients": round(r["demand"]["on_drug"]), "ptrs": round(r["ptrs"]["ptrs"], 3),
            "peak": round(r["business"]["peak"], 3), "readout": r["feas"]["readout"],
            "readout_label": r["feas"]["readout_label"], "us_net": round(r["access"]["net"]),
            "rnpv": round(r["business"]["rnpv"], 3), "basis": "stand_in_assumption"}
