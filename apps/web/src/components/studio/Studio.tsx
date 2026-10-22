"use client";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cadenceText, fmtTime } from "@/lib/format";
import { useLiveEvents } from "@/lib/hooks";
import { useUi } from "@/lib/store";
import type { ActivityEvent, Agent, Source } from "@/lib/types";
import Drawer from "../common/Drawer";
import HowItWorks from "../common/HowItWorks";
import { ErrorState, Loading } from "../common/States";
import { AgentInspector, NewAgentForm, SourceInspector } from "./Inspectors";

const CATS: [Agent["category"], string, string][] = [
  ["always_on", "Always-on", "every 6h"],
  ["daily", "Daily", "once a day"],
  ["on_event", "On event", "on trigger"],
];
const READS: Record<string, string> = { world: "World", company: "Astellas", models: "Models" };

function SourceCard({ s, agents, onOpen }: { s: Source; agents: Agent[]; onOpen: () => void }) {
  const readers = agents.filter((a) => (a.source_keys || []).includes(s.key)).map((a) => a.name);
  const bad = s.last_status === "source_unreachable" || s.last_status === "error";
  return (
    <div className="src" role="button" tabIndex={0} onClick={onOpen} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onOpen()}>
      <b>{s.name}</b>
      {s.kind}
      <em>
        {s.access_level} · {readers.length ? `read by ${readers.join(", ")}` : "no agent reading"}
      </em>
      <em className={bad ? "warn" : ""}>
        {s.last_status ? `last fetch ${s.last_status}` : "never fetched"}
        {bad && s.last_error ? ` · ${s.last_error}` : ""}
      </em>
    </div>
  );
}

function AgentCard({ a, onOpen }: { a: Agent; onOpen: () => void }) {
  const running = a.status === "running";
  const lr = a.last_run;
  const bad = lr?.status === "source_unreachable" || lr?.status === "error";
  return (
    <div className={`agent ${running ? "scan" : ""}`} role="button" tabIndex={0} onClick={onOpen} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onOpen()}>
      <div className="ah">
        <span>{a.name}</span>
        <span className="stt">
          <span className={`runner ${running ? "" : "sup"}`}>
            <i></i>
            <i></i>
            <i></i>
          </span>
          {a.status}
        </span>
      </div>
      <p>{a.description}</p>
      <div className="now">
        <span className={bad ? "warn" : ""}>
          {lr ? <b className={bad ? "warn" : ""}>{lr.status}</b> : null} {lr?.summary || (lr ? "" : "Not yet run")}
          {bad && lr?.error ? ` · ${lr.error}` : ""}
        </span>
      </div>
      <div className="ft2">
        <span style={{ color: "var(--ink-2)" }}>
          Reads {READS[a.reads] ?? a.reads}
          {a.attached_hypotheses?.length ? ` · attached to ${a.attached_hypotheses.join(", ")}` : ""}
        </span>
        <span>{cadenceText(a.cadence_minutes, a.category)}</span>
      </div>
    </div>
  );
}

function describe(e: ActivityEvent) {
  const text =
    e.message ||
    e.summary ||
    [e.action || e.type, e.entity, (e.payload as { title?: string } | null)?.title].filter(Boolean).join(" · ");
  return { who: e.actor || (e.type ? e.type.split(".")[0] : "system"), text, ts: e.created_at || e.ts };
}

function ActivityLog({ slug }: { slug: string }) {
  const recent = useQuery({ queryKey: ["events-recent", slug], queryFn: () => api.recentEvents(slug) });
  const [live, setLive] = useState<(ActivityEvent & { _k: number })[]>([]);
  useEffect(() => setLive([]), [slug]);
  const onEvent = useCallback((e: ActivityEvent) => setLive((l) => [{ ...e, _k: Date.now() + Math.random() }, ...l].slice(0, 14)), []);
  const connected = useLiveEvents(slug, onEvent);
  const rows = [
    ...live.map((e) => ({ ...describe(e), k: `l${e._k}`, fresh: true })),
    ...(recent.data || []).map((e, i) => ({ ...describe(e), k: `r${e.id ?? i}`, fresh: false })),
  ].slice(0, 14);
  return (
    <>
      <h3 style={{ margin: "30px 0 8px", display: "flex", justifyContent: "space-between" }}>
        Activity
        <span className="livepill">
          <span className={`dot ${connected ? "pulse" : ""}`} style={connected ? undefined : { background: "var(--line-2)" }} />
          {connected ? "streaming" : "stream offline"}
        </span>
      </h3>
      {recent.isError && <ErrorState err={recent.error} what="recent activity" />}
      {recent.isLoading && <Loading what="activity" />}
      {recent.data && !rows.length && <div className="f s">No agent or audit activity recorded yet.</div>}
      <div className="log">
        {rows.map((r) => (
          <div key={r.k} className={r.fresh ? "new" : ""}>
            <span className="ts">{r.fresh && !r.ts ? "now" : fmtTime(r.ts)}</span>
            <span className="ag">{r.who}</span>
            <span>{r.text}</span>
          </div>
        ))}
      </div>
    </>
  );
}

export default function Studio({ slug }: { slug: string }) {
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const { drawer, openDrawer, closeDrawer, viewRole } = useUi();
  const ag = agents.data || [];
  const src = sources.data || [];
  const col = (side: "world" | "company") => (
    <>
      {sources.isError && <ErrorState err={sources.error} what="sources" />}
      {sources.isLoading && <Loading />}
      {sources.data && !src.filter((s) => s.side === side).length && <div className="f s">No {side === "world" ? "public" : "company"} sources configured.</div>}
      {src
        .filter((s) => s.side === side)
        .map((s) => (
          <SourceCard key={s.key} s={s} agents={ag} onOpen={() => openDrawer({ kind: "source", key: s.key })} />
        ))}
    </>
  );
  return (
    <section>
      <div className="sect">
        <div>
          <h2>Agent Studio</h2>
          <p>Two kinds of knowledge on either side, the agents in between. Attach them to hypotheses, change their cadence, or draft a new one.</p>
        </div>
        <button className="btn p" disabled={viewRole === "Reviewer"} onClick={() => openDrawer({ kind: "newAgent" })}>
          + Draft a new agent
        </button>
      </div>
      <HowItWorks
        title="Agents"
        cols={[
          ["Always-on", "Scan external sources on a fixed cycle (default every 6 hours) with change detection, so only deltas are processed."],
          ["Daily", "Index Astellas's own published material — pipeline page, press releases, results presentations — once a day."],
          ["On event", "Run when something happens: a signal arrives (Implication), a confidence changes (Simulation), a brief is requested, or any claim is made (Guardrail)."],
        ]}
      />
      <div className="legendrow">
        <span>
          <i className="ld run"></i>Running
        </span>
        <span>
          <i className="ld sup"></i>Supervised · proposals reviewed
        </span>
        <span>
          <i className="ld plan"></i>Planned · not deployed
        </span>
        <span>
          <i className="ld" style={{ background: "var(--warn)" }}></i>
          <span className="warn">Source unreachable</span>
        </span>
        <span style={{ marginLeft: "auto" }} className="f">
          Click any card for the inspector
        </span>
      </div>
      <div className="flow3">
        <div>
          <h4>
            World knowledge<small>Public sources the always-on agents read</small>
          </h4>
          {col("world")}
        </div>
        <div className="mid">
          <h4>
            Agents<small>Grouped by how often they run</small>
          </h4>
          {agents.isError && <ErrorState err={agents.error} what="agents" onRetry={() => agents.refetch()} />}
          {agents.isLoading && <Loading what="agents" />}
          {CATS.map(([c, label, when]) => {
            const as = ag.filter((a) => a.category === c);
            if (!as.length) return null;
            return (
              <div className="cg" key={c}>
                <h5>
                  {label}
                  <span>
                    {when} · {as.length}
                  </span>
                </h5>
                {as.map((a) => (
                  <AgentCard key={a.id} a={a} onOpen={() => openDrawer({ kind: "agent", id: a.id })} />
                ))}
              </div>
            );
          })}
        </div>
        <div>
          <h4>
            Astellas knowledge<small>Company material, validated before it surfaces</small>
          </h4>
          {col("company")}
        </div>
      </div>
      <ActivityLog slug={slug} />
      <Drawer open={drawer?.kind === "agent"} onClose={closeDrawer}>
        {drawer?.kind === "agent" && <AgentInspector id={drawer.id} slug={slug} />}
      </Drawer>
      <Drawer open={drawer?.kind === "source"} onClose={closeDrawer}>
        {drawer?.kind === "source" && <SourceInspector k={drawer.key} />}
      </Drawer>
      <Drawer open={drawer?.kind === "newAgent"} onClose={closeDrawer}>
        <NewAgentForm slug={slug} onDone={closeDrawer} />
      </Drawer>
    </section>
  );
}
