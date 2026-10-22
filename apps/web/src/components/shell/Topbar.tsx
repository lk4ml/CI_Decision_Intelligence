"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useNow } from "@/lib/hooks";
import { useUi } from "@/lib/store";
import ThemeSelect from "../common/ThemeSelect";

export default function Topbar({ slug, live }: { slug: string; live: boolean }) {
  const path = usePathname() || "";
  const studio = path.endsWith("/studio");
  const a = useQuery({ queryKey: ["asset", slug], queryFn: () => api.asset(slug) });
  const now = useNow(60_000);
  const role = useUi((s) => s.viewRole);
  const share = () => {
    navigator.clipboard?.writeText(window.location.href).then(
      () => useUi.getState().showToast("Link copied"),
      () => useUi.getState().showToast("Could not copy link"),
    );
  };
  const initials = role
    .split(/[\s&]+/)
    .filter(Boolean)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <header className="top">
      <div className="crumb">
        {studio ? "Agent Studio" : "Decision workspace"} <span>/</span> {a.data?.name ?? slug}
        {a.data?.indication ? (
          <>
            <span>/</span>
            {a.data.biomarker} {a.data.indication}
          </>
        ) : null}
      </div>
      <div className="r">
        <span className="livepill" title="Live event stream">
          <span className={`dot ${live ? "pulse" : ""}`} style={live ? undefined : { background: "var(--line-2)" }} />
          {live ? "Live" : "Stream offline"}
        </span>
        <span>{now ? now.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" }) : ""}</span>
        <ThemeSelect />
        <button className="btn sm" onClick={share}>
          Share
        </button>
        <Link className="btn sm" href="/">
          Overview
        </Link>
        <span className="av" title={role}>
          {initials}
        </span>
      </div>
    </header>
  );
}
