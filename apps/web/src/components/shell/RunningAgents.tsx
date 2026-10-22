"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useNow } from "@/lib/hooks";
import { errorText } from "../common/States";

const CAT: [string, string][] = [
  ["always_on", "Always-on"],
  ["daily", "Daily"],
  ["on_event", "On event"],
];

function num(v: unknown): { total: number; running: number | null } {
  if (typeof v === "number") return { total: v, running: null };
  if (v && typeof v === "object") {
    const o = v as { count?: number; total?: number; running?: number };
    return { total: o.total ?? o.count ?? 0, running: o.running ?? null };
  }
  return { total: 0, running: null };
}

export default function RunningAgents() {
  const q = useQuery({ queryKey: ["agents-status"], queryFn: api.agentsStatus, refetchInterval: 60_000 });
  const now = useNow();
  if (q.isError)
    return (
      <div className="sideagents">
        <b>Agents</b>
        <span className="warn xs">{errorText(q.error)}</span>
      </div>
    );
  if (!q.data)
    return (
      <div className="sideagents">
        <b>Agents</b>
        <span className="f xs">Loading…</span>
      </div>
    );
  const s = q.data;
  const cats = CAT.map(([k, l]) => ({ k, l, ...num(s.by_category?.[k]) }));
  const running = s.running ?? cats.reduce((a, c) => a + (c.running ?? c.total), 0);
  let next = "—";
  if (s.next_cycle_at && now) {
    const ms = new Date(s.next_cycle_at).getTime() - now.getTime();
    next = ms <= 0 ? "due now" : `${Math.floor(ms / 3600000)}h ${Math.floor((ms % 3600000) / 60000)}m`;
  }
  return (
    <div className="sideagents">
      <b>
        <span className="runner">
          <i></i>
          <i></i>
          <i></i>
        </span>
        {running} agents running
      </b>
      {cats.map((c) => (
        <div key={c.k}>
          <span>{c.l}</span>
          <span>{c.total}</span>
        </div>
      ))}
      <div>
        <span>Next cycle</span>
        <span>{next}</span>
      </div>
    </div>
  );
}
