"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth";

export default function RootPage() {
  const router = useRouter();
  const token = useAuthStore((s) => s.token);

  useEffect(() => {
    if (token) {
      router.replace("/dashboard");
    } else {
      router.replace("/login");
    }
  }, [token, router]);

  return (
    <div style={{ minHeight: "100vh", background: "#060F1A", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ color: "#94A3B8", fontSize: 14 }}>Loading…</div>
    </div>
  );
}
