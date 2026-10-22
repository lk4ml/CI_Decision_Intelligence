# Decision Intelligence by ZS — Astellas pilot

Live competitive-intelligence agents that move TPP hypotheses for three Astellas programs:

| Workspace | Asset | Indication |
|---|---|---|
| `asp3082-pdac` | Setidegrasib (ASP3082), KRAS G12D degrader | KRAS G12D+ pancreatic cancer |
| `asp3082-nsclc` | Setidegrasib (ASP3082) | KRAS G12D+ NSCLC |
| `asp2138-gc` | ASP2138, CLDN18.2 × CD3 bispecific | CLDN18.2+ gastric / GEJ cancer |

Specs: `docs/PRD.md`, `docs/mockup.html`, `docs/ARCHITECTURE.md` (contract + Addendum A from design review).

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r apps/api/requirements.txt
cd apps/api && ../../.venv/bin/python -m uvicorn app.main:app --port 8000 --workers 1   # one worker: in-process SSE bus
cd apps/web && npm install && npm run build && npx next start -p 3000
```

Open http://localhost:3000. Tests: `cd apps/api && ../../.venv/bin/python -m pytest`.

Env (all optional): `DATABASE_URL` (default SQLite), `DI_DISABLE_SCHEDULER=1`, `NCBI_EMAIL`, `NCBI_API_KEY`,
`OPENALEX_MAILTO`, `DI_LLM_ENABLED=1` + `ANTHROPIC_API_KEY` (LLM-drafted so-what; otherwise rules), `NEXT_PUBLIC_API_URL`.

## Live sources

| Agent | Source | Host |
|---|---|---|
| Registry watch | ClinicalTrials.gov API v2 | clinicaltrials.gov |
| Literature | PubMed E-utilities, Europe PMC | eutils.ncbi.nlm.nih.gov, www.ebi.ac.uk |
| Research graph | OpenAlex | api.openalex.org |
| Regulatory | openFDA labels + Drugs@FDA | api.fda.gov |
| Astellas knowledge | Astellas press releases, IR library PDFs | www.astellas.com |

Agents never substitute data: an unreachable source is recorded as `source_unreachable` and shown in the UI.
Seeds contain configuration only (hypotheses as team beliefs, patterns, levers, watch-list search terms) —
no seeded trials, papers or signals. Model outputs are labelled stand-in assumptions (`apps/api/app/sim/params.py`).

## Safety properties
- Every signal is tied to a fetched item (DB NOT NULL + guardrail host/URL/date checks); no API to create signals or trials.
- LLM (opt-in) only drafts text and direction hints inside `<untrusted_source>` delimiting; rule sign wins; numbers/IDs not in the
  source are blocked; move size always comes from the PRD §7.4 formula; all signals need human review.
- Astellas IR fetcher: https-only exact host allowlist, per-hop redirect checks, private-IP block, 20 MB / 200-page caps.
- Role from `X-Role` header (no auth in this slice; missing header = read-only Reviewer). Lock = owner role or Admin.
- Append-only audit log with hash chain (`GET /api/v1/audit/verify`), DB triggers blocking UPDATE/DELETE.

## Known limits of this slice
No SSO, email digests, PDF (printable HTML brief instead), pgvector (keyword matching), Redis/Arq (in-process APScheduler).
