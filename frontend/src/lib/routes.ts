/**
 * In-app URLs that carry an id.
 *
 * The frontend is a static export (no server), so a report is one page that
 * reads its id from the query string rather than a dynamic /report/[id]
 * route, which a static host cannot serve.
 */
export function reportHref(id: string): string {
  return `/report?id=${encodeURIComponent(id)}`;
}

const LEGACY_REPORT_PATH =
  /^\/report\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/?$/i;

/**
 * The report id in an old-style /report/<id> link, or null.
 *
 * Such links (bookmarks, earlier emails) now land on the 404 page, which
 * forwards them to reportHref(id). Only a UUID — what every report id is —
 * matches. That matters: the report page's own data files live under
 * /report/ too (/report/index.txt, /report/__next.*.txt), and a pattern that
 * caught "any segment" would send the router's own requests to a report
 * called "index.txt". It is also why this is not a host redirect rule:
 * Vercel and Cloudflare apply those before checking for a real file.
 */
export function legacyReportId(pathname: string): string | null {
  return LEGACY_REPORT_PATH.exec(pathname)?.[1] ?? null;
}
