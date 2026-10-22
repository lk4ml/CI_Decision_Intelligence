"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { fmtDateTime, fmtNum } from "@/lib/format";
import { useUi } from "@/lib/store";
import type { Position } from "@/lib/types";
import { Empty, ErrorState, Loading, errorText } from "../common/States";

function History({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["position-history", id], queryFn: () => api.positionHistory(id) });
  if (q.isError) return <div className="ferr">{errorText(q.error)}</div>;
  if (!q.data) return <Loading what="history" />;
  if (!q.data.length) return <div className="f s" style={{ marginTop: 8 }}>Never locked — no versions yet.</div>;
  return (
    <div className="near" style={{ marginTop: 8 }}>
      {q.data
        .slice()
        .sort((a, b) => b.version - a.version)
        .map((h) => (
          <div key={h.id ?? h.version}>
            <span>
              <b>v{h.version}</b> · {h.snapshot?.statement ?? ""}
              <br />
              <span className="f xs">
                {(h.snapshot?.hypotheses || []).map((x) => `${x.code} ${Math.round(x.confidence)}%`).join(" · ")}
                {h.snapshot?.scenario?.peak ? ` · peak P10–P90 ${fmtNum(h.snapshot.scenario.peak.p10, "$B")}–${fmtNum(h.snapshot.scenario.peak.p90, "$B")}` : ""}
                {h.snapshot?.signal_ids?.length ? ` · ${h.snapshot.signal_ids.length} signals` : ""}
                {h.snapshot?.audit_head_hash ? ` · audit ${h.snapshot.audit_head_hash.slice(0, 10)}…` : ""}
              </span>
            </span>
            <span className="xs">
              {h.locked_by ?? "—"} · {fmtDateTime(h.locked_at)}
            </span>
          </div>
        ))}
    </div>
  );
}

function PositionRow({ p, slug, scenarioId }: { p: Position; slug: string; scenarioId?: string }) {
  const qc = useQueryClient();
  const toast = useUi((s) => s.showToast);
  const role = useUi((s) => s.viewRole);
  const [err, setErr] = useState<string | null>(null);
  const [hist, setHist] = useState(false);
  const lock = useMutation({
    mutationFn: () => api.lockPosition(p.id, scenarioId),
    onSuccess: () => {
      setErr(null);
      toast(`${p.line} locked and versioned`);
      qc.invalidateQueries({ queryKey: ["positions", slug] });
      qc.invalidateQueries({ queryKey: ["asset", slug] });
      qc.invalidateQueries({ queryKey: ["position-history", p.id] });
    },
    onError: (e) =>
      setErr(
        e instanceof ApiError && e.status === 403
          ? `Only the ${p.owner_role} owner or an Admin can lock ${p.line}. You are viewing as ${role}.`
          : errorText(e),
      ),
  });
  const locked = p.status === "locked";
  const reopened = p.status === "reopened";
  const canLock = role === "Admin" || role === p.owner_role;
  return (
    <div className={`p ${locked ? "lk" : ""}`}>
      <div className="lab">
        {p.line}
        <span>{p.hypotheses.map((h) => h.code).join(", ") || "no hypotheses yet"}</span>
      </div>
      <div>
        <div>{p.statement}</div>
        {p.why && <div className="why">{p.why}</div>}
        <div className="owns">
          Owner <b>{p.owner_role}</b>
          {p.contributor_roles.length ? (
            <>
              {" "}
              · contributors <b>{p.contributor_roles.join(", ")}</b>
            </>
          ) : null}{" "}
          · rests on{" "}
          {p.hypotheses.length
            ? p.hypotheses.map((h) => `${h.code} (${h.owner_role}, ${Math.round(h.confidence)}%)`).join(", ")
            : "no registered hypotheses"}{" "}
          · v{p.version}
        </div>
        {reopened && (
          <div className="flag">
            <b>Reopened.</b> A hypothesis behind this line crossed its threshold since it was last agreed.
          </div>
        )}
        {err && <div className="ferr">{err}</div>}
        <button className="btn sm t" style={{ marginTop: 6, paddingLeft: 0 }} onClick={() => setHist(!hist)}>
          {hist ? "Hide history" : "Version history"}
        </button>
        {hist && <History id={p.id} />}
      </div>
      <div className="side2">
        <div className="c">
          {p.confidence !== null && p.confidence !== undefined ? `${Math.round(p.confidence)}%` : "—"}
          <span>confidence</span>
        </div>
        <span className={`tag ${locked ? "" : "g"}`}>{locked ? "Locked" : reopened ? "Reopened" : "Provisional"}</span>
        {!locked && (
          <button
            className={`btn sm ${reopened ? "p" : ""}`}
            disabled={lock.isPending}
            onClick={() => lock.mutate()}
            title={canLock ? undefined : `Owner: ${p.owner_role}`}
          >
            {lock.isPending ? "Locking…" : reopened ? "Review and lock" : "Lock"}
          </button>
        )}
      </div>
    </div>
  );
}

export default function Positions({ slug }: { slug: string }) {
  const q = useQuery({ queryKey: ["positions", slug], queryFn: () => api.positions(slug) });
  const scen = useQuery({ queryKey: ["scenarios", slug], queryFn: () => api.scenarios(slug) });
  const asset = useQuery({ queryKey: ["asset", slug], queryFn: () => api.asset(slug) });
  const toast = useUi((s) => s.showToast);
  const [scenarioId, setScenarioId] = useState<string>("");
  const [expErr, setExpErr] = useState<string | null>(null);
  const exp = useMutation({
    mutationFn: async () => {
      const w = window.open("about:blank", "_blank");
      try {
        const b = await api.exportBrief(slug);
        if (w) w.location.href = api.briefHtmlUrl(b.id);
        else window.open(api.briefHtmlUrl(b.id), "_blank");
        return b;
      } catch (e) {
        w?.close();
        throw e;
      }
    },
    onSuccess: (b) => {
      setExpErr(null);
      toast(`Brief v${b.version} exported`);
    },
    onError: (e) => setExpErr(errorText(e)),
  });
  return (
    <section>
      <div className="sect">
        <div>
          <h2>Positions</h2>
          <p>
            The {asset.data?.decision_type ?? "TPP"} is six positions. Each is a sentence, an owner, a confidence, and a sign-off.
          </p>
        </div>
      </div>
      <div className="legend">
        <div>
          <b>Provisional</b>Proposed by the owner; the evidence supports it today but the team has not signed off.
        </div>
        <div>
          <b>Locked</b>The owner signed off. Versioned with the confidences, levers and scenario ranges at that moment.
        </div>
        <div>
          <b>Reopened</b>A hypothesis behind it crossed its threshold since the lock. The sign-off no longer stands by default.
        </div>
      </div>
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 6 }} className="s m">
        <span>Lock with scenario</span>
        <select className="theme" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} style={{ width: "auto" }}>
          <option value="">Run Monte Carlo on current levers</option>
          {(scen.data || []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>
      {q.isError && <ErrorState err={q.error} what="positions" onRetry={() => q.refetch()} />}
      {q.isLoading && <Loading what="positions" />}
      {q.data && !q.data.length && <Empty title="No positions configured.">This asset has no decision lines yet.</Empty>}
      <div className="pos">
        {(q.data || []).map((p) => (
          <PositionRow key={p.id} p={p} slug={slug} scenarioId={scenarioId || undefined} />
        ))}
      </div>
      <div className="foot">
        <p className="m s" style={{ maxWidth: "60ch" }}>
          Export freezes the six positions with their hypotheses, the signals that moved them (with source and retrieval date),
          the alternatives considered and the scenario ranges as a versioned, printable record.
          {expErr && <span className="ferr" style={{ display: "block" }}>{expErr}</span>}
        </p>
        <button className="btn p" disabled={exp.isPending} onClick={() => exp.mutate()}>
          {exp.isPending ? "Exporting…" : `Export ${asset.data?.decision_type ?? "TPP"} brief`}
        </button>
      </div>
    </section>
  );
}
