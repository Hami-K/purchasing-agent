"""
Drafts one RFQ email per selected vendor, from a free-text list of products
(description/qty/UOM) entered directly in the UI — no lookup against the
`items` catalog, no LLM. Every vendor in one call shares the same RFQ
number, and is addressed to every email on file for that vendor.
"""

import json
import os
import sqlite3
from datetime import date

from src.email_utils import is_test_mode, get_company_name

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "purchasing.db")


def format_rfq_id(rfq_id: int) -> str:
    return f"RFQ-{rfq_id:04d}"


def _get_vendor(cur, vendor_id: str):
    cur.execute("SELECT name FROM vendors WHERE vendor_id = ?", (vendor_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"No vendor found with id {vendor_id}")
    return row[0]


def _get_vendor_emails(cur, vendor_id: str) -> list:
    cur.execute("SELECT email FROM vendor_emails WHERE vendor_id = ? ORDER BY email_id", (vendor_id,))
    return [row[0] for row in cur.fetchall()]


def _log_rfq(cur, products: list, vendor_ids: list) -> int:
    """Always logs the batch for audit/history, regardless of whether the
    displayed RFQ number ends up being this row's auto-id or a manually
    entered one — see peek_next_rfq_number() / draft_rfq()'s rfq_number arg."""
    cur.execute(
        "INSERT INTO rfq_log (products, vendor_ids, created_at) VALUES (?, ?, ?)",
        (json.dumps(products), ",".join(vendor_ids), str(date.today())),
    )
    return cur.lastrowid


def peek_next_rfq_number() -> str:
    """Suggests the next sequential RFQ number for the UI to pre-fill a
    manual-entry field with — doesn't reserve or log anything, so calling
    this repeatedly (e.g. on every Streamlit rerun) is free. The user can
    keep the suggestion or type their own number entirely."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT MAX(rfq_id) FROM rfq_log")
    row = cur.fetchone()
    conn.close()
    next_id = (row[0] or 0) + 1
    return format_rfq_id(next_id)


# Explicit color + background on every element, not just the wrapper — some
# email clients (and Streamlit's own HTML preview, which renders in a
# transparent iframe) apply dark-mode auto-inversion per-element, so
# relying on inheritance from an outer wrapper isn't enough on its own.
_TEXT_STYLE = "font-family:Arial,sans-serif;font-size:14px;color:#111111;background-color:#ffffff;"
_CELL_STYLE = "border:1px solid #999;padding:6px 10px;font-family:Arial,sans-serif;font-size:13px;color:#111111;background-color:#ffffff;"
_HEADER_CELL_STYLE = _CELL_STYLE.replace("background-color:#ffffff;", "background-color:#cfe2f3;") + "text-align:left;"


def _build_table_html(products: list) -> str:
    header_cells = "".join(f'<th style="{_HEADER_CELL_STYLE}">{col}</th>' for col in
                            ["S.NO", "Product Description", "Qty", "UOM"])
    rows_html = ""
    for i, p in enumerate(products, start=1):
        cells = "".join(
            f'<td style="{_CELL_STYLE}">{val}</td>'
            for val in [i, p["description"], p["qty"], p["uom"]]
        )
        rows_html += f"<tr>{cells}</tr>"
    return f'<table style="border-collapse:collapse;background-color:#ffffff;"><tr>{header_cells}</tr>{rows_html}</table>'


def _build_subject(rfq_number: str) -> str:
    base = f"Request for Quotation - {rfq_number}"
    return f"{base} [TEST MODE]" if is_test_mode() else base


def _build_body(products: list, rfq_number: str) -> str:
    table_html = _build_table_html(products)
    company = get_company_name()
    intro = f'<p style="{_TEXT_STYLE}">We are reaching out from {company}.</p>' if company else ""
    return (
        '<div style="background-color:#ffffff;padding:4px;">'
        f'<p style="{_TEXT_STYLE}">Dear Team,</p>'
        f"{intro}"
        f'<p style="{_TEXT_STYLE}">Please share your quotation (Ref: {rfq_number}) '
        "for the following:</p>"
        f"{table_html}"
        f'<p style="{_TEXT_STYLE}">Kindly include unit price, minimum order quantity, '
        "and estimated lead time in your response.</p>"
        f'<p style="{_TEXT_STYLE}">Please Note: Any quotation received after 3 days '
        "from this email will not be acknowledged.</p>"
        f'<p style="{_TEXT_STYLE}">Regards,<br>Purchasing Team</p>'
        "</div>"
    )


def draft_rfq(products: list, vendor_ids: list, rfq_number: str = None) -> dict:
    """
    products: list of {"description": str, "qty": ..., "uom": str} — entered
        directly by the user, never matched against the items catalog.
    vendor_ids: list of vendor_id strings to request quotes from.
    rfq_number: optional — the UI pre-fills a suggested next number (see
        peek_next_rfq_number()) but the human can override it with their
        own before drafting. Every call still logs to rfq_log for audit
        history regardless of whether this override is used.

    Returns {"rfq_number": "RFQ-0001", "drafts": [
        {"vendor_id", "vendor_name", "emails": [...], "subject", "body"}, ...
    ]}. Sends nothing — sending is a separate, human-triggered step.
    """
    if not products:
        raise ValueError("At least one product is required to draft an RFQ.")
    if not vendor_ids:
        raise ValueError("At least one vendor is required to draft an RFQ.")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    rfq_id = _log_rfq(cur, products, vendor_ids)
    rfq_number = rfq_number.strip() if rfq_number and rfq_number.strip() else format_rfq_id(rfq_id)
    subject = _build_subject(rfq_number)
    body = _build_body(products, rfq_number)

    drafts = []
    for vendor_id in vendor_ids:
        vendor_name = _get_vendor(cur, vendor_id)
        emails = _get_vendor_emails(cur, vendor_id)
        drafts.append({
            "vendor_id": vendor_id,
            "vendor_name": vendor_name,
            "emails": emails,
            "subject": subject,
            "body": body,
        })

    conn.commit()
    conn.close()

    return {"rfq_number": rfq_number, "drafts": drafts}
