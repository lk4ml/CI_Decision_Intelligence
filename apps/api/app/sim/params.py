# stand-in parameters — replace with Astellas forecast inputs
"""All numeric model inputs used by the stand-in simulation chain live here.

These are ILLUSTRATIVE planning parameters for the stand-in engines (PRD §8). They are not
evidence and are never shown as facts: every model output lists the parameters it used under
`assumptions` and is labelled engine="stand_in". Swap this module (or the adapters in
app/sim/models.py) for Astellas forecast / feasibility / pricing engines.

`roles` maps the abstract driver each model reads (testing uptake, competitor-first, ...)
onto the hypothesis code that carries the team's confidence for that driver in each asset.
"""
from __future__ import annotations

MODEL_VERSION = "0.1.0-stand-in"
MC_N_DEFAULT = 500
MC_SEED = 11  # same seed as the mockup's runMC
BETA_CONCENTRATION = 24.0  # Beta(a,b) with a+b = this, centred on confidence

# Shared feasibility footprints: (country group, sites, competing-trial index, is_asia_pacific)
FOOTPRINTS = {
    "global": [("United States", 38, 4, False), ("EU5", 30, 3, False), ("Japan", 22, 5, True),
               ("Korea", 18, 6, True), ("China", 40, 7, True)],
    "exchina": [("United States", 44, 4, False), ("EU5", 34, 3, False), ("Japan", 24, 5, True),
                ("Korea", 18, 6, True), ("Brazil / Mexico", 14, 2, False)],
    "west": [("United States", 52, 4, False), ("EU5", 40, 3, False), ("Canada / Australia", 12, 2, False),
             ("Japan", 16, 5, True), ("Korea", 10, 6, True)],
}

PROFILES: dict[str, dict] = {
    # ---------------- KRAS G12D, pancreatic ----------------
    "kras_pdac": {
        "label": "Setidegrasib (ASP3082) in KRAS G12D+ PDAC",
        "kind": "line",  # population lever is treatment line
        "funnel_labels": ["Incident pancreatic adenocarcinoma (US+EU5+JP)", "Advanced or metastatic",
                          "Molecularly tested", "KRAS G12D+"],
        "incident": 170000,
        "advanced_frac": 0.80,
        "testing_floor": 0.45, "testing_span": 0.45,
        "biomarker_prev": 0.37,
        "line_reach": {"1L": 0.70, "2L": 0.40},
        "share_base": {"1L": 0.22, "2L": 0.34},
        "regimen_share": {"mono": 0.0, "chemo": 0.04, "pd1": 0.0},
        "months_on_therapy": {"1L": 7.0, "2L": 4.0},
        "region_split": (0.47, 0.33, 0.20),
        "compliance": 0.72,
        "ptrs_base": 0.28,
        "ptrs_line": {"1L": -0.03, "2L": 0.0},
        "ref_price_month": 20000.0,
        "premium_base": 0.20,
        "gtn": 0.20,
        "eu_ratio": 0.52, "jp_ratio": 0.46,
        "ira_years": 9, "modality": "small molecule (degrader)",
        "launch_year": 2030,
        "sample_size": {"1L": 600, "2L": 450},
        "rate_per_site": 0.30,
        "screen_fail": 0.66,
        "readout_add": {"os": 14, "pfs": 8},
        "activation_months": {"global": 8, "exchina": 6, "west": 6},
        "cost_per_patient_k": 230,
        "fpi": (2026, 4),
        "active_comparators": ["ras_active"],
        "npv_multiple": 0.55, "effective_years": 8,
        "roles": {"testing": "H1", "early_line": "H2", "dose": "H3", "combo": "H4", "diff": "H5",
                  "soc_shift": "H6", "comp_first": "H7", "os_req": "H8", "prem": "H9", "site": "H10"},
    },
    # ---------------- KRAS G12D, NSCLC ----------------
    "kras_nsclc": {
        "label": "Setidegrasib (ASP3082) in KRAS G12D+ NSCLC",
        "kind": "line",
        "funnel_labels": ["Incident NSCLC (US+EU5+JP)", "Advanced non-squamous",
                          "Tested by NGS panel", "KRAS G12D+"],
        "incident": 470000,
        "advanced_frac": 0.55,
        "testing_floor": 0.60, "testing_span": 0.35,
        "biomarker_prev": 0.045,
        "line_reach": {"1L": 0.80, "2L": 0.50},
        "share_base": {"1L": 0.18, "2L": 0.32},
        "regimen_share": {"mono": 0.0, "chemo": 0.02, "pd1": 0.05},
        "months_on_therapy": {"1L": 10.0, "2L": 6.0},
        "region_split": (0.47, 0.33, 0.20),
        "compliance": 0.72,
        "ptrs_base": 0.34,
        "ptrs_line": {"1L": -0.04, "2L": 0.0},
        "ref_price_month": 21000.0,
        "premium_base": 0.15,
        "gtn": 0.22,
        "eu_ratio": 0.52, "jp_ratio": 0.46,
        "ira_years": 9, "modality": "small molecule (degrader)",
        "launch_year": 2031,
        "sample_size": {"1L": 640, "2L": 420},
        "rate_per_site": 0.22,
        "screen_fail": 0.90,
        "readout_add": {"os": 20, "pfs": 11},
        "activation_months": {"global": 8, "exchina": 6, "west": 6},
        "cost_per_patient_k": 210,
        "fpi": (2026, 9),
        "active_comparators": ["ras_active"],
        "npv_multiple": 0.55, "effective_years": 8,
        "roles": {"testing": "H1", "early_line": "H2", "dose": "H3", "combo": "H4", "diff": "H5",
                  "soc_shift": "H6", "comp_first": "H7", "os_req": "H8", "prem": "H9", "site": "H10"},
    },
    # ---------------- CLDN18.2, gastric / GEJ (mirrors the mockup model) ----------------
    "cldn_gc": {
        "label": "ASP2138 in CLDN18.2+ gastric / GEJ",
        "kind": "cutoff",
        "funnel_labels": ["Incident gastric / GEJ (US+EU5+JP)", "Advanced or metastatic",
                          "HER2-negative", "Tested for CLDN18.2"],
        "incident": 92000,
        "advanced_frac": 0.62,
        "her2neg": 0.82,
        "testing_floor": 0.40, "testing_span": 0.45,
        "prev_by_cutoff": {"75": 0.38, "50": 0.52, "1": 0.72},
        "treated_1l": 0.78,
        "share_by_cutoff": {"75": 0.36, "50": 0.31, "1": 0.27},
        "months_on_therapy": {"1L": 12.0},
        "region_split": (0.47, 0.33, 0.20),
        "compliance": 0.72,
        "ptrs_base": 0.30,
        "cutoff_ptrs": {"75": 0.03, "50": 0.0, "1": -0.06},
        "ref_price_month": 16800.0,
        "premium_by_cutoff": {"75": 0.35, "50": 0.22, "1": 0.08},
        "gtn_by_cutoff": {"75": 0.17, "50": 0.21, "1": 0.27},
        "eu_ratio": 0.52, "jp_ratio": 0.46,
        "ira_years": 13, "modality": "biologic (bispecific T-cell engager)",
        "launch_year": 2030,
        "sample_by_cutoff": {"75": 680, "50": 620, "1": 560},
        "rate_by_cutoff": {"75": 0.36, "50": 0.44, "1": 0.52},
        "screen_fail_by_cutoff": {"75": 0.55, "50": 0.38, "1": 0.22},
        "readout_add": {"os": 22, "pfs": 13},
        "activation_months": {"global": 8, "exchina": 6, "west": 6},
        "cost_per_patient_k": 210,
        "fpi": (2026, 8),
        "active_comparators": ["zolbe_chemo"],
        "npv_multiple": 0.55, "effective_years": 13,
        "roles": {"broad": "H1", "testing": "H2", "dose": "H3", "combo": "H4", "diff": "H5",
                  "soc_shift": "H6", "comp_first": "H7", "os_req": "H8", "prem": "H9", "site": "H10"},
    },
}

# Generic profile for onboarded assets without a dedicated stand-in.
PROFILES["generic"] = {**PROFILES["kras_pdac"], "label": "Generic oncology stand-in"}


UNITS = {
    "incident": "patients/yr", "advanced_frac": "fraction", "her2neg": "fraction", "testing_floor": "fraction",
    "testing_span": "fraction", "biomarker_prev": "fraction", "prev_by_cutoff": "fraction by cutoff",
    "line_reach": "fraction by line", "treated_1l": "fraction", "share_base": "fraction by line",
    "share_by_cutoff": "fraction by cutoff", "regimen_share": "share delta by regimen",
    "months_on_therapy": "months", "region_split": "US/EU/JP weights", "compliance": "fraction",
    "ptrs_base": "probability", "ptrs_line": "probability delta", "cutoff_ptrs": "probability delta",
    "ref_price_month": "USD/month", "premium_base": "fraction", "premium_by_cutoff": "fraction",
    "gtn": "fraction", "gtn_by_cutoff": "fraction", "eu_ratio": "ratio to US net", "jp_ratio": "ratio to US net",
    "ira_years": "years", "launch_year": "year", "sample_size": "patients", "sample_by_cutoff": "patients",
    "rate_per_site": "patients/site/month", "rate_by_cutoff": "patients/site/month", "screen_fail": "fraction",
    "screen_fail_by_cutoff": "fraction", "readout_add": "months", "activation_months": "months",
    "cost_per_patient_k": "USD k/patient", "fpi": "year, month", "npv_multiple": "multiple",
    "effective_years": "years",
}
_NON_INPUT = {"label", "roles"}


def model_params_for(profile_key: str) -> dict:
    """Build Asset.model_params ({profile, bindings, inputs:{name:{value,unit,basis}}}) from a profile."""
    prof = PROFILES[profile_key]
    inputs = {}
    for k, v in prof.items():
        if k in _NON_INPUT:
            continue
        if isinstance(v, tuple):
            v = list(v)
        inputs[k] = {"value": v, "unit": UNITS.get(k, ""), "basis": "stand_in_assumption"}
    return {"profile": profile_key, "label": prof["label"], "version": MODEL_VERSION,
            "bindings": dict(prof["roles"]), "inputs": inputs}
