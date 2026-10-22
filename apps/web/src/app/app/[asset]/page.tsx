import { redirect } from "next/navigation";

export default async function AssetIndex({ params }: { params: Promise<{ asset: string }> }) {
  const { asset } = await params;
  redirect(`/app/${asset}/asset`);
}
