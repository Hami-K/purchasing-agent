"""
Sends RFQ emails via Gmail SMTP. This is the only file in the codebase
that talks to a real mail server; the TEST_MODE safety rail is enforced
here, in one place.
"""

import smtplib
from email.mime.text import MIMEText

import pandas as pd

from src.config import get_setting


def is_test_mode() -> bool:
    """
    Fail-closed: anything other than the exact (case-insensitive) string
    "false" is treated as test mode ON. Unset, "true", a typo, an empty
    string — all of those stay safe. Only a literal TEST_MODE=false
    enables sending to real vendor addresses.
    """
    return get_setting("TEST_MODE", "true").strip().lower() != "false"


def get_company_name() -> str:
    """
    Reads COMPANY_NAME for personalizing outgoing emails. Returns "" if
    unset, meaning the personalized line is omitted rather than printed
    blank.

    RFQ emails always use this — an RFQ has no PO number (products are
    free text, not tied to a specific property's PO run), so the cluster
    resolution in resolve_company_name_for_po() below does not apply
    there.
    """
    return get_setting("COMPANY_NAME", "").strip()


def is_cluster_mode() -> bool:
    """IS_CLUSTER=true (exact, case-insensitive) enables PO-number-prefix
    based property name resolution for Pending Market List. Default off."""
    return get_setting("IS_CLUSTER", "false").strip().lower() == "true"


def get_cluster_map() -> dict:
    """
    Reads CLUSTER_1_CODE/CLUSTER_1_NAME, CLUSTER_2_CODE/CLUSTER_2_NAME, ...
    and returns {code: name}, e.g. {"HJ": "Property Jumeirah",
    "HW": "Property Walk"}. Scans numbered slots until one is entirely
    unset — add CLUSTER_3_CODE/CLUSTER_3_NAME etc. for more properties.
    Codes are matched case-insensitively.
    """
    mapping = {}
    n = 1
    while True:
        code = get_setting(f"CLUSTER_{n}_CODE", "").strip().upper()
        name = get_setting(f"CLUSTER_{n}_NAME", "").strip()
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
    returns that property's CLUSTER_N_NAME. Falls back to COMPANY_NAME
    (same value RFQ emails use) when clustering is off, no code matches,
    or no cluster is configured. Accepts pandas NaN or any other
    non-string value for po_number without raising.
    """
    if is_cluster_mode():
        # pandas represents a blank Excel cell as NaN (a float); NaN is
        # truthy in Python, so `po_number or ""` does not catch it, and a
        # float has no .strip(). pd.isna() is the correct missing-value
        # check regardless of po_number's type.
        prefix = "" if pd.isna(po_number) else str(po_number).strip().upper()[:2]
        mapping = get_cluster_map()
        if prefix in mapping:
            return mapping[prefix]
    return get_company_name()


def send_email(recipient, subject: str, body: str, is_html: bool = False) -> dict:
    """
    Sends one email via Gmail SMTP (smtplib, SMTP_SSL on port 465).

    recipient: a single email string, or a list of email strings (e.g.
    every email on file for one vendor) — all go in the "To" line of one
    email.

    In TEST_MODE (default True), the real recipient(s) are ignored and the
    email goes to the single DEV_EMAIL address instead, regardless of what
    was passed in or stored in the database. Only TEST_MODE="false" sends
    to the real recipient(s).

    subject is sent exactly as given; each caller (e.g. draft_rfq.py) owns
    its own subject template, including any TEST_MODE marker in it. This
    function prepends a redirect note to the body in test mode, naming
    the original intended recipient(s) — the subject itself carries no
    such note.

    is_html=True sends body as an HTML email (e.g. a formatted table)
    instead of plain text.

    Returns a dict describing what actually happened: intended vs. actual
    recipient(s), and whether TEST_MODE redirected it.
    """
    recipients = [recipient] if isinstance(recipient, str) else list(recipient)
    recipients = [r.strip() for r in recipients if r and r.strip()]
    if not recipients:
        raise ValueError("No recipient email address given.")

    test_mode = is_test_mode()

    gmail_address = get_setting("GMAIL_ADDRESS")
    gmail_app_password = get_setting("GMAIL_APP_PASSWORD")
    if not gmail_address or not gmail_app_password:
        raise RuntimeError(
            "GMAIL_ADDRESS and GMAIL_APP_PASSWORD must be set in .env to send email."
        )

    intended = ", ".join(recipients)

    if test_mode:
        dev_email = get_setting("DEV_EMAIL")
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
