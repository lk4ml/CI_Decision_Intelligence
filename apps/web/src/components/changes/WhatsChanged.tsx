"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { countOf, signed } from "@/lib/format";
import { useUi } from "@/lib/store";
import type { ChangeHypothesis, ChangePattern, ChangePosition, ChangeSignal } from "@/lib/types";
import { ErrorState, Loading } from "../common/States";

function list<T>(v: number | T[]): T[] {
  return Array.isArray(v) ? v : [];
}

export default function WhatsChanged({ slug }: { slug: string }) {
  const role = useUi((s) => s.viewRole);
  const q = useQuery({ queryKey: ["changes", slug, role], queryFn: () => api.changes(slug, role) });
  if (q.isError) return <ErrorState err={q.error} what="what's changed" onRetry={() => q.refetch()} />;
  if (!q.data) return <Loading />;
  const c = q.data;
  const nSig = countOf(c.pending_signals);
  const nMov = countOf(c.moved_hypotheses);
  const nPat = countOf(c.fired_patterns);
  const nPos = countOf(c.reopened_positions);
  const sigs = list<ChangeSignal>(c.pending_signals);
  const movs = list<ChangeHypothesis>(c.moved_hypotheses);
  const pats = list<ChangePattern>(c.fired_patterns);
  const poss = list<ChangePosition>(c.reopened_positions);
  const rows = [
    {
      t: "Signals waiting for your review",
      d: nSig
        ? `${sigs.filter((s) => s.impact === "high").length ? sigs.filter((s) => s.impact === "high").length + " high impact · " : ""}each carries a proposed confidence move`
        : "Nothing waiting. Agents surface signals only when they touch a registered hypothesis.",
      n: nSig,
      hi: nSig > 0,
      href: "signals",
      cta: "Review",
    },
    {
      t: "Hypotheses you own that moved",
      d: nMov
        ? movs.map((h) => `${h.code ?? ""} ${h.delta !== undefined ? signed(Math.round(h.delta)) : ""}`.trim()).join(" · ") || `${nMov} moved`
        : "No material movement yet.",
      n: nMov,
      hi: false,
      href: "hypotheses",
      cta: "Open",
    },
    {
      t: "Decisions proposed from the evidence",
      d: nPat ? pats.map((p) => p.title).filter(Boolean).join(" · ") || `${nPat} proposed` : "None yet — patterns fire when hypotheses move in combination.",
      n: nPat,
      hi: nPat > 0,
      href: "workbench",
      cta: "Workbench",
    },
    {
      t: "Positions reopened",
      d: nPos
        ? `${poss.map((p) => p.line).filter(Boolean).join(", ")} — a hypothesis crossed its threshold`
        : "No position reopened; no hypothesis crossed a threshold.",
      n: nPos,
      hi: nPos > 0,
      href: "positions",
      cta: nPos ? "Decide" : "View",
    },
  ];
  return (
    <section>
      <h1>What&apos;s changed</h1>
      <p className="m" style={{ margin: "6px 0 22px", maxWidth: "62ch" }}>
        {c.lede}
      </p>
      <div className="todo">
        {rows.map((r) => (
          <div className="it" key={r.t}>
            <div>
              <div className="t">{r.t}</div>
              <div className="d">{r.d}</div>
            </div>
            <div className="rt">
              <span className={`n ${r.hi ? "a" : ""}`}>{r.n}</span>
              <Link className="btn sm" href={`/app/${slug}/${r.href}`}>
                {r.cta}
              </Link>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
