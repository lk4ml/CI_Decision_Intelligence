import AssetContext from "@/components/asset/AssetContext";

export default async function Page({ params }: { params: Promise<{ asset: string }> }) {
  const { asset } = await params;
  return <AssetContext slug={asset} />;
}
