import { fmtNum } from "@/lib/format";

type Row = { label: string; value: number; unit?: string };

function asRows(v: unknown): Row[] | null {
  if (!Array.isArray(v) || !v.length) return null;
  const rows: Row[] = [];
  for (const it of v) {
    if (Array.isArray(it) && it.length >= 2 && typeof it[1] === "number") rows.push({ label: String(it[0]), value: it[1] });
    else if (it && typeof it === "object") {
      const o = it as Record<string, unknown>;
      const label = o.label ?? o.name ?? o.stage ?? o.market ?? o.country ?? o.year ?? o.key;
      const value = o.value ?? o.patients ?? o.count ?? o.amount ?? o.n;
      if (label !== undefined && typeof value === "number") rows.push({ label: String(label), value, unit: (o.unit as string) || undefined });
      else return null;
    } else return null;
  }
  return rows;
}

function Bars({ rows }: { rows: Row[] }) {
  const mx = Math.max(...rows.map((r) => Math.abs(r.value)), 1);
  return (
    <div className="fun">
      {rows.map((r, i) => (
        <div className="fr" key={r.label + i}>
          <div>{r.label}</div>
          <div className="b">
            <i style={{ width: `${(Math.abs(r.value) / mx) * 100}%` }}></i>
          </div>
          <div className="n">{fmtNum(r.value, r.unit)}</div>
        </div>
      ))}
    </div>
  );
}

const title = (k: string) => k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** Renders the model-specific `series` payload generically: lists become bars, scalars a key-value table. */
export default function SeriesView({ series }: { series: unknown }) {
  if (series === null || series === undefined) return null;
  const direct = asRows(series);
  if (direct) return <Bars rows={direct} />;
  if (typeof series !== "object" || Array.isArray(series)) return null;
  const entries = Object.entries(series as Record<string, unknown>);
  const lists = entries.map(([k, v]) => [k, asRows(v)] as const).filter(([, r]) => r);
  const scalars = entries.filter(([, v]) => typeof v === "number" || typeof v === "string");
  return (
    <div className="series">
      {lists.map(([k, r]) => (
        <div key={k} style={{ marginBottom: 18 }}>
          <h4 style={{ marginBottom: 6 }}>{title(k)}</h4>
          <Bars rows={r!} />
        </div>
      ))}
      {scalars.length > 0 && (
        <div className="mk" style={{ gridTemplateColumns: "1fr 1fr" }}>
          {scalars.map(([k, v]) => (
            <div className="kv" key={k}>
              <span>{title(k)}</span>
              <b>{typeof v === "number" ? fmtNum(v) : String(v)}</b>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
