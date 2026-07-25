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
        <div style="font-size: 24px; font-weight: 800; color: #F8FAFC; margin-bottom: 8px;">🔎 HireLens</div>
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

    # 1. Try Resend API if configured
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
                    logger.info(f"Team invite email sent via Resend to {to_email}")
                    return True
                else:
                    logger.warning(f"Resend email API returned status {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"Resend email dispatch error: {e}")

    # 2. Try SMTP if configured
    if settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD:
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = settings.SMTP_FROM_EMAIL
            msg["To"] = to_email
            msg.set_content(f"You are invited to join team '{team_name}' on HireLens. Click: {invite_url}")
            msg.add_alternative(html_content, subtype="html")

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
            logger.info(f"Team invite email sent via SMTP to {to_email}")
            return True
        except Exception as e:
            logger.error(f"SMTP email dispatch error: {e}")

    logger.info(f"No active email provider (Resend/SMTP) configured. Generated share link for {to_email}: {invite_url}")
    return False
