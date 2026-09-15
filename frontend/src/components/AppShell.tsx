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
  Menu,
  X,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { useAuthStore } from "@/store/auth";
import { initials } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Skeleton } from "@/components/ui/Feedback";

/**
 * Application chrome: a persistent left sidebar plus a slim top bar.
 *
 * Navigation moved out of the top bar because the product is a workspace, not
 * a site. A vertical rail has room for the labels to sit at a consistent left
 * edge, it scales past five destinations without the items compressing, and
 * it leaves the full top edge for page-level context and actions.
 *
 * The collapsed/expanded choice persists per browser (localStorage), since it
 * is a per-person preference about their own screen rather than shared state.
 */

export const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, hint: "All candidate files" },
  { href: "/analyze", label: "Analyze", icon: ScanLine, hint: "Single resume" },
  { href: "/bulk", label: "Bulk", icon: Layers, hint: "Up to 50 at once" },
  { href: "/match", label: "JD Match", icon: Crosshair, hint: "Rank against a role" },
  { href: "/teams", label: "Teams", icon: Users, hint: "Share and discuss" },
] as const;

const COLLAPSE_KEY = "hirelens:sidebar-collapsed";

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <span
        aria-hidden
        className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-brand-500 text-white"
      >
        <Aperture className="size-4" strokeWidth={2.25} />
      </span>
      {!compact && (
        <span className="text-[15px] font-semibold tracking-tight text-content">HireLens</span>
      )}
    </span>
  );
}

function NavList({
  collapsed,
  onNavigate,
}: {
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();

  return (
    <nav aria-label="Main" className="flex-1 space-y-0.5 px-2 py-3">
      {NAV_ITEMS.map(({ href, label, icon: Icon, hint }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            title={collapsed ? label : undefined}
            className={cn(
              "group relative flex items-center gap-3 rounded-md px-2.5 py-2 text-sm font-medium",
              "transition-colors duration-150 focus-visible:outline-none focus-visible:shadow-focus",
              collapsed && "justify-center px-0",
              active
                ? "bg-brand-500/10 text-content"
                : "text-content-faint hover:bg-canvas-overlay hover:text-content-muted",
            )}
          >
            {/* Active marker on the rail's left edge */}
            <span
              aria-hidden
              className={cn(
                "absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r-full transition-opacity",
                active ? "bg-brand-500 opacity-100" : "opacity-0",
              )}
            />
            <Icon
              aria-hidden
              className={cn("size-[18px] shrink-0", active && "text-brand-400")}
            />
            {!collapsed && (
              <span className="min-w-0 flex-1">
                <span className="block truncate">{label}</span>
                <span className="block truncate text-2xs font-normal text-content-faint">
                  {hint}
                </span>
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

function UserMenu({ collapsed }: { collapsed: boolean }) {
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
    <div ref={ref} className="relative border-t border-line-subtle p-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={collapsed ? name : undefined}
        className={cn(
          "flex w-full items-center gap-2.5 rounded-md p-1.5 transition-colors",
          "hover:bg-canvas-overlay focus-visible:outline-none focus-visible:shadow-focus",
          collapsed && "justify-center",
          open && "bg-canvas-overlay",
        )}
      >
        <span
          aria-hidden
          className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-500/20 text-2xs font-semibold text-brand-300"
        >
          {initials(name)}
        </span>
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1 text-left">
              <span className="block truncate text-xs font-medium text-content">
                {user?.full_name || "Recruiter"}
              </span>
              <span className="block truncate text-2xs text-content-faint">{user?.email}</span>
            </span>
            <ChevronDown aria-hidden className="size-3.5 shrink-0 text-content-faint" />
          </>
        )}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute bottom-full left-2 right-2 z-50 mb-1 overflow-hidden rounded-lg border border-line-strong bg-canvas-overlay shadow-popover animate-fade-in"
        >
          <div className="border-b border-line-subtle px-3 py-2.5">
            <div className="truncate text-sm font-medium text-content">
              {user?.full_name || "Recruiter"}
            </div>
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

function SidebarBody({
  collapsed,
  onToggleCollapse,
  onNavigate,
  showCollapseControl = true,
}: {
  collapsed: boolean;
  onToggleCollapse?: () => void;
  onNavigate?: () => void;
  showCollapseControl?: boolean;
}) {
  return (
    <>
      <div
        className={cn(
          "flex h-14 shrink-0 items-center border-b border-line-subtle px-3",
          collapsed ? "justify-center" : "justify-between",
        )}
      >
        <Link href="/dashboard" onClick={onNavigate} className="rounded focus-visible:outline-none focus-visible:shadow-focus">
          <Logo compact={collapsed} />
        </Link>
        {showCollapseControl && !collapsed && (
          <button
            type="button"
            onClick={onToggleCollapse}
            aria-label="Collapse sidebar"
            className="rounded p-1 text-content-faint transition-colors hover:bg-canvas-overlay hover:text-content-muted focus-visible:outline-none focus-visible:shadow-focus"
          >
            <PanelLeftClose className="size-4" />
          </button>
        )}
      </div>

      {showCollapseControl && collapsed && (
        <button
          type="button"
          onClick={onToggleCollapse}
          aria-label="Expand sidebar"
          className="mx-auto mt-2 rounded p-1.5 text-content-faint transition-colors hover:bg-canvas-overlay hover:text-content-muted focus-visible:outline-none focus-visible:shadow-focus"
        >
          <PanelLeftOpen className="size-4" />
        </button>
      )}

      <NavList collapsed={collapsed} onNavigate={onNavigate} />
      <UserMenu collapsed={collapsed} />
    </>
  );
}

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
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();

  // Read the stored preference after mount. Reading during render would
  // desync the server-rendered markup from the first client paint.
  useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      // Private mode or blocked storage — the default (expanded) is fine.
    }
  }, []);

  function toggleCollapse() {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        // Not persisting is acceptable; the session still works.
      }
      return next;
    });
  }

  // Close the mobile drawer on navigation, and lock body scroll while open.
  useEffect(() => setMobileOpen(false), [pathname]);
  useEffect(() => {
    if (!mobileOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMobileOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", onKey);
    };
  }, [mobileOpen]);

  return (
    <div className="min-h-screen bg-canvas">
      {/* Desktop rail */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 hidden flex-col border-r border-line bg-canvas-raised lg:flex",
          "transition-[width] duration-200 ease-out",
          collapsed ? "w-[3.75rem]" : "w-60",
        )}
      >
        <SidebarBody collapsed={collapsed} onToggleCollapse={toggleCollapse} />
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setMobileOpen(false)}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
          />
          <aside className="relative flex h-full w-64 flex-col border-r border-line bg-canvas-raised animate-fade-in">
            <SidebarBody
              collapsed={false}
              showCollapseControl={false}
              onNavigate={() => setMobileOpen(false)}
            />
            <button
              type="button"
              onClick={() => setMobileOpen(false)}
              aria-label="Close navigation"
              className="absolute right-2 top-4 rounded p-1 text-content-faint hover:text-content"
            >
              <X className="size-4" />
            </button>
          </aside>
        </div>
      )}

      <div className={cn("transition-[padding] duration-200 ease-out", collapsed ? "lg:pl-[3.75rem]" : "lg:pl-60")}>
        {/* Mobile top bar — the rail is off-screen here, so the brand and the
            drawer trigger need somewhere to live. */}
        <div className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-canvas/85 px-4 backdrop-blur-xl lg:hidden">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
            aria-expanded={mobileOpen}
            className="rounded p-1.5 text-content-muted transition-colors hover:bg-canvas-overlay focus-visible:outline-none focus-visible:shadow-focus"
          >
            <Menu className="size-5" />
          </button>
          <Link href="/dashboard" className="rounded focus-visible:outline-none focus-visible:shadow-focus">
            <Logo />
          </Link>
        </div>

        <main
          className={cn(
            "mx-auto px-5 py-8 lg:px-8",
            width === "narrow" && "max-w-3xl",
            width === "default" && "max-w-[1180px]",
            width === "wide" && "max-w-[1440px]",
          )}
        >
          {children}
        </main>
      </div>
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
        <div className="hidden w-60 border-r border-line lg:block" />
        <div className="mx-auto max-w-[1180px] space-y-4 px-5 py-8 lg:pl-8">
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
