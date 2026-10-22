"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AssetCounts } from "@/lib/types";

export const STEPS: { key: string; no: string; title: string; q: string; badge?: (c: AssetCounts) => string }[] = [
  { key: "asset", no: "01", title: "Asset context", q: "What are we developing?" },
  { key: "changes", no: "02", title: "What's changed", q: "Since you last looked" },
  { key: "hypotheses", no: "03", title: "Hypotheses", q: "What are we testing?", badge: (c) => (c.hypotheses ? String(c.hypotheses) : "") },
  { key: "signals", no: "04", title: "Signals", q: "What did agents find?", badge: (c) => (c.pending_signals ? String(c.pending_signals) : "") },
  { key: "workbench", no: "05", title: "Decision workbench", q: "What is proposed?", badge: (c) => (c.proposals ? String(c.proposals) : "") },
  { key: "simulate", no: "06", title: "Simulate", q: "What if we chose differently?" },
  { key: "positions", no: "07", title: "Positions", q: "What do we commit to?", badge: (c) => `${c.locked_positions ?? 0}/6` },
];

export default function JourneyStrip({ slug }: { slug: string }) {
  const path = usePathname() || "";
  const cur = path.split("/").pop();
  const a = useQuery({ queryKey: ["asset", slug], queryFn: () => api.asset(slug) });
  const counts = a.data?.counts;
  return (
    <nav className="steps tabs" role="tablist" aria-label="Decision journey">
      {STEPS.map((s) => (
        <Link key={s.key} href={`/app/${slug}/${s.key}`} className={cur === s.key ? "on" : ""} role="tab" aria-selected={cur === s.key}>
          <div className="no">{s.no}</div>
          <div className="tt">
            {s.title} {counts && s.badge ? <b>{s.badge(counts)}</b> : null}
          </div>
          <div className="ss">{s.q}</div>
        </Link>
      ))}
    </nav>
  );
}
