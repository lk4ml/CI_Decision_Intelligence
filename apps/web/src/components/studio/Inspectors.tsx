"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { cadenceText, fmtDateTime } from "@/lib/format";
import { useUi } from "@/lib/store";
import { ErrorState, Loading, errorText } from "../common/States";

const CATN: Record<string, string> = { always_on: "Always-on", daily: "Daily", on_event: "On event" };
const READS: Record<string, string> = { world: "World", company: "Astellas", models: "Models" };
const CADENCES: [number, string][] = [
  [60, "1h"],
  [360, "6h"],
  [720, "12h"],
  [1440, "daily"],
  [10080, "weekly"],
];

export function AgentInspector({ id, slug }: { id: string; slug: string }) {
  const qc = useQueryClient();
  const toast = useUi((s) => s.showToast);
  const role = useUi((s) => s.viewRole);
  const q = useQuery({ queryKey: ["agent", id], queryFn: () => api.agent(id) });
  const hyps = useQuery({ queryKey: ["hypotheses", slug], queryFn: () => api.hypotheses(slug) });
  const cad = useMutation({
    mutationFn: (m: number) => api.patchAgent(id, { cadence_minutes: m }),
    onSuccess: () => {
      toast("Cadence updated");
      qc.invalidateQueries({ queryKey: ["agent", id] });
      qc.invalidateQueries({ queryKey: ["agents"] });
    },
    onError: (e) => toast(errorText(e)),
  });
  const run = useMutation({
    mutationFn: () => api.runAgent(id, slug),
    onSettled: () => qc.invalidateQueries(),
  });
  if (q.isError) return <ErrorState err={q.error} what="the agent" />;
  if (!q.data) return <Loading what="agent" />;
  const a = q.data;
  const hidSet = new Set(a.hypothesis_ids || []);
  const attached = (hyps.data || []).filter((h) => hidSet.has(h.id) || h.agents.some((x) => x.id === a.id));
  const lr = a.last_run;
  return (
    <div className="insp">
      <span className="kick">{CATN[a.category] ?? a.category} agent</span>
      <h3>{a.name}</h3>
      <div className="st">
        <i className={`ld ${a.status === "running" ? "run" : a.status === "supervised" ? "sup" : "plan"}`}></i>
        {a.status === "running" ? "Running" : a.status === "supervised" ? "Supervised — every proposal reviewed" : "Planned · not deployed"}
      </div>
      <p className="m" style={{ marginBottom: 10 }}>
        {a.description}
      </p>
      <div className="kv">
        <b>Reads</b>
        <span>
          {READS[a.reads] ?? a.reads} knowledge{a.source_keys?.length ? ` · ${a.source_keys.join(", ")}` : ""}
        </span>
      </div>
      <div className="kv">
        <b>Cadence</b>
        <span>
          {cadenceText(a.cadence_minutes, a.category)}
          {a.category !== "on_event" && (
            <select
              value={String(a.cadence_minutes ?? "")}
              onChange={(e) => cad.mutate(+e.target.value)}
              disabled={cad.isPending || role === "Reviewer"}
              style={{ width: "auto", marginLeft: 8, padding: "3px 24px 3px 8px", fontSize: 12 }}
            >
              {!CADENCES.some(([m]) => m === a.cadence_minutes) && <option value={String(a.cadence_minutes ?? "")}>{cadenceText(a.cadence_minutes)}</option>}
              {CADENCES.map(([m, l]) => (
                <option key={m} value={m}>
                  {l}
                </option>
              ))}
            </select>
          )}
        </span>
      </div>
      <div className="kv">
        <b>Attached to</b>
        <span>
          {attached.length
            ? attached.map((h) => (
                <span key={h.id} style={{ display: "block" }}>
                  {h.code} — {h.statement.length > 80 ? h.statement.slice(0, 80) + "…" : h.statement}
                </span>
              ))
            : "No hypotheses on this asset"}
        </span>
      </div>
      <div className="kv">
        <b>Now</b>
        <span>{lr?.summary || (lr ? `Last run ${lr.status}` : "Not yet run")}</span>
      </div>
      <div className="kv">
        <b>Last run</b>
        <span className={lr?.status === "source_unreachable" || lr?.status === "error" ? "warn" : ""}>
          {lr ? (
            <>
              {lr.status} · {fmtDateTime(lr.finished_at ?? lr.started_at)}
              {lr.items_fetched !== undefined ? ` · ${lr.items_fetched} fetched, ${lr.items_new ?? 0} new, ${lr.signals_created ?? 0} signals` : ""}
              {lr.error ? <span style={{ display: "block" }}>{lr.error}</span> : null}
            </>
          ) : (
            "never"
          )}
        </span>
      </div>
      <div className="kv">
        <b>Governance</b>
        <span>
          {a.governance_notes ||
            "Every output cited with source and retrieval date; Guardrail agent blocks unverifiable claims."}
        </span>
      </div>
      {run.data && (
        <div className={`read ${run.data.status === "ok" ? "" : "warn"}`} style={{ marginTop: 14 }}>
          <b>Run finished: {run.data.status}.</b> {run.data.summary ?? ""}{" "}
          {run.data.items_fetched !== undefined ? `${run.data.items_fetched} fetched · ${run.data.signals_created ?? 0} signals.` : ""}{" "}
          {run.data.error ? <span className="warn">{run.data.error}</span> : null}
        </div>
      )}
      {run.isError && <div className="ferr">{errorText(run.error)}</div>}
      <div style={{ display: "flex", gap: 8, marginTop: 18 }}>
        {a.category !== "on_event" && (
          <button className="btn sm p" disabled={run.isPending || role === "Reviewer"} onClick={() => run.mutate()}>
            {run.isPending ? "Running…" : `Run now on ${slug}`}
          </button>
        )}
        <button className="btn sm" onClick={() => useUi.getState().closeDrawer()}>
          Close
        </button>
      </div>
    </div>
  );
}

export function SourceInspector({ k }: { k: string }) {
  const q = useQuery({ queryKey: ["source", k], queryFn: () => api.source(k) });
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  if (q.isError) return <ErrorState err={q.error} what="the source" />;
  if (!q.data) return <Loading what="source" />;
  const s = q.data;
  const readers = (s.agent_keys || []).map((key) => agents.data?.find((a) => a.key === key)?.name ?? key);
  const bad = s.last_status === "source_unreachable" || s.last_status === "error";
  return (
    <div className="insp">
      <span className="kick">{s.side === "world" ? "World knowledge" : "Astellas knowledge"} source</span>
      <h3>{s.name}</h3>
      <div className="kv">
        <b>Kind</b>
        <span>{s.kind}</span>
      </div>
      <div className="kv">
        <b>Endpoint</b>
        <span>
          <a className="a" href={s.base_url} target="_blank" rel="noreferrer">
            {s.base_url}
          </a>
        </span>
      </div>
      <div className="kv">
        <b>Access level</b>
        <span>{s.access_level}</span>
      </div>
      <div className="kv">
        <b>Agents reading it</b>
        <span>{readers.length ? readers.join(", ") : "—"}</span>
      </div>
      <div className="kv">
        <b>Last fetch</b>
        <span className={bad ? "warn" : ""}>
          {fmtDateTime(s.last_fetch_at)} · {s.last_status ?? "never fetched"}
          {s.last_error ? <span style={{ display: "block" }}>{s.last_error}</span> : null}
        </span>
      </div>
      <div className="kv">
        <b>Last OK</b>
        <span>{fmtDateTime(s.last_ok_at)}</span>
      </div>
      <div className="kv">
        <b>License</b>
        <span>{s.license_notes || "—"}</span>
      </div>
    </div>
  );
}

export function NewAgentForm({ slug, onDone }: { slug: string; onDone: () => void }) {
  const qc = useQueryClient();
  const toast = useUi((s) => s.showToast);
  const hyps = useQuery({ queryKey: ["hypotheses", slug], queryFn: () => api.hypotheses(slug) });
  const [name, setName] = useState("");
  const [cat, setCat] = useState("always_on");
  const [reads, setReads] = useState("world");
  const [desc, setDesc] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const m = useMutation({
    mutationFn: () => api.createAgent({ name: name.trim(), category: cat, reads, description: desc.trim(), hypothesis_ids: [...picked] }),
    onSuccess: (a) => {
      toast(`${a.name} created · supervised`);
      qc.invalidateQueries();
      onDone();
    },
  });
  return (
    <div className="reg">
      <span className="kick">New agent</span>
      <h3>Draft a new agent</h3>
      <div className="fm">
        <div className="full">
          <label>Name</label>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. HTA precedent agent" />
        </div>
        <div>
          <label>Category</label>
          <select value={cat} onChange={(e) => setCat(e.target.value)}>
            <option value="always_on">Always-on · every 6h</option>
            <option value="daily">Daily</option>
            <option value="on_event">On event</option>
          </select>
        </div>
        <div>
          <label>Reads</label>
          <select value={reads} onChange={(e) => setReads(e.target.value)}>
            <option value="world">World knowledge</option>
            <option value="company">Astellas knowledge</option>
            <option value="models">Models</option>
          </select>
        </div>
        <div className="full">
          <label>What it does</label>
          <textarea value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Sources it reads, what it extracts, which hypotheses or models it feeds" />
        </div>
        <div className="full">
          <label>Attach to hypotheses</label>
          <div className="chips">
            {(hyps.data || []).map((h) => (
              <button
                key={h.id}
                className={`chip ${picked.has(h.id) ? "on" : ""}`}
                onClick={() => {
                  const n = new Set(picked);
                  if (n.has(h.id)) n.delete(h.id);
                  else n.add(h.id);
                  setPicked(n);
                }}
              >
                {h.code}
              </button>
            ))}
            {hyps.data && !hyps.data.length && <span className="f xs">No hypotheses on this asset yet.</span>}
          </div>
        </div>
      </div>
      {m.isError && <div className="ferr">{errorText(m.error)}</div>}
      <div className="ft">
        <span className="f s">Starts supervised: every proposal is reviewed for eight weeks.</span>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn sm" onClick={onDone}>
            Cancel
          </button>
          <button className="btn sm p" disabled={!name.trim() || m.isPending} onClick={() => m.mutate()}>
            {m.isPending ? "Creating…" : "Create agent"}
          </button>
        </div>
      </div>
    </div>
  );
}
