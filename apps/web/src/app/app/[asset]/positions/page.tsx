import Positions from "@/components/positions/Positions";

export default async function Page({ params }: { params: Promise<{ asset: string }> }) {
  const { asset } = await params;
  return <Positions slug={asset} />;
}
