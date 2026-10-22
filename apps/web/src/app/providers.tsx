"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { setIdentity } from "@/lib/api";
import { actorFor, useUi } from "@/lib/store";

function IdentitySync() {
  const role = useUi((s) => s.viewRole);
  useEffect(() => {
    setIdentity(actorFor(role), role);
  }, [role]);
  return null;
}

export default function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: 1, staleTime: 15_000, refetchOnWindowFocus: false } },
      }),
  );
  return (
    <QueryClientProvider client={qc}>
      <IdentitySync />
      {children}
    </QueryClientProvider>
  );
}
