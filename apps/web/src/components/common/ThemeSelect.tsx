"use client";
import { useEffect, useState } from "react";

type Theme = "system" | "light" | "dark";

export default function ThemeSelect() {
  const [theme, setTheme] = useState<Theme>("system");
  useEffect(() => {
    const t = (typeof localStorage !== "undefined" && localStorage.getItem("di-theme")) as Theme | null;
    if (t) setTheme(t);
  }, []);
  const apply = (t: Theme) => {
    setTheme(t);
    try {
      localStorage.setItem("di-theme", t);
    } catch {
      /* storage unavailable */
    }
    if (t === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", t);
  };
  return (
    <select className="theme" aria-label="Theme" value={theme} onChange={(e) => apply(e.target.value as Theme)}>
      <option value="system">System theme</option>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
    </select>
  );
}
