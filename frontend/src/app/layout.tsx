import type { Metadata } from "next";
// Self-hosted fonts (bundled at build time, no runtime fetch to
// fonts.googleapis.com) — next/font/google previously made every
// production build take a hard dependency on Google Fonts being
// reachable at build time; if that's ever blocked (a restrictive CI
// network, an outage, a proxy), the build fails outright. @fontsource
// ships the actual font files as regular npm packages instead.
import "@fontsource/fraunces/400.css";
import "@fontsource/fraunces/500.css";
import "@fontsource/fraunces/600.css";
import "@fontsource/fraunces/700.css";
import "@fontsource/fraunces/900.css";
import "@fontsource/fraunces/400-italic.css";
import "@fontsource/fraunces/500-italic.css";
import "@fontsource/fraunces/600-italic.css";
import "@fontsource/fraunces/700-italic.css";
import "@fontsource/fraunces/900-italic.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-sans/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "HireLens — Resume Credibility Examination",
  description:
    "Real-time resume credibility scoring, AI-generated-content detection, and public-data verification for recruiters.",
  keywords: ["resume analysis", "AI recruiting", "credibility score", "HireLens", "fake resume detection"],
  openGraph: {
    title: "HireLens",
    description: "Resume credibility examination for recruiters",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

