# Decision Intelligence by ZS — Product Requirements Document

**Version** 1.0 · **Status** Frozen against mockup `ci_decision_space_final.html` · **Owner** ZS product team · **Client** Astellas R&D (pilot: ASP-C2, CLDN18.2, TPP/CDP decision)

**Stack:** Next.js 15 (App Router, TypeScript) · FastAPI (Python 3.12) · PostgreSQL 16 + pgvector · Redis · Arq workers · SSE for live agent activity

---

## 1. Summary

Decision Intelligence turns competitive intelligence into governed R&D decisions. A team registers the hypotheses behind a decision (for the pilot, a Target Product Profile), attaches agents that watch public sources and the company's own knowledge, lets evidence move the hypotheses, and gets decisions *proposed* when hypotheses move in combination. Five linked models price the options; six positions are locked with an auditable trail and exported to governance.

The mockup is the specification for behavior, copy and layout. Where this document and the mockup disagree, the mockup wins for UI; this document wins for data, API and backend behavior.

### 1.1 Goals (pilot, 12 weeks)
1. One live decision workspace (ASP-C2 TPP) running on real sources with supervised agents.
2. Every number on screen traceable to a signal, a hypothesis confidence, or a named model parameter.
3. A committee brief exported from Positions that a reviewer can audit without the team present.

### 1.2 Non-goals (pilot)
- Replacing Astellas forecasting, PTRS or feasibility engines (we integrate; model stubs allowed behind the interface).
- Multi-tenant SaaS, billing, public sign-up.
- Autonomous (unreviewed) confidence changes — all agent proposals are reviewed until precision metrics clear the bar (§7.6).

### 1.3 Success metrics
| Metric | Target | Where measured |
|---|---|---|
| Signal precision (accepted ÷ surfaced) | ≥ 80% by week 8 | `signals` table, `review_action` |
| Signals surfaced before the team found them elsewhere | ≥ 5 per month | manual tag `found_first=true` |
| Time from material signal to re-locked position | ≤ 10 business days | `positions_history` |
| Assembly hours removed per brief | ≥ 50% vs baseline | team survey + `brief_generation` timing |
| Guardrail blocks on unverifiable claims | 100% of unsourced claims blocked | `audit_events` |

---

## 2. Users and roles

Roles are workspace-scoped. A person can hold different roles on different assets.

| Role | Owns | Default view | Can |
|---|---|---|---|
| Asset lead | Decision, Population/TA positions | Business case | Register hypotheses, lock any position, export brief, onboard assets |
| Clinical | Intervention, Comparator, Outcomes positions | PTRS | Register/own hypotheses on those lines, lock those positions |
| Access & pricing | Price & access position | Price & access | Same, on that line |
| Forecasting | Testing/demand hypotheses | Population & demand | Same |
| Operations | Timeline position | Feasibility | Same |
| Reviewer (read-only) | — | Positions | View, comment, export |
| Admin | — | Agent Studio | Manage agents, cadences, sources, users |

**Authorization rule:** a position can only be locked by its owner role or Admin. Any role may apply/dismiss a signal on hypotheses they own; Asset lead and Admin may do so on all.

---

## 3. Domain model and glossary

| Entity | Definition | Key fields |
|---|---|---|
| **Asset** | A program under a decision (e.g., ASP-C2) | code, name, mechanism, indication, phase, decision_type, governance_forum, governance_date, owner_role |
| **Decision** | The question a governance forum will rule on; one per asset per decision_type | type (TPP/CDP, TA/DA, Protocol, Feasibility, BD), status |
| **Position** | One line of the decision (TPP: Population, Intervention, Comparator, Outcomes, Price & access, Timeline) | statement, owner_role, contributor_roles, status (provisional / locked / reopened), confidence (derived), version |
| **Hypothesis** | A falsifiable belief about the world at launch, tied to one position | statement, category (P/I/C/O/Business), owner_role, confidence_start, confidence, threshold, change_trigger_text, attached_agent_ids |
| **Signal** | A detected change with a "so what" and proposed moves | title, so_what, source (name, url, retrieved_at), agent_id, impact (high/normal), proposed_moves[{hypothesis_id, delta, weight}], review_status (pending/applied/dismissed), reviewer |
| **Confidence event** | An applied or overridden move on a hypothesis | hypothesis_id, signal_id, delta_proposed, delta_applied, actor, reason |
| **Agent** | A configured worker | name, category (always_on / daily / on_event), reads (world / company / models), cadence, sources[], status (running / supervised / planned), description |
| **Pattern** | A rule over hypothesis states that proposes a decision | title, position_id, trigger (expression), options[{lever, value, label}], rationale |
| **Proposed decision** | A fired pattern with its evidence chain and priced options | pattern_id, fired_at, hypothesis_ids, signal_ids, options_results |
| **Scenario run** | A Monte Carlo evaluation of a lever set | levers, hypothesis_snapshot, n, outputs (P10/P50/P90 per metric), model_versions |
| **Brief** | Versioned export of positions + evidence + alternatives | version, positions_snapshot, hypotheses_snapshot, signals, scenarios, exported_by |
| **Audit event** | Immutable log entry | actor (user/agent), action, entity, before/after hash, timestamp |

---

## 4. Information architecture

```
/                      Landing (public to authenticated org users)
/app                   Redirects to last asset
/app/[asset]           Workspace shell (sidebar + topbar + 7-step journey)
  /asset               01 Asset context
  /changes             02 What's changed
  /hypotheses          03 Hypothesis tracking
  /signals             04 Signals
  /workbench           05 Decision workbench
  /simulate            06 Simulate
  /positions           07 Positions
/app/[asset]/studio    Agent Studio (three columns)
/app/onboard           Onboard asset (drawer, also reachable from sidebar)
```

**Shell (persistent):** sidebar — product mark, Workspace nav (Decision workspace / Agent Studio), running-agents panel, Your assets list, `+ Onboard asset`, Viewing-as role selector, demo/environment notice. Topbar — breadcrumb, environment label, date, theme selector, Share, Overview, avatar.

**Journey strip:** seven steps, numbered, title + question. Active step has a 2px accent top rule and tinted background. Badge counts: hypotheses, pending signals, proposed decisions, locked positions.

---

## 5. Functional requirements by screen

Every row names the Next.js component that renders the action and the FastAPI endpoint that serves it. Components live under `apps/web/src/components/<screen>/`; endpoints under `apps/api/app/routers/`.

### 5.1 Landing (`/`)

| # | Requirement | Frontend | Backend |
|---|---|---|---|
| L1 | Hero with product name, lead, live eyebrow "Always-on agents refreshed N sources in the last hour" | `landing/Hero.tsx` (Server Component) | `GET /stats/landing` → `{sources_refreshed_1h, agents_running}` |
| L2 | Framed preview of top hypotheses and proposed decisions for the default asset | `landing/Preview.tsx` | `GET /assets/{id}/summary` |
| L3 | CTA "Open the CLDN18.2 program" → `/app/<asset>/asset`; "Request access" opens form → email to admins | `landing/Cta.tsx`, `AccessRequestDialog.tsx` | `POST /access-requests` |
| L4 | Four pillars, five decision types (TPP live, others template) | static MDX | — |
| L5 | Theme selector (system / light / dark), persisted per user | `ThemeSelect.tsx` using `next-themes` | `PATCH /me/preferences` |

### 5.2 Shell

| # | Requirement | Frontend | Backend |
|---|---|---|---|
| S1 | Sidebar asset list; selecting switches all steps to that asset | `shell/Sidebar.tsx`, route param `[asset]` | `GET /assets` |
| S2 | Running-agents panel: counts by category, next cycle countdown | `shell/RunningAgents.tsx` (client, subscribes to SSE) | `GET /agents/status`, `GET /events/stream` (SSE) |
| S3 | Viewing-as role selector; changes default model tab, hypothesis ordering, digest copy. Does **not** change permissions (permissions come from auth) | `shell/RoleSelect.tsx` → Zustand `viewRole` | `GET /me` returns assigned roles per asset |
| S4 | `+ Onboard asset` opens drawer form | `shell/OnboardDrawer.tsx` (`Sheet` from shadcn) | `POST /assets` |
| S5 | Topbar breadcrumb from asset; Share copies a read-only link | `shell/Topbar.tsx` | `POST /share-links` → token with `reviewer` scope |
| S6 | Environment notice text from config | `shell/EnvNotice.tsx` | `GET /config/public` |

### 5.3 Step 01 — Asset context

| # | Requirement | Frontend | Backend |
|---|---|---|---|
| A1 | Eyebrow, title, one-line descriptor from asset record | `asset/AssetHeader.tsx` | `GET /assets/{id}` |
| A2 | Asset brief: target population, mechanism, program status, what it must show, monitoring scope; each row links to a step | `asset/BriefRows.tsx` | `GET /assets/{id}/brief` (derived: hypotheses count, agents attached) |
| A3 | Today's focus: top fired pattern → else top pending high-impact signal → else "no open decision" | `asset/TodaysFocus.tsx` | `GET /assets/{id}/focus` |
| A4 | Trial landscape timeline (Gantt 2025–2032): own trials, approved standard, competitors; hover tooltip (phase, line, n, completion quarter, endpoints, relevance); click opens detail panel | `asset/TrialTimeline.tsx` (SVG, `@visx/scale`), `TrialTooltip.tsx`, `TrialDetail.tsx` | `GET /assets/{id}/trials` — populated by Registry watch agent; manual edits allowed |
| A5 | Patient pools at each cutoff, computed by the demand model with current H2 confidence | `asset/PatientPools.tsx` | `POST /models/demand/pools` |
| A6 | Empty states for newly onboarded assets (no trials, no pools, no hypotheses) | `EmptyState.tsx` | — |

### 5.4 Step 02 — What's changed

| # | Requirement | Frontend | Backend |
|---|---|---|---|
| C1 | Role-specific lede | `changes/Lede.tsx` | `GET /assets/{id}/changes?role=` |
| C2 | Four rows with counts and one action each: signals waiting (for your hypotheses), hypotheses you own that moved ≥8 pts, decisions proposed, positions reopened | `changes/TodoList.tsx` | same endpoint returns `{pending_signals, moved_hypotheses, fired_patterns, reopened_positions}` |

### 5.5 Step 03 — Hypothesis tracking

| # | Requirement | Frontend | Backend |
|---|---|---|---|
| H1 | Grouped list by category; groups and rows the viewer owns sort first; others dimmed | `hypotheses/HypothesisList.tsx` | `GET /assets/{id}/hypotheses` |
| H2 | Row: ID, statement, owner, for/against counts, attached agent chips, confidence bar + number, movement this week. Whole row clickable (Enter/Space too) | `HypothesisRow.tsx` | — |
| H3 | Detail: evidence trail (newest first, +/− with source and date), threshold editor, "what would change my mind", agents on this hypothesis (animated running indicator, cadence, current activity), attach/detach chips | `HypothesisDetail.tsx`, `AgentRunner.tsx` | `PATCH /hypotheses/{id}` (threshold), `POST/DELETE /hypotheses/{id}/agents/{agent_id}` |
| H4 | "How this works" collapsible: what / who owns / how it updates | `HowItWorks.tsx` (shared) | content from `GET /help/{screen}` |
| H5 | Register hypothesis drawer: statement, position, owner, starting confidence, threshold, change trigger, attach agents (chips with cadence), inline "draft a new agent" | `RegisterHypothesisDrawer.tsx` | `POST /assets/{id}/hypotheses`; `POST /agents` (if drafted) |
| H6 | Validation: statement ≥ 20 chars; threshold > starting confidence; at least one agent recommended (warn, not block) | `zod` schema `hypothesisSchema` | Pydantic model mirrors |

### 5.6 Step 04 — Signals

| # | Requirement | Frontend | Backend |
|---|---|---|---|
| G1 | Feed grouped by day, newest first; only signals touching a hypothesis in this asset | `signals/SignalFeed.tsx` | `GET /assets/{id}/signals?status=` |
| G2 | Card: impact tag, agent that found it, source, title, so-what, proposed moves per hypothesis, Apply / Dismiss, Undo after action | `SignalCard.tsx` | `POST /signals/{id}/apply`, `POST /signals/{id}/dismiss`, `POST /signals/{id}/undo` |
| G3 | Apply writes `confidence_event`s, recomputes derived confidences, evaluates thresholds and patterns, emits SSE | — | service `review_signal()` → `patterns.evaluate()` |
| G4 | "Apply all remaining" (owner-scoped) | `ApplyAllButton.tsx` | `POST /assets/{id}/signals/apply-all` |
| G5 | Digest preview (collapsible email render) for the viewer's role | `DigestPreview.tsx` | `GET /assets/{id}/digest?role=` (same renderer used by the mailer) |
| G6 | Notification rules per user: immediate for high impact, daily digest at 07:00 local, threshold alerts, weekly summary | `NotificationRules.tsx` (in user settings) | `PATCH /me/notifications`; mailer job |

### 5.7 Step 05 — Decision workbench

| # | Requirement | Frontend | Backend |
|---|---|---|---|
| W1 | Lede with counts; "How this works" | `workbench/Lede.tsx` | `GET /assets/{id}/proposals` |
| W2 | Proposed decision card per fired pattern, ordered: threshold-crossed first, then total movement | `ProposalCard.tsx` | proposals include `hypotheses[]`, `signals[]`, `trigger_text`, `rationale` |
| W3 | Framing: "Decision to take" if any hypothesis crossed threshold, else "Decision to frame" | `ProposalFraming.tsx` | — |
| W4 | Trigger line: the expression that fired, quoted from the hypotheses' change triggers | `TriggerLine.tsx` | — |
| W5 | Evidence chain as a vertical flow line (signal, agent, source, date, per-hypothesis deltas) | `EvidenceFlow.tsx` | — |
| W6 | "How it got here": agents involved with counts; Implication, Simulation, Guardrail roles | `Provenance.tsx` | — |
| W7 | Options table priced with today's confidences (patients, PTRS, peak, readout, US net); current option highlighted; Explore sets levers and opens Simulate | `OptionsTable.tsx` → Zustand `levers` | `POST /models/evaluate` with `{levers[], hypothesis_snapshot}` |
| W8 | Actions: Take to positions, Open full simulation | — | — |
| W9 | "Patterns not yet fired" list with their trigger thresholds | `PatternsPending.tsx` | `GET /patterns?asset=` |

### 5.8 Step 06 — Simulate

| # | Requirement | Frontend | Backend |
|---|---|---|---|
| M1 | Lever row: cutoff, comparator, endpoint, footprint; toggles dose cohort, pancreatic cohort, biologic. Reset | `simulate/Levers.tsx` | lever schema from `GET /assets/{id}/levers` |
| M2 | Model tabs: Population & demand, PTRS, Price & access, Feasibility, Business case; default tab by role | `ModelTabs.tsx` | — |
| M3 | Each model view renders KPIs + model-specific visual (funnel, build-up, markets, country table, histogram) and a "reading" paragraph | `models/*.tsx`, Recharts | `POST /models/run` returns all five models for a lever set; `POST /models/montecarlo` (n=500) |
| M4 | "Models underneath" table: reads / returns / engine (real vs stand-in) per model | `ModelsUnderneath.tsx` | `GET /models/registry` |
| M5 | Save current configuration as an option; appears in Positions alternatives and Brief | `SaveOptionButton.tsx` | `POST /assets/{id}/scenarios` |

### 5.9 Step 07 — Positions

| # | Requirement | Frontend | Backend |
|---|---|---|---|
| P1 | Legend: Provisional / Locked / Reopened definitions | static | — |
| P2 | Six position rows: line, hypotheses, statement (templated from levers + model outputs), why, owner + contributors + hypotheses with owners, confidence, status, action | `positions/PositionRow.tsx` | `GET /assets/{id}/positions` |
| P3 | Lock (owner only): versions the position with hypothesis confidences, scenario ranges, signal ids | `LockButton.tsx` | `POST /positions/{id}/lock` |
| P4 | Reopen automatically when any hypothesis behind it crosses threshold; shows flag and "Review and lock" | service `positions.recompute()` on confidence events | SSE `position.reopened` |
| P5 | Export TPP vX.Y: brief PDF + JSON | `ExportButton.tsx` | `POST /assets/{id}/briefs` → async job → `GET /briefs/{id}` (PDF via WeasyPrint) |

### 5.10 Agent Studio (`/studio`)

| # | Requirement | Frontend | Backend |
|---|---|---|---|
| T1 | Three columns: World knowledge sources · Agents (grouped Always-on / Daily / On event) · Company knowledge sources, with legend (running / supervised / planned) | `studio/Studio.tsx`, `SourceCard.tsx`, `AgentCard.tsx` | `GET /sources`, `GET /agents` |
| T2 | Agent card: name, running animation, description, reads/attached/cadence footer. Click → inspector drawer (cadence editable, Run now, attached hypotheses, governance notes) | `AgentInspectorDrawer.tsx` | `PATCH /agents/{id}` (cadence), `POST /agents/{id}/run` |
| T3 | Draft a new agent drawer: name, category, reads, description, attach to hypotheses. New agents start `supervised` | `NewAgentDrawer.tsx` | `POST /agents` |
| T4 | Activity log streaming (last 14 events, new ones highlighted) | `ActivityLog.tsx` (SSE) | `GET /events/stream?asset=` |
| T5 | Source card click → source inspector (access level, agents reading it, last fetch, license notes) | `SourceInspectorDrawer.tsx` | `GET /sources/{id}` |

---

## 6. Decision patterns engine

Patterns turn hypothesis state into proposed decisions. They are data, not code, so the team can add them from Admin.

```json
{
  "id": "broaden_population",
  "title": "Broaden the label population",
  "position": "Population",
  "trigger": "H1.conf >= 0.65 and H2.conf >= 0.60",
  "trigger_text_from": ["H1", "H2"],
  "rationale": "Broad expression is becoming the standard and testing is catching up...",
  "options": [
    {"lever": "cutoff", "value": "75", "label": "Keep ≥75%, defend on effect size"},
    {"lever": "cutoff", "value": "50", "label": "Hedge at ≥50%"},
    {"lever": "cutoff", "value": "1",  "label": "Go broad, ≥1%"}
  ]
}
```

- Triggers are evaluated by a safe expression evaluator (`simpleeval`) over `{Hn.conf, Hn.crossed, levers.*}` after every confidence event and lever change.
- A pattern **fires** when the expression is true and it was false at the previous evaluation; it **clears** when false. Both are audit events.
- Firing creates a `proposed_decision` and queues a Simulation job for its options.
- Pilot ships the seven patterns in the mockup; Admin UI for patterns is Phase 2.

---

## 7. Agents and pipelines

### 7.1 Categories and cadence
| Category | Default cadence | Examples | Trigger |
|---|---|---|---|
| Always-on | every 6h (1h–weekly configurable) | Registry watch, Congress & literature, Regulatory & HTA, Market & deals | Arq cron |
| Daily | 07:00 workspace-local | Institutional memory, Portfolio memory | Arq cron |
| On event | — | Implication (on new signal), Simulation (on confidence/lever change), Brief (on request), Guardrail (on every write) | Redis pub/sub |

### 7.2 Pipeline (always-on)
1. **Fetch** source with change detection (ETag / content hash / registry `lastUpdatePostDate`). Only deltas proceed.
2. **Extract** structured facts (cutoff, comparator, endpoint, n, sites, dates) with LLM + schema validation (Pydantic). Store raw and structured with `source_url`, `retrieved_at`.
3. **Match** against hypotheses: embedding similarity (pgvector) on hypothesis statement + change trigger, plus rule hints per agent (e.g., Registry watch → H1/H7/H10 keys).
4. **Implication agent** writes the so-what, proposes `delta = strength × reliability × relevance` (§7.4), assigns impact.
5. **Guardrail agent** validates: every claim has a source URL and retrieval date; blocked items go to `unmatched_queue` with reason.
6. **Emit** `signal.created` → SSE, notifications per user rules.

### 7.3 Company-knowledge agents
- Read only from authorized connectors (SharePoint/Box folders, RWE warehouse views, forecast archive) via service accounts with role-based scopes.
- Medical/forecasting validation flag required before a signal from these agents is visible to the team (`validated_by`).

### 7.4 Confidence move sizing
`delta = round(base_strength × reliability × relevance × 10)`, clamped to ±10, where
- `base_strength`: Phase 3 start / approval / guideline = 1.0; Phase 2 readout / HTA decision = 0.8; treatment-pattern shift = 0.6; press / investor call = 0.3; ad-board theme = 0.5.
- `reliability`: registry / regulator / guideline = 1.0; peer-reviewed / congress = 0.9; licensed dataset = 0.8; press = 0.5; internal validated = 0.9.
- `relevance`: cosine similarity bucketed to 1.0 / 0.7 / 0.4.
Sign comes from the Implication agent's support/contradict classification. Owner may override; override and reason are logged.

### 7.5 Confidence and positions
- `hypothesis.confidence = clamp(start + Σ applied deltas, 5, 95)`.
- `position.confidence = mean(confidence of hypotheses on that line)`.
- Threshold crossing (`conf ≥ threshold` transitioning from below) sets position `reopened` and emits a notification; a locked position remains in history as a prior version.

### 7.6 Supervision policy
All agents start `supervised`: proposals require review. An agent may be promoted to auto-apply **routine** moves (|delta| ≤ 4, impact normal) when its 8-week rolling precision ≥ 80% and recall gaps ≤ 2/month. Threshold crossings and high-impact signals always require review.

---

## 8. Simulation models

Each model is a Python class behind a common interface so stand-ins can be swapped for Astellas engines without UI change.

```python
class Model(Protocol):
    name: str
    version: str
    engine: Literal["stand_in", "astellas", "vendor"]
    def run(self, levers: Levers, params: HypothesisParams, rng: np.random.Generator | None) -> ModelOutput: ...
```

| Model | Reads (levers · hypotheses) | Returns | Pilot engine |
|---|---|---|---|
| Population & demand | cutoff, footprint · H2 testing, H7 competitor-first, H5 payload | funnel stages, share, patients on drug | stand-in → Astellas forecast via adapter |
| PTRS | cutoff, endpoint, comparator, dose, pancreatic · H4, H6, H7 | probability + itemized increments | vendor score + design deltas |
| Price & access | cutoff, endpoint, biologic · H5, H9 | net price by market, GTN, HTA rating, months to reimbursement, negotiation year | archetype tables owned by Access |
| Feasibility | cutoff, footprint, dose, pancreatic, endpoint · H10 | enrollment months, readout, screen failure, cost, country table | stand-in → Astellas feasibility model |
| Business case | all | peak, rNPV, P10/P50/P90, share of negative scenarios | finance pro-forma |

- `POST /models/run` executes the chain deterministically (rng=None).
- `POST /models/montecarlo` runs n=500 with hypothesis parameters drawn as Beta distributions centered on confidence; results cached by `(levers, hypothesis_snapshot_hash, model_versions)`.
- Model parameters and formulas are versioned; every scenario stores `model_versions` so briefs are reproducible.

---

## 9. Data model (PostgreSQL)

Core tables (all with `id uuid`, `created_at`, `updated_at`, `org_id`):

- `assets`, `decisions`, `positions`, `positions_history`
- `hypotheses`, `hypothesis_agents` (m:n), `confidence_events`
- `agents`, `agent_runs`, `sources`, `agent_sources` (m:n)
- `signals`, `signal_moves`, `unmatched_queue`
- `patterns`, `proposed_decisions`
- `scenarios`, `briefs`
- `users`, `user_roles` (asset-scoped), `notification_rules`, `share_links`
- `audit_events` (append-only; `INSERT` only via DB role; hash chain column `prev_hash`)
- `embeddings` (pgvector) for hypotheses and signals

Retention: raw fetched content 180 days; structured facts, signals and audit events indefinitely.

---

## 10. API (FastAPI)

- Base `/api/v1`, JSON, OpenAPI published; auth via OIDC (Astellas IdP) → JWT; `reviewer` scope for share links.
- Routers: `assets`, `hypotheses`, `signals`, `proposals`, `patterns`, `models`, `scenarios`, `positions`, `briefs`, `agents`, `sources`, `events` (SSE), `me`, `admin`.
- All mutations emit `audit_events` and, where user-visible, an SSE event: `signal.created`, `signal.reviewed`, `hypothesis.updated`, `pattern.fired`, `pattern.cleared`, `position.reopened`, `position.locked`, `agent.run`, `brief.ready`.
- Idempotency keys on `apply/dismiss/lock`.
- Rate limits per agent run; backoff on source errors; dead-letter queue for failed extractions.

---

## 11. Frontend architecture (Next.js)

- **App Router**, TypeScript strict, React Server Components for read-mostly views (Asset context, Positions), Client Components for interactive steps.
- **Data:** TanStack Query for server state; Zustand for ephemeral UI state (`viewRole`, `levers`, open drawers); SSE via `EventSource` hook `useLiveEvents(asset)` invalidating queries.
- **UI:** Tailwind + shadcn/ui (`Sheet` for drawers, `Tabs`, `Tooltip`, `Select`), design tokens from the mockup CSS variables (`--acc #2563EB`, surfaces, Inter body + Manrope display), `next-themes`.
- **Charts:** Recharts for histograms/funnels; `@visx` for the trial Gantt and flow line.
- **Forms:** react-hook-form + zod; schemas shared with the API via generated OpenAPI types (`openapi-typescript`).
- **Accessibility:** rows and steps keyboard-operable; drawers trap focus; animations respect `prefers-reduced-motion`.
- **Routing guard:** middleware checks JWT and asset membership; read-only share tokens render Positions and Brief only.

---

## 12. Non-functional requirements

| Area | Requirement |
|---|---|
| Security | OIDC SSO; asset-scoped RBAC; secrets in vault; company-knowledge connectors use least-privilege service accounts; no raw internal documents leave the tenant VPC |
| Audit | Append-only `audit_events` with hash chain; every signal carries `source_url` and `retrieved_at`; briefs reproducible from snapshots |
| Data governance | Company-knowledge signals require validator sign-off before visibility; licensed-feed terms enforced per source (AI processing, redistribution flags) |
| Performance | Workspace step loads < 1.5 s P95; model chain run < 2 s; Monte Carlo n=500 < 6 s (cached thereafter); SSE latency < 2 s |
| Reliability | Agent runs idempotent and resumable; 99.5% availability business hours |
| Observability | OpenTelemetry traces across web → API → workers; per-agent dashboards: items fetched, deltas, signals surfaced, precision |
| Privacy | No patient-level data in the platform; aggregate RWE views only |

---

## 13. Telemetry events (product analytics)

`landing_cta_clicked`, `asset_opened`, `step_viewed(step)`, `hypothesis_registered`, `hypothesis_opened`, `agent_attached`, `signal_applied/dismissed/undone`, `pattern_fired(pattern_id)`, `option_explored`, `scenario_saved`, `position_locked`, `brief_exported`, `agent_created`, `agent_cadence_changed`, `theme_changed`.

---

## 14. Delivery plan

| Phase | Weeks | Scope | Exit criteria |
|---|---|---|---|
| 0 Foundation | 1–2 | Repo, CI, auth, data model, shell, Asset context, Hypothesis tracking (register, attach), Agent catalog (read) | Register 10 pilot hypotheses with agents attached |
| 1 Signals | 3–5 | Registry watch + Congress agents live on CLDN18.2 watch-list; Implication + Guardrail; Signals feed; digest email; What's changed | Precision measured weekly; first digest sent |
| 2 Decisions | 6–8 | Patterns engine, Workbench, Simulate with stand-in models, Positions lock/reopen, SSE | Pattern fires from a real signal; position reopened and re-locked |
| 3 Fidelity | 9–11 | Swap PTRS and Feasibility to real engines; Institutional + Portfolio memory agents on two released corpora; Brief export | Backtest reproduces a past decision's inputs |
| 4 Governance readout | 12 | Mock committee with exported brief; metrics review; scaling proposal | Go/no-go on second decision type |

---

## 15. Acceptance criteria (pilot)

1. A user with the Clinical role sees Clinical hypotheses first, PTRS as default model, and cannot lock the Population position.
2. Applying a signal updates hypothesis confidence, the position confidence, the What's changed counts and (if applicable) fires a pattern — within 2 s, visible via SSE in another session.
3. Every signal card shows the agent, source URL and retrieval date; a signal without a source cannot exist (Guardrail test).
4. Explore on a workbench option sets the levers and the Simulate view reflects the same numbers as the options table.
5. Locking a position stores a version containing hypothesis confidences, scenario P10/P50/P90 and signal ids; a later threshold crossing reopens it and the prior version is retained.
6. Onboarding a new asset yields an empty workspace with the seven steps and correct empty states; registering the first hypothesis schedules attached agents.
7. Exported brief PDF lists positions, evidence with citations, alternatives considered and "what would change our mind".

---

## 16. Open questions and risks

| Item | Owner | Due |
|---|---|---|
| Which internal corpora are released for the pilot (ad-board summaries, forecast archive)? | Astellas sponsor | Week 1 |
| Vendor license terms for AI processing of Citeline / Evaluate feeds | ZS legal | Week 2 |
| PTRS engine: vendor API vs internal benchmark | Clinical + ZS | Week 6 |
| Pricing archetype tables ownership and refresh cadence | Access lead | Week 7 |
| Risk: agent precision below 80% delays auto-apply — mitigation: keep supervised, tune relevance bucket | ZS | ongoing |
| Risk: competitor trial facts in demo are illustrative — must be replaced by Registry watch output before client use | ZS | Phase 1 |

---

*Appendix A — Pilot hypothesis set (H1–H10), pattern set (7), agent catalog (10) and lever schema are carried verbatim from the frozen mockup and seed the database via `scripts/seed_pilot.py`.*
