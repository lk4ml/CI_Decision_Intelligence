import { fmtNum } from "@/lib/format";
import type { MonteCarloResult } from "@/lib/types";

export default function Histogram({ mc }: { mc: MonteCarloResult }) {
  const bins = mc.histogram.map((h) =>
    typeof h === "number" ? { count: h, lo: undefined as number | undefined, hi: undefined as number | undefined } : { count: h.count, lo: h.lo ?? h.x ?? h.bin, hi: h.hi },
  );
  if (!bins.length) return <div className="f s">No histogram returned.</div>;
  const mx = Math.max(...bins.map((b) => b.count), 1);
  const W = 600;
  const H = 110;
  const bw = W / bins.length;
  let med = bins.findIndex((b) => b.lo !== undefined && b.hi !== undefined && mc.peak.p50 >= b.lo && mc.peak.p50 < b.hi);
  if (med < 0) {
    // cumulative median bin
    const tot = bins.reduce((a, b) => a + b.count, 0);
    let c = 0;
    med = bins.findIndex((b) => (c += b.count) >= tot / 2);
  }
  const lo = bins[0].lo;
  const hi = bins[bins.length - 1].hi ?? bins[bins.length - 1].lo;
  return (
    <>
      <svg className="histsvg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Peak sales distribution">
        {bins.map((b, i) => {
          const h = (b.count / mx) * H;
          const inMid = i >= bins.length * 0.1 && i <= bins.length * 0.9;
          return (
            <rect
              key={i}
              x={i * bw + 1}
              y={H - h}
              width={Math.max(bw - 2, 1)}
              height={h}
              fill={i === med ? "var(--acc)" : inMid ? "var(--ink)" : "var(--bg-3)"}
            >
              <title>{`${b.count} scenarios${b.lo !== undefined ? ` · ${fmtNum(b.lo)}–${fmtNum(b.hi ?? null)}` : ""}`}</title>
            </rect>
          );
        })}
        <line x1="0" y1={H - 0.5} x2={W} y2={H - 0.5} stroke="var(--line-2)" />
      </svg>
      <div className="axis">
        <span>{lo !== undefined ? fmtNum(lo, "$B") : `P10 ${fmtNum(mc.peak.p10, "$B")}`}</span>
        <span>P50 {fmtNum(mc.peak.p50, "$B")}</span>
        <span>{hi !== undefined ? fmtNum(hi, "$B") : `P90 ${fmtNum(mc.peak.p90, "$B")}`}</span>
      </div>
    </>
  );
}
