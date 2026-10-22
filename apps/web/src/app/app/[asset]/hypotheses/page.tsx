import HypothesisTracking from "@/components/hypotheses/HypothesisTracking";

export default async function Page({ params }: { params: Promise<{ asset: string }> }) {
  const { asset } = await params;
  return <HypothesisTracking slug={asset} />;
}
