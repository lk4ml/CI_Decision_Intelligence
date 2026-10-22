import Simulate from "@/components/simulate/Simulate";

export default async function Page({ params }: { params: Promise<{ asset: string }> }) {
  const { asset } = await params;
  return <Simulate slug={asset} />;
}
