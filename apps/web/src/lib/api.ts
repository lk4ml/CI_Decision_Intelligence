// Tiny typed client for the Decision Intelligence API (docs/ARCHITECTURE.md).
// No mock data and no fallbacks: every failure surfaces as an ApiError.
import type {
  ActivityEvent,
  Agent,
  AgentRun,
  AgentsStatus,
  AssetBrief,
  AssetDetail,
  AssetSummary,
  BriefExport,
  Changes,
  Focus,
  Hypothesis,
  HypothesisCreate,
  LandingStats,
  LeverSchema,
  Levers,
  ModelRegistryEntry,
  ModelRunResult,
  MonteCarloResult,
  Pattern,
  Position,
  Proposal,
  Scenario,
  Signal,
  Source,
  Trial,
  Covered,
  Coverage,
  PositionHistoryEntry,
  UnmatchedItem,
  Digest,
  Me,
  AssetCreate,
} from "./types";

export const API_BASE = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"
).replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string, path: string) {
    super(status ? `${status} on ${path}: ${detail}` : `${path}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

/** Identity headers sent on every mutation (Addendum A #10). Updated from the Viewing-as selector. */
const identity = { actor: "user:Asset lead", role: "Asset lead" };
export function setIdentity(actor: string, role: string) {
  identity.actor = actor;
  identity.role = role;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  const mutating = !!init?.method && init.method !== "GET";
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(mutating ? { "X-Actor": identity.actor, "X-Role": identity.role } : {}),
        ...(init?.headers || {}),
      },
      cache: "no-store",
    });
  } catch (e) {
    throw new ApiError(0, `API unreachable at ${API_BASE} (${(e as Error).message})`, path);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail ?? body);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail, path);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const get = <T>(p: string) => request<T>(p);
const post = <T>(p: string, body?: unknown) =>
  request<T>(p, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const put = <T>(p: string, body: unknown) => request<T>(p, { method: "PUT", body: JSON.stringify(body) });
const patch = <T>(p: string, body: unknown) => request<T>(p, { method: "PATCH", body: JSON.stringify(body) });
const del = <T>(p: string) => request<T>(p, { method: "DELETE" });
const q = (params: Record<string, string | undefined>) => {
  const s = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && s.set(k, v));
  const out = s.toString();
  return out ? `?${out}` : "";
};

const EMPTY_COVERAGE: Coverage = { status: "never_run", last_run: null };
async function getCovered<T>(path: string): Promise<Covered<T>> {
  const r = await get<Covered<T> | T[]>(path);
  // Contract (Addendum A #6): {items, coverage}. A bare array is tolerated and treated as "ok".
  if (Array.isArray(r)) return { items: r, coverage: { status: "ok", last_run: null } };
  return { items: r.items ?? [], coverage: r.coverage ?? EMPTY_COVERAGE };
}

export const api = {
  health: () => get<{ ok: boolean }>("/health"),
  landingStats: () => get<LandingStats>("/stats/landing"),

  assets: () => get<AssetSummary[]>("/assets"),
  asset: (slug: string) => get<AssetDetail>(`/assets/${slug}`),
  brief: (slug: string) => get<AssetBrief>(`/assets/${slug}/brief`),
  focus: (slug: string) => get<Focus>(`/assets/${slug}/focus`),
  trials: (slug: string) => getCovered<Trial>(`/assets/${slug}/trials`),
  createAsset: (body: AssetCreate) => post<AssetSummary>("/assets", body),
  digest: (slug: string, role: string) => get<Digest>(`/assets/${slug}/digest${q({ role })}`),
  unmatched: (slug: string) => get<UnmatchedItem[]>(`/assets/${slug}/unmatched`),
  me: () => get<Me>("/me"),
  changes: (slug: string, role: string) => get<Changes>(`/assets/${slug}/changes${q({ role })}`),

  hypotheses: (slug: string) => get<Hypothesis[]>(`/assets/${slug}/hypotheses`),
  createHypothesis: (slug: string, body: HypothesisCreate) => post<Hypothesis>(`/assets/${slug}/hypotheses`, body),
  patchHypothesis: (id: string, body: Partial<Pick<Hypothesis, "threshold" | "change_trigger_text" | "statement">>) =>
    patch<Hypothesis>(`/hypotheses/${id}`, body),
  attachAgent: (hid: string, aid: string) => post<unknown>(`/hypotheses/${hid}/agents/${aid}`),
  detachAgent: (hid: string, aid: string) => del<unknown>(`/hypotheses/${hid}/agents/${aid}`),

  signals: (slug: string, status?: string) => getCovered<Signal>(`/assets/${slug}/signals${q({ status })}`),
  applySignal: (id: string, overrides?: Record<string, number>, reason?: string) =>
    post<unknown>(`/signals/${id}/apply`, { overrides, reason }),
  dismissSignal: (id: string) => post<unknown>(`/signals/${id}/dismiss`, {}),
  undoSignal: (id: string) => post<unknown>(`/signals/${id}/undo`, {}),
  applyAll: (slug: string) => post<unknown>(`/assets/${slug}/signals/apply-all`, {}),

  proposals: (slug: string) => get<Proposal[]>(`/assets/${slug}/proposals`),
  patterns: (slug: string) => get<Pattern[]>(`/assets/${slug}/patterns`),

  levers: (slug: string) => get<LeverSchema>(`/assets/${slug}/levers`),
  putLevers: (slug: string, levers: Levers) => put<LeverSchema>(`/assets/${slug}/levers`, { levers }),
  runModels: (asset: string, levers: Levers) => post<ModelRunResult>("/models/run", { asset, levers }),
  monteCarlo: (asset: string, levers: Levers, n = 500) =>
    post<MonteCarloResult>("/models/montecarlo", { asset, levers, n }),
  modelRegistry: () => get<ModelRegistryEntry[]>("/models/registry"),
  scenarios: (slug: string) => get<Scenario[]>(`/assets/${slug}/scenarios`),
  saveScenario: (slug: string, name: string, levers: Levers) =>
    post<Scenario>(`/assets/${slug}/scenarios`, { name, levers }),

  positions: (slug: string) => get<Position[]>(`/assets/${slug}/positions`),
  lockPosition: (id: string, scenario_id?: string) =>
    post<Position>(`/positions/${id}/lock`, scenario_id ? { scenario_id } : {}),
  positionHistory: (id: string) => get<PositionHistoryEntry[]>(`/positions/${id}/history`),
  exportBrief: (slug: string) => post<BriefExport>(`/assets/${slug}/briefs`, {}),
  briefHtmlUrl: (id: string) => `${API_BASE}/briefs/${id}.html`,

  agents: () => get<Agent[]>("/agents"),
  agent: (id: string) => get<Agent>(`/agents/${id}`),
  agentsStatus: () => get<AgentsStatus>("/agents/status"),
  patchAgent: (id: string, body: Partial<Pick<Agent, "cadence_minutes" | "status" | "description">>) =>
    patch<Agent>(`/agents/${id}`, body),
  runAgent: (id: string, asset?: string) => post<AgentRun>(`/agents/${id}/run${q({ asset })}`),
  createAgent: (body: { name: string; category: string; reads: string; description: string; hypothesis_ids?: string[] }) =>
    post<Agent>("/agents", body),

  sources: () => get<Source[]>("/sources"),
  source: (key: string) => get<Source>(`/sources/${key}`),

  recentEvents: (asset?: string) => get<ActivityEvent[]>(`/events/recent${q({ asset })}`),
  streamUrl: (asset?: string) => `${API_BASE}/events/stream${q({ asset })}`,
};
