import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "HireLens — AI Recruiter Intelligence",
  description:
    "Analyze resumes for credibility signals, skills verification, and risk — powered by HireLens Decision Intelligence.",
  keywords: ["resume analysis", "AI recruiting", "credibility score", "HireLens"],
  openGraph: {
    title: "HireLens",
    description: "AI-powered recruiter decision intelligence",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}

