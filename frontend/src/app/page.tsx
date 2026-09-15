"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { Logo } from "@/components/AppShell";

/**
 * Entry point. Sends signed-in users to their dashboard and everyone else to
 * sign-in. Rendering the brand mark rather than a bare "Loading…" keeps the
 * first paint from looking like a broken page during the redirect.
 */
export default function RootPage() {
  const router = useRouter();
  const { token, hasHydrated } = useAuthStore();

  useEffect(() => {
    if (!hasHydrated) return;
    router.replace(token ? "/dashboard" : "/login");
  }, [hasHydrated, token, router]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-canvas">
      <Logo />
      <p className="text-sm text-content-faint" role="status">
        Loading your workspace…
      </p>
    </div>
  );
}
