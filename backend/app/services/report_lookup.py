"""
Batched report lookups for the batch status, ranking and notify paths.

Those paths used to read one report per query, inside a loop over the batch:
a fifty-file batch cost fifty round trips to Supabase on every status poll,
and the browser polls every two to three seconds for as long as the page is
open. JD match also pulled each complete report blob to read one field.

One `in_` query per call replaces the loop. Reports the database does not
return (no Supabase, or a write that fell back to the local store) are filled
from the in-process cache and then the durable local store, so the ranking is
the same whichever store a report landed in.
"""

import logging

from app.core import local_db
from app.core.shapes import as_dict, as_str, normalize_report, report_summary_row

logger = logging.getLogger("hirelens")

# PostgREST puts `in.(...)` in the URL; keep each request comfortably short.
_CHUNK = 100


def fetch_rows(db, report_ids: list[str], columns: str) -> tuple[dict[str, dict], bool]:
    """
    {report_id: row} for every id the database returned, and whether the
    database failed. Ids are deduplicated; order is irrelevant to callers.
    """
    wanted = [rid for rid in dict.fromkeys(report_ids) if rid]
    found: dict[str, dict] = {}
    if not (db and wanted):
        return found, False
    try:
        for start in range(0, len(wanted), _CHUNK):
            chunk = wanted[start:start + _CHUNK]
            res = db.table("reports").select(columns).in_("id", chunk).execute()
            for row in res.data or []:
                if isinstance(row, dict) and row.get("id"):
                    found[str(row["id"])] = row
    except Exception as e:
        logger.warning(f"Batched report lookup failed for {len(wanted)} report(s): {e}")
        return found, True
    return found, False


def local_report(report_id: str, owner_id: str | None, jobs) -> dict | None:
    """A full, normalised report from the process cache or the local store."""
    data = jobs.get(f"report_{report_id}")
    if isinstance(data, dict) and data:
        return normalize_report(data)
    if owner_id:
        persisted = local_db.get_report(report_id, owner_id)
        if persisted:
            return normalize_report(persisted)
    return None


def summaries(db, report_ids: list[str], owner_id: str, jobs) -> dict[str, dict]:
    """Ranking summaries: file_name, candidate_name, overall_score, recommendation."""
    rows, _ = fetch_rows(
        db, report_ids, "id,file_name,candidate_name,overall_score,recommendation"
    )
    out = dict(rows)
    for rid in report_ids:
        if rid in out:
            continue
        report = local_report(rid, owner_id, jobs)
        if report:
            out[rid] = report_summary_row(rid, report)
    return out


def candidate_contacts(db, report_ids: list[str], owner_id: str, jobs) -> dict[str, dict]:
    """
    {report_id: {"candidate_name", "email", "notified_decision"}} for notify.

    Reads the email as a JSON path instead of downloading every report.
    """
    rows, _ = fetch_rows(
        db,
        report_ids,
        "id,candidate_name,candidate_notified_decision,"
        "email:report_data->candidate->>email",
    )
    out: dict[str, dict] = {}
    for rid, row in rows.items():
        out[rid] = {
            "candidate_name": as_str(row.get("candidate_name")),
            "email": as_str(row.get("email")).strip(),
            "notified_decision": row.get("candidate_notified_decision"),
        }
    for rid in report_ids:
        if rid in out:
            continue
        report = local_report(rid, owner_id, jobs)
        if report:
            cand = as_dict(report.get("candidate"))
            out[rid] = {
                "candidate_name": as_str(cand.get("name")),
                "email": as_str(cand.get("email")).strip(),
                "notified_decision": report.get("candidate_notified_decision"),
            }
    return out


def full_reports(db, report_ids: list[str], owner_id: str, jobs) -> dict[str, dict]:
    """{report_id: {"candidate_name", "file_name", ..., "report_data": normalised}}."""
    rows, _ = fetch_rows(
        db,
        report_ids,
        "id,file_name,candidate_name,overall_score,recommendation,report_data",
    )
    out: dict[str, dict] = {}
    for rid, row in rows.items():
        merged = dict(row)
        merged["report_data"] = normalize_report(row.get("report_data"))
        out[rid] = merged
    for rid in report_ids:
        if rid in out:
            continue
        report = local_report(rid, owner_id, jobs)
        if report:
            cred = as_dict(report.get("credibility"))
            cand = as_dict(report.get("candidate"))
            out[rid] = {
                "id": rid,
                "file_name": report.get("file_name"),
                "candidate_name": as_str(cand.get("name")) or "Unknown",
                "overall_score": cred.get("overall", 0),
                "recommendation": cred.get("recommendation", "manual_review"),
                "report_data": report,
            }
    return out
