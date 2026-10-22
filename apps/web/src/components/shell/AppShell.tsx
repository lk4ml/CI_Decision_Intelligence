"use client";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { useUi } from "@/lib/store";
import { useLiveEvents } from "@/lib/hooks";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import JourneyStrip from "./JourneyStrip";
import Toast from "../common/Toast";

export default function AppShell({ slug, children }: { slug: string; children: React.ReactNode }) {
  const path = usePathname() || "";
  const studio = path.endsWith("/studio");
  const live = useLiveEvents(slug);
  useEffect(() => useUi.getState().closeDrawer(), [path]);
  return (
    <div className="app">
      <Sidebar slug={slug} />
      <div className="main">
        <Topbar slug={slug} live={live} />
        <div className="wrap">
          {!studio && <JourneyStrip slug={slug} />}
          {studio && <div style={{ height: 22 }} />}
          {children}
        </div>
      </div>
      <Toast />
    </div>
  );
}
