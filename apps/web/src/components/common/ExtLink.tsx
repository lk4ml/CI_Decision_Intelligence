import { safeHref } from "@/lib/format";

/** External link for API-sourced URLs: renders an anchor only for http(s) URLs, otherwise plain text. */
export default function ExtLink({ url, className, children }: { url?: string | null; className?: string; children: React.ReactNode }) {
  const href = safeHref(url);
  if (!href) return <span className={className}>{children}</span>;
  return (
    <a className={className} href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}
