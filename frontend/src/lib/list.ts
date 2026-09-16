/**
 * Read a field that should be a list without trusting that it is one.
 *
 * Report panels iterate nested fields directly — `analysis.indicators.map(…)`,
 * `verification.education.length`. That is fine for a report this build wrote
 * and not fine for one written by an older build, saved partially, or holding
 * a field whose type changed. A missing `indicators` threw "Cannot read
 * properties of undefined (reading 'length')" during render, which the error
 * boundary could only contain by replacing the whole panel.
 *
 * `asList` is deliberately not `Array.from(value)`: a string is iterable, so
 * that would turn "AWS" into three single-character entries.
 */
export function asList<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}
