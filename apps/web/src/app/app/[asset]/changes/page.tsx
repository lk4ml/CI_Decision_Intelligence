import WhatsChanged from "@/components/changes/WhatsChanged";

export default async function Page({ params }: { params: Promise<{ asset: string }> }) {
  const { asset } = await params;
  return <WhatsChanged slug={asset} />;
}
