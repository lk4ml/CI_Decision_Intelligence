"use client";
import { ApiError } from "@/lib/api";

export function Loading({ what }: { what?: string }) {
  return <div className="loading">Loading{what ? ` ${what}` : ""}…</div>;
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return `Not permitted for your role: ${err.detail}`;
    if (err.status === 409) return `Conflict: ${err.detail}`;
    if (err.status === 0) return err.detail;
    return `${err.status} — ${err.detail}`;
  }
  return (err as Error)?.message || String(err);
}

export function ErrorState({ err, what, onRetry }: { err: unknown; what?: string; onRetry?: () => void }) {
  return (
    <div className="errbox" role="alert">
      <b>Could not load{what ? ` ${what}` : ""}.</b> {errorText(err)}
      {onRetry && (
        <button className="btn sm" style={{ marginLeft: 10 }} onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="read" style={{ marginTop: 0 }}>
      <b>{title}</b> {children}
    </div>
  );
}

export function Illustrative({ text = "illustrative stand-in" }: { text?: string }) {
  return (
    <span className="illus" title="Value comes from a stand-in model assumption, not Astellas's engine or a sourced input">
      {text}
    </span>
  );
}
