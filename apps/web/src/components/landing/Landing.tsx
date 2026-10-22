"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { phaseSourceLabel } from "@/lib/format";
import ThemeSelect from "../common/ThemeSelect";
import { errorText } from "../common/States";

const PILLARS: [string, string][] = [
  ["Register beliefs", "Hypotheses with an owner, a starting confidence, a threshold, and the agents that will look for evidence."],
  ["Agents watch", "Always-on agents for the world — registries, literature, regulators; daily agents for Astellas's own disclosures; event agents for implication and simulation."],
  ["Decisions are proposed", "When hypotheses move in combination, the workbench proposes the decision, the options, and the evidence chain."],
  ["Positions are locked", "Each TPP line is a position with an owner and a sign-off, tied to its hypotheses so a threshold crossing reopens it."],
];

const TYPES: [string, string, string, boolean][] = [
  ["TA / DA strategy", "Where to play and how to win", "Landscape · whitespace · wargaming", false],
  ["TPP / CDP strategy", "How the asset must perform, and what evidence when", "", true],
  ["Clinical program & protocol", "A competitive, executable design", "Design benchmark · HA precedent", false],
  ["Feasibility & planning", "Geographies, sites, investigators", "Competing-trial demand · site intel", false],
  ["BD & licensing", "Which assets, at what value", "Asset scouting · PTRS sweet spot", false],
];

export default function Landing() {
  const stats = useQuery({ queryKey: ["landing", "stats"], queryFn: api.landingStats, refetchInterval: 60_000 });
  const assets = useQuery({ queryKey: ["assets"], queryFn: api.assets });
  const first = assets.data?.[0];
  const hyps = useQuery({
    queryKey: ["hypotheses", first?.slug],
    queryFn: () => api.hypotheses(first!.slug),
    enabled: !!first,
  });
  const props = useQuery({
    queryKey: ["proposals", first?.slug],
    queryFn: () => api.proposals(first!.slug),
    enabled: !!first,
  });
  const top = (hyps.data || []).slice().sort((a, b) => b.confidence - a.confidence).slice(0, 4);
  const enter = first ? `/app/${first.slug}/asset` : "/app";

  return (
    <section className="landing">
      <div className="lbar">
        <div className="mark">
          <div>
            <b>Decision Intelligence</b>
            <small>
              by <em>ZS</em>
            </small>
          </div>
        </div>
        <nav style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ThemeSelect />
          <Link className="btn p" href={enter}>
            Enter the Astellas programs
          </Link>
        </nav>
      </div>
      <div className="hero">
        <span className="eyebrow">
          <span className="dot pulse"></span>
          {stats.data
            ? `Always-on agents refreshed ${stats.data.sources_refreshed_1h} source${stats.data.sources_refreshed_1h === 1 ? "" : "s"} in the last hour · ${stats.data.agents_running} agents running`
            : stats.isError
              ? `Agent status unavailable — ${errorText(stats.error)}`
              : "Checking agent status…"}
        </span>
        <h1>
          Clinical decisions, <em>with intelligence</em> behind them
        </h1>
        <p className="sub">
          Every R&amp;D decision rests on a handful of beliefs about the world at launch. Register them. Attach agents that
          watch the world and Astellas&apos;s own knowledge. Let the evidence move the beliefs, propose the decisions, and
          simulate the trade-offs before they reach governance.
        </p>
        <div className="cta">
          <Link className="btn p lg" href={enter}>
            {first ? `Open the ${first.name} program` : "Open the workspace"}
          </Link>
        </div>
      </div>
      <div className="shot">
        <div className="frame">
          <div className="fb">
            <i></i>
            <i></i>
            <i></i>
          </div>
          <div className="body">
            <div className="sb">
              {(assets.data || []).map((a, i) => (
                <div key={a.slug} className={i === 0 ? "on" : ""}>
                  {a.name}
                  <br />
                  <span className="f xs">
                    {a.biomarker} {a.indication}
                  </span>
                </div>
              ))}
              {assets.isError && <div className="warn">{errorText(assets.error)}</div>}
            </div>
            <div className="col">
              <h4>Hypotheses {first ? `· ${first.name}` : ""}</h4>
              {hyps.isError && <div className="warn s">{errorText(hyps.error)}</div>}
              {hyps.data && !top.length && <div className="f s">No hypotheses registered yet.</div>}
              {top.map((h) => (
                <div className="ln" key={h.id}>
                  <div>
                    {h.code} · {h.statement}
                    <div className="b">
                      <i style={{ width: `${h.confidence}%` }}></i>
                    </div>
                  </div>
                  <b>{Math.round(h.confidence)}%</b>
                </div>
              ))}
            </div>
            <div className="col">
              <h4>Decisions proposed</h4>
              {props.isError && <div className="warn s">{errorText(props.error)}</div>}
              {props.data && !props.data.length && (
                <div className="f s">None yet — patterns fire when hypotheses move in combination.</div>
              )}
              {(props.data || []).slice(0, 3).map((p) => (
                <div className="sg" key={p.id}>
                  {p.pattern.title}
                  <span>
                    {p.hypotheses.map((h) => `${h.code} ${Math.round(h.confidence)}%`).join(" · ")} · {p.options.length} options
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      <div className="pillars">
        {PILLARS.map(([t, d], i) => (
          <div key={t}>
            <h3>
              <i>{i + 1}</i>
              {t}
            </h3>
            <p>{d}</p>
          </div>
        ))}
      </div>
      <div className="streams">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <h2>One pattern, five decision types</h2>
        </div>
        <div className="g">
          {TYPES.map(([t, d, s, live]) => (
            <div key={t} className={`st ${live ? "live" : ""}`}>
              <b>{t}</b>
              {d}
              <span>
                {live
                  ? `● Live: ${(assets.data || []).map((a) => a.code).join(" · ") || "—"}`
                  : `Template · ${s}`}
              </span>
            </div>
          ))}
        </div>
      </div>
      <div className="lfoot">
        <span>
          Pilot · live public sources · model outputs are illustrative stand-ins · ZS 2026
          {first ? ` · ${first.name} phase ${phaseSourceLabel(first.phase_source)}` : ""}
        </span>
        <span>Prepared for Astellas R&amp;D</span>
      </div>
    </section>
  );
}
