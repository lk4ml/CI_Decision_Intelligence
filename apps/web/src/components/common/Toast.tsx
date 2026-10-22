"use client";
import { useUi } from "@/lib/store";

export default function Toast() {
  const t = useUi((s) => s.toast);
  return (
    <div className={`toast ${t ? "on" : ""}`} role="status" aria-live="polite">
      {t}
    </div>
  );
}
