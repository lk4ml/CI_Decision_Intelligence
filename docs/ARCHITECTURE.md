# Decision Intelligence — Architecture contract (v0.1, 2-hour slice)

Source of truth: `docs/PRD.md` (data/API/backend) and `docs/mockup.html` (UI, copy, layout,
and the inline JS model logic). This file fixes the **contracts** so builders can work in parallel.

## Assets in scope (real Astellas programs)
| code | name | indication | biomarker | phase | slug |
|---|---|---|---|---|---|
| ASP3082-PDAC | Setidegrasib (ASP3082) | Pancreatic ductal adenocarcinoma | KRAS G12D+ | Phase 3 (started Apr 2026) | `asp3082-pdac` |
| ASP3082-NSCLC | Setidegrasib (ASP3082) | Non-small cell lung cancer | KRAS G12D+ | Phase 3 (started Sep 2026) | `asp3082-nsclc` |
| ASP2138-GC | ASP2138 | Gastric / GEJ adenocarcinoma | CLDN18.2+ | Phase 3 (started Aug 2026) | `asp2138-gc` |

Setidegrasib is a KRAS G12D–selective targeted protein degrader. ASP2138 is a CLDN18.2 × CD3
bispecific T-cell engager. Phase/start facts are user-provided and must be **reconciled by the
Registry watch agent** against ClinicalTrials.gov (the UI shows "registry-verified" vs "user-provided").

## Hard rules
1. **No fabricated evidence.** Signals, trials, publications and IR facts come only from live
   connector fetches. Seeds contain *configuration* only: assets, positions, hypotheses (team
   beliefs), patterns, levers, agents, sources, watch-list query terms. No seeded signals or trials.
2. Every signal has `source_url` + `retrieved_at` (Guardrail rejects otherwise → `unmatched_queue`).
3. If a source is unreachable, record an `agent_runs` row with `status="source_unreachable"` and
   the error; the UI shows it. Never substitute mock data in the running app.
4. Test fixtures under `apps/api/tests/fixtures/` are allowed for unit tests only and are never
   loaded by the app.

## Layout
```
apps/api/            FastAPI, Python 3.12+, SQLAlchemy 2, SQLite default (DATABASE_URL for Postgres)
  app/main.py        app factory, CORS, routers under /api/v1, scheduler start
  app/db.py          engine/session, Base, init_db()
  app/models.py      ORM tables (below)            [owner: CORE]
  app/schemas.py     Pydantic response/request      [owner: CORE]
  app/seed.py        3-asset configuration seed     [owner: CORE]
  app/services/      audit.py, review.py, patterns.py, positions.py, events.py (SSE bus) [CORE]
  app/sim/           demand, ptrs, access, feasibility, business, montecarlo   [CORE]
  app/routers/       assets, hypotheses, signals, proposals, patterns, models,
                     scenarios, positions, briefs, agents, sources, events, me  [CORE]
  app/connectors/    http.py, ctgov.py, pubmed.py, europepmc.py, openalex.py,
                     openfda.py, astellas_ir.py                                 [AGENTS]
  app/agents/        pipeline.py, extract.py, match.py, implication.py,
                     guardrail.py, registry.py (agent catalog → runner), scheduler.py [AGENTS]
  tests/
apps/web/            Next.js 15 App Router, TS strict, Tailwind, TanStack Query, Zustand [WEB]
```

## Tables (`app/models.py`) — all have `id` (str uuid4), `created_at`
- `Asset(slug unique, code, name, mechanism, indication, biomarker, phase, phase_source["user"|"registry"], decision_type="TPP", governance_forum, governance_date, descriptor, watch_terms JSON{own:[..], competitors:[..], literature:[..]})`
- `Position(asset_id, line["Population","Intervention","Comparator","Outcomes","Price & access","Timeline"], statement, why, owner_role, contributor_roles JSON, status["provisional","locked","reopened"], version int, hypothesis_codes JSON)`
- `PositionHistory(position_id, version, snapshot JSON, locked_by, locked_at)`
- `Hypothesis(asset_id, code "H1".., statement, category, owner_role, confidence_start float 0-100, confidence float, threshold float, change_trigger_text, keywords JSON)`
- `HypothesisAgent(hypothesis_id, agent_id)`
- `ConfidenceEvent(hypothesis_id, signal_id nullable, delta_proposed, delta_applied, actor, reason, undone bool)`
- `Agent(key unique, name, category["always_on","daily","on_event"], reads["world","company","models"], cadence_minutes nullable, status["running","supervised","planned"], description, source_keys JSON, last_run_at)`
- `AgentRun(agent_id, asset_id nullable, started_at, finished_at, status["ok","source_unreachable","error"], items_fetched, items_new, signals_created, blocked, error)`
- `Source(key unique, name, side["world","company"], kind, base_url, access_level, license_notes, last_fetch_at, last_status)`
- `FetchedItem(source_key, external_id, url, title, content_hash, raw JSON, structured JSON, retrieved_at)` unique(source_key, external_id)
- `Trial(asset_id, nct_id, title, sponsor, phase, status, start_date, primary_completion, enrollment, conditions JSON, interventions JSON, endpoints JSON, role["own","competitor","standard"], source_url, retrieved_at)` unique(asset_id, nct_id)
- `Signal(asset_id, agent_id, title, so_what, source_name, source_url NOT NULL, retrieved_at NOT NULL, published_at, impact["high","normal"], review_status["pending","applied","dismissed"], reviewer, fetched_item_id)`
- `SignalMove(signal_id, hypothesis_id, delta int, weight float, rationale)`
- `UnmatchedItem(fetched_item_id, reason)`
- `Pattern(asset_id, key, title, position_line, trigger expr, trigger_text, rationale, options JSON[{lever,value,label}], is_fired bool)`
- `ProposedDecision(pattern_id, fired_at, cleared_at nullable, hypothesis_codes JSON, signal_ids JSON)`
- `Scenario(asset_id, name, levers JSON, hypothesis_snapshot JSON, outputs JSON, model_versions JSON)`
- `Brief(asset_id, version str, snapshot JSON, exported_by)`
- `AuditEvent(actor, action, entity, entity_id, before_hash, after_hash, payload JSON, prev_hash, hash)` — append-only, hash chain

## Confidence math (PRD §7.4/7.5)
`delta = clamp(round(base_strength × reliability × relevance × 10), -10, 10)`, sign from support/contradict.
`confidence = clamp(start + Σ applied non-undone deltas, 5, 95)`. Position confidence = mean of its hypotheses.
Threshold crossing from below → position `reopened`, audit + SSE `position.reopened`.
Pattern trigger: `simpleeval` over names `H1..Hn` (confidence as 0–1 fraction) and `crossed_Hn`, `levers_<name>`.

## API (`/api/v1`) — response shapes the web app relies on
- `GET /assets` → `[{id,slug,code,name,indication,biomarker,phase,phase_source}]`
- `GET /assets/{slug}` → asset + `{counts:{hypotheses,pending_signals,proposals,locked_positions}}`
- `GET /assets/{slug}/brief` → `{rows:[{label,value,step}]}`
- `GET /assets/{slug}/focus` → `{kind:"pattern"|"signal"|"none", title, detail, link_step}`
- `GET /assets/{slug}/trials` → `[Trial]`  (empty + `last_run` status if registry unreachable)
- `GET /assets/{slug}/changes?role=` → `{lede, pending_signals, moved_hypotheses, fired_patterns, reopened_positions}`
- `GET /assets/{slug}/hypotheses` → `[{id,code,statement,category,owner_role,confidence,confidence_start,threshold,change_trigger_text,for_count,against_count,week_delta,agents:[{id,key,name,cadence_minutes,status}],evidence:[{signal_id,title,delta,source_name,source_url,retrieved_at}]}]`
- `POST /assets/{slug}/hypotheses`, `PATCH /hypotheses/{id}`, `POST|DELETE /hypotheses/{id}/agents/{agent_id}`
- `GET /assets/{slug}/signals?status=` → `[{id,title,so_what,impact,agent:{key,name},source_name,source_url,retrieved_at,published_at,review_status,moves:[{hypothesis_code,delta,rationale}]}]`
- `POST /signals/{id}/apply` (body `{overrides?:{H1:4}, reason?, actor}`), `/dismiss`, `/undo`; `POST /assets/{slug}/signals/apply-all`
- `GET /assets/{slug}/proposals` → `[{id,pattern:{key,title,position_line,trigger_text,rationale},framing:"take"|"frame",hypotheses:[..],signals:[..],options:[{label,lever,value,results:{patients,ptrs,peak,readout,us_net}}]}]`
- `GET /assets/{slug}/patterns` → all patterns with `is_fired`
- `GET /assets/{slug}/levers` → `{schema:[{name,label,type:"select"|"toggle",options?}], defaults:{}}`
- `POST /models/run` `{asset, levers}` → `{demand,ptrs,access,feasibility,business}` each `{kpis:[{label,value,unit}], series:..., reading}`
- `POST /models/montecarlo` `{asset, levers, n=500}` → `{peak:{p10,p50,p90}, rnpv:{...}, histogram:[..], negative_share}`
- `GET /models/registry` → `[{name,reads,returns,engine,version}]`
- `POST /assets/{slug}/scenarios`, `GET /assets/{slug}/scenarios`
- `GET /assets/{slug}/positions` → `[{id,line,statement,why,owner_role,contributor_roles,status,version,confidence,hypotheses:[{code,confidence,owner_role}]}]`
- `POST /positions/{id}/lock` `{actor, role}` (403 unless owner_role or Admin)
- `POST /assets/{slug}/briefs` → `{id,version}`; `GET /briefs/{id}` → JSON; `GET /briefs/{id}.html` printable
- `GET /agents` (with `last_run`), `GET /agents/status` → `{by_category:{..}, next_cycle_at}`, `PATCH /agents/{id}`, `POST /agents/{id}/run?asset=` (runs synchronously, returns AgentRun), `POST /agents`
- `GET /sources`, `GET /sources/{key}`
- `GET /events/recent?asset=` → last 50 audit/agent events; `GET /events/stream?asset=` SSE (`event: <type>`, `data: json`)
- `GET /stats/landing` → `{sources_refreshed_1h, agents_running}`
- `GET /health` → `{ok:true}`

## Agent catalog (keys) and live sources
| key | category | sources | does |
|---|---|---|---|
| registry_watch | always_on 6h | ctgov | own trials + competitor trials per watch_terms → `Trial` rows; new/changed trials → signals (Phase 3 start, status change, completion date move) |
| literature | always_on 6h | pubmed, europepmc | new papers/abstracts on watch terms |
| research_graph | daily | openalex | citation/topic momentum, new works by key authors/institutions |
| regulatory | always_on 6h | openfda | label changes/approvals for competitor & standard-of-care drugs |
| astellas_ir | daily | astellas_ir | Astellas pipeline page, press releases, earnings/FY presentation PDFs → company-knowledge signals (require `validated_by` before visible? pilot: visible, tagged "company") |
| implication | on_event | — | so-what + proposed moves |
| guardrail | on_event | — | blocks unsourced claims |
| simulation | on_event | — | re-prices fired pattern options |
| brief | on_event | — | brief export |

Connectors: async `httpx`, UA `ZS-DecisionIntelligence/0.1 (contact: admin)`, timeout 20s, honour
`REQUESTS_CA_BUNDLE`/`SSL_CERT_FILE`, raise `SourceUnavailable(host, detail)` on network/4xx/5xx.
NCBI: `tool=zs_di&email=` from env `NCBI_EMAIL`, ≤3 req/s. OpenAlex: `mailto` from env.

## Implication agent
Rule-based by default (keywords per hypothesis + base_strength by item kind + reliability by
source). If `ANTHROPIC_API_KEY` is set, call Claude (`claude-sonnet-5-5`) with a JSON schema for
`{so_what, moves:[{hypothesis_code, direction, relevance, rationale}]}`; validate with Pydantic;
fall back to rules on any failure. LLM output never sets numbers directly — delta always comes
from the §7.4 formula.

## Web routes (PRD §4)
`/`, `/app/[asset]/{asset,changes,hypotheses,signals,workbench,simulate,positions}`, `/app/[asset]/studio`.
API base from `NEXT_PUBLIC_API_URL` (default `http://localhost:8000/api/v1`).

## Addendum A (architecture review, binding — supersedes conflicting lines above)
1. **Per-asset model config.** `Asset.lever_schema JSON`, `Asset.model_params JSON` =
   `{bindings:{role_name:"Hn"}, inputs:{name:{value,unit,basis:"stand_in_assumption"|"sourced",source_url?}}}`.
   `/levers` and `/models/*` read these. Every KPI carries `basis`; UI labels stand-in values. Mockup H1–H10 / 7 patterns are
   CLDN18.2-only: do not copy into KRAS assets. `/models/registry` → `engine:"stand_in"` for all five.
2. `Hypothesis.position_line` (one of the 6 lines, NOT NULL); position's hypotheses are derived from it (drop `Position.hypothesis_codes`).
   Category enum `Population|Intervention|Comparator|Outcomes|Business`.
3. **Server lever state.** `Asset.current_levers JSON` (defaults from lever_schema). `PUT /assets/{slug}/levers {levers}` → audit,
   patterns.evaluate, SSE `levers.updated`. `Position.statement_template` rendered with levers + model outputs.
   Trigger namespace exactly: `H1..Hn` (0–1), `crossed_H1..`, `levers_<name>`.
4. `Hypothesis.crossed bool`, `crossed_at`; recompute after apply/undo/threshold PATCH. `ProposedDecision.framing ("take"|"frame")`,
   `total_movement`. Un-crossing does not un-reopen; reopened stays until re-locked.
5. **Provenance.** `Signal.fetched_item_id` NOT NULL; guardrail asserts source_url/retrieved_at equal the FetchedItem's and the URL
   host matches the Source host. `Signal.so_what_origin "rules"|"llm"`; LLM so_what blocked if it contains a number/NCT/PMID absent from
   the fetched raw/structured. No `POST /signals`, no manual trial create. `UnmatchedItem.asset_id`; `GET /assets/{slug}/unmatched`.
6. **Coverage envelope.** `/trials`, `/signals` return `{items:[...], coverage:{status:"ok"|"source_unreachable"|"never_run",
   last_run:{agent_key,finished_at,error}|null}}`. `Source.last_error`, `last_ok_at`. `AgentRun.summary` = agent card "current activity"
   ("Not yet run" if none). `sources_refreshed_1h` counts only ok runs.
7. **Lock.** body `{scenario_id?}`; if absent run Monte Carlo on current_levers. `PositionHistory.snapshot =
   {statement, levers, hypotheses:[{code,confidence,threshold}], signal_ids, scenario:{id,peak:{p10,p50,p90},rnpv:{..}}, model_versions,
   audit_head_hash}`. `GET /positions/{id}/history`.
8. **Explore parity.** proposal `options[]` include `levers` (full dict), `is_current`, `results` computed by the same deterministic
   function as `POST /models/run`.
9. Extra endpoints: `POST /assets` (onboard → 6 empty positions), `GET /assets/{slug}/digest?role=` (render only),
   `demand.series.pools` in `/models/run`, `GET /me` → `{actor, role}`, `GET /agents/{id}` (+hypothesis_ids, governance_notes),
   `GET /sources/{key}` (+agent_keys), `GET /audit/verify` → `{ok,length,head_hash}`.
10. **Roles.** Enum `"Asset lead","Clinical","Access & pricing","Forecasting","Operations","Reviewer","Admin"`. No auth in slice:
    mutations read `X-Actor` and `X-Role` headers. Enforce: lock = owner_role or Admin (403); apply/dismiss = owns a moved hypothesis or
    Asset lead/Admin (403); apply-all scoped to role's hypotheses; Reviewer is read-only. `ROLE_DEFAULTS` (Clinical → ptrs tab, etc.).
11. **Append-only.** Undo appends a compensating ConfidenceEvent (`reverts_event_id`); confidence = clamp(start + Σ events).
    `AuditEvent.ts`; hash = sha256(canonical JSON sorted keys + prev_hash); process-wide lock on audit writes. 409 on apply/dismiss of a
    non-pending signal and undo of a pending one.
12. Scheduler runs distinct (agent, asset) pairs from HypothesisAgent; `POST /hypotheses` enqueues immediate run for attached agents and
    returns `scheduled:[{agent_key,run_at}]`. `Asset.registry_phase`, `registry_nct_ids JSON`, `registry_checked_at`,
    `phase_discrepancy`; phase_source stays "user" until registry confirms.
13. Brief = printable HTML (pilot substitute for PDF) incl. citations (url+retrieved_at), alternatives, change_trigger_text.
    Run uvicorn with `--workers 1` (in-process SSE bus). SSE payload `{asset_slug, entity, id, ...}`.
