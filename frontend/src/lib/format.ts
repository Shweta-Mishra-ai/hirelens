/**
 * Shared formatting helpers.
 *
 * `relativeTime` renders a dash for anything it cannot read as a date. The
 * backend always stamps `created_at`, but a formatter that turns a missing or
 * malformed value into visible garbage — "NaNd ago" — is a defect on its own
 * terms, so this one fails closed.
 */
/**
 * Timestamps here are always creation times for records this product wrote,
 * so anything before this is corrupt input rather than a real date. Without
 * the floor, `new Date("0000")` parses successfully and renders as
 * "Jan 1, 1" — garbage that looks deliberate.
 */
const EARLIEST_PLAUSIBLE = Date.UTC(2000, 0, 1);

function parseTimestamp(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < EARLIEST_PLAUSIBLE) return null;
  return ms;
}

export function relativeTime(iso: string | null | undefined): string {
  const then = parseTimestamp(iso);
  if (then === null) return "—";

  const diff = Date.now() - then;
  if (diff < 0) return "just now"; // clock skew between client and server
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(then).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function absoluteTime(iso: string | null | undefined): string {
  const ms = parseTimestamp(iso);
  if (ms === null) return "";
  return new Date(ms).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function initials(nameOrEmail: string | null | undefined): string {
  const s = (nameOrEmail ?? "").trim();
  if (!s) return "?";
  const parts = s.split(/[\s@._-]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

export function pluralize(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Truncate on a word boundary rather than mid-word. */
export function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  const cut = s.slice(0, max);
  const lastSpace = cut.lastIndexOf(" ");
  return `${(lastSpace > max * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 KB";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
