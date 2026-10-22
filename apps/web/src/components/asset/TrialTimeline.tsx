"use client";
import { useState } from "react";
import { fmtDate, quarterOf, yearFrac } from "@/lib/format";
import type { Trial } from "@/lib/types";

const Y0 = 2025;
const Y1 = 2032;
const YEARS = Array.from({ length: Y1 - Y0 }, (_, i) => Y0 + i);
const ROLE_ORDER: Record<string, number> = { own: 0, standard: 1, competitor: 2 };
const ROLE_LABEL: Record<string, string> = { own: "Ours", standard: "Standard of care", competitor: "Competitor" };

export default function TrialTimeline({ trials }: { trials: Trial[] }) {
  const [tip, setTip] = useState<{ t: Trial; x: number; y: number } | null>(null);
  const [sel, setSel] = useState<Trial | null>(null);
  const now = new Date();
  const nowPct = ((now.getFullYear() + now.getMonth() / 12 - Y0) / (Y1 - Y0)) * 100;
  const rows = trials.slice().sort((a, b) => (ROLE_ORDER[a.role] ?? 9) - (ROLE_ORDER[b.role] ?? 9));
  return (
    <>
      <div className="gantt">
        <div className="yrs">
          <span></span>
          <div className="ax">
            {YEARS.map((y) => (
              <span key={y}>{y}</span>
            ))}
          </div>
        </div>
        {rows.map((t) => {
          const s = yearFrac(t.start_date);
          const e = yearFrac(t.primary_completion);
          const s0 = Math.max(Y0, Math.min(Y1, s ?? Y0));
          const e0 = Math.max(s0 + 0.15, Math.min(Y1, e ?? s0 + 0.5));
          const left = ((s0 - Y0) / (Y1 - Y0)) * 100;
          const width = ((e0 - s0) / (Y1 - Y0)) * 100;
          const cls = t.role === "own" ? "ours" : t.role === "standard" ? "std" : "";
          return (
            <div className="row" key={t.id || t.nct_id}>
              <div className="lab">
                <b>
                  {t.nct_id} · {t.sponsor || "Sponsor not listed"}
                </b>
                <span>
                  {ROLE_LABEL[t.role] || t.role} · {t.phase || "phase n/a"} · {t.status || "status n/a"}
                </span>
              </div>
              <div className="lane">
                {nowPct > 0 && nowPct < 100 && <div className="now" style={{ left: `${nowPct}%` }} />}
                <button
                  className={`bar ${cls}`}
                  style={{ left: `${left}%`, width: `${width}%` }}
                  onMouseMove={(ev) => setTip({ t, x: ev.clientX, y: ev.clientY })}
                  onMouseLeave={() => setTip(null)}
                  onFocus={(ev) => {
                    const r = ev.currentTarget.getBoundingClientRect();
                    setTip({ t, x: r.left, y: r.bottom });
                  }}
                  onBlur={() => setTip(null)}
                  onClick={() => setSel(t)}
                  aria-label={`${t.nct_id} details`}
                >
                  {t.title}
                  {e !== null && <span className="ro" />}
                </button>
              </div>
            </div>
          );
        })}
      </div>
      {tip && (
        <div className="tip on" style={{ left: tip.x + 14, top: tip.y + 14 }}>
          <b>{tip.t.title}</b>
          {tip.t.phase || "—"} · n {tip.t.enrollment ?? "—"} · {tip.t.status || "—"}
          <br />
          <span>
            Primary completion ~{quarterOf(tip.t.primary_completion)} · {(tip.t.endpoints || []).slice(0, 2).join("; ") || "endpoints not listed"}
          </span>
          <br />
          <span>{ROLE_LABEL[tip.t.role] || tip.t.role} · retrieved {fmtDate(tip.t.retrieved_at)}</span>
        </div>
      )}
      {sel && (
        <div className="tdet on">
          <div>
            <b>Trial</b>
            <span>
              <a className="a" href={sel.source_url} target="_blank" rel="noreferrer">
                {sel.nct_id}
              </a>{" "}
              · {sel.sponsor || "—"}
            </span>
          </div>
          <div>
            <b>Population</b>
            <span>
              {(sel.conditions || []).join(", ") || "—"} · n {sel.enrollment ?? "—"}
            </span>
          </div>
          <div>
            <b>Endpoints</b>
            <span>{(sel.endpoints || []).join("; ") || "—"}</span>
          </div>
          <div>
            <b>Expected primary completion</b>
            <span>~{quarterOf(sel.primary_completion)}</span>
          </div>
          <div style={{ gridColumn: "1/3" }}>
            <b>Interventions</b>
            <span>{(sel.interventions || []).join("; ") || "—"}</span>
          </div>
          <div style={{ gridColumn: "3/5" }}>
            <b>Source</b>
            <span>
              ClinicalTrials.gov · retrieved {fmtDate(sel.retrieved_at)} ·{" "}
              <button className="btn sm t" onClick={() => setSel(null)}>
                Close
              </button>
            </span>
          </div>
        </div>
      )}
    </>
  );
}
