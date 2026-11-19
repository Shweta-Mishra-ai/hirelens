import Link from "next/link";
import { Logo } from "@/components/AppShell";
import { company, companyConfigured } from "@/lib/company";

const LINKS = [
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
  { href: "/refunds", label: "Refunds" },
  { href: "/contact", label: "Contact" },
];

export default function LegalLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-canvas">
      <header className="border-b border-line-subtle">
        <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-5">
          <Link href="/" className="rounded focus-visible:outline-none focus-visible:shadow-focus">
            <Logo />
          </Link>
          <nav aria-label="Legal" className="flex gap-4 text-sm">
            {LINKS.map((l) => (
              <Link key={l.href} href={l.href} className="text-content-muted hover:text-content">
                {l.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-5 py-10">
        {!companyConfigured && (
          <div
            role="note"
            className="mb-8 rounded-lg border border-caution-line bg-caution-soft px-4 py-3 text-sm text-content"
          >
            <strong>Template — not yet in force.</strong> The operator of this site has not filled in
            its business details (NEXT_PUBLIC_COMPANY_NAME and NEXT_PUBLIC_CONTACT_EMAIL). Bracketed
            text below is a placeholder, and this page should be reviewed by a lawyer before launch.
          </div>
        )}
        <article className="legal space-y-4 text-sm leading-relaxed text-content-muted">{children}</article>
        <p className="mt-12 border-t border-line-subtle pt-4 text-xs text-content-faint">
          {company.name || "HireLens"}
          {company.effectiveDate ? ` · Effective ${company.effectiveDate}` : ""}
        </p>
      </main>
    </div>
  );
}
