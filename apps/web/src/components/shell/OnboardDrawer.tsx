"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import type { AssetCreate } from "@/lib/types";
import Drawer from "../common/Drawer";
import { errorText } from "../common/States";

const PHASES = ["Preclinical", "Phase 1", "Phase 2", "Phase 3", "Approved"];
const DECISIONS = ["TPP", "TA/DA", "Protocol", "Feasibility", "BD"];

export default function OnboardDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const router = useRouter();
  const [f, setF] = useState<AssetCreate>({
    code: "",
    name: "",
    mechanism: "",
    indication: "",
    biomarker: "",
    phase: "Phase 2",
    decision_type: "TPP",
    governance_forum: "",
    governance_date: "",
  });
  const set = (k: keyof AssetCreate) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.value });
  const m = useMutation({
    mutationFn: () => api.createAsset({ ...f, governance_date: f.governance_date || undefined }),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["assets"] });
      onClose();
      if (a?.slug) router.push(`/app/${a.slug}/asset`);
    },
  });
  const ok = f.code.trim() && f.name.trim() && f.indication.trim();
  return (
    <Drawer open={open} onClose={onClose}>
      <span className="kick">New asset</span>
      <h3>Onboard an asset</h3>
      <p className="m s">
        The same seven-step workflow starts for every asset. Agents begin once the first hypothesis is registered.
      </p>
      <div className="fm">
        <div>
          <label>Asset code</label>
          <input type="text" value={f.code} onChange={set("code")} placeholder="e.g. ASP-3082" />
        </div>
        <div>
          <label>Name</label>
          <input type="text" value={f.name} onChange={set("name")} />
        </div>
        <div>
          <label>Phase</label>
          <select value={f.phase} onChange={set("phase")}>
            {PHASES.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </div>
        <div>
          <label>Decision type</label>
          <select value={f.decision_type} onChange={set("decision_type")}>
            {DECISIONS.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </div>
        <div className="full">
          <label>Mechanism / target</label>
          <input type="text" value={f.mechanism} onChange={set("mechanism")} />
        </div>
        <div>
          <label>Indication and line</label>
          <input type="text" value={f.indication} onChange={set("indication")} />
        </div>
        <div>
          <label>Biomarker</label>
          <input type="text" value={f.biomarker} onChange={set("biomarker")} />
        </div>
        <div>
          <label>Governance forum</label>
          <input type="text" value={f.governance_forum} onChange={set("governance_forum")} />
        </div>
        <div>
          <label>Governance date</label>
          <input type="text" value={f.governance_date} onChange={set("governance_date")} placeholder="YYYY-MM-DD" />
        </div>
      </div>
      {m.isError && <div className="ferr">{errorText(m.error)}</div>}
      <div className="ft">
        <span className="f s">Phase stays user-provided until Registry watch verifies it.</span>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn sm" onClick={onClose}>
            Cancel
          </button>
          <button className="btn sm p" disabled={!ok || m.isPending} onClick={() => m.mutate()}>
            {m.isPending ? "Creating…" : "Create workspace"}
          </button>
        </div>
      </div>
    </Drawer>
  );
}
