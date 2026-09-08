/**
 * 404 page.
 *
 * The build was emitting Next's default `/_not-found` route — an unstyled
 * black-on-white "404 | This page could not be found". A mistyped or stale
 * report link is the most likely way a recruiter meets it, so it should at
 * least look like the product and point somewhere useful.
 */

import Link from "next/link";
import { color, font } from "@/lib/design-tokens";
import { Button, Card, PageShell } from "@/components/ui/primitives";

export default function NotFound() {
  return (
    <PageShell>
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 24,
        }}
      >
        <Card style={{ maxWidth: 480, width: "100%", padding: 32 }}>
          <div
            style={{
              fontFamily: font.mono,
              fontSize: 12,
              color: color.textMuted,
              marginBottom: 10,
            }}
          >
            404
          </div>
          <h1
            style={{
              fontFamily: font.display,
              fontSize: 22,
              fontWeight: 600,
              color: color.textPrimary,
              margin: "0 0 12px",
            }}
          >
            Page not found
          </h1>
          <p style={{ fontSize: 14, lineHeight: 1.6, color: color.textSecondary, margin: "0 0 22px" }}>
            This link doesn&apos;t point anywhere in HireLens. It may have been
            deleted, or the address may be mistyped.
          </p>
          <Link href="/dashboard" style={{ textDecoration: "none" }}>
            <Button>Back to dashboard</Button>
          </Link>
        </Card>
      </div>
    </PageShell>
  );
}
