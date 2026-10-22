"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { signed } from "@/lib/format";
import { useUi } from "@/lib/store";
import type { Hypothesis } from "@/lib/types";
import Drawer from "../common/Drawer";
import HowItWorks from "../common/HowItWorks";
import { Empty, ErrorState, Loading } from "../common/States";
import HypothesisDetail from "./HypothesisDetail";
import RegisterHypothesisForm, { CATEGORIES } from "./RegisterHypothesisDrawer";

const SEES_ALL = new Set(["Asset lead", "Admin", "Reviewer"]);

export default function HypothesisTracking({ slug }: { slug: string }) {
  const q = useQuery({ queryKey: ["hypotheses", slug], queryFn: () => api.hypotheses(slug) });
  const { viewRole, drawer, openDrawer, closeDrawer } = useUi();
  const mine = (h: Hypothesis) => h.owner_role === viewRole;
  const all = SEES_ALL.has(viewRole);

  const hs = q.data || [];
  const cats = [...CATEGORIES, ...[...new Set(hs.map((h) => h.category))].filter((c) => !CATEGORIES.includes(c))];
  const groups = cats
    .map((c) => ({ c, hs: hs.filter((h) => h.category === c).sort((a, b) => Number(mine(b)) - Number(mine(a))) }))
    .filter((g) => g.hs.length)
    .sort((a, b) => Number(b.hs.some(mine)) - Number(a.hs.some(mine)));
  const open = drawer?.kind === "hypothesis" ? hs.find((h) => h.id === drawer.id) : undefined;

  return (
    <section>
      <div className="sect">
        <div>
          <h2>Hypothesis tracking</h2>
          <p>The beliefs behind each TPP line, who owns them, and the agents watching for evidence.</p>
        </div>
        <button className="btn p" onClick={() => openDrawer({ kind: "registerHypothesis" })} disabled={viewRole === "Reviewer"}>
          + Register hypothesis
        </button>
      </div>
      <HowItWorks
        title="Hypotheses"
        cols={[
          ["What it is", "A falsifiable statement about the market at launch, tied to one TPP line. Confidence starts at the owner's judgment."],
          ["Who owns it", "The function responsible for that TPP line: Clinical for comparator and endpoints, Access for pricing, Forecasting for testing and demand, Operations for timeline."],
          ["How it updates", "Attached agents surface signals; the Implication agent proposes a move; the owner applies or dismisses. Crossing the threshold reopens the position."],
        ]}
      />
      {q.isError && <ErrorState err={q.error} what="hypotheses" onRetry={() => q.refetch()} />}
      {q.isLoading && <Loading what="hypotheses" />}
      {q.data && !hs.length && (
        <Empty title="No hypotheses yet.">
          Register the first belief behind this program and attach the agents that should look for evidence.
        </Empty>
      )}
      {groups.map((g) => (
        <div className="grp" key={g.c}>
          <h4>{g.c}</h4>
          {g.hs.map((h) => {
            const d = Math.round(h.week_delta || 0);
            const toggle = () => openDrawer({ kind: "hypothesis", id: h.id });
            return (
              <div className={`h ${!all && !mine(h) ? "dim" : ""}`} key={h.id}>
                <div
                  className="tp"
                  role="button"
                  tabIndex={0}
                  onClick={toggle}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      toggle();
                    }
                  }}
                >
                  <div>
                    <div className="st">
                      <span>{h.code}</span>
                      {h.statement}
                    </div>
                    <div className="meta">
                      <span>{h.owner_role}</span>
                      <span>·</span>
                      <span>{h.for_count + h.against_count ? `${h.for_count} for · ${h.against_count} against` : "no evidence yet"}</span>
                      <span>·</span>
                      {h.agents.map((a) => (
                        <span className="ag" key={a.id}>
                          <i></i>
                          {a.name}
                        </span>
                      ))}
                      {!h.agents.length && <span className="warn">no agents attached</span>}
                      {(h.crossed ?? h.confidence >= h.threshold) && (
                        <span className="a">· threshold reached, {h.position_line} reopened</span>
                      )}
                    </div>
                  </div>
                  <div className="cf">
                    <div className="b">
                      <i style={{ width: `${h.confidence}%` }}></i>
                    </div>
                    <b>{Math.round(h.confidence)}</b>
                  </div>
                  <div className={`mv ${d > 0 ? "up" : "z"}`}>{d ? `${signed(d)} this week` : "—"}</div>
                </div>
              </div>
            );
          })}
        </div>
      ))}
      <Drawer open={drawer?.kind === "hypothesis" && !!open} onClose={closeDrawer}>
        {open && <HypothesisDetail h={open} slug={slug} />}
      </Drawer>
      <Drawer open={drawer?.kind === "registerHypothesis"} onClose={closeDrawer}>
        <RegisterHypothesisForm slug={slug} onDone={closeDrawer} />
      </Drawer>
    </section>
  );
}
