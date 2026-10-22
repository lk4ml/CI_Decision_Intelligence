"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cadenceText, fmtDate, signed } from "@/lib/format";
import { useUi } from "@/lib/store";
import type { Agent, Hypothesis } from "@/lib/types";
import { errorText } from "../common/States";

export function AgentRunnerRow({ a, full }: { a: { name: string; status: string; cadence_minutes: number | null }; full?: Agent }) {
  const sup = a.status !== "running";
  const activity = full?.last_run?.summary || (full?.last_run ? `last run ${full.last_run.status}` : "Not yet run");
  const unreachable = full?.last_run?.status === "source_unreachable";
  return (
    <div>
      <span className={`runner ${sup ? "sup" : ""}`}>
        <i></i>
        <i></i>
        <i></i>
      </span>
      <b>{a.name}</b>
      <span className={`f ${unreachable ? "warn" : ""}`}>
        {cadenceText(a.cadence_minutes, full?.category)} · {a.status} · {activity}
      </span>
    </div>
  );
}

export default function HypothesisDetail({ h, slug }: { h: Hypothesis; slug: string }) {
  const qc = useQueryClient();
  const toast = useUi((s) => s.showToast);
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  const [thr, setThr] = useState(String(h.threshold));
  useEffect(() => setThr(String(h.threshold)), [h.threshold]);
  const inv = () => {
    qc.invalidateQueries({ queryKey: ["hypotheses", slug] });
    qc.invalidateQueries({ queryKey: ["asset", slug] });
    qc.invalidateQueries({ queryKey: ["agents"] });
  };
  const patchThr = useMutation({
    mutationFn: (v: number) => api.patchHypothesis(h.id, { threshold: v }),
    onSuccess: (_d, v) => {
      toast(`${h.code} threshold set to ${v}%`);
      inv();
    },
    onError: (e) => toast(errorText(e)),
  });
  const toggle = useMutation({
    mutationFn: ({ aid, on }: { aid: string; on: boolean }) => (on ? api.detachAgent(h.id, aid) : api.attachAgent(h.id, aid)),
    onSuccess: (_d, v) => {
      toast(v.on ? "Detached" : "Attached");
      inv();
    },
    onError: (e) => toast(errorText(e)),
  });
  const attached = new Set(h.agents.map((a) => a.id));
  const trail = h.evidence.slice().reverse();
  return (
    <div>
      <span className="kick">
        {h.category} · {h.position_line}
      </span>
      <h3>
        <span className="a">{h.code}</span> {h.statement}
      </h3>
      <p className="m s">
        Owner {h.owner_role} · confidence {Math.round(h.confidence)}% (started {Math.round(h.confidence_start)}%) ·{" "}
        {h.for_count} for · {h.against_count} against
        {h.crossed ? <span className="a"> · threshold reached, {h.position_line} reopened</span> : null}
      </p>
      <div className="cf" style={{ margin: "12px 0 18px" }}>
        <div className="b">
          <i style={{ width: `${h.confidence}%` }}></i>
        </div>
        <b>{Math.round(h.confidence)}</b>
      </div>

      <h4>Evidence trail</h4>
      <div className="trail" style={{ marginBottom: 18 }}>
        {trail.length ? (
          trail.map((x, i) => (
            <div key={(x.signal_id || "") + i}>
              <span className={`d ${x.delta > 0 ? "p" : ""}`}>{x.delta ? signed(x.delta) : "set"}</span>
              <span>
                {x.source_url ? (
                  <a href={x.source_url} target="_blank" rel="noreferrer">
                    {x.title}
                  </a>
                ) : (
                  x.title
                )}{" "}
                <span className="w">
                  {x.source_name ?? ""} {x.retrieved_at ? `· retrieved ${fmtDate(x.retrieved_at)}` : ""}
                </span>
              </span>
            </div>
          ))
        ) : (
          <div>
            <span className="d">—</span>
            <span className="f">No evidence applied yet</span>
          </div>
        )}
      </div>

      <h4>Threshold</h4>
      <div className="thr">
        <span className="m s">Reopen {h.position_line} at</span>
        <input
          type="text"
          value={thr}
          onChange={(e) => setThr(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          onBlur={() => {
            const v = parseInt(thr, 10);
            if (v > 0 && v < 100 && v !== h.threshold) patchThr.mutate(v);
            else setThr(String(h.threshold));
          }}
          aria-label="Threshold"
        />
        <span className="m s">% confidence</span>
      </div>
      <h4>What would change my mind</h4>
      <p className="m" style={{ marginBottom: 14 }}>
        {h.change_trigger_text || "—"}
      </p>
      <h4>Agents on this hypothesis</h4>
      <div className="agon" style={{ marginBottom: 14 }}>
        {h.agents.length ? (
          h.agents.map((a) => <AgentRunnerRow key={a.id} a={a} full={agents.data?.find((x) => x.id === a.id)} />)
        ) : (
          <div className="f">No agents attached yet</div>
        )}
      </div>
      <h4>Attach or detach</h4>
      {agents.isError && <div className="warn xs">{errorText(agents.error)}</div>}
      <div className="chips">
        {(agents.data || []).map((a) => (
          <button
            key={a.id}
            className={`chip ${attached.has(a.id) ? "on" : ""}`}
            disabled={toggle.isPending}
            onClick={() => toggle.mutate({ aid: a.id, on: attached.has(a.id) })}
          >
            {a.name}
            <small>{cadenceText(a.cadence_minutes, a.category)}</small>
          </button>
        ))}
      </div>
    </div>
  );
}
