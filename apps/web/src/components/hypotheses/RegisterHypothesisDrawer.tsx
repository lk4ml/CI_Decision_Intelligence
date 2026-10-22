"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { cadenceText } from "@/lib/format";
import { ROLES, useUi } from "@/lib/store";
import { errorText } from "../common/States";

export const LINES = ["Population", "Intervention", "Comparator", "Outcomes", "Price & access", "Timeline"];
export const CATEGORIES = ["Population", "Intervention", "Comparator", "Outcomes", "Business"];
const lineToCat = (l: string) => (CATEGORIES.includes(l) ? l : "Business");

export default function RegisterHypothesisForm({ slug, onDone }: { slug: string; onDone: () => void }) {
  const qc = useQueryClient();
  const toast = useUi((s) => s.showToast);
  const role = useUi((s) => s.viewRole);
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  const [statement, setStatement] = useState("");
  const [line, setLine] = useState(LINES[0]);
  const [category, setCategory] = useState(lineToCat(LINES[0]));
  const [owner, setOwner] = useState<string>(ROLES.slice(0, 5).includes(role as never) ? role : "Asset lead");
  const [start, setStart] = useState(50);
  const [threshold, setThreshold] = useState(70);
  const [change, setChange] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [draft, setDraft] = useState(false);
  const [dName, setDName] = useState("");
  const [dCat, setDCat] = useState("always_on");
  const [dReads, setDReads] = useState("world");
  const [dDesc, setDDesc] = useState("");
  const [touched, setTouched] = useState(false);

  const errs: string[] = [];
  if (statement.trim().length < 20) errs.push("Statement must be at least 20 characters.");
  if (!(threshold > start)) errs.push("Threshold must be above the starting confidence.");
  if (start < 5 || start > 95) errs.push("Starting confidence must be between 5 and 95.");
  const warnNoAgent = picked.size === 0 && !(draft && dName.trim());

  const m = useMutation({
    mutationFn: async () => {
      const ids = [...picked];
      if (draft && dName.trim()) {
        const a = await api.createAgent({ name: dName.trim(), category: dCat, reads: dReads, description: dDesc });
        ids.push(a.id);
      }
      return api.createHypothesis(slug, {
        statement: statement.trim(),
        category,
        position_line: line,
        owner_role: owner,
        confidence_start: start,
        threshold,
        change_trigger_text: change.trim(),
        agent_ids: ids,
      });
    },
    onSuccess: (h) => {
      const sch = (h as unknown as { scheduled?: { agent_key: string }[] }).scheduled;
      toast(`${h.code ?? "Hypothesis"} registered${sch?.length ? ` · ${sch.length} agent run${sch.length > 1 ? "s" : ""} scheduled` : ""}`);
      qc.invalidateQueries();
      onDone();
    },
  });

  return (
    <div className="reg">
      <span className="kick">New hypothesis</span>
      <h3>Register a hypothesis</h3>
      <div className="fm">
        <div className="full">
          <label>Statement — falsifiable, about the world at launch</label>
          <input type="text" value={statement} onChange={(e) => setStatement(e.target.value)} />
        </div>
        <div>
          <label>TPP line it supports</label>
          <select
            value={line}
            onChange={(e) => {
              setLine(e.target.value);
              setCategory(lineToCat(e.target.value));
            }}
          >
            {LINES.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
        </div>
        <div>
          <label>Category</label>
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
        </div>
        <div>
          <label>Owner</label>
          <select value={owner} onChange={(e) => setOwner(e.target.value)}>
            {ROLES.slice(0, 5).map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </div>
        <div>
          <label>Starting confidence (%)</label>
          <input type="number" value={start} min={5} max={95} onChange={(e) => setStart(+e.target.value)} />
        </div>
        <div>
          <label>Threshold that reopens the line (%)</label>
          <input type="number" value={threshold} min={5} max={99} onChange={(e) => setThreshold(+e.target.value)} />
        </div>
        <div className="full">
          <label>What would change my mind</label>
          <input
            type="text"
            value={change}
            onChange={(e) => setChange(e.target.value)}
            placeholder="The observable event that should move this"
          />
        </div>
        <div className="full">
          <label>Attach agents from the catalog</label>
          {agents.isError && <div className="warn xs">{errorText(agents.error)}</div>}
          <div className="chips">
            {(agents.data || []).map((a) => (
              <button
                key={a.id}
                className={`chip ${picked.has(a.id) ? "on" : ""}`}
                onClick={() => {
                  const n = new Set(picked);
                  if (n.has(a.id)) n.delete(a.id);
                  else n.add(a.id);
                  setPicked(n);
                }}
              >
                {a.name}
                <small>{cadenceText(a.cadence_minutes, a.category)}</small>
              </button>
            ))}
          </div>
        </div>
        <div className="full" style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button className="btn sm" onClick={() => setDraft(!draft)}>
            {draft ? "− Remove draft agent" : "+ Draft a new agent for this hypothesis"}
          </button>
          <span className="f xs">New agents start supervised and join the catalog.</span>
        </div>
        {draft && (
          <div className="draft on">
            <b className="s">New agent</b>
            <div className="g">
              <input type="text" placeholder="Agent name" value={dName} onChange={(e) => setDName(e.target.value)} />
              <select value={dCat} onChange={(e) => setDCat(e.target.value)}>
                <option value="always_on">Always-on</option>
                <option value="daily">Daily</option>
                <option value="on_event">On event</option>
              </select>
              <select value={dReads} onChange={(e) => setDReads(e.target.value)}>
                <option value="world">World knowledge</option>
                <option value="company">Astellas knowledge</option>
                <option value="models">Models</option>
              </select>
            </div>
            <input
              type="text"
              placeholder="What it reads and what it extracts"
              style={{ marginTop: 8 }}
              value={dDesc}
              onChange={(e) => setDDesc(e.target.value)}
            />
          </div>
        )}
      </div>
      {touched && errs.map((e) => <div className="ferr" key={e}>{e}</div>)}
      {warnNoAgent && <div className="fwarn">No agent attached — nothing will look for evidence on this hypothesis.</div>}
      {m.isError && <div className="ferr">{errorText(m.error)}</div>}
      <div className="ft">
        <span className="f s">Agents begin scanning for this hypothesis on their next cycle.</span>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn sm" onClick={onDone}>
            Cancel
          </button>
          <button
            className="btn sm p"
            disabled={m.isPending}
            onClick={() => {
              setTouched(true);
              if (!errs.length) m.mutate();
            }}
          >
            {m.isPending ? "Registering…" : "Register"}
          </button>
        </div>
      </div>
    </div>
  );
}
