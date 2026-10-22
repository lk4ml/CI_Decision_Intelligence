import Workbench from "@/components/workbench/Workbench";

export default async function Page({ params }: { params: Promise<{ asset: string }> }) {
  const { asset } = await params;
  return <Workbench slug={asset} />;
}
