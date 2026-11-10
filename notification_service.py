"""External notification channels for the ERP Attendance prototype.
Credentials are read from environment variables / local .env file.
"""
import os
import logging
import smtplib
from email.message import EmailMessage
import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)


def send_email(to_email, subject, body):
    sender = os.getenv("SMTP_EMAIL")
    password = os.getenv("SMTP_APP_PASSWORD", "").replace(" ", "")
    if not (sender and password and to_email):
        log.info("EMAIL SKIPPED: set SMTP_EMAIL, SMTP_APP_PASSWORD and student email.")
        return "skipped"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(body)
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=20) as server:
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
    log.info("Email accepted by SMTP for %s", to_email)
    return "sent"


def send_whatsapp(phone, body):
    token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    if not (token and phone_id and phone):
        log.info("WHATSAPP SKIPPED: set Meta credentials and student phone.")
        return "skipped"
    version = os.getenv("WHATSAPP_API_VERSION", "v23.0")
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    to = "".join(ch for ch in str(phone) if ch.isdigit())
    mode = os.getenv("WHATSAPP_MODE", "text").lower()
    if mode == "template":
        template_name = os.getenv("WHATSAPP_TEMPLATE_NAME")
        language = os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US")
        if not template_name:
            log.info("WHATSAPP SKIPPED: set WHATSAPP_TEMPLATE_NAME to an approved template.")
            return "skipped"
        # The approved template should have one body placeholder {{1}} for the message text.
        payload = {
            "messaging_product": "whatsapp", "to": to, "type": "template",
            "template": {"name": template_name, "language": {"code": language},
                         "components": [{"type": "body", "parameters": [{"type": "text", "text": body[:900]}]}]}
        }
    else:
        # Free-form text is allowed only within the customer-service window after the recipient messages the business.
        payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}}
    response = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=20)
    if not response.ok:
        raise RuntimeError(f"WhatsApp API error {response.status_code}: {response.text[:500]}")
    log.info("WhatsApp API accepted message for %s", phone)
    return "sent"


def send_sms(phone, body):
    provider = os.getenv("SMS_PROVIDER", "disabled").lower()
    if provider != "twilio":
        log.info("SMS NOT SENT: SMS_PROVIDER is not set to twilio.")
        return "skipped"
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    sender = os.getenv("TWILIO_FROM_NUMBER")
    if not (sid and token and sender and phone):
        log.info("SMS SKIPPED: set Twilio SID, auth token, sender number and student phone.")
        return "skipped"
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    response = requests.post(url, auth=(sid, token), data={"To": str(phone), "From": sender, "Body": body}, timeout=20)
    if not response.ok:
        raise RuntimeError(f"SMS provider error {response.status_code}: {response.text[:500]}")
    log.info("SMS provider accepted message for %s", phone)
    return "sent"


def send_configured_notifications(student_name, email, phone, subject, message):
    results = {}
    for channel, action in (
        ("email", lambda: send_email(email, subject, message)),
        ("whatsapp", lambda: send_whatsapp(phone, message)),
        ("sms", lambda: send_sms(phone, message)),
    ):
        try:
            results[channel] = action()
        except Exception as exc:
            log.exception("%s notification failed for %s", channel, student_name)
            results[channel] = "failed"
    return results
