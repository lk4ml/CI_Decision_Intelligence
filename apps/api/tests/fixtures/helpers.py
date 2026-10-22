"""Helpers for connector/agent tests. Everything here is SYNTHETIC and test-only."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import httpx

FIXTURES = Path(__file__).parent


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def load_json(name: str) -> dict:
    return json.loads(load(name))


def make_pdf(pages: list[str]) -> bytes:
    """Build a tiny valid PDF (Helvetica text, one line per page). SYNTHETIC."""
    objs: list[bytes] = []
    n = len(pages)
    font_id = 3 + 2 * n
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    for i, text in enumerate(pages):
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 10 Tf 40 700 Td ({safe}) Tj ET".encode()
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode())
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def route_transport(routes: dict[str, Callable[[httpx.Request], httpx.Response]] | None = None,
                    default_status: int | None = None) -> httpx.MockTransport:
    """MockTransport dispatching on host+path prefix (longest match wins)."""
    routes = routes or {}

    def handler(req: httpx.Request) -> httpx.Response:
        key = f"{req.url.host}{req.url.path}"
        best = None
        for prefix in routes:
            if key.startswith(prefix) and (best is None or len(prefix) > len(best)):
                best = prefix
        if best is not None:
            return routes[best](req)
        if default_status is not None:
            return httpx.Response(default_status, text="blocked by test proxy")
        return httpx.Response(404, text="no fixture route")

    return httpx.MockTransport(handler)


def json_resp(name: str):
    return lambda req: httpx.Response(200, json=load_json(name))


def text_resp(name: str, content_type: str = "text/html"):
    return lambda req: httpx.Response(200, text=load(name), headers={"content-type": content_type})


def all_source_routes() -> dict:
    pdf = make_pdf(["FY2026 Q2 highlights", "Pipeline: setidegrasib (ASP3082) Phase 3 started in PDAC",
                    "ASP2138 Phase 1b expansion ongoing"])
    return {
        "clinicaltrials.gov/api/v2/studies": json_resp("ctgov_studies.json"),
        "eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi": json_resp("pubmed_esearch.json"),
        "eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi": json_resp("pubmed_esummary.json"),
        "eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi": text_resp("pubmed_efetch.xml", "text/xml"),
        "www.ebi.ac.uk/europepmc/webservices/rest/search": json_resp("europepmc_search.json"),
        "api.openalex.org/works": json_resp("openalex_works.json"),
        "api.fda.gov/drug/label.json": json_resp("openfda_label.json"),
        "api.fda.gov/drug/drugsfda.json": json_resp("openfda_drugsfda.json"),
        "www.astellas.com/en/news/99901": text_resp("astellas_press_99901.html"),
        "www.astellas.com/en/news/99902": text_resp("astellas_press_99902.html"),
        "www.astellas.com/en/news": text_resp("astellas_news.html"),
        "www.astellas.com/en/investors/ir-library": text_resp("astellas_ir_library.html"),
        "www.astellas.com/en/investors/financial-results": lambda r: httpx.Response(404, text="gone"),
        "www.astellas.com/en/system/files/fake_fy2026_q2_presentation.pdf":
            lambda r: httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"}),
        "www.astellas.com/en/system/files/fake_governance.pdf":
            lambda r: httpx.Response(200, content=make_pdf(["Governance only"]),
                                     headers={"content-type": "application/pdf"}),
    }
