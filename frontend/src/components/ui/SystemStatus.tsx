"use client";

/**
 * Real system status pill.
 *
 * This replaces a hardcoded `<Badge tone="success" dot>All systems
 * operational</Badge>` on the dashboard, which checked nothing at all. It
 * showed a green "operational" badge unconditionally — while the LLM key was
 * missing, while storage had silently fallen back to container-local SQLite
 * that gets wiped on every redeploy, while CORS was misconfigured. A status
 * indicator that can only ever say "fine" is worse than no indicator: it
 * actively tells a recruiter their data is safe at the exact moment it isn't.
 *
 * Now it reads GET /api/v1/health and reflects what it actually says,
 * including the `config_warnings` array the backend computes for precisely
 * this class of "healthy process, broken product" problem.
 *
 * Deliberately quiet on the happy path — a small green dot, no drama — and
 * specific when something is wrong, because the whole point is that the
 * degraded state has to be distinguishable at a glance.
 */

import { useEffect, useState } from "react";
import { AlertTriangle, Database } from "lucide-react";
import { healthAPI, type HealthStatus } from "@/lib/api";
import { Badge } from "@/components/ui/primitives";

export function SystemStatus() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    healthAPI
      .check()
      .then((h) => {
        if (!cancelled) setHealth(h);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // The API is unreachable. Say so — this is the one case the old hardcoded
  // badge got most wrong, cheerfully reporting "operational" from a page whose
  // every other request was failing.
  if (failed) {
    return (
      <Badge tone="danger" dot title="Could not reach the HireLens API">
        API unreachable
      </Badge>
    );
  }

  // Nothing to claim until we know.
  if (!health) return null;

  const ephemeralStorage = health.storage_mode !== "supabase";

  if (ephemeralStorage) {
    return (
      <Badge
        tone="danger"
        icon={<Database size={12} />}
        title={
          health.storage_warning ??
          "Reports and accounts are on temporary storage and will be lost on restart."
        }
      >
        Temporary storage
      </Badge>
    );
  }

  if (health.status !== "ok" || health.config_warnings?.length) {
    const detail =
      health.config_warnings?.[0]?.message ??
      (health.llm_ready ? "Some services are degraded." : "Resume analysis is unavailable — no AI provider configured.");
    return (
      <Badge tone="warning" icon={<AlertTriangle size={12} />} title={detail}>
        Degraded
      </Badge>
    );
  }

  return (
    <Badge tone="success" dot title={`HireLens API v${health.version} — all services responding`}>
      All systems operational
    </Badge>
  );
}
