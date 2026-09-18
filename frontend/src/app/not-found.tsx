import Link from "next/link";
import { FileQuestion, LayoutDashboard } from "lucide-react";

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-5">
      <div className="w-full max-w-md text-center">
        <div
          aria-hidden
          className="mx-auto flex size-11 items-center justify-center rounded-xl border border-line bg-canvas-overlay text-content-faint"
        >
          <FileQuestion className="size-5" />
        </div>
        <h1 className="mt-5 text-xl font-semibold text-content">Page not found</h1>
        <p className="mt-2 text-sm leading-relaxed text-content-muted">
          That link doesn&apos;t point anywhere in HireLens. It may have been deleted, or the
          address may be slightly off.
        </p>
        <Link
          href="/dashboard"
          className="mt-6 inline-flex h-9 items-center gap-2 rounded-md bg-brand-500 px-3.5 text-sm font-medium text-white transition-colors hover:bg-brand-400 focus-visible:outline-none focus-visible:shadow-focus"
        >
          <LayoutDashboard aria-hidden className="size-4" />
          Back to dashboard
        </Link>
      </div>
    </div>
  );
}
