"""
HireLens — outbound email.

Sends via the Resend API, falling back to SMTP.

EVERY value interpolated into an email body is HTML-escaped. That is not
boilerplate caution — these templates carry attacker-reachable strings:

  - `team_name` is chosen by whoever created the team, with no constraint
    beyond a length cap. It went into the invite email unescaped, so a team
    named `"><a href="https://phish.example">Verify your account</a><b x="`
    put the attacker's own markup and links inside a message delivered from
    HireLens's sending domain, with HireLens's branding, to any address they
    typed in. That is a phishing kit, assembled out of the product's own
    features.
  - `body` in the candidate notification was assigned to a variable named
    `safe_body_html` that performed no escaping whatsoever — only a newline
    to <br> substitution. The name asserted a property the code did not have.

Templates use the app's current design tokens (see
frontend/src/lib/design-tokens.ts) so an email looks like the product a
recipient just used, rather than the indigo/emoji styling the UI moved away
from.
"""

import html
import smtplib
import logging
import httpx
from email.message import EmailMessage
from app.core.config import settings
from app.core.redaction import mask_email

logger = logging.getLogger("hirelens")


async def send_raw_email(to_email: str, subject: str, html_content: str, text_fallback: str) -> bool:
    """
    Low-level sender shared by all outbound email helpers.
    Tries Resend first, then SMTP. Returns True only if a provider
    actually accepted the message — never raises, so a failed send
    never blocks the caller's main flow (e.g. saving a decision).
    """
    if settings.RESEND_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": settings.SMTP_FROM_EMAIL,
                        "to": [to_email],
                        "subject": subject,
                        "html": html_content,
                    },
                )
                if res.status_code in (200, 201):
                    logger.info(f"Email sent via Resend to {mask_email(to_email)}")
                    return True
                logger.warning(f"Resend email API returned status {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"Resend email dispatch error: {e}")

    if settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD:
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = settings.SMTP_FROM_EMAIL
            msg["To"] = to_email
            msg.set_content(text_fallback)
            msg.add_alternative(html_content, subtype="html")

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
            logger.info(f"Email sent via SMTP to {mask_email(to_email)}")
            return True
        except Exception as e:
            logger.error(f"SMTP email dispatch error: {e}")

    logger.info(
        f"No active email provider (Resend/SMTP) configured. "
        f"Would have sent to {mask_email(to_email)}: {subject}"
    )
    return False


# Design tokens mirrored from frontend/src/lib/design-tokens.ts. Inlined
# because email clients strip <style> blocks and do not resolve CSS
# variables, so every value has to be literal.
_INK = "#12141A"
_SURFACE = "#191B22"
_BORDER = "#2A2D37"
_TEXT = "#EDEDEA"
_TEXT_MUTED = "#B4B4AC"
_TEXT_FAINT = "#8A8B82"
_BRAND = "#3B7D78"

_SERIF = "Georgia, 'Times New Roman', serif"
_SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


def _shell(inner_html: str) -> str:
    """Wrap message content in the shared HireLens email frame."""
    return f"""<!DOCTYPE html>
<html>
  <body style="margin:0;padding:32px 16px;background-color:{_INK};font-family:{_SANS};">
    <div style="max-width:540px;margin:0 auto;background:{_SURFACE};border:1px solid {_BORDER};border-radius:8px;padding:32px;">
      <div style="font-family:{_SERIF};font-size:20px;font-weight:600;color:{_TEXT};margin-bottom:24px;">HireLens</div>
      {inner_html}
    </div>
    <div style="max-width:540px;margin:16px auto 0;font-size:11px;color:{_TEXT_FAINT};text-align:center;">
      Sent by HireLens because someone using it contacted you.
    </div>
  </body>
</html>"""


async def send_team_invite_email(to_email: str, team_name: str, inviter_name: str, invite_url: str) -> bool:
    """Invite someone to a team workspace. Returns True only if a provider
    accepted the message.

    `team_name` and `inviter_name` are both user-authored and are escaped
    before they touch the markup — see the module docstring for what happens
    otherwise. `invite_url` is built by this application from FRONTEND_URL,
    not supplied by a caller, but is escaped for consistency: an attribute
    that is escaped only "when it matters" eventually stops being escaped.
    """
    e_team = html.escape(team_name or "a workspace")
    e_inviter = html.escape(inviter_name or "A teammate")
    e_url = html.escape(invite_url, quote=True)

    subject = f"You're invited to join '{team_name}' on HireLens"
    html_content = _shell(f"""
      <h2 style="font-family:{_SERIF};font-size:18px;font-weight:600;color:{_TEXT};margin:0 0 12px;">Team invitation</h2>
      <p style="font-size:14px;color:{_TEXT_MUTED};line-height:1.6;margin:0 0 24px;">
        <strong style="color:{_TEXT};">{e_inviter}</strong> invited you to collaborate in
        <strong style="color:{_TEXT};">{e_team}</strong> on HireLens.
      </p>
      <div style="margin:0 0 24px;">
        <a href="{e_url}" style="display:inline-block;padding:11px 22px;background:{_BRAND};color:#F5F5F2;font-weight:600;font-size:13px;text-decoration:none;border-radius:6px;">
          Accept invitation
        </a>
      </div>
      <p style="font-size:12px;color:{_TEXT_FAINT};line-height:1.5;margin:0;">
        Or paste this link into your browser:<br>
        <a href="{e_url}" style="color:{_BRAND};word-break:break-all;">{e_url}</a>
      </p>
    """)
    text_fallback = (
        f"{inviter_name or 'A teammate'} invited you to join '{team_name}' on HireLens.\n\n"
        f"Accept: {invite_url}"
    )
    return await send_raw_email(to_email, subject, html_content, text_fallback)


DECISION_EMAIL_DEFAULTS = {
    "advance": {
        "subject": "Update on your application — {team_name}",
        "body": (
            "Hi {candidate_name},\n\n"
            "Thank you for applying. We've reviewed your resume and would like to "
            "move forward with your application for the next stage of our hiring process.\n\n"
            "A member of our team will be in touch shortly to schedule the next steps.\n\n"
            "Best regards,\n{sender_name}\n{team_name}"
        ),
    },
    "schedule_followup": {
        "subject": "A quick follow-up on your application — {team_name}",
        "body": (
            "Hi {candidate_name},\n\n"
            "Thank you for your application. Before we proceed, we'd like to request "
            "a bit more information to complete our review.\n\n"
            "Someone from our team will reach out shortly with specific questions.\n\n"
            "Best regards,\n{sender_name}\n{team_name}"
        ),
    },
    "reject": {
        "subject": "Update on your application — {team_name}",
        "body": (
            "Hi {candidate_name},\n\n"
            "Thank you for taking the time to apply and for your interest in joining us. "
            "After careful review, we've decided to move forward with other candidates "
            "for this particular role.\n\n"
            "We appreciate the effort you put into your application and wish you the "
            "very best in your job search.\n\n"
            "Best regards,\n{sender_name}\n{team_name}"
        ),
    },
}


def build_decision_email(decision: str, candidate_name: str, sender_name: str, team_name: str) -> dict:
    """
    Returns a default {subject, body} pair for a given decision, with
    placeholders already filled in. The caller (via the /notify endpoint)
    may send this as-is (one-click) or let the recruiter edit it first —
    this function only supplies the starting draft.
    """
    template = DECISION_EMAIL_DEFAULTS.get(decision, DECISION_EMAIL_DEFAULTS["reject"])
    ctx = {
        "candidate_name": candidate_name or "there",
        "sender_name": sender_name or "The Hiring Team",
        "team_name": team_name or "HireLens",
    }
    return {
        "subject": template["subject"].format(**ctx),
        "body": template["body"].format(**ctx),
    }


async def send_candidate_decision_email(to_email: str, subject: str, body: str) -> bool:
    """Send a recruiter-authored (or default-template) decision notification.

    `body` is plain text. It is HTML-escaped before newlines become <br>, so
    a recruiter writing "salary range < 100k" gets exactly that in the
    delivered email instead of losing everything after the "<" to a
    half-parsed tag — and no input can introduce markup of its own.
    """
    escaped_body = html.escape(body or "").replace("\n", "<br>")
    html_content = _shell(
        f'<div style="font-size:14px;color:{_TEXT_MUTED};line-height:1.7;">{escaped_body}</div>'
    )
    return await send_raw_email(to_email, subject, html_content, text_fallback=body)
