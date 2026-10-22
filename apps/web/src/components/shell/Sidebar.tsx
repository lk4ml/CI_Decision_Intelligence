"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { phaseSourceLabel } from "@/lib/format";
import { ROLES, type Role, useUi } from "@/lib/store";
import RunningAgents from "./RunningAgents";
import OnboardDrawer from "./OnboardDrawer";
import { errorText } from "../common/States";

export default function Sidebar({ slug }: { slug: string }) {
  const path = usePathname() || "";
  const studio = path.endsWith("/studio");
  const assets = useQuery({ queryKey: ["assets"], queryFn: api.assets });
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  const { viewRole, setViewRole } = useUi();
  const [onb, setOnb] = useState(false);
  const step = studio ? "asset" : path.split("/").pop() || "asset";
  return (
    <aside className="side">
      <div className="mark">
        <div>
          <b>Decision Intelligence</b>
          <small>
            by <em>ZS</em>
          </small>
        </div>
      </div>
      <div>
        <h4>Workspace</h4>
        <div className="nv">
          <Link className={studio ? "" : "on"} href={`/app/${slug}/asset`}>
            <i></i>Decision workspace
          </Link>
          <Link className={studio ? "on" : ""} href={`/app/${slug}/studio`}>
            <i className="o"></i>Agent Studio<span className="n">{agents.data?.length ?? ""}</span>
          </Link>
        </div>
      </div>
      <RunningAgents />
      <div>
        <h4>Your assets</h4>
        {assets.isError && <div className="warn xs" style={{ marginBottom: 8 }}>{errorText(assets.error)}</div>}
        {assets.isLoading && <div className="f xs" style={{ marginBottom: 8 }}>Loading…</div>}
        {assets.data?.map((a) => (
          <Link
            key={a.slug}
            className={`asset ${a.slug === slug ? "" : "off"}`}
            href={`/app/${a.slug}/${studio ? "studio" : step}`}
          >
            <b>{a.name}</b>
            <span>
              {a.biomarker} {a.indication}
            </span>
            <span className="ph">
              {a.phase} · {phaseSourceLabel(a.phase_source)}
            </span>
          </Link>
        ))}
        <button className="onb" onClick={() => setOnb(true)}>
          + Onboard asset
        </button>
      </div>
      <div>
        <h4>Viewing as</h4>
        <select
          className="theme"
          style={{ width: "100%", borderRadius: 10 }}
          value={viewRole}
          onChange={(e) => setViewRole(e.target.value as Role)}
          aria-label="Viewing as role"
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>
      <div className="ft">
        <b>PILOT ENVIRONMENT</b>
        Agents read live public sources. Model outputs are stand-ins until Astellas engines are connected. Not connected
        to internal systems.
      </div>
      <OnboardDrawer open={onb} onClose={() => setOnb(false)} />
    </aside>
  );
}
