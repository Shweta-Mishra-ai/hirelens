"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { color, radius } from "@/lib/design-tokens";
import { Search, LayoutDashboard, Zap, Files, Target, Users } from "lucide-react";

const NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard", icon: <LayoutDashboard size={14} /> },
  { href: "/analyze", label: "Analyze", icon: <Zap size={14} /> },
  { href: "/bulk", label: "Bulk Upload", icon: <Files size={14} /> },
  { href: "/match", label: "JD Match", icon: <Target size={14} /> },
  { href: "/teams", label: "Teams", icon: <Users size={14} /> },
];

export function AppNavbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuthStore();

  return (
    <nav style={{
      height: 60, borderBottom: `1px solid ${color.border}`,
      display: "flex", alignItems: "center", paddingInline: 28, gap: 28,
      position: "sticky", top: 0, background: color.bg, zIndex: 100,
    }}>
      <Link href="/dashboard" style={{ display: "flex", alignItems: "center", gap: 9, textDecoration: "none" }}>
        <div style={{
          width: 26, height: 26, borderRadius: radius.sm,
          background: color.brand,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}><Search size={14} color="#F5F5F2" strokeWidth={2.5} /></div>
        <span className="font-display" style={{ fontWeight: 600, fontSize: 17, color: color.textPrimary }}>HireLens</span>
      </Link>

      {/* Tab links — plain underline for the active tab, no pill/glow */}
      <div style={{ display: "flex", alignItems: "center", gap: 22, height: "100%" }}>
        {NAV_LINKS.map(link => {
          const active = pathname === link.href;
          return (
            <Link key={link.href} href={link.href} style={{
              height: "100%", display: "flex", alignItems: "center", gap: 7,
              fontSize: 13, fontWeight: 500,
              color: active ? color.textPrimary : color.textMuted,
              borderBottom: active ? `2px solid ${color.brand}` : "2px solid transparent",
              textDecoration: "none",
            }}>
              <span style={{ display: "inline-flex", alignItems: "center" }}>{link.icon}</span>
              <span>{link.label}</span>
            </Link>
          );
        })}
      </div>

      <div style={{ flex: 1 }} />

      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 22, height: 22, borderRadius: "50%", background: color.surfaceRaised, border: `1px solid ${color.border}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 600, color: color.textSecondary }}>
            {user?.full_name ? user.full_name[0].toUpperCase() : "U"}
          </div>
          <span style={{ fontSize: 12.5, color: color.textSecondary }}>{user?.email}</span>
        </div>
        <button
          onClick={() => { logout(); router.replace("/login"); }}
          style={{ padding: "5px 12px", borderRadius: radius.sm, border: `1px solid ${color.border}`, background: "transparent", color: color.textMuted, cursor: "pointer", fontSize: 12, fontWeight: 500 }}
        >
          Sign out
        </button>
      </div>
    </nav>
  );
}
