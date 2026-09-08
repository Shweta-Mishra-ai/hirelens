"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { color, radius } from "@/lib/design-tokens";
import { Card, Button } from "@/components/ui/primitives";
import {
  Search,
  ShieldCheck,
  Github,
  BarChart3,
  Users,
  Target,
  Files,
  FileText,
  ArrowRight,
} from "lucide-react";

const FEATURES = [
  {
    icon: <FileText size={18} />,
    title: "Credibility scoring",
    body: "Every resume gets a 0–100 score across six dimensions — timeline, skills, education, project authenticity, resume quality, and AI-generated-content detection.",
  },
  {
    icon: <Github size={18} />,
    title: "Real-time verification",
    body: "Live checks against GitHub, university domains, certification links, and employer websites — not just what the resume claims.",
  },
  {
    icon: <ShieldCheck size={18} />,
    title: "Evidence, not guesses",
    body: "Every risk flag quotes the exact resume text that triggered it, so you can judge the evidence yourself instead of trusting a black box.",
  },
  {
    icon: <Files size={18} />,
    title: "Bulk analysis",
    body: "Upload up to 50 resumes at once. Get a ranked list by credibility score with one-click CSV export.",
  },
  {
    icon: <Target size={18} />,
    title: "JD matching",
    body: "Paste a job description and see match percentage, missing skills, and the best-fit candidate across your pipeline.",
  },
  {
    icon: <BarChart3 size={18} />,
    title: "Talent analytics",
    body: "Pool-level intelligence — score distribution, top verified skills, and risk breakdown across every candidate you've reviewed.",
  },
  {
    icon: <Users size={18} />,
    title: "Team collaboration",
    body: "Share reports, comment, and vote (advance / maybe / reject) with the rest of your hiring team in one workspace.",
  },
  {
    icon: <Search size={18} />,
    title: "Duplicate & fraud detection",
    body: "Cross-candidate similarity checks catch resume mills and template fraud rings before they reach an interview.",
  },
];

export default function LandingPage() {
  const router = useRouter();
  const { token, sessionChecked } = useAuthStore();
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    if (!sessionChecked) return;
    if (token) {
      router.replace("/dashboard");
    } else {
      setCheckingSession(false);
    }
  }, [sessionChecked, token, router]);

  if (checkingSession) {
    return (
      <div style={{ minHeight: "100vh", background: color.bg, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ color: color.textMuted, fontSize: 14 }}>Loading…</div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", background: color.bg, color: color.textPrimary }}>
      {/* Nav */}
      <nav style={{ height: 60, borderBottom: `1px solid ${color.border}`, display: "flex", alignItems: "center", paddingInline: 28, gap: 12, position: "sticky", top: 0, background: color.bg, zIndex: 100 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <div style={{ width: 26, height: 26, borderRadius: radius.sm, background: color.brand, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Search size={14} color="#F5F5F2" strokeWidth={2.5} />
          </div>
          <span className="font-display" style={{ fontWeight: 600, fontSize: 17 }}>HireLens</span>
        </div>
        <div style={{ flex: 1 }} />
        <Link href="/login" style={{ fontSize: 13.5, fontWeight: 500, color: color.textSecondary, textDecoration: "none", padding: "8px 6px" }}>
          Sign in
        </Link>
        <Link href="/signup" style={{ fontSize: 13.5, fontWeight: 600, color: "#F5F5F2", background: color.brand, borderRadius: radius.md, padding: "8px 16px", textDecoration: "none" }}>
          Get started
        </Link>
      </nav>

      {/* Hero */}
      <section style={{ maxWidth: 780, margin: "0 auto", padding: "80px 24px 56px", textAlign: "center" }}>
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 7, padding: "5px 12px",
          border: `1px solid ${color.border}`, borderRadius: radius.pill, fontSize: 12.5,
          color: color.textSecondary, marginBottom: 28,
        }}>
          <ShieldCheck size={13} color={color.brandLight} />
          <span>Evidence-based candidate screening for recruiters</span>
        </div>

        <h1 className="font-display" style={{ fontSize: 46, lineHeight: 1.15, fontWeight: 600, margin: "0 0 20px", letterSpacing: -0.5 }}>
          Know which resumes to trust — before the interview.
        </h1>

        <p style={{ fontSize: 16.5, color: color.textMuted, lineHeight: 1.65, maxWidth: 580, margin: "0 auto 36px" }}>
          HireLens scores every resume for credibility, verifies claims against real public data — GitHub, universities, certifications — and shows you the exact evidence behind every flag.
        </p>

        <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
          <Link href="/signup" style={{ display: "inline-flex", alignItems: "center", gap: 8, background: color.brand, color: "#F5F5F2", fontWeight: 600, fontSize: 14.5, padding: "12px 24px", borderRadius: radius.md, textDecoration: "none" }}>
            Create free account
            <ArrowRight size={15} />
          </Link>
          <Link href="/login" style={{ display: "inline-flex", alignItems: "center", background: "transparent", color: color.textSecondary, border: `1px solid ${color.borderStrong}`, fontWeight: 600, fontSize: 14.5, padding: "12px 24px", borderRadius: radius.md, textDecoration: "none" }}>
            Sign in
          </Link>
        </div>

        <div style={{ marginTop: 8, fontSize: 12.5, color: color.textFaint }}>
          A decision-support tool for recruiters — every score is a signal to investigate, not an automated verdict.
        </div>
      </section>

      {/* Features grid */}
      <section style={{ maxWidth: 1040, margin: "0 auto", padding: "16px 24px 88px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 14 }}>
          {FEATURES.map(f => (
            <Card key={f.title} style={{ padding: "20px 20px" }}>
              <div style={{ width: 34, height: 34, borderRadius: radius.md, background: color.surfaceRaised, border: `1px solid ${color.border}`, display: "flex", alignItems: "center", justifyContent: "center", color: color.brandLight, marginBottom: 14 }}>
                {f.icon}
              </div>
              <div style={{ fontSize: 14.5, fontWeight: 600, marginBottom: 6 }}>{f.title}</div>
              <div style={{ fontSize: 13, color: color.textMuted, lineHeight: 1.6 }}>{f.body}</div>
            </Card>
          ))}
        </div>
      </section>

      {/* Closing CTA */}
      <section style={{ borderTop: `1px solid ${color.border}`, padding: "56px 24px", textAlign: "center" }}>
        <h2 className="font-display" style={{ fontSize: 26, fontWeight: 600, margin: "0 0 14px" }}>
          Start screening with evidence, not guesswork.
        </h2>
        <Link href="/signup" style={{ display: "inline-flex", alignItems: "center", gap: 8, background: color.brand, color: "#F5F5F2", fontWeight: 600, fontSize: 14.5, padding: "12px 24px", borderRadius: radius.md, textDecoration: "none" }}>
          Create free account
          <ArrowRight size={15} />
        </Link>
      </section>

      <footer style={{ borderTop: `1px solid ${color.border}`, padding: "24px", textAlign: "center", fontSize: 12.5, color: color.textFaint }}>
        HireLens — AI-powered candidate credibility & verification intelligence.
      </footer>
    </div>
  );
}
