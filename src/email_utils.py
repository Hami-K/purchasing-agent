"""
Actually sends RFQ emails via Gmail SMTP. This is the only file in the
codebase that talks to a real mail server — keep it that way so the
TEST_MODE safety rail only has to be enforced in one place.
"""

import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()


def is_test_mode() -> bool:
    """
    Fail-closed: anything other than the exact (case-insensitive) string
    "false" is treated as test mode ON. Unset, "true", a typo, an empty
    string — all of those stay safe. Only a literal TEST_MODE=false in
    .env enables sending to real vendor addresses.
    """
    return os.getenv("TEST_MODE", "true").strip().lower() != "false"


def get_company_name() -> str:
    """
    Reads COMPANY_NAME from .env (e.g. "Hilton Dubai Jumeirah") for
    personalizing outgoing emails. Returns "" if unset — callers should
    treat that as "omit the personalized line", not print a blank name.

    This is what RFQ emails always use — there's no PO number on an RFQ
    (it's free-text products, not tied to a specific property's PO run),
    so cluster resolution below doesn't apply there.
    """
    return os.getenv("COMPANY_NAME", "").strip()


def is_cluster_mode() -> bool:
    """IS_CLUSTER=true (exact, case-insensitive) enables PO-number-prefix
    based property name resolution for Pending Market List. Defaults off."""
    return os.getenv("IS_CLUSTER", "false").strip().lower() == "true"


def get_cluster_map() -> dict:
    """
    Reads CLUSTER_1_CODE/CLUSTER_1_NAME, CLUSTER_2_CODE/CLUSTER_2_NAME, ...
    from .env and returns {code: name}, e.g. {"HJ": "Hilton Dubai Jumeirah",
    "HW": "Hilton Dubai The Walk"}. Scans as many numbered slots as are
    actually set — not hardcoded to 2, add CLUSTER_3_CODE/CLUSTER_3_NAME
    etc. for more properties. Codes are matched case-insensitively.
    """
    mapping = {}
    n = 1
    while True:
        code = os.getenv(f"CLUSTER_{n}_CODE", "").strip().upper()
        name = os.getenv(f"CLUSTER_{n}_NAME", "").strip()
        if not code and not name:
            break
        if code and name:
            mapping[code] = name
        n += 1
    return mapping


def resolve_company_name_for_po(po_number: str) -> str:
    """
    For Pending Market List: if IS_CLUSTER is on, matches the PO number's
    first 2 characters against the configured CLUSTER_N_CODE values and
    returns that property's CLUSTER_N_NAME. Falls back to COMPANY_NAME —
    same as the non-cluster/RFQ behavior — whenever clustering is off, no
    code matches, or nothing is configured. Never raises; a bad/missing
    PO number just falls through to the fallback.
    """
    if is_cluster_mode():
        prefix = (po_number or "").strip().upper()[:2]
        mapping = get_cluster_map()
        if prefix in mapping:
            return mapping[prefix]
    return get_company_name()


def send_email(recipient, subject: str, body: str, is_html: bool = False) -> dict:
    """
    Sends one email via Gmail SMTP (smtplib, SMTP_SSL on port 465).

    `recipient` may be a single email string or a list of email strings
    (e.g. every email on file for one vendor) — all of them go in the "To"
    line of one email.

    In TEST_MODE (default True), the real recipient(s) are ignored and the
    email is sent to the single DEV_EMAIL address instead — regardless of
    what's passed in or what's stored in the database. Only when TEST_MODE
    is explicitly "false" do the real recipient(s) get used.

    `subject` is sent exactly as given — callers (e.g. draft_rfq.py) are
    responsible for their own TEST_MODE-aware subject line, since they own
    the template. This function only adds a short redirect note to the
    BODY in test mode, so a redirected email still says who it was really
    meant for even though the subject won't.

    Set is_html=True to send `body` as an HTML email (e.g. a formatted
    table) instead of plain text.

    Returns a dict describing what actually happened (intended vs. actual
    recipient(s), and whether test mode redirected it), for the UI to show.
    """
    recipients = [recipient] if isinstance(recipient, str) else list(recipient)
    recipients = [r.strip() for r in recipients if r and r.strip()]
    if not recipients:
        raise ValueError("No recipient email address given.")

    test_mode = is_test_mode()

    gmail_address = os.getenv("GMAIL_ADDRESS")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")
    if not gmail_address or not gmail_app_password:
        raise RuntimeError(
            "GMAIL_ADDRESS and GMAIL_APP_PASSWORD must be set in .env to send email."
        )

    intended = ", ".join(recipients)

    if test_mode:
        dev_email = os.getenv("DEV_EMAIL")
        if not dev_email:
            raise RuntimeError(
                "TEST_MODE is on but DEV_EMAIL is not set in .env — refusing to send."
            )
        actual_recipients = [dev_email]
        actual_subject = subject
        note = (
            f"(TEST MODE: this email was redirected here instead of being sent to "
            f"the intended recipient(s) {intended}.)"
        )
        actual_body = (
            f'<p style="font-family:Arial,sans-serif;font-size:13px;color:#111111;'
            f'background-color:#ffffff;"><em>{note}</em></p>\n{body}'
            if is_html else f"{note}\n\n{body}"
        )
    else:
        actual_recipients = recipients
        actual_subject = subject
        actual_body = body

    msg = MIMEText(actual_body, "html" if is_html else "plain")
    msg["Subject"] = actual_subject
    msg["From"] = gmail_address
    msg["To"] = ", ".join(actual_recipients)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, actual_recipients, msg.as_string())

    return {
        "intended_recipient": intended,
        "actual_recipient": ", ".join(actual_recipients),
        "test_mode": test_mode,
    }
