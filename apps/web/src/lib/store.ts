"use client";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export const ROLES = [
  "Asset lead",
  "Clinical",
  "Access & pricing",
  "Forecasting",
  "Operations",
  "Reviewer",
  "Admin",
] as const;
export type Role = (typeof ROLES)[number];

/** Default model tab per role (PRD §2 "Default view"). */
export const ROLE_DEFAULT_MODEL: Record<Role, string> = {
  "Asset lead": "business",
  Clinical: "ptrs",
  "Access & pricing": "access",
  Forecasting: "demand",
  Operations: "feasibility",
  Reviewer: "business",
  Admin: "business",
};

/** Actor string sent with review/lock actions until auth exists. */
export const actorFor = (role: Role) => `user:${role}`;

export type Drawer =
  | { kind: "registerHypothesis" }
  | { kind: "hypothesis"; id: string }
  | { kind: "agent"; id: string }
  | { kind: "source"; key: string }
  | { kind: "trial"; id: string }
  | { kind: "newAgent" }
  | null;

interface UiState {
  viewRole: Role;
  setViewRole: (r: Role) => void;
  modelTab: string | null;
  setModelTab: (t: string | null) => void;
  drawer: Drawer;
  openDrawer: (d: Drawer) => void;
  closeDrawer: () => void;
  toast: string | null;
  showToast: (m: string) => void;
}

let toastTimer: ReturnType<typeof setTimeout> | undefined;

export const useUi = create<UiState>()(
  persist(
    (set) => ({
      viewRole: "Asset lead",
      setViewRole: (viewRole) => set({ viewRole, modelTab: null }),
      modelTab: null,
      setModelTab: (modelTab) => set({ modelTab }),
      drawer: null,
      openDrawer: (drawer) => set({ drawer }),
      closeDrawer: () => set({ drawer: null }),
      toast: null,
      showToast: (m) => {
        set({ toast: m });
        if (toastTimer) clearTimeout(toastTimer);
        toastTimer = setTimeout(() => set({ toast: null }), 2600);
      },
    }),
    { name: "di-ui", partialize: (s) => ({ viewRole: s.viewRole }) },
  ),
);
