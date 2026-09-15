"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  ScanLine,
  Layers,
  Crosshair,
  Users,
  LogOut,
  ChevronDown,
  Aperture,
} from "lucide-react";
import { useAuthStore } from "@/store/auth";
import { initials } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Skeleton } from "@/components/ui/Feedback";

/**
 * The single application chrome. Every authenticated page renders inside
 * this. Previously each of the five pages declared its own NAV_LINKS array
 * and its own copy of the navbar markup, which is why the active-state,
 * spacing and user menu drifted between them.
 */

export const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/analyze", label: "Analyze", icon: ScanLine },
  { href: "/bulk", label: "Bulk", icon: Layers },
  { href: "/match", label: "JD Match", icon: Crosshair },
  { href: "/teams", label: "Teams", icon: Users },
] as const;

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <span
        aria-hidden
        className="flex size-7 items-center justify-center rounded-lg bg-brand-500 text-white"
      >
        <Aperture className="size-4" strokeWidth={2.25} />
      </span>
      {!compact && (
        <span className="text-[15px] font-semibold tracking-tight text-content">HireLens</span>
      )}
    </span>
  );
}

function UserMenu() {
  const { user, logout } = useAuthStore();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const name = user?.full_name || user?.email || "";

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={cn(
          "flex items-center gap-2 rounded-md py-1 pl-1 pr-2 transition-colors",
          "hover:bg-canvas-overlay focus-visible:outline-none focus-visible:shadow-focus",
          open && "bg-canvas-overlay",
        )}
      >
        <span
          aria-hidden
          className="flex size-7 items-center justify-center rounded-full bg-brand-500/20 text-2xs font-semibold text-brand-300"
        >
          {initials(name)}
        </span>
        <span className="hidden max-w-[10rem] truncate text-xs text-content-muted sm:block">
          {user?.full_name || user?.email}
        </span>
        <ChevronDown aria-hidden className="size-3.5 text-content-faint" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-1.5 w-56 overflow-hidden rounded-lg border border-line-strong bg-canvas-overlay shadow-popover animate-fade-in"
        >
          <div className="border-b border-line-subtle px-3 py-2.5">
            <div className="truncate text-sm font-medium text-content">{user?.full_name || "Recruiter"}</div>
            <div className="truncate text-xs text-content-faint">{user?.email}</div>
          </div>
          <button
            role="menuitem"
            type="button"
            onClick={() => {
              logout();
              router.replace("/login");
            }}
            className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-content-muted transition-colors hover:bg-canvas-inset hover:text-content"
          >
            <LogOut aria-hidden className="size-4" />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function TopNav() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-canvas/85 backdrop-blur-xl">
      <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-6 px-5">
        <Link href="/dashboard" className="shrink-0 rounded focus-visible:outline-none focus-visible:shadow-focus">
          <Logo />
        </Link>

        <nav aria-label="Main" className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto [&::-webkit-scrollbar]:hidden">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex shrink-0 items-center gap-2 rounded-md px-2.5 py-1.5 text-sm font-medium",
                  "transition-colors duration-150 focus-visible:outline-none focus-visible:shadow-focus",
                  active
                    ? "bg-canvas-overlay text-content"
                    : "text-content-faint hover:bg-canvas-overlay/60 hover:text-content-muted",
                )}
              >
                <Icon aria-hidden className="size-4" />
                {label}
              </Link>
            );
          })}
        </nav>

        <UserMenu />
      </div>
    </header>
  );
}

/**
 * Page scaffold. `title` and `description` render a consistent page header;
 * `actions` sits on the header's trailing edge.
 */
export function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  breadcrumb?: React.ReactNode;
}) {
  return (
    <div className="mb-7">
      {breadcrumb && <div className="mb-3">{breadcrumb}</div>}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold text-content">{title}</h1>
          {description && (
            <p className="mt-1.5 max-w-2xl text-sm text-content-muted">{description}</p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}

export function AppShell({
  children,
  width = "default",
}: {
  children: React.ReactNode;
  width?: "default" | "wide" | "narrow";
}) {
  return (
    <div className="min-h-screen bg-canvas">
      <TopNav />
      <main
        className={cn(
          "mx-auto px-5 py-8",
          width === "narrow" && "max-w-3xl",
          width === "default" && "max-w-[1200px]",
          width === "wide" && "max-w-[1400px]",
        )}
      >
        {children}
      </main>
    </div>
  );
}

/**
 * Guards an authenticated route. Renders a skeleton until the persisted auth
 * store has rehydrated, so a signed-in user never sees a flash of the login
 * page on a hard refresh.
 */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { token, hasHydrated } = useAuthStore();
  const router = useRouter();

  useEffect(() => {
    if (hasHydrated && !token) router.replace("/login");
  }, [hasHydrated, token, router]);

  if (!hasHydrated || !token) {
    return (
      <div className="min-h-screen bg-canvas">
        <div className="h-14 border-b border-line" />
        <div className="mx-auto max-w-[1200px] space-y-4 px-5 py-8">
          <Skeleton className="h-9 w-56" />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-72" />
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
