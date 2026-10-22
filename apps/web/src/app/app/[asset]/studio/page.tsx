import Studio from "@/components/studio/Studio";

export default async function Page({ params }: { params: Promise<{ asset: string }> }) {
  const { asset } = await params;
  return <Studio slug={asset} />;
}
