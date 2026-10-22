"use client";
import ExtLink from "../common/ExtLink";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDate, fmtNum } from "@/lib/format";
import { ROLE_DEFAULT_MODEL, useUi } from "@/lib/store";
import type { Kpi, LeverOption, LeverSchemaItem, Levers, ModelKey, ModelOutput } from "@/lib/types";
import { ErrorState, Illustrative, Loading, errorText } from "../common/States";
import Histogram from "./Histogram";
import SeriesView from "./SeriesView";

const TABS: [ModelKey, string][] = [
  ["demand", "Population & demand"],
  ["ptrs", "Probability of success"],
  ["access", "Price & access"],
  ["feasibility", "Feasibility"],
  ["business", "Business case"],
];

const opt = (o: LeverOption | string): LeverOption => (typeof o === "string" ? { value: o, label: o } : o);

function LeverControl({ s, value, onChange, disabled }: { s: LeverSchemaItem; value: Levers[string] | undefined; onChange: (v: Levers[string]) => void; disabled: boolean }) {
  if (s.type === "toggle") {
    const on = value === true || value === "true";
    return (
      <button className={`lv tg ${on ? "on" : ""}`} onClick={() => onChange(!on)} disabled={disabled} aria-pressed={on}>
        <span className="dot"></span>
        {s.label}
      </button>
    );
  }
  return (
    <span className="lv">
      {s.label}
      <select value={value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
        {(s.options || []).map(opt).map((o) => (
          <option key={String(o.value)} value={String(o.value)}>
            {o.label}
          </option>
        ))}
      </select>
    </span>
  );
}

function KpiStrip({ kpis }: { kpis: Kpi[] }) {
  return (
    <div className="k">
      {kpis.slice(0, 4).map((k, i) => (
        <div key={k.label}>
          <div className="l">{k.label}</div>
          <div className={`v ${i === 0 ? "a" : ""}`}>{fmtNum(k.value, k.unit)}</div>
          <div className="r">
            {k.note ? `${k.note} · ` : ""}
            {k.basis === "sourced" ? (
              <ExtLink className="a" url={k.source_url}>
                sourced
              </ExtLink>
            ) : (
              <span className="warn">stand-in assumption</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function ModelView({ m }: { m: ModelOutput }) {
  const extra = m.kpis.slice(4);
  return (
    <div>
      <KpiStrip kpis={m.kpis} />
      {extra.length > 0 && (
        <div className="mk" style={{ gridTemplateColumns: "1fr 1fr", marginBottom: 18 }}>
          {extra.map((k) => (
            <div className="kv" key={k.label}>
              <span>
                {k.label} {k.basis !== "sourced" && <span className="warn xs">· stand-in</span>}
              </span>
              <b>{fmtNum(k.value, k.unit)}</b>
            </div>
          ))}
        </div>
      )}
      <SeriesView series={m.series} />
      {m.reading && (
        <div className="read">
          <b>Reading this.</b> {m.reading}
        </div>
      )}
    </div>
  );
}

export default function Simulate({ slug }: { slug: string }) {
  const qc = useQueryClient();
  const { viewRole, modelTab, setModelTab, showToast } = useUi();
  const lq = useQuery({ queryKey: ["levers", slug], queryFn: () => api.levers(slug) });
  const [local, setLocal] = useState<Levers | null>(null);
  useEffect(() => {
    if (lq.data) setLocal(lq.data.current ?? lq.data.defaults);
  }, [lq.data]);
  const tab = (modelTab as ModelKey) || (ROLE_DEFAULT_MODEL[viewRole] as ModelKey) || "business";

  const put = useMutation({
    mutationFn: (l: Levers) => api.putLevers(slug, l),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["levers", slug] });
      qc.invalidateQueries({ queryKey: ["proposals", slug] });
      qc.invalidateQueries({ queryKey: ["positions", slug] });
    },
    onError: (e) => {
      showToast(errorText(e));
      if (lq.data) setLocal(lq.data.current ?? lq.data.defaults);
    },
  });
  const run = useQuery({ queryKey: ["models-run", slug, local], queryFn: () => api.runModels(slug, local!), enabled: !!local });
  const mc = useQuery({ queryKey: ["montecarlo", slug, local], queryFn: () => api.monteCarlo(slug, local!, 500), enabled: !!local });
  const reg = useQuery({ queryKey: ["model-registry"], queryFn: api.modelRegistry });
  const scen = useQuery({ queryKey: ["scenarios", slug], queryFn: () => api.scenarios(slug) });
  const [name, setName] = useState("");
  const save = useMutation({
    mutationFn: () => api.saveScenario(slug, name.trim() || `Scenario ${new Date().toLocaleString("en-GB")}`, local!),
    onSuccess: () => {
      showToast("Saved as an option — appears in Positions and the brief");
      setName("");
      qc.invalidateQueries({ queryKey: ["scenarios", slug] });
    },
    onError: (e) => showToast(errorText(e)),
  });

  const change = (k: string, v: Levers[string]) => {
    const next = { ...(local || {}), [k]: v };
    setLocal(next);
    put.mutate(next);
  };
  const m = run.data?.[tab];
  const allStandIn = (reg.data || []).every((r) => r.engine === "stand_in" || r.engine === "stand-in");

  return (
    <section>
      <div className="sect">
        <div>
          <h2>Simulate</h2>
          <p>One set of levers, five linked models. Hypothesis confidences set the parameters.</p>
        </div>
        <button
          className="btn"
          disabled={!lq.data || put.isPending || viewRole === "Reviewer"}
          onClick={() => {
            if (!lq.data) return;
            setLocal(lq.data.defaults);
            put.mutate(lq.data.defaults);
          }}
        >
          Reset levers
        </button>
      </div>
      {lq.isError && <ErrorState err={lq.error} what="levers" onRetry={() => lq.refetch()} />}
      {lq.isLoading && <Loading what="levers" />}
      {lq.data && local && (
        <div className="levers">
          {lq.data.schema.map((s) => (
            <LeverControl key={s.name} s={s} value={local[s.name]} onChange={(v) => change(s.name, v)} disabled={viewRole === "Reviewer"} />
          ))}
          {put.isPending && <span className="f xs" style={{ alignSelf: "center" }}>saving…</span>}
        </div>
      )}
      <div className="mtabs">
        {TABS.map(([k, l]) => (
          <button key={k} className={tab === k ? "on" : ""} onClick={() => setModelTab(k)}>
            {l}
          </button>
        ))}
        <span style={{ marginLeft: "auto", alignSelf: "center" }}>
          {allStandIn ? <Illustrative /> : null}
        </span>
      </div>
      {run.isError && <ErrorState err={run.error} what="model outputs" onRetry={() => run.refetch()} />}
      {run.isLoading && <Loading what="models" />}
      {m && <ModelView m={m} />}
      {run.data && !m && <div className="f">This model returned no output.</div>}

      <div style={{ marginTop: 28 }}>
        <h3>
          Monte Carlo · peak sales across {mc.data?.n ?? 500} scenarios <Illustrative />
        </h3>
        {mc.isError && <ErrorState err={mc.error} what="Monte Carlo" />}
        {mc.isLoading && <Loading what="Monte Carlo" />}
        {mc.data && (
          <>
            <div className="k" style={{ marginTop: 12 }}>
              <div>
                <div className="l">Peak sales, P50</div>
                <div className="v a">{fmtNum(mc.data.peak.p50, "$B")}</div>
                <div className="r">
                  P10 {fmtNum(mc.data.peak.p10, "$B")} · P90 {fmtNum(mc.data.peak.p90, "$B")}
                </div>
              </div>
              <div>
                <div className="l">Risk-adjusted NPV, P50</div>
                <div className="v">{fmtNum(mc.data.rnpv.p50, "$B")}</div>
                <div className="r">
                  P10 {fmtNum(mc.data.rnpv.p10, "$B")} · P90 {fmtNum(mc.data.rnpv.p90, "$B")}
                </div>
              </div>
              <div>
                <div className="l">Scenarios below zero</div>
                <div className="v">{fmtNum(mc.data.negative_share, "%")}</div>
                <div className="r">no-go pressure</div>
              </div>
              <div>
                <div className="l">Basis</div>
                <div className="v" style={{ fontSize: 15 }}>Stand-in</div>
                <div className="r">
                  <span className="warn">stand-in assumption</span>
                </div>
              </div>
            </div>
            <Histogram mc={mc.data} />
          </>
        )}
      </div>

      <div className="foot">
        <div style={{ display: "flex", gap: 8, alignItems: "center", flex: 1 }}>
          <input type="text" placeholder="Name this configuration (optional)" value={name} onChange={(e) => setName(e.target.value)} style={{ maxWidth: 360 }} />
          <button className="btn p" disabled={!local || save.isPending || viewRole === "Reviewer"} onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : "Save as option"}
          </button>
        </div>
        <span className="f s">
          {scen.data ? `${scen.data.length} saved option${scen.data.length !== 1 ? "s" : ""}` : scen.isError ? errorText(scen.error) : ""}
        </span>
      </div>
      {scen.data && scen.data.length > 0 && (
        <div className="near" style={{ marginTop: 10 }}>
          {scen.data.slice(0, 6).map((s) => (
            <div key={s.id}>
              <span>
                <b>{s.name}</b> · {Object.entries(s.levers || {}).map(([k, v]) => `${k} ${String(v)}`).join(" · ")}
              </span>
              <span>{fmtDate(s.created_at)}</span>
            </div>
          ))}
        </div>
      )}

      <div className="models">
        <div className="sect">
          <div>
            <h3>Models underneath</h3>
            <p>What each model reads, what it returns, and whether it is Astellas&apos;s engine or a stand-in.</p>
          </div>
        </div>
        {reg.isError && <ErrorState err={reg.error} what="the model registry" />}
        {reg.data && (
          <>
            <div className="row" style={{ color: "var(--ink-3)", fontSize: 12 }}>
              <span>Model</span>
              <span>Reads</span>
              <span>Returns</span>
              <span className="st">Engine</span>
            </div>
            {reg.data.map((r) => (
              <div className="row" key={r.name}>
                <b>{r.name}</b>
                <span>{r.reads}</span>
                <span>{r.returns}</span>
                <span className="st">
                  {r.engine === "stand_in" || r.engine === "stand-in" ? <Illustrative /> : r.engine} <span className="f xs">v{r.version}</span>
                </span>
              </div>
            ))}
          </>
        )}
      </div>
    </section>
  );
}
