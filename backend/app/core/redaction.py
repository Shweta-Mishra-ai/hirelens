"""
HireLens — log redaction helpers.

Recruiting data is unusually sensitive in one specific way: most of the
people whose personal data flows through this system — the CANDIDATES — are
not users. They never signed up, never agreed to anything here, and have no
way to ask for their data back. Their name, email and full work history
arrive in an uploaded file and end up in analysis, verification and
notification code paths that all log freely.

Application logs are the easiest place for that data to escape: they are
shipped to third-party log services, kept far longer than the reports
themselves, and readable by anyone with dashboard access rather than only by
the recruiter who owns the report.

So candidate identifiers get masked on the way into a log line. Enough is
kept to correlate an incident ("was it the same address?") without the log
becoming a mailing list.
"""


def mask_email(email: str | None) -> str:
    """j***@example.com — recognisable, not reusable.

    The domain is kept because it is operationally useful (bounces and
    deliverability problems cluster by domain) and is not personally
    identifying on its own.
    """
    if not email:
        return "<none>"
    email = str(email).strip()
    if "@" not in email:
        return "<invalid>"
    local, _, domain = email.partition("@")
    if not local:
        return f"<blank>@{domain}"
    return f"{local[0]}***@{domain}"
