"""ClinicalTrials.gov API v2 connector (https://clinicaltrials.gov/data-api/api)."""
from __future__ import annotations

import re
from typing import Any

import httpx

from .http import RawItem, content_hash, get_json, now_utc

SOURCE_KEY = "ctgov"
BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
STUDY_URL = "https://clinicaltrials.gov/study/{nct}"

FIELDS = ",".join([
    "protocolSection.identificationModule",
    "protocolSection.statusModule",
    "protocolSection.designModule",
    "protocolSection.conditionsModule",
    "protocolSection.armsInterventionsModule",
    "protocolSection.outcomesModule",
    "protocolSection.sponsorCollaboratorsModule",
])

_PHASE_LABEL = {
    "EARLY_PHASE1": "Early Phase 1",
    "PHASE1": "Phase 1",
    "PHASE2": "Phase 2",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "NA": "N/A",
}


def phase_label(phases: list[str] | None) -> str | None:
    if not phases:
        return None
    labels = [_PHASE_LABEL.get(p, p) for p in phases]
    if len(labels) == 1:
        return labels[0]
    # e.g. ["PHASE2","PHASE3"] -> "Phase 2/3"
    nums = [l.replace("Phase ", "") for l in labels if l.startswith("Phase ")]
    if len(nums) == len(labels):
        return "Phase " + "/".join(nums)
    return "/".join(labels)


def phase_rank(phase: str | None) -> int:
    """Highest numeric phase in a label ("Phase 2/3" -> 3)."""
    if not phase:
        return 0
    m = re.search(r"phase\s*([1-4]|I{1,3}V?)(?:\s*/\s*([1-4]|I{1,3}V?))?", phase, re.IGNORECASE)
    if not m:
        return 0
    roman = {"I": 1, "II": 2, "III": 3, "IV": 4}

    def _v(x: str | None) -> int:
        if not x:
            return 0
        return int(x) if x.isdigit() else roman.get(x.upper(), 0)

    return max(_v(m.group(1)), _v(m.group(2)))


def _status_label(s: str | None) -> str | None:
    return s.replace("_", " ").title() if s else None


def map_study(study: dict[str, Any]) -> dict[str, Any]:
    ps = study.get("protocolSection", {}) or {}
    ident = ps.get("identificationModule", {}) or {}
    status = ps.get("statusModule", {}) or {}
    design = ps.get("designModule", {}) or {}
    conds = ps.get("conditionsModule", {}) or {}
    arms = ps.get("armsInterventionsModule", {}) or {}
    outcomes = ps.get("outcomesModule", {}) or {}
    sponsor = ps.get("sponsorCollaboratorsModule", {}) or {}

    nct = ident.get("nctId")
    endpoints = []
    for kind, key in (("primary", "primaryOutcomes"), ("secondary", "secondaryOutcomes")):
        for o in outcomes.get(key, []) or []:
            if o.get("measure"):
                endpoints.append({"type": kind, "measure": o.get("measure"),
                                  "time_frame": o.get("timeFrame")})
    interventions = [
        {"type": i.get("type"), "name": i.get("name"),
         "other_names": i.get("otherNames") or []}
        for i in arms.get("interventions", []) or []
    ]
    return {
        "nct_id": nct,
        "title": ident.get("briefTitle") or ident.get("officialTitle") or nct,
        "official_title": ident.get("officialTitle"),
        "acronym": ident.get("acronym"),
        "sponsor": (sponsor.get("leadSponsor") or {}).get("name"),
        "collaborators": [c.get("name") for c in sponsor.get("collaborators", []) or []],
        "phase": phase_label(design.get("phases")),
        "status": _status_label(status.get("overallStatus")),
        "start_date": (status.get("startDateStruct") or {}).get("date"),
        "primary_completion": (status.get("primaryCompletionDateStruct") or {}).get("date"),
        "completion": (status.get("completionDateStruct") or {}).get("date"),
        "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
        "conditions": conds.get("conditions", []) or [],
        "keywords": conds.get("keywords", []) or [],
        "interventions": interventions,
        "endpoints": endpoints,
        "last_update": (status.get("lastUpdatePostDateStruct") or {}).get("date"),
        "first_posted": (status.get("studyFirstPostDateStruct") or {}).get("date"),
    }


def trial_text(t: dict[str, Any]) -> str:
    parts = [
        t.get("title") or "", t.get("official_title") or "", t.get("sponsor") or "",
        t.get("phase") or "", t.get("status") or "",
        " ".join(t.get("conditions") or []), " ".join(t.get("keywords") or []),
        " ".join(
            " ".join([i.get("name") or ""] + list(i.get("other_names") or []))
            for i in t.get("interventions") or []
        ),
        " ".join(e.get("measure") or "" for e in t.get("endpoints") or []),
        f"enrollment {t.get('enrollment')}" if t.get("enrollment") else "",
        f"start {t.get('start_date')}" if t.get("start_date") else "",
        f"primary completion {t.get('primary_completion')}" if t.get("primary_completion") else "",
    ]
    return " | ".join(p for p in parts if p)


def to_raw_item(study: dict[str, Any]) -> RawItem | None:
    t = map_study(study)
    if not t.get("nct_id"):
        return None
    # Change detection: hash over the mapped record incl. lastUpdatePostDate.
    return RawItem(
        source_key=SOURCE_KEY,
        external_id=t["nct_id"],
        url=STUDY_URL.format(nct=t["nct_id"]),
        title=t["title"],
        published_at=t.get("last_update") or t.get("first_posted"),
        kind="trial",
        text=trial_text(t),
        data=t,
        retrieved_at=now_utc(),
        content_hash=content_hash(t),
    )


async def search_studies(
    term: str | None = None,
    cond: str | None = None,
    intr: str | None = None,
    page_size: int = 50,
    max_pages: int = 2,
    client: httpx.AsyncClient | None = None,
) -> list[RawItem]:
    params: dict[str, Any] = {"format": "json", "pageSize": page_size, "fields": FIELDS,
                              "sort": "LastUpdatePostDate:desc"}
    if term:
        params["query.term"] = term
    if cond:
        params["query.cond"] = cond
    if intr:
        params["query.intr"] = intr
    items: list[RawItem] = []
    token = None
    for _ in range(max_pages):
        if token:
            params["pageToken"] = token
        payload = await get_json(SOURCE_KEY, BASE_URL, params, client)
        for s in payload.get("studies", []) or []:
            it = to_raw_item(s)
            if it:
                items.append(it)
        token = payload.get("nextPageToken")
        if not token:
            break
    return items
