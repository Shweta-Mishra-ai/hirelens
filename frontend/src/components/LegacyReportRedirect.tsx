"use client";

import { useEffect } from "react";
import { legacyReportId, reportHref } from "@/lib/routes";

/**
 * Mounted on the 404 page: forwards an old /report/<id> link to the report.
 * See legacyReportId for why this is done here and not by the host.
 */
export function LegacyReportRedirect() {
  useEffect(() => {
    const id = legacyReportId(window.location.pathname);
    if (id) window.location.replace(reportHref(id));
  }, []);
  return null;
}
