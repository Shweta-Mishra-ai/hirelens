"""
HireLens — Real Email Sender Service
Supports sending real HTML emails via Resend API, SMTP (Gmail/SES/SendGrid), or Supabase Auth.
"""

import smtplib
import logging
import httpx
from email.message import EmailMessage
from app.core.config import settings

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
                    logger.info(f"Email sent via Resend to {to_email}")
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
            logger.info(f"Email sent via SMTP to {to_email}")
            return True
        except Exception as e:
            logger.error(f"SMTP email dispatch error: {e}")

    logger.info(f"No active email provider (Resend/SMTP) configured. Would have sent to {to_email}: {subject}")
    return False


async def send_team_invite_email(to_email: str, team_name: str, inviter_name: str, invite_url: str) -> bool:
    """
    Sends a real team invitation email to to_email.
    Returns True if an email was successfully sent.
    """
    subject = f"You're invited to join team '{team_name}' on HireLens"
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="background-color: #0B0F17; color: #F8FAFC; font-family: sans-serif; padding: 30px;">
      <div style="max-width: 540px; margin: 0 auto; background: #1E293B; border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 32px;">
        <div style="font-size: 24px; font-weight: 800; color: #F8FAFC; margin-bottom: 8px;">HireLens</div>
        <h2 style="font-size: 20px; color: #F8FAFC; margin-top: 0;">Team Invitation</h2>
        <p style="font-size: 14px; color: #CBD5E1; line-height: 1.6;">
          <strong style="color: #818CF8;">{inviter_name}</strong> invited you to collaborate in the workspace <strong style="color: #F8FAFC;">"{team_name}"</strong> on HireLens.
        </p>
        <div style="margin: 28px 0; text-align: center;">
          <a href="{invite_url}" style="display: inline-block; padding: 12px 28px; background: linear-gradient(135deg, #6366F1, #4F46E5); color: #FFFFFF; font-weight: 700; font-size: 14px; text-decoration: none; border-radius: 10px;">
            Accept & Join Team
          </a>
        </div>
        <p style="font-size: 12px; color: #94A3B8; line-height: 1.5;">
          Or copy and paste this link in your browser:<br>
          <a href="{invite_url}" style="color: #818CF8; word-break: break-all;">{invite_url}</a>
        </p>
      </div>
    </body>
    </html>
    """
    text_fallback = f"You are invited to join team '{team_name}' on HireLens. Click: {invite_url}"
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
    """
    Sends a recruiter-authored (or default-template) decision notification
    to a candidate. `body` is plain text; a light HTML wrapper is applied
    for clients that render HTML, with the exact same text as content.
    """
    safe_body_html = body.replace("\n", "<br>")
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="background-color: #0B0F17; color: #F8FAFC; font-family: sans-serif; padding: 30px;">
      <div style="max-width: 540px; margin: 0 auto; background: #1E293B; border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 32px;">
        <div style="font-size: 22px; font-weight: 800; color: #F8FAFC; margin-bottom: 20px;">HireLens</div>
        <div style="font-size: 14px; color: #E2E8F0; line-height: 1.7; white-space: pre-line;">{safe_body_html}</div>
      </div>
    </body>
    </html>
    """
    return await send_raw_email(to_email, subject, html_content, text_fallback=body)
