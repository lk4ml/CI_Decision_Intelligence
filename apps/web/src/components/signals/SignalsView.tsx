"use client";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { dayLabel, fmtDate, fmtDateTime, safeHref, signed } from "@/lib/format";
import ExtLink from "../common/ExtLink";
import { useUi } from "@/lib/store";
import type { Signal } from "@/lib/types";
import { CoverageNotice } from "../common/Coverage";
import HowItWorks from "../common/HowItWorks";
import { ErrorState, Loading, errorText } from "../common/States";

function SignalCard({ s, slug }: { s: Signal; slug: string }) {
  const qc = useQueryClient();
  const toast = useUi((st) => st.showToast);
  const role = useUi((st) => st.viewRole);
  const [err, setErr] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: (action: "apply" | "dismiss" | "undo") =>
      action === "apply" ? api.applySignal(s.id) : action === "dismiss" ? api.dismissSignal(s.id) : api.undoSignal(s.id),
    onSuccess: (_d, action) => {
      setErr(null);
      toast(action === "apply" ? "Applied — confidences updated" : action === "dismiss" ? "Dismissed" : "Undone");
      qc.invalidateQueries();
    },
    onError: (e) => setErr(errorText(e)),
  });
  const done = s.review_status !== "pending";
  const readOnly = role === "Reviewer";
  return (
    <div className={`sg ${done ? "done" : ""}`}>
      <div>
        <div className="src">
          {s.impact === "high" && <span className="tag">High impact</span>}
          <span className="tag g">
            <span className="dot"></span>
            {s.agent?.name ?? "Unknown agent"}
          </span>
          <ExtLink url={s.source_url}>{s.source_name}</ExtLink>
          <span>retrieved {fmtDateTime(s.retrieved_at)}</span>
          {s.published_at && <span>· published {fmtDate(s.published_at)}</span>}
        </div>
        <div className="t">{s.title}</div>
        <div className="so">
          {s.so_what_origin === "llm" && (
            <span className="tag w" style={{ marginRight: 6 }} title="So-what drafted by an LLM from the fetched item; numbers and identifiers are checked against the source">
              AI-drafted
            </span>
          )}
          {s.so_what}
        </div>
        <div className="mvs">
          <span className="f">Proposed</span>
          {s.moves.length ? (
            s.moves.map((mv) => (
              <span key={mv.hypothesis_code} title={mv.rationale || undefined}>
                {mv.hypothesis_code} <span className={`d ${mv.delta > 0 ? "p" : ""}`}>{signed(mv.delta)}</span>
              </span>
            ))
          ) : (
            <span className="f">no move</span>
          )}
          {s.review_status === "applied" && <span className="tag">applied</span>}
          {s.review_status === "dismissed" && <span className="tag g">dismissed</span>}
        </div>
        {err && <div className="ferr">{err}</div>}
      </div>
      <div className="acts">
        {!done ? (
          <>
            <button className="btn sm p" disabled={m.isPending || readOnly} onClick={() => m.mutate("apply")}>
              Apply
            </button>
            <button className="btn sm" disabled={m.isPending || readOnly} onClick={() => m.mutate("dismiss")}>
              Dismiss
            </button>
          </>
        ) : (
          <button className="btn sm t" disabled={m.isPending || readOnly} onClick={() => m.mutate("undo")}>
            Undo
          </button>
        )}
      </div>
    </div>
  );
}

function Digest({ slug }: { slug: string }) {
  const role = useUi((s) => s.viewRole);
  const [open, setOpen] = useState(false);
  const q = useQuery({ queryKey: ["digest", slug, role], queryFn: () => api.digest(slug, role), enabled: open });
  return (
    <details className="mail" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        <span>Preview this morning&apos;s digest to {role.toLowerCase()}</span>
        <span>07:00</span>
      </summary>
      <div className="eb">
        {q.isError && <ErrorState err={q.error} what="the digest" />}
        {q.isLoading && <Loading what="digest" />}
        {q.data && (
          <>
            {q.data.subject && <div className="subj">{q.data.subject}</div>}
            {q.data.html ? (
              <iframe
                title="Digest preview"
                sandbox=""
                srcDoc={q.data.html}
                style={{ width: "100%", minHeight: 320, border: "1px solid var(--line)", borderRadius: 10, background: "#fff" }}
              />
            ) : q.data.items ? (
              <ul>
                {q.data.items.map((it, i) => (
                  <li key={i}>
                    <b>{it.title}</b>
                    <br />
                    <span>{it.so_what}</span> <span className="f xs">{[it.agent, it.moves].filter(Boolean).join(" · ")}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <pre className="s" style={{ whiteSpace: "pre-wrap", fontFamily: "inherit" }}>
                {q.data.text ?? q.data.body ?? ""}
              </pre>
            )}
            <Link className="btn p sm" style={{ marginTop: 8 }} href={`/app/${slug}/workbench`}>
              Open the workbench
            </Link>
          </>
        )}
      </div>
    </details>
  );
}

function HeldForTriage({ slug }: { slug: string }) {
  const q = useQuery({ queryKey: ["unmatched", slug], queryFn: () => api.unmatched(slug) });
  if (q.isError) return <div style={{ marginTop: 28 }}><ErrorState err={q.error} what="items held for triage" /></div>;
  if (!q.data?.length) return null;
  return (
    <details className="mail" style={{ marginTop: 28 }}>
      <summary>
        <span>Held for triage by the Guardrail agent · {q.data.length}</span>
        <span>not shown as signals</span>
      </summary>
      <div className="eb">
        <ul>
          {q.data.map((u) => (
            <li key={u.id}>
              <ExtLink className={safeHref(u.url) ? "a" : undefined} url={u.url}>
                {u.title || u.url || "Untitled item"}
              </ExtLink>
              <br />
              <span>{u.reason}</span>{" "}
              <span className="f xs">
                {u.source_key ?? ""} {u.retrieved_at ? `· retrieved ${fmtDate(u.retrieved_at)}` : ""} {u.created_at ? `· held ${fmtDate(u.created_at)}` : ""}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}

export default function SignalsView({ slug }: { slug: string }) {
  const qc = useQueryClient();
  const toast = useUi((s) => s.showToast);
  const role = useUi((s) => s.viewRole);
  const q = useQuery({ queryKey: ["signals", slug], queryFn: () => api.signals(slug) });
  const all = useMutation({
    mutationFn: () => api.applyAll(slug),
    onSuccess: () => {
      toast("Applied all remaining signals in your scope");
      qc.invalidateQueries();
    },
    onError: (e) => toast(errorText(e)),
  });
  const items = q.data?.items || [];
  const pending = items.filter((s) => s.review_status === "pending").length;
  const groups: { label: string; sigs: Signal[] }[] = [];
  items
    .slice()
    .sort((a, b) => (b.retrieved_at || "").localeCompare(a.retrieved_at || ""))
    .forEach((s) => {
      const l = dayLabel(s.retrieved_at);
      const g = groups.find((x) => x.label === l);
      if (g) g.sigs.push(s);
      else groups.push({ label: l, sigs: [s] });
    });

  return (
    <section>
      <div className="sect">
        <div>
          <h2>Signals</h2>
          <p>Only items that touch a hypothesis. Each carries the agent that found it, its source and retrieval date, and a proposed move.</p>
        </div>
        <button className="btn" disabled={!pending || all.isPending || role === "Reviewer"} onClick={() => all.mutate()}>
          {all.isPending ? "Applying…" : `Apply all remaining${pending ? ` (${pending})` : ""}`}
        </button>
      </div>
      <HowItWorks
        title="Signals"
        cols={[
          ["What it is", "A detectable change in the world or in Astellas's own disclosures, with a one-line \"so what\" for this decision."],
          ["Who owns it", "The agent that found it is named on each signal; the hypothesis owner decides whether to apply the proposed move."],
          ["How the move is sized", "Evidence strength × source reliability × relevance. A registry Phase 3 start is strong; an investor-call remark is weak. Overrides are logged."],
        ]}
      />
      <Digest slug={slug} />
      {q.isError && <ErrorState err={q.error} what="signals" onRetry={() => q.refetch()} />}
      {q.isLoading && <Loading what="signals" />}
      {q.data && !items.length && (
        <div style={{ marginTop: 16 }}>
          <CoverageNotice
            coverage={q.data.coverage}
            slug={slug}
            agentKey="registry_watch"
            emptyTitle="No signals yet."
            emptyNeverRun="Agents are configured and live, but none has run for this asset yet. Signals appear only from live fetches that touch a registered hypothesis."
            emptyOk="Agents are live and running; none has produced a signal that touches a hypothesis on this asset yet."
          />
        </div>
      )}
      {q.data && items.length > 0 && q.data.coverage.status === "source_unreachable" && (
        <div className="errbox" style={{ marginTop: 16 }}>
          <b>Latest agent run could not reach its source.</b> {q.data.coverage.last_run?.agent_key}{" "}
          {q.data.coverage.last_run?.error ? `· ${q.data.coverage.last_run.error}` : ""}
        </div>
      )}
      {groups.map((g) => (
        <div key={g.label}>
          <div className="dayh">{g.label}</div>
          {g.sigs.map((s) => (
            <SignalCard key={s.id} s={s} slug={slug} />
          ))}
        </div>
      ))}
      <HeldForTriage slug={slug} />
    </section>
  );
}
