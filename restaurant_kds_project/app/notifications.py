"""
Lead email notifications — dormant until configured via env vars.

Turn it on by setting:
  EMAIL_PROVIDER = "resend"  (or "gmail")
  LEAD_NOTIFY_TO = "you@example.com"        # where alerts are sent

For Resend:
  RESEND_API_KEY = "re_xxx"
  LEAD_NOTIFY_FROM = "Listo <leads@tudominio.com>"   # must be a verified sender

For Gmail SMTP:
  GMAIL_USER = "you@gmail.com"
  GMAIL_APP_PASSWORD = "app-password"        # NOT your normal password

If EMAIL_PROVIDER is unset/empty, notifications are skipped silently (the lead
is still stored in the DB and shown in the admin inbox). This function never
raises — a mail failure must never break the public contact form.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import urllib.request
from email.mime.text import MIMEText

logger = logging.getLogger("leads")


def _body(lead) -> tuple[str, str]:
    subject = f"Nuevo lead: {lead.name}" + (f" ({lead.restaurant})" if lead.restaurant else "")
    lines = [
        f"Nombre: {lead.name}",
        f"Restaurante: {lead.restaurant or '-'}",
        f"Email: {lead.email}",
        f"Teléfono: {lead.phone or '-'}",
        f"Sucursales: {lead.locations or '-'}",
        f"Usa hoy: {lead.current_system or '-'}",
        f"Idioma: {lead.lang or '-'}",
        "",
        "Mensaje:",
        (lead.message or "(sin mensaje)"),
    ]
    return subject, "\n".join(lines)


def send_lead_notification(lead) -> bool:
    """Best-effort email alert for a new lead. Returns True if sent."""
    provider = (os.getenv("EMAIL_PROVIDER") or "").strip().lower()
    to_addr = os.getenv("LEAD_NOTIFY_TO") or os.getenv("ADMIN_EMAIL")
    if not provider or not to_addr:
        return False  # dormant — not configured yet

    subject, text = _body(lead)
    try:
        if provider == "resend":
            return _send_resend(to_addr, subject, text)
        if provider == "gmail":
            return _send_gmail(to_addr, subject, text)
        logger.warning("Unknown EMAIL_PROVIDER=%r; skipping notification", provider)
        return False
    except Exception:
        logger.exception("Lead email notification failed (lead #%s)", getattr(lead, "id", "?"))
        return False


def _send_resend(to_addr: str, subject: str, text: str) -> bool:
    api_key = os.getenv("RESEND_API_KEY")
    from_addr = os.getenv("LEAD_NOTIFY_FROM") or "Listo <onboarding@resend.dev>"
    if not api_key:
        logger.warning("EMAIL_PROVIDER=resend but RESEND_API_KEY is missing")
        return False
    payload = json.dumps({
        "from": from_addr,
        "to": [to_addr],
        "subject": subject,
        "text": text,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return 200 <= resp.status < 300


def _send_gmail(to_addr: str, subject: str, text: str) -> bool:
    user = os.getenv("GMAIL_USER")
    pw = os.getenv("GMAIL_APP_PASSWORD")
    if not user or not pw:
        logger.warning("EMAIL_PROVIDER=gmail but GMAIL_USER/GMAIL_APP_PASSWORD missing")
        return False
    msg = MIMEText(text, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as server:
        server.starttls()
        server.login(user, pw)
        server.sendmail(user, [to_addr], msg.as_string())
    return True
