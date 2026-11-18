import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { RecoveryLinkCatcher } from "@/components/RecoveryLinkCatcher";
import { contentSecurityPolicy } from "@/lib/csp";

/**
 * Typography: one sans for everything, one mono for evidence quotes and
 * identifiers. The previous build loaded a serif display face (Fraunces)
 * alongside IBM Plex Sans and applied it to every heading, which fought
 * with the data-dense UI it sat in.
 */
const sans = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: {
    default: "HireLens",
    template: "%s · HireLens",
  },
  description:
    "Evidence-linked resume credibility analysis for recruiters. Every score and flag quotes the text that produced it.",
  keywords: ["resume screening", "candidate verification", "recruiting", "credibility analysis"],
  openGraph: {
    title: "HireLens",
    description: "Evidence-linked resume credibility analysis for recruiters.",
    type: "website",
  },
  robots: { index: false, follow: false }, // authenticated product surface
};

export const viewport: Viewport = {
  themeColor: "#0A0C10",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <head>
        {/* Production only: the dev server needs eval() for hot reload. */}
        {process.env.NODE_ENV === "production" && (
          <meta
            httpEquiv="Content-Security-Policy"
            content={contentSecurityPolicy({
              apiUrl: process.env.NEXT_PUBLIC_API_URL,
              supabaseUrl: process.env.NEXT_PUBLIC_SUPABASE_URL,
            })}
          />
        )}
      </head>
      <body>
        {/* A password recovery link can land on any page, depending on a
            Supabase setting this app does not control. Mounted here so it is
            caught wherever it arrives. */}
        <RecoveryLinkCatcher />
        {children}
      </body>
    </html>
  );
}
