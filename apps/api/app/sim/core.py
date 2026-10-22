"""Stand-in model chain (ported from docs/mockup.html `model()`, generalised per asset).

Pure functions of (asset model config, levers, hypothesis confidences[, rng]).
All numeric inputs come from `Asset.model_params.inputs` (seeded from app/sim/params.py).
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np

from app.sim import params as P

ROLE_NAMES = ["testing", "broad", "early_line", "dose", "combo", "diff", "soc_shift", "comp_first",
              "os_req", "prem", "site"]


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def inputs_of(cfg: dict) -> dict:
    """Flatten {name:{value,...}} → {name:value}."""
    raw = (cfg.get("model_params") or {}).get("inputs") or {}
    return {k: (v.get("value") if isinstance(v, dict) and "value" in v else v) for k, v in raw.items()}


def basis_of(cfg: dict, names: list[str]) -> str:
    raw = (cfg.get("model_params") or {}).get("inputs") or {}
    vals = [raw.get(n) for n in names if n in raw]
    if vals and all(isinstance(v, dict) and v.get("basis") == "sourced" for v in vals):
        return "sourced"
    return "stand_in_assumption"


def drivers(cfg: dict, conf: dict[str, float]) -> dict[str, float]:
    """Map role → confidence fraction (0–1) via model_params.bindings; unbound roles = 0.5."""
    b = (cfg.get("model_params") or {}).get("bindings") or {}
    out = {}
    for r in ROLE_NAMES:
        code = b.get(r)
        out[r] = float(conf.get(code, 0.5)) if code else 0.5
    return out


def full_levers(cfg: dict, levers: Optional[dict]) -> dict:
    out = {}
    for item in cfg.get("lever_schema") or []:
        out[item["name"]] = item.get("default")
    out.update(cfg.get("current_levers") or {})
    out.update(levers or {})
    # coerce toggles
    for item in cfg.get("lever_schema") or []:
        if item.get("type") == "toggle":
            v = out.get(item["name"])
            if isinstance(v, str):
                out[item["name"]] = v.lower() in ("1", "true", "yes", "on")
            else:
                out[item["name"]] = bool(v)
        elif out.get(item["name"]) is not None:
            out[item["name"]] = str(out[item["name"]])
    return out


def ymo(fpi: tuple, months: float) -> str:
    y, m = int(fpi[0]), int(fpi[1])
    tot = (m - 1) + int(round(months))
    yy, mm = y + tot // 12, tot % 12
    return f"Q{mm // 3 + 1} {yy}"


def chain(cfg: dict, levers: dict, conf: dict[str, float], rng: Optional[np.random.Generator] = None,
          p_override: Optional[dict] = None) -> dict:
    """Run demand → ptrs → access → feasibility → business. Returns raw numbers (no formatting)."""
    I = inputs_of(cfg)
    L = full_levers(cfg, levers)
    p = p_override or drivers(cfg, conf)
    g = (lambda k: float(rng.normal()) * k) if rng is not None else (lambda k: 0.0)
    kind = I.get("kind", "line")
    active = set(I.get("active_comparators") or [])
    comp_active = L.get("comp") in active
    geo = L.get("geo", "global")
    ep = L.get("ep", "pfs")
    dose = bool(L.get("dose"))
    labels = I.get("funnel_labels") or ["Incident", "Advanced", "Tested", "Biomarker+"]

    # ---------------- demand ----------------
    testing = clamp(I["testing_floor"] + I["testing_span"] * p["testing"] + (0.03 if geo == "west" else 0) + g(0.05), 0.3, 0.95)
    incident = float(I["incident"])
    advanced = incident * I["advanced_frac"]
    pools = []
    if kind == "cutoff":
        cutoff = str(L.get("cutoff", "75"))
        her2 = advanced * I.get("her2neg", 1.0)
        tested = her2 * testing
        prev = I["prev_by_cutoff"][cutoff]
        positive = tested * max(0.2, prev + g(0.03))
        treated = positive * I["treated_1l"]
        share = (I["share_by_cutoff"][cutoff] + (0.05 if comp_active else -0.04) - p["comp_first"] * 0.08
                 + p["diff"] * 0.06 * (1 if cutoff == "1" else 0.3)
                 + (0.03 * p["combo"] if L.get("combo") else 0) + g(0.04))
        months = I["months_on_therapy"]["1L"]
        funnel = [(labels[0], incident), (labels[1], advanced), (labels[2], her2), (labels[3], tested),
                  (f"Positive at cutoff ≥{cutoff}%", positive), ("Treated in 1L", treated)]
        for c in sorted(I["prev_by_cutoff"], key=lambda x: -int(x)):
            pools.append({"cutoff": c, "label": f"≥{c}%", "patients": round(tested * I["prev_by_cutoff"][c])})
    else:
        line = str(L.get("line", "2L"))
        regimen = str(L.get("regimen", "mono"))
        tested = advanced * testing
        prev = I["biomarker_prev"]
        positive = tested * max(0.005, prev + g(prev * 0.05))
        treated = positive * I["line_reach"][line]
        share = (I["share_base"][line] + I["regimen_share"].get(regimen, 0) + (0.04 if comp_active else -0.03)
                 - p["comp_first"] * 0.10 + p["diff"] * 0.06
                 + (0.04 if line == "1L" else -0.04) * (p["early_line"] - 0.5)
                 + (0.04 * (p["combo"] - 0.5) if regimen != "mono" else 0) + g(0.04))
        months = I["months_on_therapy"][line]
        funnel = [(labels[0], incident), (labels[1], advanced), (labels[2], tested), (labels[3], positive),
                  (f"Treated in {line}", treated)]
        for ln in I["line_reach"]:
            pools.append({"line": ln, "label": ln, "patients": round(positive * I["line_reach"][ln])})
    share = clamp(share, 0.05, 0.6)
    on_drug = treated * share
    funnel.append(("On drug at peak share", on_drug))

    # ---------------- PTRS ----------------
    items: list[tuple[str, float]] = []
    base = I["ptrs_base"]
    items.append(("Phase 3 base rate (stand-in)", base))
    if kind == "cutoff":
        cutoff = str(L.get("cutoff", "75"))
        cut = I["cutoff_ptrs"][cutoff] + (0.08 * p["diff"] if cutoff == "1" else 0)
        items.append(("Expression cutoff" + (" (offset by low-expresser activity)" if cutoff == "1" else ""), cut))
        if L.get("combo"):
            items.append(("Biologic combination backbone", 0.02 - 0.04 * (1 - p["combo"])))
    else:
        line = str(L.get("line", "2L"))
        regimen = str(L.get("regimen", "mono"))
        items.append((f"Line of therapy {line}", I["ptrs_line"][line] + (0.04 * (p["early_line"] - 0.5) if line == "1L" else 0)))
        if regimen != "mono":
            items.append((f"Combination regimen ({regimen})", -0.02 + 0.06 * (p["combo"] - 0.5)))
    items.append((f"Primary endpoint {ep.upper()}", -0.05 if ep == "os" else -0.06 * max(0.0, p["os_req"] - 0.5) * 2))
    items.append(("Active comparator, harder to beat" if comp_active else "Standard comparator, acceptability risk",
                  (-0.04 + 0.02 * p["soc_shift"]) if comp_active else -0.09 * p["soc_shift"]))
    items.append(("Dose-optimization cohort" if dose else "No dose cohort while expected", 0.04 if dose else -0.08 * p["dose"]))
    items.append(("Bar reset by earlier competitor approval", -max(0.0, p["comp_first"] - 0.5) * 0.06))
    ptrs = clamp(sum(v for _, v in items) + g(0.04), 0.05, 0.75)

    # ---------------- access ----------------
    os_ev = 1.0 if ep == "os" else 0.35
    tol = 0.5 + 0.3 * p["diff"]
    prem_ok = min(1.0, os_ev * 0.7 + tol * 0.4 + (1 - p["prem"]) * 0.3)
    if kind == "cutoff":
        prem_base = I["premium_by_cutoff"][str(L.get("cutoff", "75"))]
        gtn = I["gtn_by_cutoff"][str(L.get("cutoff", "75"))]
    else:
        prem_base, gtn = I["premium_base"], I["gtn"]
    prem = prem_base * prem_ok
    wac = I["ref_price_month"] * (1 + prem) * (1 + g(0.05))
    net = wac * (1 - gtn)
    eu = net * I["eu_ratio"] * (1 if ep == "os" else 0.88)
    jp = net * I["jp_ratio"]
    hta_months = 9 if ep == "os" else 14
    negotiation_year = int(I["launch_year"]) + int(I["ira_years"])
    gba = "Considerable added benefit, plausible" if ep == "os" else ("Minor added benefit" if tol > 0.7 else "Non-quantifiable or hint")
    nice = "Within threshold at ~15% discount" if ep == "os" else "Above threshold; 25–35% discount likely"

    # ---------------- feasibility ----------------
    countries = P.FOOTPRINTS.get(geo, P.FOOTPRINTS["global"])
    drag = [(1 - 0.35 * p["site"]) if asia else 1.0 for (_, _, _, asia) in countries]
    if kind == "cutoff":
        c = str(L.get("cutoff", "75"))
        n = I["sample_by_cutoff"][c]; rb = I["rate_by_cutoff"][c]; sf = I["screen_fail_by_cutoff"][c]
    else:
        n = I["sample_size"][str(L.get("line", "2L"))]; rb = I["rate_per_site"]; sf = I["screen_fail"]
    rate = sum(sites * rb * drag[i] for i, (_, sites, _, _) in enumerate(countries)) * (1 + g(0.08))
    enroll = I["activation_months"].get(geo, 8) + n / max(0.1, rate)
    if dose:
        enroll += 4
    readout = round(enroll + I["readout_add"][ep])
    cost = round(n * I["cost_per_patient_k"] / 1000 + (36 if dose else 0) + (42 if ep == "os" else 0) + (28 if geo == "west" else 0))

    # ---------------- business ----------------
    rs = I["region_split"]
    yearly = months * I["compliance"]
    peak = on_drug * (rs[0] * net + rs[1] * eu + rs[2] * jp) * yearly / 1e9
    rnpv = peak * I["npv_multiple"] * I["effective_years"] * ptrs - cost / 1000 * 1.1

    return {
        "levers": L, "drivers": p,
        "demand": {"testing": testing, "funnel": funnel, "share": share, "on_drug": on_drug, "pools": pools},
        "ptrs": {"ptrs": ptrs, "items": items},
        "access": {"wac": wac, "net": net, "gtn": gtn, "eu": eu, "jp": jp, "hta_months": hta_months,
                   "negotiation_year": negotiation_year, "gba": gba, "nice": nice, "prem": prem, "prem_ok": prem_ok},
        "feas": {"countries": countries, "drag": drag, "n": n, "rate": rate, "screen_fail": sf, "enroll": enroll,
                 "readout": readout, "readout_label": ymo(I["fpi"], readout), "cost": cost},
        "business": {"peak": peak, "rnpv": rnpv},
    }
