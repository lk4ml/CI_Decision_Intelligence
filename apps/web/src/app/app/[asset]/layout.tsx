import AppShell from "@/components/shell/AppShell";

export default async function AssetLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ asset: string }>;
}) {
  const { asset } = await params;
  return <AppShell slug={asset}>{children}</AppShell>;
}
