// Types mirroring docs/ARCHITECTURE.md "API (/api/v1)" response shapes.
// Fields marked optional are either not fixed by the contract or derived defensively.

export type PhaseSource = "user" | "registry" | string;

export interface AssetSummary {
  id: string;
  slug: string;
  code: string;
  name: string;
  indication: string;
  biomarker: string;
  phase: string;
  phase_source: PhaseSource;
  registry_phase?: string | null;
  phase_discrepancy?: string | null;
}

export interface AssetCounts {
  hypotheses: number;
  pending_signals: number;
  proposals: number;
  locked_positions: number;
}

export interface AssetDetail extends AssetSummary {
  mechanism?: string;
  decision_type?: string;
  governance_forum?: string | null;
  governance_date?: string | null;
  descriptor?: string | null;
  watch_terms?: { own?: string[]; competitors?: string[]; literature?: string[] } | null;
  counts: AssetCounts;
}

export type StepKey =
  | "asset"
  | "changes"
  | "hypotheses"
  | "signals"
  | "workbench"
  | "simulate"
  | "positions";

export interface BriefRow {
  label: string;
  value: string;
  step?: StepKey | string | null;
}
export interface AssetBrief {
  rows: BriefRow[];
}

export interface Focus {
  kind: "pattern" | "signal" | "none";
  title: string;
  detail: string;
  link_step?: StepKey | string | null;
}

export type RunStatus = "ok" | "source_unreachable" | "error" | string;

export interface AgentRun {
  id?: string;
  agent_id?: string;
  asset_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  status: RunStatus;
  items_fetched?: number;
  items_new?: number;
  signals_created?: number;
  blocked?: number;
  error?: string | null;
  summary?: string | null;
}

export interface Trial {
  id: string;
  nct_id: string;
  title: string;
  sponsor?: string | null;
  phase?: string | null;
  status?: string | null;
  start_date?: string | null;
  primary_completion?: string | null;
  enrollment?: number | null;
  conditions?: string[] | null;
  interventions?: string[] | null;
  endpoints?: string[] | null;
  role: "own" | "competitor" | "standard" | string;
  source_url: string;
  retrieved_at: string;
}

export type CoverageStatus = "ok" | "source_unreachable" | "never_run" | string;
export interface Coverage {
  status: CoverageStatus;
  last_run: { agent_key: string; finished_at: string | null; error: string | null } | null;
}
/** Addendum A #6 coverage envelope used by /trials and /signals. */
export interface Covered<T> {
  items: T[];
  coverage: Coverage;
}
export type TrialsResponse = Covered<Trial>;

export interface ChangeSignal {
  id?: string;
  title?: string;
  impact?: string;
}
export interface ChangeHypothesis {
  code?: string;
  delta?: number;
  confidence?: number;
}
export interface ChangePattern {
  title?: string;
  key?: string;
}
export interface ChangePosition {
  line?: string;
}

/** Each bucket may be a number or a list; the UI accepts both. */
export type CountOrList<T> = number | T[];

export interface Changes {
  lede: string;
  pending_signals: CountOrList<ChangeSignal>;
  moved_hypotheses: CountOrList<ChangeHypothesis>;
  fired_patterns: CountOrList<ChangePattern>;
  reopened_positions: CountOrList<ChangePosition>;
}

export interface AgentRef {
  id: string;
  key: string;
  name: string;
  cadence_minutes: number | null;
  status: AgentStatus;
}

export interface EvidenceItem {
  signal_id: string | null;
  title: string;
  delta: number;
  source_name?: string | null;
  source_url?: string | null;
  retrieved_at?: string | null;
}

export interface Hypothesis {
  id: string;
  code: string;
  statement: string;
  category: string;
  owner_role: string;
  confidence: number;
  confidence_start: number;
  threshold: number;
  change_trigger_text: string;
  for_count: number;
  against_count: number;
  week_delta: number;
  agents: AgentRef[];
  evidence: EvidenceItem[];
  position_line: string;
  crossed?: boolean;
  crossed_at?: string | null;
}

export interface HypothesisCreate {
  statement: string;
  category: string;
  owner_role: string;
  confidence_start: number;
  threshold: number;
  change_trigger_text: string;
  agent_ids: string[];
  position_line: string;
  keywords?: string[];
}

export type ReviewStatus = "pending" | "applied" | "dismissed";

export interface SignalMove {
  hypothesis_code: string;
  delta: number;
  rationale?: string | null;
}

export interface Signal {
  id: string;
  title: string;
  so_what: string;
  impact: "high" | "normal" | string;
  agent: { key: string; name: string } | null;
  source_name: string;
  source_url: string;
  retrieved_at: string;
  published_at: string | null;
  review_status: ReviewStatus;
  moves: SignalMove[];
}

export interface LeverOption {
  value: string;
  label: string;
}
export interface LeverSchemaItem {
  name: string;
  label: string;
  type: "select" | "toggle";
  options?: (LeverOption | string)[];
}
export type LeverValue = string | boolean | number;
export type Levers = Record<string, LeverValue>;
export interface LeverSchema {
  schema: LeverSchemaItem[];
  defaults: Levers;
  current?: Levers;
}

export interface OptionResults {
  patients?: number | null;
  ptrs?: number | null;
  peak?: number | null;
  readout?: number | string | null;
  us_net?: number | null;
}

export interface ProposalOption {
  label: string;
  lever: string;
  value: LeverValue;
  levers?: Levers;
  is_current?: boolean;
  results: OptionResults;
}

export interface ProposalHypothesis {
  code: string;
  confidence: number;
  threshold?: number;
  statement?: string;
  crossed?: boolean;
}

export interface ProposalSignal {
  id: string;
  title: string;
  agent?: { key?: string; name: string } | string | null;
  source_name?: string | null;
  source_url?: string | null;
  retrieved_at?: string | null;
  moves?: SignalMove[];
}

export interface Proposal {
  id: string;
  pattern: {
    key: string;
    title: string;
    position_line: string;
    trigger_text: string;
    rationale: string;
  };
  framing: "take" | "frame";
  hypotheses: ProposalHypothesis[];
  signals: ProposalSignal[];
  options: ProposalOption[];
  fired_at?: string | null;
  total_movement?: number;
}

export interface Pattern {
  id: string;
  key: string;
  title: string;
  position_line: string;
  trigger?: string;
  trigger_text: string;
  rationale?: string;
  is_fired: boolean;
}

export interface Kpi {
  label: string;
  value: number | string | null;
  unit?: string | null;
  note?: string | null;
  basis?: "stand_in_assumption" | "sourced" | string | null;
  source_url?: string | null;
}

export interface ModelOutput {
  kpis: Kpi[];
  series?: unknown;
  reading?: string | null;
  engine?: string | null;
  illustrative?: boolean;
}

export type ModelKey = "demand" | "ptrs" | "access" | "feasibility" | "business";
export type ModelRunResult = Record<ModelKey, ModelOutput>;

export interface Quantiles {
  p10: number;
  p50: number;
  p90: number;
}

export interface MonteCarloResult {
  peak: Quantiles;
  rnpv: Quantiles;
  histogram: (number | { x?: number; bin?: number; lo?: number; hi?: number; count: number })[];
  negative_share: number;
  n?: number;
}

export interface ModelRegistryEntry {
  name: string;
  reads: string;
  returns: string;
  engine: string;
  version: string;
}

export interface Scenario {
  id: string;
  name: string;
  levers: Levers;
  outputs?: unknown;
  created_at?: string;
}

export type PositionStatus = "provisional" | "locked" | "reopened";

export interface Position {
  id: string;
  line: string;
  statement: string;
  why: string;
  owner_role: string;
  contributor_roles: string[];
  status: PositionStatus;
  version: number;
  confidence: number | null;
  hypotheses: { code: string; confidence: number; owner_role: string }[];
}

export interface BriefExport {
  id: string;
  version: string;
}

export type AgentStatus = "running" | "supervised" | "planned" | string;
export type AgentCategory = "always_on" | "daily" | "on_event";

export interface Agent {
  id: string;
  key: string;
  name: string;
  category: AgentCategory;
  reads: "world" | "company" | "models" | string;
  cadence_minutes: number | null;
  status: AgentStatus;
  description: string;
  source_keys: string[];
  last_run_at: string | null;
  last_run: AgentRun | null;
  attached_hypotheses?: string[];
  hypothesis_ids?: string[];
  governance_notes?: string | null;
}

export interface AgentsStatus {
  by_category: Record<string, number | { count?: number; running?: number; total?: number }>;
  next_cycle_at: string | null;
  running?: number;
}

export interface Source {
  id?: string;
  key: string;
  name: string;
  side: "world" | "company";
  kind: string;
  base_url: string;
  access_level: string;
  license_notes: string | null;
  last_fetch_at: string | null;
  last_status: string | null;
  last_error?: string | null;
  last_ok_at?: string | null;
  agent_keys?: string[];
  agents?: { key: string; name: string }[] | string[];
}

export interface ActivityEvent {
  id?: string;
  type?: string;
  action?: string;
  actor?: string;
  entity?: string;
  entity_id?: string;
  message?: string;
  summary?: string;
  payload?: Record<string, unknown> | null;
  created_at?: string;
  ts?: string;
}

export interface LandingStats {
  sources_refreshed_1h: number;
  agents_running: number;
}

export interface PositionHistoryEntry {
  id?: string;
  version: number;
  locked_by: string | null;
  locked_at: string | null;
  snapshot: {
    statement?: string;
    levers?: Levers;
    hypotheses?: { code: string; confidence: number; threshold?: number }[];
    signal_ids?: string[];
    scenario?: { id?: string; peak?: Quantiles; rnpv?: Quantiles } | null;
    model_versions?: Record<string, string> | null;
    audit_head_hash?: string | null;
  } | null;
}

export interface UnmatchedItem {
  id: string;
  reason: string;
  title?: string | null;
  url?: string | null;
  source_key?: string | null;
  retrieved_at?: string | null;
  created_at?: string | null;
}

export interface Digest {
  subject?: string;
  html?: string;
  text?: string;
  body?: string;
  role?: string;
  items?: { title: string; so_what?: string; agent?: string; moves?: string }[];
}

export interface Me {
  actor: string;
  role: string;
}

export interface AssetCreate {
  code: string;
  name: string;
  mechanism: string;
  indication: string;
  biomarker?: string;
  phase: string;
  decision_type: string;
  governance_forum?: string;
  governance_date?: string;
}
