"""Email delivery.

Intentionally provider-agnostic. The ``provider`` argument lets operators
swap in SES / SendGrid / SMTP without changing the library. Default is
``stdout`` so the template is safe to run locally without any credentials.
"""

from __future__ import annotations

from ..models import EmailMessage


def send_email(message: EmailMessage, provider: str = "stdout", dry_run: bool = False) -> dict:
    if dry_run:
        return {"status": "dry_run", "recipients": message.recipients, "subject": message.subject}

    provider_key = (provider or "stdout").strip().lower()

    if provider_key == "stdout":
        print(f"[email:{provider_key}] to={message.recipients} subject={message.subject!r}")
        print(message.body_text)
        return {"status": "queued", "provider": provider_key, "recipients": message.recipients}

    # Real provider integrations live here. Keeping them behind explicit
    # switches prevents surprise egress when the template is pulled into a
    # new environment.
    return {
        "status": "skipped",
        "reason": f"provider_not_implemented:{provider_key}",
        "recipients": message.recipients,
    }
