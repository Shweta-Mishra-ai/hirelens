"use client";
import Link from "next/link";
import { Quote, ShieldCheck, ScanLine, Users } from "lucide-react";
import { Logo } from "@/components/AppShell";

const PILLARS = [
  {
    icon: ScanLine,
    title: "Every flag quotes the resume",
    body: "Scores are never a black box. Each concern cites the exact sentence that raised it, so you can judge the evidence yourself.",
  },
  {
    icon: ShieldCheck,
    title: "Checked against public record",
    body: "GitHub activity, institution domains and certificate links are verified live — not inferred from writing style.",
  },
  {
    icon: Users,
    title: "Built for a hiring panel",
    body: "Share a candidate file, leave notes, and record a decision your whole team can see.",
  },
];

/**
 * Shared chrome for the sign-in and sign-up pages.
 *
 * The marketing panel is not decoration. HireLens produces judgements about
 * real people, and the standing disclaimer at the bottom of this panel — that
 * it is decision support, never an automated gatekeeper — belongs on the
 * first screen a new recruiter sees, not buried in a README.
 */
export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1fr_minmax(0,32rem)]">
      {/* Brand panel — hidden on small screens where it would just push the form down */}
      <aside className="relative hidden flex-col justify-between overflow-hidden border-r border-line bg-canvas-raised p-12 lg:flex">
        <div
          aria-hidden
          className="pointer-events-none absolute -left-32 -top-32 size-[28rem] rounded-full bg-brand-500/10 blur-3xl"
        />
        <div className="relative">
          <Logo />
        </div>

        <div className="relative max-w-md">
          <Quote aria-hidden className="mb-5 size-7 text-brand-400" />
          <p className="text-xl font-medium leading-snug text-content">
            Screening is a judgement call. HireLens gives you the evidence to
            make it — it does not make it for you.
          </p>

          <ul className="mt-10 space-y-6">
            {PILLARS.map(({ icon: Icon, title: t, body }) => (
              <li key={t} className="flex gap-3.5">
                <span
                  aria-hidden
                  className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-line bg-canvas-overlay text-brand-400"
                >
                  <Icon className="size-4" />
                </span>
                <div>
                  <div className="text-sm font-medium text-content">{t}</div>
                  <p className="mt-0.5 text-sm leading-relaxed text-content-faint">{body}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <p className="relative max-w-md text-xs leading-relaxed text-content-faint">
          HireLens is decision support, not an automated gatekeeper. Every score,
          flag and verification result is a signal for a human recruiter to
          investigate — never proof of misconduct, and never grounds for an
          automated reject.
        </p>
      </aside>

      {/* Form panel */}
      <main className="flex items-center justify-center px-5 py-12 sm:px-10">
        <div className="w-full max-w-sm animate-fade-in">
          <div className="lg:hidden">
            <Logo />
          </div>

          <h1 className="mt-8 text-2xl font-semibold text-content lg:mt-0">{title}</h1>
          <p className="mt-1.5 text-sm text-content-muted">{subtitle}</p>

          <div className="mt-8">{children}</div>

          <div className="mt-8 text-sm text-content-faint">{footer}</div>
        </div>
      </main>
    </div>
  );
}

export function GoogleButton({
  onClick,
  label,
  disabled,
}: {
  onClick: () => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex h-10 w-full items-center justify-center gap-2.5 rounded-md border border-line-strong bg-canvas-overlay text-sm font-medium text-content transition-colors hover:bg-canvas-inset focus-visible:outline-none focus-visible:shadow-focus disabled:cursor-not-allowed disabled:opacity-50"
    >
      <svg aria-hidden width="16" height="16" viewBox="0 0 24 24">
        <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
        <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
        <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" fill="#FBBC05" />
        <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" fill="#EA4335" />
      </svg>
      {label}
    </button>
  );
}

export function OrDivider() {
  return (
    <div className="my-5 flex items-center gap-3">
      <span className="h-px flex-1 bg-line" />
      <span className="text-xs text-content-faint">or</span>
      <span className="h-px flex-1 bg-line" />
    </div>
  );
}

export function AuthFooterLink({
  prompt,
  href,
  label,
}: {
  prompt: string;
  href: string;
  label: string;
}) {
  return (
    <>
      {prompt}{" "}
      <Link href={href} className="font-medium text-brand-400 underline-offset-4 hover:underline">
        {label}
      </Link>
    </>
  );
}
