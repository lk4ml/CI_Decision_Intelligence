"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { Empty, ErrorState, Illustrative, Loading } from "../common/States";
import { CoverageNotice } from "../common/Coverage";
import PhaseBadge from "../common/PhaseBadge";
import TrialTimeline from "./TrialTimeline";

type Pool = { label?: string; name?: string; cutoff?: string; value?: number; patients?: number; note?: string; basis?: string };

function normPools(raw: unknown): Pool[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw as Pool[];
  if (typeof raw === "object")
    return Object.entries(raw as Record<string, unknown>).map(([k, v]) =>
      typeof v === "number" ? { label: k, value: v } : { label: k, ...(v as Pool) },
    );
  return [];
}

export default function AssetContext({ slug }: { slug: string }) {
  const asset = useQuery({ queryKey: ["asset", slug], queryFn: () => api.asset(slug) });
  const brief = useQuery({ queryKey: ["brief", slug], queryFn: () => api.brief(slug) });
  const focus = useQuery({ queryKey: ["focus", slug], queryFn: () => api.focus(slug) });
  const trials = useQuery({ queryKey: ["trials", slug], queryFn: () => api.trials(slug) });
  const levers = useQuery({ queryKey: ["levers", slug], queryFn: () => api.levers(slug) });
  const cur = levers.data ? levers.data.current ?? levers.data.defaults : undefined;
  const run = useQuery({
    queryKey: ["models-run", slug, cur],
    queryFn: () => api.runModels(slug, cur!),
    enabled: !!cur,
  });

  if (asset.isError) return <ErrorState err={asset.error} what="the asset" onRetry={() => asset.refetch()} />;
  if (!asset.data) return <Loading what="asset" />;
  const a = asset.data;
  const series = run.data?.demand?.series as { pools?: unknown } | undefined;
  const pools = normPools(series?.pools);

  return (
    <section>
      <div className="ah1">
        <div>
          <div className="eyeb">
            Decision workspace / {a.code}
          </div>
          <h1>{a.name}</h1>
          <div className="sub">
            {[a.mechanism, `${a.biomarker} ${a.indication}`].filter(Boolean).join(" · ")} ·{" "}
            <PhaseBadge phase={a.phase} source={a.phase_source} discrepancy={a.phase_discrepancy} />
            {a.decision_type ? ` · ${a.decision_type}` : ""}
          </div>
          {a.descriptor && <p className="m s" style={{ marginTop: 6, maxWidth: "70ch" }}>{a.descriptor}</p>}
        </div>
      </div>
      <div className="ctx">
        <div>
          <h4>Asset brief</h4>
          <div className="ttl">A shared context for every decision</div>
          {brief.isError && <ErrorState err={brief.error} what="the brief" />}
          {brief.isLoading && <Loading />}
          {brief.data?.rows.map((r) => (
            <div className="brow" key={r.label}>
              <div>
                <b>{r.label}</b>
                <span>{r.value}</span>
              </div>
              {r.step ? <Link href={`/app/${slug}/${r.step}`}>Open →</Link> : <span />}
            </div>
          ))}
        </div>
        <div>
          <h4>Today&apos;s focus</h4>
          <div className="ttl">A decision, not another report</div>
          <div className="focus">
            {focus.isError && <ErrorState err={focus.error} what="today's focus" />}
            {focus.isLoading && <Loading />}
            {focus.data && (
              <>
                {focus.data.kind === "pattern" && <span className="kick">Proposed decision</span>}
                {focus.data.kind === "signal" && <span className="kick">High-impact signal</span>}
                <b>{focus.data.title}</b>
                <p>{focus.data.detail}</p>
                {focus.data.link_step && (
                  <Link className="a" style={{ display: "inline-block", marginTop: 12, fontWeight: 700 }} href={`/app/${slug}/${focus.data.link_step}`}>
                    {focus.data.kind === "pattern"
                      ? "Open proposed decision →"
                      : focus.data.kind === "signal"
                        ? "Review the signal →"
                        : "View positions →"}
                  </Link>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      <div className="tl">
        <div className="hd">
          <div>
            <h3>Trials that shape this decision</h3>
            <p>
              Ours and the competing programs for the same patients, as retrieved by Registry watch from ClinicalTrials.gov.
              Hover for the profile; click for the detail.
            </p>
          </div>
        </div>
        {trials.isError && <ErrorState err={trials.error} what="trials" onRetry={() => trials.refetch()} />}
        {trials.isLoading && <Loading what="trials" />}
        {trials.data &&
          (trials.data.items.length ? (
            <>
              <TrialTimeline trials={trials.data.items} />
              {trials.data.coverage.status === "source_unreachable" && (
                <div style={{ marginTop: 12 }}>
                  <CoverageNotice
                    coverage={trials.data.coverage}
                    slug={slug}
                    agentKey="registry_watch"
                    emptyTitle="Latest registry refresh failed; showing last retrieved trials"
                    emptyNeverRun=""
                    emptyOk=""
                  />
                </div>
              )}
            </>
          ) : (
            <CoverageNotice
              coverage={trials.data.coverage}
              slug={slug}
              agentKey="registry_watch"
              emptyTitle="Registry watch has not retrieved trials yet."
              emptyNeverRun="The agent has not run for this asset. Trials appear here only after a live fetch from ClinicalTrials.gov."
              emptyOk="The last run completed but found no matching trials for this asset's watch terms."
            />
          ))}
      </div>

      <div className="pools">
        <h3>
          Patient pools the designs compete for <Illustrative />
        </h3>
        {run.isError && <ErrorState err={run.error} what="the demand model" />}
        {levers.isError && <ErrorState err={levers.error} what="levers" />}
        {(levers.isLoading || run.isLoading) && <Loading what="demand model" />}
        {run.data && !pools.length && <Empty title="No patient pools returned.">The demand model did not return pools for this asset.</Empty>}
        {pools.length > 0 && (
          <div className="pg">
            {pools.map((p, i) => (
              <div className="pc" key={i}>
                <b>{fmtNum(p.value ?? p.patients ?? null)}</b>
                <span>{p.label ?? p.name ?? p.cutoff}</span>
                {p.note && <small>{p.note}</small>}
                <small>{p.basis === "sourced" ? "sourced input" : "stand-in assumption"}</small>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
