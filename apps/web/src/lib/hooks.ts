"use client";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type { ActivityEvent } from "./types";

/** Subscribes to GET /events/stream (SSE) and invalidates affected queries. */
export function useLiveEvents(asset?: string, onEvent?: (e: ActivityEvent) => void) {
  const qc = useQueryClient();
  const [connected, setConnected] = useState(false);
  const cb = useRef(onEvent);
  cb.current = onEvent;
  useEffect(() => {
    if (typeof window === "undefined" || typeof EventSource === "undefined") return;
    const es = new EventSource(api.streamUrl(asset));
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    const handle = (type: string) => (msg: MessageEvent) => {
      let data: Record<string, unknown> = {};
      try {
        data = JSON.parse(msg.data);
      } catch {
        /* ignore */
      }
      const ev: ActivityEvent = { type, ...(data as ActivityEvent) };
      if (!ev.type) ev.type = type;
      cb.current?.(ev);
      // Invalidate everything asset-scoped; queries are cheap and the bus is low-volume.
      qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "landing" });
    };
    const types = [
      "message",
      "signal.created",
      "signal.applied",
      "signal.dismissed",
      "signal.undone",
      "hypothesis.updated",
      "hypothesis.created",
      "hypothesis.crossed",
      "position.reopened",
      "position.locked",
      "pattern.fired",
      "pattern.cleared",
      "levers.updated",
      "agent.run.started",
      "agent.run.finished",
      "agent_run",
      "agent.updated",
      "trial.updated",
      "brief.exported",
      "audit",
    ];
    const listeners = types.map((t) => {
      const h = handle(t);
      es.addEventListener(t, h as EventListener);
      return [t, h] as const;
    });
    return () => {
      listeners.forEach(([t, h]) => es.removeEventListener(t, h as EventListener));
      es.close();
    };
  }, [asset, qc]);
  return connected;
}

export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}
