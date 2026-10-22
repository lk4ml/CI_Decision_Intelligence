"use client";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { api } from "@/lib/api";
import { Empty, ErrorState, Loading } from "@/components/common/States";

export default function AppIndex() {
  const router = useRouter();
  const q = useQuery({ queryKey: ["assets"], queryFn: api.assets });
  useEffect(() => {
    if (q.data && q.data.length) router.replace(`/app/${q.data[0].slug}/asset`);
  }, [q.data, router]);
  return (
    <div className="wrap" style={{ maxWidth: 640, paddingTop: 80 }}>
      {q.isError ? (
        <ErrorState err={q.error} what="assets" onRetry={() => q.refetch()} />
      ) : q.data && !q.data.length ? (
        <Empty title="No assets configured.">Seed the API or onboard an asset.</Empty>
      ) : (
        <Loading what="your assets" />
      )}
    </div>
  );
}
