"use client";
import ExtLink from "../common/ExtLink";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtDate, fmtNum, signed } from "@/lib/format";
import { useUi } from "@/lib/store";
import type { Levers, Proposal, ProposalOption } from "@/lib/types";
import HowItWorks from "../common/HowItWorks";
import { Empty, ErrorState, Illustrative, Loading, errorText } from "../common/States";

const agentName = (a: Proposal["signals"][number]["agent"]) => (typeof a === "string" ? a : a?.name ?? "agent");

function ProposalCard({ p, slug, current }: { p: Proposal; slug: string; current?: Levers }) {
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useUi((s) => s.showToast);
  const explore = useMutation({
    mutationFn: (o: ProposalOption) => api.putLevers(slug, o.levers ?? { ...(current || {}), [o.lever]: o.value }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["levers", slug] });
      toast("Levers set — exploring this option");
      router.push(`/app/${slug}/simulate`);
    },
    onError: (e) => toast(errorText(e)),
  });
  const take = p.framing === "take";
  const conf = p.hypotheses.length ? Math.round(p.hypotheses.reduce((a, h) => a + h.confidence, 0) / p.hypotheses.length) : null;
  const codes = new Set(p.hypotheses.map((h) => h.code));
  const agents: Record<string, number> = {};
  p.signals.forEach((s) => {
    const n = agentName(s.agent);
    agents[n] = (agents[n] || 0) + 1;
  });
  const isCur = (o: ProposalOption) =>
    o.is_current ?? (current ? String(current[o.lever]) === String(o.value) : false);
  return (
    <div className="di">
      <div className="dh">
        <div>
          <div className="ln">{p.pattern.position_line} · proposed</div>
          <h3>{p.pattern.title}</h3>
          <div className="ev">
            {p.signals.length} signal{p.signals.length !== 1 ? "s" : ""} ·{" "}
            {p.hypotheses.map((h) => `${h.code} ${Math.round(h.confidence)}%`).join(" · ")}
            {take ? " · threshold crossed" : ""}
            {p.fired_at ? ` · fired ${fmtDate(p.fired_at)}` : ""}
          </div>
        </div>
        <div className="stat">
          <b>{conf !== null ? `${conf}%` : "—"}</b>position confidence
        </div>
      </div>
      <div className="q">
        <b>{take ? "Decision to take:" : "Decision to frame:"}</b> {p.pattern.rationale}
      </div>
      <div className="trg">
        <b>Trigger fired:</b> {p.pattern.trigger_text} — from each hypothesis&apos;s &quot;what would change my mind&quot;.
      </div>
      <div className="chain">
        <div>
          <h4>Evidence chain</h4>
          <div className="evl">
            {p.signals.length ? (
              p.signals.map((s) => (
                <div key={s.id}>
                  <span>
                    <ExtLink url={s.source_url}>{s.title}</ExtLink>
                    <small>
                      {agentName(s.agent)} · {s.source_name ?? "source"} · {fmtDate(s.retrieved_at)}
                    </small>
                  </span>
                  <span className="mm">
                    {(s.moves || [])
                      .filter((m) => codes.has(m.hypothesis_code))
                      .map((m) => `${m.hypothesis_code} ${signed(m.delta)}`)
                      .join(", ")}
                  </span>
                </div>
              ))
            ) : (
              <div>
                <span className="f">Triggered by threshold edits or lever state rather than signals</span>
              </div>
            )}
          </div>
        </div>
        <div>
          <h4>How it got here</h4>
          <div className="agl">
            {Object.entries(agents).map(([a, n]) => (
              <div key={a}>
                <b>{a}</b>
                <span>
                  {n} signal{n > 1 ? "s" : ""} surfaced
                </span>
              </div>
            ))}
            <div>
              <b>Implication agent</b>
              <span>proposed the moves and fired this pattern</span>
            </div>
            <div>
              <b>Simulation agent</b>
              <span>priced the options below</span>
            </div>
            <div>
              <b>Guardrail agent</b>
              <span>every signal cited with source and date</span>
            </div>
          </div>
        </div>
      </div>
      <div className="opts">
        <h4>
          Options, simulated with today&apos;s confidences <Illustrative />
        </h4>
        <table>
          <thead>
            <tr>
              <th>Option</th>
              <th className="n">Patients</th>
              <th className="n">PTRS</th>
              <th className="n">Peak</th>
              <th className="n">Readout</th>
              <th className="n">US net / mo</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {p.options.map((o) => (
              <tr key={o.label} className={isCur(o) ? "cur" : ""}>
                <td className="o">
                  {o.label} {isCur(o) && <span className="tag g">current</span>}
                </td>
                <td className="n">{fmtNum(o.results.patients ?? null)}</td>
                <td className="n">{fmtNum(o.results.ptrs ?? null, "%")}</td>
                <td className="n">{fmtNum(o.results.peak ?? null, "$B")}</td>
                <td className="n">{o.results.readout ?? "—"}</td>
                <td className="n">{fmtNum(o.results.us_net ?? null, "$")}</td>
                <td className="n">
                  <button className="btn sm" disabled={explore.isPending} onClick={() => explore.mutate(o)}>
                    Explore
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="acts">
        <Link className="btn sm p" href={`/app/${slug}/positions`}>
          Take to positions
        </Link>
        <Link className="btn sm" href={`/app/${slug}/simulate`}>
          Open full simulation
        </Link>
      </div>
    </div>
  );
}

export default function Workbench({ slug }: { slug: string }) {
  const props = useQuery({ queryKey: ["proposals", slug], queryFn: () => api.proposals(slug) });
  const pats = useQuery({ queryKey: ["patterns", slug], queryFn: () => api.patterns(slug) });
  const levers = useQuery({ queryKey: ["levers", slug], queryFn: () => api.levers(slug) });
  const current = levers.data ? levers.data.current ?? levers.data.defaults : undefined;
  const list = (props.data || [])
    .slice()
    .sort((a, b) => Number(b.framing === "take") - Number(a.framing === "take") || (b.total_movement ?? 0) - (a.total_movement ?? 0));
  const nSig = new Set(list.flatMap((p) => p.signals.map((s) => s.id))).size;
  const notFired = (pats.data || []).filter((p) => !p.is_fired);
  return (
    <section>
      <div className="sect">
        <div>
          <h2>Decision workbench</h2>
          <p>
            {props.data
              ? list.length
                ? `${list.length} decision${list.length > 1 ? "s" : ""} proposed from ${nSig} applied signal${nSig !== 1 ? "s" : ""}. Each shows the trigger that fired, the evidence chain, and the options priced with today's confidences.`
                : "No decisions proposed yet. Patterns fire when hypotheses move in combination."
              : ""}
          </p>
        </div>
      </div>
      <HowItWorks
        title="Proposed decisions"
        cols={[
          ["What it is", "Decisions proposed from combinations of hypothesis movement — not a fixed list. Each names the trigger that fired, the evidence, and the options."],
          ["Who owns it", "The owner of the affected TPP line frames and takes the decision; contributors see the same chain in their view."],
          ["How it works", "Every hypothesis carries a \"what would change my mind\" trigger. When triggers fire together, a decision pattern proposes options and the Simulation agent prices them with today's confidences."],
        ]}
      />
      {props.isError && <ErrorState err={props.error} what="proposals" onRetry={() => props.refetch()} />}
      {props.isLoading && <Loading what="proposals" />}
      {props.data && !list.length && (
        <Empty title="No proposed decisions.">Apply signals in step 04 — patterns fire when the hypotheses they watch move together.</Empty>
      )}
      {list.map((p) => (
        <ProposalCard key={p.id} p={p} slug={slug} current={current} />
      ))}
      <div className="near">
        <h4>Patterns not yet fired</h4>
        {pats.isError && <ErrorState err={pats.error} what="patterns" />}
        {pats.data && !notFired.length && <div className="f">Every configured pattern has fired.</div>}
        {notFired.map((p) => (
          <div key={p.id || p.key}>
            <span>
              <b>{p.title}</b> · {p.position_line}
            </span>
            <span>fires at {p.trigger_text}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
