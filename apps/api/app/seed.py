"""Idempotent CONFIGURATION seed (ARCHITECTURE hard rule 1).

Seeds assets, positions, hypotheses (team beliefs), patterns, levers, model config, agents, sources and
watch-list SEARCH TERMS only. No signals, trials, publications or numeric evidence are seeded.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, Asset, Hypothesis, HypothesisAgent, Pattern, Position, Source
from app.services import audit
from app.sim.params import model_params_for

# ---------------------------------------------------------------- agents & sources
AGENTS = [
    dict(key="registry_watch", name="Registry watch", category="always_on", reads="world", cadence_minutes=360,
         status="running", source_keys=["ctgov"],
         description="Diffs ClinicalTrials.gov for own and competitor trials on the watch-list; new or changed trials "
                     "(Phase 3 start, status change, completion-date move) become signals."),
    dict(key="literature", name="Congress & literature", category="always_on", reads="world", cadence_minutes=360,
         status="running", source_keys=["pubmed", "europepmc"],
         description="Reads PubMed and Europe PMC for new papers and abstracts on the watch terms."),
    dict(key="research_graph", name="Research graph", category="daily", reads="world", cadence_minutes=1440,
         status="running", source_keys=["openalex"],
         description="OpenAlex citation and topic momentum; new works by key authors and institutions."),
    dict(key="regulatory", name="Regulatory watch", category="always_on", reads="world", cadence_minutes=360,
         status="running", source_keys=["openfda"],
         description="openFDA label changes and approvals for competitor and standard-of-care drugs."),
    dict(key="astellas_ir", name="Astellas investor relations", category="daily", reads="company", cadence_minutes=1440,
         status="supervised", source_keys=["astellas_ir"],
         description="Astellas pipeline page, press releases and FY presentations → company-knowledge signals (tagged company)."),
    dict(key="implication", name="Implication agent", category="on_event", reads="models", cadence_minutes=None,
         status="running", source_keys=[], description="Writes the so-what and proposes confidence moves (PRD §7.4 formula)."),
    dict(key="guardrail", name="Guardrail agent", category="on_event", reads="models", cadence_minutes=None,
         status="running", source_keys=[], description="Blocks any claim without a source URL and retrieval date."),
    dict(key="simulation", name="Simulation agent", category="on_event", reads="models", cadence_minutes=None,
         status="running", source_keys=[], description="Re-prices fired pattern options with today's confidences."),
    dict(key="brief", name="Brief agent", category="on_event", reads="models", cadence_minutes=None,
         status="running", source_keys=[], description="Assembles the versioned brief export on request."),
]

SOURCES = [
    dict(key="ctgov", name="ClinicalTrials.gov", side="world", kind="registry", base_url="https://clinicaltrials.gov/api/v2",
         access_level="public API", license_notes="Public domain (U.S. NLM)."),
    dict(key="pubmed", name="PubMed (NCBI E-utilities)", side="world", kind="literature",
         base_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils", access_level="public API",
         license_notes="NCBI usage policy; abstracts subject to publisher copyright."),
    dict(key="europepmc", name="Europe PMC", side="world", kind="literature",
         base_url="https://www.ebi.ac.uk/europepmc/webservices/rest", access_level="public API",
         license_notes="EMBL-EBI terms of use."),
    dict(key="openalex", name="OpenAlex", side="world", kind="research_graph", base_url="https://api.openalex.org",
         access_level="public API", license_notes="CC0."),
    dict(key="openfda", name="openFDA", side="world", kind="regulator", base_url="https://api.fda.gov",
         access_level="public API", license_notes="Public domain; openFDA terms of service."),
    dict(key="astellas_ir", name="Astellas investor relations", side="company", kind="company_ir",
         base_url="https://www.astellas.com/en/investors", access_level="public website",
         license_notes="Astellas website terms of use."),
]

# ---------------------------------------------------------------- lever schemas
GEO = {"name": "geo", "label": "Footprint", "type": "select", "default": "global",
       "options": [{"value": "global", "label": "Global incl. China"}, {"value": "exchina", "label": "Ex-China"},
                   {"value": "west", "label": "US + EU heavy"}]}
EP = {"name": "ep", "label": "Primary endpoint", "type": "select", "default": "pfs",
      "options": [{"value": "pfs", "label": "PFS"}, {"value": "os", "label": "OS"}]}
DOSE = {"name": "dose", "label": "Dose-optimization cohort", "type": "toggle", "default": False}
LINE = {"name": "line", "label": "Line of therapy", "type": "select", "default": "2L",
        "options": [{"value": "1L", "label": "1L"}, {"value": "2L", "label": "2L"}]}

LEVERS_PDAC = [
    LINE,
    {"name": "regimen", "label": "Regimen", "type": "select", "default": "mono",
     "options": [{"value": "mono", "label": "Monotherapy"}, {"value": "chemo", "label": "+ chemotherapy"}]},
    {"name": "comp", "label": "Comparator", "type": "select", "default": "chemo",
     "options": [{"value": "chemo", "label": "Standard chemotherapy (investigator's choice)"},
                 {"value": "ras_active", "label": "Active RAS-directed control"}]},
    EP, GEO, DOSE,
]
LEVERS_NSCLC = [
    LINE,
    {"name": "regimen", "label": "Regimen", "type": "select", "default": "mono",
     "options": [{"value": "mono", "label": "Monotherapy"}, {"value": "chemo", "label": "+ chemotherapy"},
                 {"value": "pd1", "label": "+ anti-PD-1"}]},
    {"name": "comp", "label": "Comparator", "type": "select", "default": "docetaxel",
     "options": [{"value": "docetaxel", "label": "Docetaxel"},
                 {"value": "chemo_io", "label": "Platinum chemotherapy + anti-PD-1"},
                 {"value": "ras_active", "label": "Active RAS-directed control"}]},
    EP, GEO, DOSE,
]
LEVERS_GC = [
    {"name": "cutoff", "label": "CLDN18.2 cutoff", "type": "select", "default": "75",
     "options": [{"value": "75", "label": "≥75%"}, {"value": "50", "label": "≥50%"}, {"value": "1", "label": "≥1%"}]},
    {"name": "comp", "label": "Comparator", "type": "select", "default": "chemo_nivo",
     "options": [{"value": "chemo_nivo", "label": "Chemotherapy ± nivolumab"},
                 {"value": "zolbe_chemo", "label": "Zolbetuximab + chemotherapy"}]},
    EP, GEO, DOSE,
    {"name": "combo", "label": "Biologic combination (anti-PD-1 backbone)", "type": "toggle", "default": False},
]


def H(code, cat, line, owner, start, thr, statement, change, keywords, agents):
    return dict(code=code, category=cat, position_line=line, owner_role=owner, confidence_start=float(start),
                threshold=float(thr), statement=statement, change_trigger_text=change, keywords=keywords, agents=agents)


# ---------------------------------------------------------------- hypotheses (team beliefs, falsifiable)
HYP_PDAC = [
    H("H1", "Population", "Population", "Forecasting", 55, 70,
      "By launch, more than 80% of US patients with advanced pancreatic adenocarcinoma will have a KRAS variant result (tissue or ctDNA) before second-line treatment.",
      "A guideline recommendation for universal molecular profiling in PDAC plus two quarters of testing above 65% in claims.",
      ["KRAS testing", "molecular profiling", "ctDNA", "liquid biopsy", "next-generation sequencing", "pancreatic"],
      ["literature", "research_graph"]),
    H("H2", "Population", "Population", "Asset lead", 50, 65,
      "First-line metastatic PDAC will hold most of the KRAS G12D value; a second-line-only label will capture less than a third of it.",
      "A KRAS-directed agent showing benefit in 1L PDAC in a randomized trial, or a 1L Phase 3 start by a competitor.",
      ["first-line", "1L", "metastatic pancreatic", "untreated", "KRAS G12D"], ["registry_watch", "literature"]),
    H("H3", "Intervention", "Intervention", "Clinical", 60, 75,
      "Regulators will require randomized dose-optimization data comparing at least two setidegrasib doses before approval.",
      "An FDA action or guidance on a targeted oncology dossier citing dose justification.",
      ["dose optimization", "Project Optimus", "dose selection", "randomized dose"], ["regulatory", "literature"]),
    H("H4", "Intervention", "Intervention", "Clinical", 50, 65,
      "Setidegrasib can be combined with gemcitabine/nab-paclitaxel or FOLFIRINOX at full doses of both without unacceptable additive toxicity.",
      "A KRAS-directed combination with standard PDAC chemotherapy reporting manageable grade ≥3 toxicity at full doses.",
      ["combination", "gemcitabine", "nab-paclitaxel", "FOLFIRINOX", "chemotherapy", "toxicity"], ["literature", "registry_watch"]),
    H("H5", "Intervention", "Intervention", "Clinical", 50, 65,
      "Targeted degradation of KRAS G12D will produce more durable responses than reversible KRAS G12D inhibition.",
      "Head-to-head or cross-trial data showing longer duration of response for a degrader than for reversible inhibitors.",
      ["degrader", "protein degradation", "duration of response", "resistance", "KRAS G12D inhibitor"], ["literature", "research_graph"]),
    H("H6", "Comparator", "Comparator", "Clinical", 45, 60,
      "By our readout, a RAS-directed therapy will be an accepted standard in previously treated PDAC, making chemotherapy alone an unacceptable control arm.",
      "A RAS-directed agent approved or guideline-listed in 2L PDAC, or HA advice rejecting a chemotherapy-only control.",
      ["pan-RAS", "RAS inhibitor", "second-line", "previously treated", "approval", "guideline"], ["registry_watch", "regulatory"]),
    H("H7", "Comparator", "Comparator", "Asset lead", 45, 60,
      "At least one competitor KRAS G12D-selective or pan-RAS agent will reach approval in PDAC before our pivotal reads out.",
      "A competitor PDAC Phase 3 fully enrolled, or a competitor regulatory submission in PDAC.",
      ["Phase 3", "competitor", "KRAS G12D", "pan-RAS", "approval", "submission"], ["registry_watch", "regulatory", "astellas_ir"]),
    H("H8", "Outcomes", "Outcomes", "Clinical", 60, 75,
      "Overall survival, not PFS alone, will be required as the primary endpoint for full approval in PDAC.",
      "An FDA or EMA decision in PDAC resting on PFS alone, or explicit guidance accepting PFS.",
      ["overall survival", "OS", "progression-free survival", "endpoint", "primary endpoint"], ["regulatory", "literature"]),
    H("H9", "Business", "Price & access", "Access & pricing", 60, 75,
      "Payers in Germany and the UK will accept a premium over chemotherapy only with an OS benefit of at least three months.",
      "An HTA body granting added benefit to a PDAC therapy on PFS or a sub-three-month OS gain.",
      ["HTA", "G-BA", "NICE", "added benefit", "reimbursement", "price"], ["regulatory"]),
    H("H10", "Business", "Timeline", "Operations", 50, 65,
      "Competing KRAS-directed PDAC trials will extend our enrollment by six months or more unless the footprint is rebalanced.",
      "More than ten competing KRAS-directed PDAC trials recruiting in our countries, or site activation lagging a quarter.",
      ["recruiting", "sites", "enrollment", "KRAS", "pancreatic"], ["registry_watch"]),
]
HYP_NSCLC = [
    H("H1", "Population", "Population", "Forecasting", 60, 75,
      "By launch, at least 90% of advanced non-squamous NSCLC patients in the US and EU5 will have a KRAS variant result before first-line treatment.",
      "Two quarters of claims showing broad-panel NGS above 85% at diagnosis, or a guideline mandating plasma-first testing.",
      ["NGS", "biomarker testing", "liquid biopsy", "KRAS testing", "non-small cell"], ["literature", "research_graph"]),
    H("H2", "Population", "Population", "Asset lead", 50, 65,
      "Most KRAS G12D NSCLC value will sit in first-line combination with anti-PD-1; a second-line-only label will capture less than a third of it.",
      "A KRAS-directed agent plus anti-PD-1 showing benefit in 1L NSCLC, or a competitor 1L Phase 3 start.",
      ["first-line", "1L", "pembrolizumab", "anti-PD-1", "KRAS G12D"], ["registry_watch", "literature"]),
    H("H3", "Intervention", "Intervention", "Clinical", 60, 75,
      "Regulators will require randomized dose-optimization data comparing at least two setidegrasib doses before approval.",
      "An FDA action or guidance on a targeted oncology dossier citing dose justification.",
      ["dose optimization", "Project Optimus", "dose selection", "randomized dose"], ["regulatory", "literature"]),
    H("H4", "Intervention", "Intervention", "Clinical", 45, 60,
      "Setidegrasib can be combined with anti-PD-1 at full doses without excess grade ≥3 hepatotoxicity or immune-related adverse events.",
      "A KRAS-directed agent plus anti-PD-1 reporting grade ≥3 hepatotoxicity below 15% at full doses.",
      ["combination", "anti-PD-1", "pembrolizumab", "hepatotoxicity", "immune-related"], ["literature", "registry_watch"]),
    H("H5", "Intervention", "Intervention", "Clinical", 50, 65,
      "Setidegrasib will show intracranial activity and response durability that reversible KRAS G12D inhibitors cannot claim.",
      "Intracranial response or duration-of-response data for KRAS G12D agents in NSCLC with brain metastases.",
      ["brain metastases", "intracranial", "CNS", "duration of response", "degrader"], ["literature", "research_graph"]),
    H("H6", "Comparator", "Comparator", "Clinical", 45, 60,
      "By our readout, a RAS-directed therapy will be an accepted standard in previously treated NSCLC, making docetaxel an unacceptable control arm.",
      "A RAS-directed agent approved or guideline-listed after IO and platinum, or HA advice rejecting docetaxel control.",
      ["docetaxel", "second-line", "previously treated", "RAS inhibitor", "approval"], ["registry_watch", "regulatory"]),
    H("H7", "Comparator", "Comparator", "Asset lead", 45, 60,
      "At least one competitor KRAS G12D-selective or pan-RAS agent will reach approval in NSCLC before our pivotal reads out.",
      "A competitor NSCLC Phase 3 fully enrolled, or a competitor regulatory submission in NSCLC.",
      ["Phase 3", "competitor", "KRAS G12D", "pan-RAS", "approval", "submission"], ["registry_watch", "regulatory", "astellas_ir"]),
    H("H8", "Outcomes", "Outcomes", "Clinical", 45, 60,
      "Regulators will require an OS benefit, not PFS alone, for full approval of a KRAS-directed agent in previously treated NSCLC.",
      "A confirmatory-trial decision in KRAS-mutant NSCLC that turns on OS rather than PFS.",
      ["overall survival", "OS", "progression-free survival", "confirmatory", "endpoint"], ["regulatory", "literature"]),
    H("H9", "Business", "Price & access", "Access & pricing", 60, 75,
      "Payers in Germany and the UK will accept a premium over docetaxel only with an OS benefit or a clear tolerability advantage.",
      "An HTA body granting added benefit to a KRAS-directed NSCLC therapy on PFS alone.",
      ["HTA", "G-BA", "NICE", "added benefit", "reimbursement"], ["regulatory"]),
    H("H10", "Business", "Timeline", "Operations", 50, 65,
      "Competing KRAS-directed NSCLC trials in East Asia will extend our enrollment by six months or more unless the footprint is rebalanced.",
      "More than fifteen competing KRAS-directed NSCLC trials recruiting in JP/KR/CN, or site activation lagging a quarter.",
      ["recruiting", "sites", "enrollment", "KRAS", "lung"], ["registry_watch"]),
]
HYP_GC = [
    H("H1", "Population", "Population", "Asset lead", 55, 75,
      "By 2030, CLDN18.2 eligibility for new agents will be defined by a broad cutoff (≥1% of tumour cells), not ≥75% moderate-to-strong staining.",
      "Two or more Phase 3 starts with a broad cutoff, or efficacy shown to hold in low expressers.",
      ["CLDN18.2", "cutoff", "expression", "low expressers", "IHC", "Phase 3"], ["registry_watch", "literature"]),
    H("H2", "Population", "Population", "Forecasting", 55, 70,
      "Reflex CLDN18.2 testing will exceed 70% of HER2-negative advanced gastric/GEJ patients in the US by launch.",
      "A guideline reflex recommendation plus two quarters above 55% in claims.",
      ["CLDN18.2 testing", "reflex testing", "IHC", "biomarker testing", "gastric"], ["literature", "research_graph"]),
    H("H3", "Intervention", "Intervention", "Clinical", 60, 75,
      "Regulators will expect randomized dose-optimization data, including the step-up schedule, for a CD3 bispecific pivotal.",
      "An FDA action on a T-cell engager dossier citing dose or step-up justification.",
      ["dose optimization", "step-up dosing", "T-cell engager", "bispecific", "Project Optimus"], ["regulatory", "literature"]),
    H("H4", "Intervention", "Intervention", "Clinical", 50, 65,
      "ASP2138 can be combined with chemotherapy and anti-PD-1 without cytokine release syndrome rates that force inpatient dosing.",
      "Combination data for a CLDN18.2 T-cell engager with grade ≥2 CRS below 10% in outpatient settings.",
      ["cytokine release syndrome", "CRS", "combination", "nivolumab", "T-cell engager"], ["literature", "registry_watch"]),
    H("H5", "Intervention", "Intervention", "Clinical", 55, 70,
      "ASP2138's T-cell engager mechanism will retain activity in lower CLDN18.2 expressers, which antibody and ADC approaches cannot claim.",
      "Competitor subgroup data in low expressers matching ours, or our Phase 1 expansion failing to show activity below 50%.",
      ["low expression", "CLDN18.2", "bispecific", "subgroup", "response rate"], ["literature", "research_graph"]),
    H("H6", "Comparator", "Comparator", "Clinical", 55, 70,
      "The 1L control at our readout for CLDN18.2+ patients will be zolbetuximab + chemotherapy; chemotherapy ± nivolumab alone will not be acceptable.",
      "Zolbetuximab share above 40% of eligible US or Japan 1L starts, or HA advice rejecting a chemotherapy ± nivolumab control.",
      ["zolbetuximab", "first-line", "standard of care", "nivolumab", "control arm"], ["regulatory", "literature"]),
    H("H7", "Comparator", "Comparator", "Asset lead", 45, 60,
      "At least one other CLDN18.2-directed ADC or cell therapy will reach gastric approval before our pivotal reads out.",
      "A competitor CLDN18.2 Phase 3 fully enrolled, or a competitor regulatory submission in gastric cancer.",
      ["CLDN18.2", "antibody-drug conjugate", "CAR-T", "Phase 3", "approval"], ["registry_watch", "regulatory", "astellas_ir"]),
    H("H8", "Outcomes", "Outcomes", "Clinical", 55, 70,
      "OS, not PFS alone, will be required as the primary endpoint for 1L gastric approval of a new CLDN18.2 agent.",
      "Any 1L gastric approval resting on PFS alone, or explicit HA advice accepting PFS.",
      ["overall survival", "progression-free survival", "endpoint", "hazard ratio"], ["regulatory", "literature"]),
    H("H9", "Business", "Price & access", "Access & pricing", 60, 75,
      "Payers will accept a premium over zolbetuximab only with meaningful OS benefit or a clear tolerability advantage.",
      "An HTA body rating a CLDN18.2 therapy on PFS alone as added benefit.",
      ["HTA", "G-BA", "NICE", "added benefit", "premium", "reimbursement"], ["regulatory"]),
    H("H10", "Business", "Timeline", "Operations", 55, 70,
      "Trial competition in Korea, Japan and China will extend enrollment by 6–12 months unless the footprint is rebalanced.",
      "More than 12 competing CLDN18.2 trials recruiting in KR/JP/CN, or site activation lagging a quarter.",
      ["recruiting", "sites", "enrollment", "CLDN18.2", "Asia"], ["registry_watch"]),
]


def PAT(key, title, line, trigger, trigger_text, rationale, lever, opts):
    return dict(key=key, title=title, position_line=line, trigger=trigger, trigger_text=trigger_text,
                rationale=rationale, options=[{"lever": lever, "value": v, "label": l} for v, l in opts])


PAT_KRAS_COMMON = [
    PAT("move_1l", "Move the pivotal question into first line", "Population", "H2 >= 0.62 and H4 >= 0.55",
        "H2 ≥ 62% and H4 ≥ 55%",
        "First line is where the value sits and the combination looks tolerable; a later-line-only programme cedes it.",
        "line", [("1L", "Move to 1L in combination"), ("2L", "Stay in 2L, expand later")]),
    PAT("control", "Confirm or change the control arm", "Comparator", "H6 >= 0.58", "H6 ≥ 58%",
        "A RAS-directed standard would make the current control questionable for regulators and payers.",
        "comp", [("ras_active", "Design against an active RAS-directed control"), (None, "Keep the current control, accept the challenge")]),
    PAT("dose", "Add the dose-optimization cohort", "Intervention", "H3 >= 0.72 and not levers_dose",
        "H3 ≥ 72% while no dose cohort",
        "Regulators are expected to ask for randomized dose data; the plan currently lacks it.",
        "dose", [(True, "Add a two-dose randomized cohort"), (False, "Keep a single dose, accept the risk")]),
    PAT("endpoint", "Choose the primary endpoint", "Outcomes", "H8 >= 0.70", "H8 ≥ 70%",
        "If OS is required for full approval, a PFS-primary design buys speed at regulatory risk.",
        "ep", [("os", "OS primary"), ("pfs", "PFS primary with OS interim")]),
    PAT("footprint", "Rebalance the country footprint", "Timeline", "H10 >= 0.62", "H10 ≥ 62%",
        "Site competition now costs months; geography is a trade-off, not a default.",
        "geo", [("global", "Global incl. China"), ("exchina", "Ex-China"), ("west", "US + EU heavy")]),
    PAT("reanchor", "Re-anchor the differentiation claim", "Intervention", "H7 >= 0.58 and H5 <= 0.45",
        "H7 ≥ 58% and H5 ≤ 45%",
        "A competitor is likely first while durability differentiation weakens; the story has to move to the regimen.",
        "regimen", [("chemo", "Lead with the chemotherapy combination"), ("mono", "Stay with monotherapy")]),
]

PAT_GC = [
    PAT("broaden", "Broaden the label population", "Population", "H1 >= 0.65 and H2 >= 0.60", "H1 ≥ 65% and H2 ≥ 60%",
        "Broad expression is becoming the standard and testing is catching up — a narrow label would leave patients to competitors.",
        "cutoff", [("75", "Keep ≥75%, defend on effect size"), ("50", "Hedge at ≥50%"), ("1", "Go broad, ≥1%")]),
    PAT("reanchor", "Re-anchor the differentiation claim", "Intervention", "H1 >= 0.60 and H5 <= 0.50",
        "H1 ≥ 60% and H5 ≤ 50%",
        "Broad expression is normalising while low-expresser differentiation weakens; the story has to move to tolerability or outcomes.",
        "ep", [("pfs", "PFS primary, tolerability-led story"), ("os", "OS primary, outcomes-led story")]),
    PAT("control", "Confirm or change the control arm", "Comparator", "H6 >= 0.68", "H6 ≥ 68%",
        "Zolbetuximab + chemotherapy is becoming the real-world control; a chemotherapy ± nivolumab comparator will be questioned.",
        "comp", [("zolbe_chemo", "Design against zolbetuximab + chemotherapy"), ("chemo_nivo", "Keep chemotherapy ± nivolumab, accept the challenge")]),
    PAT("footprint", "Rebalance the country footprint", "Timeline", "H10 >= 0.62", "H10 ≥ 62%",
        "Asian site competition now costs months; geography is a trade-off, not a default.",
        "geo", [("global", "Global incl. China"), ("exchina", "Ex-China"), ("west", "US + EU heavy")]),
    PAT("access", "Choose the access evidence strategy", "Price & access", "H9 >= 0.74", "H9 ≥ 74%",
        "A premium needs OS or tolerability evidence in Germany and the UK; decide what we launch with.",
        "ep", [("pfs", "Launch on PFS with OS interim"), ("os", "Launch on OS")]),
    PAT("dose", "Add the dose-optimization cohort", "Intervention", "H3 >= 0.75 and not levers_dose",
        "H3 ≥ 75% while no dose cohort",
        "Regulators expect randomized dose data for a T-cell engager; the protocol currently lacks it.",
        "dose", [(True, "Add a two-dose randomized cohort"), (False, "Keep a single dose, accept the risk")]),
]


def _kras_patterns(default_comp: str) -> list[dict]:
    out = []
    for p in PAT_KRAS_COMMON:
        p = {**p, "options": [dict(o) for o in p["options"]]}
        for o in p["options"]:
            if o["value"] is None:
                o["value"] = default_comp
        out.append(p)
    return out


def POS(line, owner, contrib, template, why):
    return dict(line=line, owner_role=owner, contributor_roles=contrib, statement_template=template, why=why)


POS_KRAS = lambda indication: [  # noqa: E731
    POS("Population", "Asset lead", ["Forecasting"], f"KRAS G12D+ {indication}, {{line_label}} setting.",
        "Rests on the testing and line-of-therapy hypotheses."),
    POS("Intervention", "Clinical", ["Asset lead"],
        "Setidegrasib {regimen_label}, at the dose selected from {dose_text}.",
        "Rests on dose-expectation, combinability and differentiation hypotheses."),
    POS("Comparator", "Clinical", ["Asset lead", "Access & pricing"], "Control arm: {comp_label}.",
        "Rests on the standard-of-care shift and competitor-first hypotheses."),
    POS("Outcomes", "Clinical", ["Access & pricing"],
        "Primary endpoint {ep_upper}; PTRS {ptrs_pct}% on today's confidences (stand-in).",
        "Rests on the endpoint-requirement hypothesis."),
    POS("Price & access", "Access & pricing", ["Forecasting"],
        "US net ~${us_net}/month, {prem_pct}% premium over reference (stand-in).",
        "Rests on the payer-premium hypothesis."),
    POS("Timeline", "Operations", ["Clinical"],
        "Primary readout {readout_label} from first patient; {geo_label} footprint; cost ~${cost}M (stand-in).",
        "Rests on the site-competition hypothesis."),
]
POS_GC = [
    POS("Population", "Asset lead", ["Forecasting"],
        "CLDN18.2 {cutoff_label}, HER2-negative, 1L advanced gastric or GEJ adenocarcinoma.",
        "Rests on the cutoff and testing hypotheses."),
    POS("Intervention", "Clinical", ["Asset lead"],
        "ASP2138 at the dose selected from {dose_text}, with chemotherapy{combo_text}.",
        "Rests on dose-expectation, combinability and low-expresser differentiation hypotheses."),
    POS("Comparator", "Clinical", ["Asset lead", "Access & pricing"], "Control arm: {comp_label}.",
        "Rests on the standard-of-care shift and competitor-first hypotheses."),
    POS("Outcomes", "Clinical", ["Access & pricing"],
        "Primary endpoint {ep_upper}; PTRS {ptrs_pct}% on today's confidences (stand-in).",
        "Rests on the endpoint-requirement hypothesis."),
    POS("Price & access", "Access & pricing", ["Forecasting"],
        "US net ~${us_net}/month, {prem_pct}% premium over reference (stand-in).",
        "Rests on the payer-premium hypothesis."),
    POS("Timeline", "Operations", ["Clinical"],
        "Primary readout {readout_label} from first patient; {geo_label} footprint; cost ~${cost}M (stand-in).",
        "Rests on the site-competition hypothesis."),
]

KRAS_COMPETITORS = ["zoldonrasib", "RMC-9805", "daraxonrasib", "RMC-6236", "HRS-4642", "VS-7375", "GFH375",
                    "INCB161734", "LY3962673"]
CLDN_COMPETITORS = ["zolbetuximab", "AZD0901", "CMG901", "IBI343", "SHR-A1904", "satricabtagene autoleucel", "CT041",
                    "givastomig", "osemitamab", "TST001"]

ASSETS = [
    dict(slug="asp3082-pdac", code="ASP3082-PDAC", name="Setidegrasib (ASP3082)",
         mechanism="KRAS G12D–selective targeted protein degrader", indication="Pancreatic ductal adenocarcinoma",
         biomarker="KRAS G12D+", phase="Phase 3 (started Apr 2026)", decision_type="TPP",
         governance_forum="Investment committee", governance_date=None,
         descriptor="KRAS G12D–selective targeted protein degrader · pancreatic ductal adenocarcinoma · TPP",
         watch_terms={"own": ["ASP3082", "setidegrasib"], "competitors": KRAS_COMPETITORS,
                      "literature": ["KRAS G12D pancreatic cancer", "KRAS G12D inhibitor", "pan-RAS inhibitor",
                                     "KRAS degrader", "pancreatic ductal adenocarcinoma KRAS"],
                      "standard_of_care": ["gemcitabine", "nab-paclitaxel", "irinotecan liposome", "FOLFIRINOX"],
                      "conditions": ["Pancreatic Ductal Adenocarcinoma", "Pancreatic Cancer"],
                      "ir": ["ASP3082", "setidegrasib", "KRAS G12D", "pancreatic"]},
         levers=LEVERS_PDAC, profile="kras_pdac", hyps=HYP_PDAC, patterns=_kras_patterns("chemo"),
         positions=POS_KRAS("metastatic pancreatic ductal adenocarcinoma")),
    dict(slug="asp3082-nsclc", code="ASP3082-NSCLC", name="Setidegrasib (ASP3082)",
         mechanism="KRAS G12D–selective targeted protein degrader", indication="Non-small cell lung cancer",
         biomarker="KRAS G12D+", phase="Phase 3 (started Sep 2026)", decision_type="TPP",
         governance_forum="Investment committee", governance_date=None,
         descriptor="KRAS G12D–selective targeted protein degrader · non-small cell lung cancer · TPP",
         watch_terms={"own": ["ASP3082", "setidegrasib"], "competitors": KRAS_COMPETITORS,
                      "literature": ["KRAS G12D non-small cell lung cancer", "KRAS G12D inhibitor", "pan-RAS inhibitor",
                                     "KRAS degrader", "KRAS mutant NSCLC"],
                      "standard_of_care": ["docetaxel", "pembrolizumab", "carboplatin", "pemetrexed"],
                      "conditions": ["Non-small Cell Lung Cancer", "NSCLC"],
                      "ir": ["ASP3082", "setidegrasib", "KRAS G12D", "lung"]},
         levers=LEVERS_NSCLC, profile="kras_nsclc", hyps=HYP_NSCLC, patterns=_kras_patterns("docetaxel"),
         positions=POS_KRAS("advanced non-squamous non-small cell lung cancer")),
    dict(slug="asp2138-gc", code="ASP2138-GC", name="ASP2138",
         mechanism="CLDN18.2 × CD3 bispecific T-cell engager", indication="Gastric / GEJ adenocarcinoma",
         biomarker="CLDN18.2+", phase="Phase 3 (started Aug 2026)", decision_type="TPP",
         governance_forum="Investment committee", governance_date=None,
         descriptor="CLDN18.2 × CD3 bispecific T-cell engager · gastric / GEJ adenocarcinoma · TPP",
         watch_terms={"own": ["ASP2138"], "competitors": CLDN_COMPETITORS,
                      "literature": ["claudin 18.2", "CLDN18.2 gastric cancer", "CLDN18.2 bispecific",
                                     "CLDN18.2 antibody-drug conjugate", "CLDN18.2 CAR-T"],
                      "standard_of_care": ["nivolumab", "zolbetuximab", "oxaliplatin", "capecitabine"],
                      "conditions": ["Gastric Adenocarcinoma", "Gastroesophageal Junction Adenocarcinoma", "Gastric Cancer"],
                      "ir": ["ASP2138", "CLDN18.2", "gastric"]},
         levers=LEVERS_GC, profile="cldn_gc", hyps=HYP_GC, patterns=PAT_GC, positions=POS_GC),
]


def lever_defaults(schema: list[dict]) -> dict:
    return {i["name"]: i.get("default") for i in schema}


def seed_catalog(session: Session) -> None:
    for a in AGENTS:
        if not session.execute(select(Agent).where(Agent.key == a["key"])).scalar_one_or_none():
            session.add(Agent(**a))
    for s in SOURCES:
        if not session.execute(select(Source).where(Source.key == s["key"])).scalar_one_or_none():
            session.add(Source(**s))
    session.flush()


def create_positions(session: Session, asset: Asset, positions: list[dict] | None) -> None:
    from app.models import POSITION_LINES

    if positions is None:
        positions = [POS(l, o, [], None, None) for l, o in zip(POSITION_LINES, [
            "Asset lead", "Clinical", "Clinical", "Clinical", "Access & pricing", "Operations"])]
    for p in positions:
        session.add(Position(asset_id=asset.id, line=p["line"], owner_role=p["owner_role"],
                             contributor_roles=p["contributor_roles"], statement_template=p["statement_template"],
                             statement="Not yet drafted." if not p["statement_template"] else "Pending first render.",
                             why=p["why"], status="provisional", version=0))


def seed_asset(session: Session, spec: dict) -> Asset:
    existing = session.execute(select(Asset).where(Asset.slug == spec["slug"])).scalar_one_or_none()
    if existing:
        return existing
    agents = {a.key: a for a in session.execute(select(Agent)).scalars()}
    asset = Asset(slug=spec["slug"], code=spec["code"], name=spec["name"], mechanism=spec["mechanism"],
                  indication=spec["indication"], biomarker=spec["biomarker"], phase=spec["phase"], phase_source="user",
                  decision_type=spec["decision_type"], governance_forum=spec["governance_forum"],
                  governance_date=spec["governance_date"], descriptor=spec["descriptor"], watch_terms=spec["watch_terms"],
                  lever_schema=spec["levers"], current_levers=lever_defaults(spec["levers"]),
                  model_params=model_params_for(spec["profile"]), registry_nct_ids=[])
    session.add(asset)
    session.flush()
    for h in spec["hyps"]:
        hyp = Hypothesis(asset_id=asset.id, code=h["code"], statement=h["statement"], category=h["category"],
                         position_line=h["position_line"], owner_role=h["owner_role"],
                         confidence_start=h["confidence_start"], confidence=h["confidence_start"],
                         threshold=h["threshold"], change_trigger_text=h["change_trigger_text"], keywords=h["keywords"])
        session.add(hyp)
        session.flush()
        for k in h["agents"]:
            if k in agents:
                session.add(HypothesisAgent(hypothesis_id=hyp.id, agent_id=agents[k].id))
    for p in spec["patterns"]:
        session.add(Pattern(asset_id=asset.id, is_fired=False, **p))
    create_positions(session, asset, spec["positions"])
    session.flush()
    audit.record(session, "system:seed", "asset.seeded", "asset", asset.id,
                 {"slug": asset.slug, "hypotheses": len(spec["hyps"]), "patterns": len(spec["patterns"])},
                 asset_id=asset.id)
    return asset


def seed(session: Session) -> None:
    seed_catalog(session)
    for spec in ASSETS:
        seed_asset(session, spec)
    session.commit()
    # render templated statements
    from app.services import positions as pos_svc

    for a in session.execute(select(Asset)).scalars():
        pos_svc.render_all(session, a)
    session.commit()
