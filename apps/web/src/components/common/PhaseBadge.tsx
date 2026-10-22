import { phaseSourceLabel } from "@/lib/format";

export default function PhaseBadge({ phase, source, discrepancy }: { phase: string; source?: string | null; discrepancy?: string | null }) {
  const verified = source === "registry";
  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
      <span>{phase}</span>
      <span className={`tag ${verified ? "" : "w"}`} title={verified ? "Confirmed against ClinicalTrials.gov by Registry watch" : "Provided by the team; Registry watch has not confirmed it"}>
        {phaseSourceLabel(source)}
      </span>
      {discrepancy ? <span className="tag w">Registry differs: {discrepancy}</span> : null}
    </span>
  );
}
