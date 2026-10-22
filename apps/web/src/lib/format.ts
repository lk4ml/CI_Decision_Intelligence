export function fmtDate(iso?: string | null, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", year: "numeric" }) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", opts);
}

export function fmtDateTime(iso?: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function fmtTime(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

export function dayLabel(iso?: string | null) {
  if (!iso) return "Undated";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "Undated";
  const today = new Date();
  const y = new Date(today);
  y.setDate(today.getDate() - 1);
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  const base = d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "short" });
  if (same(d, today)) return `Today · ${base}`;
  if (same(d, y)) return `Yesterday · ${base}`;
  return base;
}

export function signed(n: number) {
  return `${n > 0 ? "+" : ""}${n}`;
}

export function fmtNum(v: number | string | null | undefined, unit?: string | null) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "string") return unit ? `${v} ${unit}` : v;
  let u = unit || "";
  const ul = u.toLowerCase();
  if (ul === "probability" || ul === "fraction" || ul === "share") u = "%";
  else if (ul === "usd b" || ul === "usd bn") u = "$B";
  else if (ul === "usd m") u = "$M";
  else if (ul === "usd/month" || ul === "usd / month" || ul === "$/month" || ul === "$/mo") u = "$/mo";
  else if (ul === "usd") u = "$";
  const abs = Math.abs(v);
  let s: string;
  if (u === "%" ) s = `${Math.round(v * (abs <= 1 ? 100 : 1))}`;
  else if (abs >= 1_000_000) s = `${(v / 1_000_000).toFixed(1)}M`;
  else if (abs >= 10_000) s = `${Math.round(v / 1000)}k`;
  else if (u === "$/mo" || u === "$") s = Math.round(v).toLocaleString("en-US");
  else if (Number.isInteger(v)) s = v.toLocaleString("en-US");
  else s = v.toFixed(abs < 10 ? 2 : 1);
  if (!u) return s;
  if (u === "%") return `${s}%`;
  if (u === "$") return `$${s}`;
  if (u === "$/mo") return `$${s}/mo`;
  if (u === "$B" || u === "$bn") return `$${s}B`;
  if (u === "$M" || u === "$m") return `$${s}M`;
  return `${s} ${u}`;
}

export function cadenceText(min: number | null | undefined, category?: string) {
  if (category === "on_event" || !min) return "on event";
  if (min % 1440 === 0) return min === 1440 ? "daily" : `every ${min / 1440}d`;
  if (min % 60 === 0) return `every ${min / 60}h`;
  return `every ${min}m`;
}

/** Addendum A #12: anything other than "registry" is user-provided and not yet verified. */
export function phaseSourceLabel(src?: string | null) {
  return src === "registry" ? "registry-verified" : "user-provided, not registry-verified";
}

type Bucket<T> = number | T[] | { count?: number; items?: T[] } | null | undefined;

export function countOf<T>(v: Bucket<T>): number {
  if (v === null || v === undefined) return 0;
  if (typeof v === "number") return v;
  if (Array.isArray(v)) return v.length;
  return v.count ?? v.items?.length ?? 0;
}

export function itemsOf<T>(v: Bucket<T>): T[] {
  if (!v || typeof v === "number") return [];
  if (Array.isArray(v)) return v;
  return v.items ?? [];
}

export function yearFrac(iso?: string | null): number | null {
  if (!iso) return null;
  const m = /^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?/.exec(iso);
  if (!m) return null;
  const y = +m[1];
  const mo = m[2] ? +m[2] - 1 : 0;
  const d = m[3] ? +m[3] - 1 : 0;
  return y + (mo + d / 30) / 12;
}

export function quarterOf(iso?: string | null) {
  const f = yearFrac(iso);
  if (f === null) return "—";
  return `${Math.floor(f)} Q${Math.floor((f % 1) * 4) + 1}`;
}

/** Returns the URL only if it is an absolute http(s) URL; anything else (javascript:, data:, relative) is rejected. */
export function safeHref(url?: string | null): string | undefined {
  if (!url || typeof url !== "string") return undefined;
  const u = url.trim();
  if (!/^https?:\/\//i.test(u)) return undefined;
  try {
    const p = new URL(u);
    return p.protocol === "http:" || p.protocol === "https:" ? p.href : undefined;
  } catch {
    return undefined;
  }
}
