import SignalsView from "@/components/signals/SignalsView";

export default async function Page({ params }: { params: Promise<{ asset: string }> }) {
  const { asset } = await params;
  return <SignalsView slug={asset} />;
}
