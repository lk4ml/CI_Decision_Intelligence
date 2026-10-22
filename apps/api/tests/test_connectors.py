"""Connector parsing tests against SYNTHETIC fixtures (httpx.MockTransport)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.connectors import astellas_ir, ctgov, europepmc, http, openalex, openfda, pubmed
from app.connectors.http import SourceUnavailable

from fixtures.helpers import all_source_routes, route_transport, text_resp


@pytest.fixture
def mock_sources():
    http.set_transport(route_transport(all_source_routes()))
    yield
    http.set_transport(None)


@pytest.fixture
def blocked_403():
    http.set_transport(route_transport({}, default_status=403))
    yield
    http.set_transport(None)


def run(coro):
    return asyncio.run(coro)


def test_ctgov_maps_trials(mock_sources):
    items = run(ctgov.search_studies(intr="ASP3082"))
    assert [i.external_id for i in items] == ["NCT99990001", "NCT99990002"]
    t = items[0].data
    assert t["phase"] == "Phase 3"
    assert t["status"] == "Recruiting"
    assert t["sponsor"].startswith("Astellas")
    assert t["enrollment"] == 450
    assert t["start_date"] == "2026-04-20"
    assert t["primary_completion"] == "2028-12-31"
    assert "Pancreatic Ductal Adenocarcinoma" in t["conditions"]
    assert any(i["name"] == "ASP3082" for i in t["interventions"])
    assert t["endpoints"][0] == {"type": "primary", "measure": "Overall survival (OS)",
                                 "time_frame": "Up to 36 months"}
    assert t["last_update"] == "2026-10-01"
    assert items[0].url == "https://clinicaltrials.gov/study/NCT99990001"
    assert items[0].kind == "trial" and items[0].content_hash


def test_ctgov_hash_changes_with_last_update():
    payload = {"protocolSection": {"identificationModule": {"nctId": "NCT99990009"},
                                   "statusModule": {"lastUpdatePostDateStruct": {"date": "2026-01-01"}}}}
    a = ctgov.to_raw_item(payload)
    payload["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"]["date"] = "2026-02-01"
    b = ctgov.to_raw_item(payload)
    assert a.content_hash != b.content_hash


def test_ctgov_query_params():
    seen = {}

    def h(req: httpx.Request):
        seen.update(dict(req.url.params))
        seen["ua"] = req.headers["user-agent"]
        return httpx.Response(200, json={"studies": []})

    http.set_transport(httpx.MockTransport(h))
    try:
        run(ctgov.search_studies(term="KRAS", cond="Pancreatic", intr="ASP3082"))
    finally:
        http.set_transport(None)
    assert seen["query.term"] == "KRAS" and seen["query.cond"] == "Pancreatic"
    assert seen["query.intr"] == "ASP3082"
    assert "protocolSection.outcomesModule" in seen["fields"]
    assert seen["ua"].startswith("ZS-DecisionIntelligence/0.1")


def test_ctgov_phase_labels():
    assert ctgov.phase_label(["PHASE2", "PHASE3"]) == "Phase 2/3"
    assert ctgov.phase_rank("Phase 2/3") == 3
    assert ctgov.phase_label(None) is None


def test_pubmed_esearch_esummary_efetch(mock_sources, monkeypatch):
    monkeypatch.setenv("NCBI_EMAIL", "test@example.org")
    items = run(pubmed.search("ASP3082"))
    assert [i.external_id for i in items] == ["99000001", "99000002"]
    a = items[0]
    assert a.url == "https://pubmed.ncbi.nlm.nih.gov/99000001/"
    assert a.data["doi"] == "10.9999/fake.0001"
    assert "objective response rate was 30%" in a.data["abstract"]
    assert a.kind == "paper_trial"
    assert items[1].kind == "review"


def test_pubmed_sends_tool_and_email(monkeypatch):
    monkeypatch.setenv("NCBI_EMAIL", "ops@example.org")
    seen = []

    def h(req):
        seen.append(dict(req.url.params))
        return httpx.Response(200, json={"esearchresult": {"idlist": []}})

    http.set_transport(httpx.MockTransport(h))
    try:
        assert run(pubmed.search("x", reldate_days=30)) == []
    finally:
        http.set_transport(None)
    assert seen[0]["tool"] == "zs_di" and seen[0]["email"] == "ops@example.org"
    assert seen[0]["sort"] == "pub_date" and seen[0]["reldate"] == "30"


def test_europepmc(mock_sources):
    items = run(europepmc.search("ASP3082"))
    assert len(items) == 2
    c, p = items
    assert c.kind == "congress_abstract"
    assert c.url == "https://europepmc.org/article/MED/99000003"
    assert c.data["doi_url"] == "https://doi.org/10.9999/fake.0003"
    assert p.kind == "preprint" and p.external_id == "PPR:PPR999001"


def test_openalex(mock_sources, monkeypatch):
    monkeypatch.setenv("OPENALEX_MAILTO", "ops@example.org")
    items = run(openalex.search_works("CLDN18.2 bispecific"))
    assert len(items) == 1
    w = items[0]
    assert w.external_id == "W9999000001"
    assert w.url == "https://openalex.org/W9999000001"
    assert w.data["cited_by_count"] == 25
    assert w.data["abstract"].startswith("CLDN18.2 bispecific engagers")
    assert w.data["institutions"] == ["Example University"]


def test_openfda(mock_sources):
    items = run(openfda.search_drug("zolbetuximab"))
    label, appl = items
    assert label.kind == "label_change"
    assert label.url.startswith("https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=")
    assert label.data["effective_time"] == "2026-09-01"
    assert appl.external_id == "appl:BLA761365"
    assert appl.data["submissions"][0]["status_date"] == "2026-08-15"
    assert appl.kind == "approval"
    assert "ApplNo=761365" in appl.url


def test_openfda_not_found_is_empty():
    http.set_transport(httpx.MockTransport(
        lambda r: httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "No matches found!"}})))
    try:
        assert run(openfda.search_drug("nothing")) == []
    finally:
        http.set_transport(None)


def test_astellas_ir_press_and_pdf(mock_sources):
    items = run(astellas_ir.fetch(["ASP3082", "setidegrasib", "ASP2138"]))
    press = [i for i in items if i.data["type"] == "press_release"]
    pdfs = [i for i in items if i.data["type"] == "ir_pdf"]
    assert len(press) == 1  # board-changes release does not mention watch terms
    assert press[0].url == "https://www.astellas.com/en/news/99901"
    assert press[0].published_at == "2026-04-20"
    assert "ASP3082" in press[0].data["terms"]
    assert all(i.kind == "company_ir" for i in items)
    assert len(pdfs) == 1
    pdf = pdfs[0]
    assert pdf.url.endswith("fake_fy2026_q2_presentation.pdf#page=2")
    assert [h["page"] for h in pdf.data["page_hits"]] == [2, 3]
    assert "script must be ignored" not in " ".join(i.text for i in items)


@pytest.mark.parametrize("call", [
    lambda: ctgov.search_studies(intr="ASP3082"),
    lambda: pubmed.search("ASP3082"),
    lambda: europepmc.search("ASP3082"),
    lambda: openalex.search_works("ASP3082"),
    lambda: openfda.search_drug("zolbetuximab"),
    lambda: astellas_ir.fetch(["ASP3082"]),
])
def test_source_unavailable_on_403(blocked_403, call):
    with pytest.raises(SourceUnavailable) as ei:
        run(call())
    assert "403" in ei.value.detail
    assert ei.value.source_key and ei.value.host


def test_retry_then_unavailable_on_503():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(503)

    http.set_transport(httpx.MockTransport(h))
    try:
        with pytest.raises(SourceUnavailable):
            run(ctgov.search_studies(intr="x"))
    finally:
        http.set_transport(None)
    assert calls["n"] == 3  # 1 + 2 retries


def test_retry_recovers_after_429():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"studies": []})

    http.set_transport(httpx.MockTransport(h))
    try:
        assert run(ctgov.search_studies(intr="x")) == []
    finally:
        http.set_transport(None)
    assert calls["n"] == 2


def test_connect_error_is_unavailable():
    def h(req):
        raise httpx.ConnectError("connection refused", request=req)

    http.set_transport(httpx.MockTransport(h))
    try:
        with pytest.raises(SourceUnavailable) as ei:
            run(openalex.search_works("x"))
    finally:
        http.set_transport(None)
    assert ei.value.host == "api.openalex.org"


# ------------------------------------------------------------- transport safety

def _with(handler):
    http.set_transport(httpx.MockTransport(handler))


def test_astellas_redirect_to_foreign_host_rejected():
    def h(req):
        return httpx.Response(302, headers={"location": "https://evil.example.com/news"})
    _with(h)
    try:
        with pytest.raises(SourceUnavailable) as ei:
            run(astellas_ir.fetch(["ASP3082"]))
    finally:
        http.set_transport(None)
    assert "allowlist" in ei.value.detail


@pytest.mark.parametrize("target", ["http://127.0.0.1/admin", "https://169.254.169.254/latest",
                                    "https://10.0.0.5/x", "http://www.astellas.com/en/news"])
def test_astellas_redirect_to_internal_or_http_rejected(target):
    _with(lambda req: httpx.Response(301, headers={"location": target}))
    try:
        with pytest.raises(SourceUnavailable):
            run(astellas_ir.fetch(["ASP3082"]))
    finally:
        http.set_transport(None)


def test_host_allowlist_suffix_check():
    assert astellas_ir.allowed_host("astellas.com") and astellas_ir.allowed_host("www.astellas.com")
    assert not astellas_ir.allowed_host("evilastellas.com")
    assert not astellas_ir.allowed_host("astellas.com.evil.net")


def test_response_size_cap(monkeypatch):
    monkeypatch.setattr(http, "MAX_BYTES", 1000)
    _with(lambda req: httpx.Response(200, content=b"x" * 5000))
    try:
        with pytest.raises(SourceUnavailable) as ei:
            run(http.get_response("t", "https://www.astellas.com/a", max_bytes=1000))
    finally:
        http.set_transport(None)
    assert "exceeds" in ei.value.detail or "too large" in ei.value.detail


def test_astellas_final_url_and_pdf_content_type():
    routes = all_source_routes()
    # press release reached via an in-allowlist redirect -> item.url is the final URL
    routes["www.astellas.com/en/news/99901"] = lambda r: httpx.Response(
        301, headers={"location": "https://newsroom.astellas.com/releases/99901"})
    routes["newsroom.astellas.com/releases/99901"] = text_resp("astellas_press_99901.html")
    # PDF served as HTML -> must be skipped, never parsed
    routes["www.astellas.com/en/system/files/fake_fy2026_q2_presentation.pdf"] = \
        lambda r: httpx.Response(200, text="<html>not a pdf ASP3082</html>",
                                 headers={"content-type": "text/html"})
    http.set_transport(route_transport(routes))
    try:
        items = run(astellas_ir.fetch(["ASP3082", "setidegrasib"]))
    finally:
        http.set_transport(None)
    assert [i.url for i in items] == ["https://newsroom.astellas.com/releases/99901"]


def test_openalex_without_work_id_skipped():
    _with(lambda r: httpx.Response(200, json={"results": [
        {"id": None, "doi": "https://doi.org/10.1/x", "display_name": "no id"}]}))
    try:
        assert run(openalex.search_works("x")) == []
    finally:
        http.set_transport(None)
