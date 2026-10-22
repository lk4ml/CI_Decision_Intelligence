"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import type { Coverage } from "@/lib/types";
import { errorText } from "./States";

/** Honest empty / unreachable state driven by coverage.status (Addendum A #6), with a Run-now button. */
export function CoverageNotice({
  coverage,
  slug,
  agentKey,
  emptyTitle,
  emptyNeverRun,
  emptyOk,
}: {
  coverage: Coverage;
  slug: string;
  agentKey: string;
  emptyTitle: string;
  emptyNeverRun: string;
  emptyOk: string;
}) {
  const qc = useQueryClient();
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  const agent = agents.data?.find((a) => a.key === (coverage.last_run?.agent_key || agentKey));
  const run = useMutation({
    mutationFn: () => api.runAgent(agent!.id, slug),
    onSettled: () => qc.invalidateQueries(),
  });
  const lr = coverage.last_run;
  const unreachable = coverage.status === "source_unreachable";
  return (
    <div className={unreachable ? "errbox" : "read"} style={{ marginTop: 0 }}>
      {unreachable ? <b>{emptyTitle} — source unreachable.</b> : <b>{emptyTitle}</b>}{" "}
      {coverage.status === "never_run" ? emptyNeverRun : unreachable ? "" : emptyOk}
      {lr && (
        <div className="s" style={{ marginTop: 6 }}>
          Last run: <span className={unreachable ? "warn" : ""}>{coverage.status}</span>
          {lr.agent_key ? ` · ${agent?.name ?? lr.agent_key}` : ""} · {fmtDateTime(lr.finished_at)}
          {lr.error ? (
            <>
              {" "}
              · <span className="warn">{lr.error}</span>
            </>
          ) : null}
        </div>
      )}
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 10, flexWrap: "wrap" }}>
        <button className="btn sm p" disabled={!agent || run.isPending} onClick={() => run.mutate()}>
          {run.isPending ? "Running…" : `Run ${agent?.name ?? agentKey.replace("_", " ")} now`}
        </button>
        {agents.isError && <span className="warn xs">{errorText(agents.error)}</span>}
        {run.data && (
          <span className={`xs ${run.data.status === "ok" ? "a" : "warn"}`}>
            Run finished: {run.data.status}
            {run.data.items_fetched !== undefined ? ` · ${run.data.items_fetched} fetched` : ""}
            {run.data.signals_created !== undefined ? ` · ${run.data.signals_created} signals` : ""}
            {run.data.error ? ` · ${run.data.error}` : ""}
          </span>
        )}
        {run.isError && <span className="warn xs">{errorText(run.error)}</span>}
      </div>
    </div>
  );
}
