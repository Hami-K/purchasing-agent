"""
Pending Market List: turns an uploaded "pending deliveries" Excel export
into one plain-code (no LLM) email draft per supplier, cross-checking
supplier names against the vendors table for a contact email.
"""

import re
import sqlite3
import os

import pandas as pd

from src.email_utils import is_test_mode, get_company_name

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "purchasing.db")

# Canonical column name -> the various lowercase/case-variant headers we
# accept in the uploaded file (matched case-insensitively after stripping).
REQUIRED_COLUMNS = {
    "delivery date": "Delivery Date",
    "supplier name": "Supplier Name",
    "item description": "Item Description",
    "qty": "Qty",
    "uom": "UOM",
    "po number": "PO Number",
}

DISPLAY_COLUMNS = ["Delivery Date", "Item Description", "Qty", "UOM", "PO Number"]


def _format_date(value) -> str:
    if pd.isna(value):
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    return str(value).strip()


def parse_market_list(file) -> pd.DataFrame:
    """
    Parses an uploaded pending-market-list Excel file into a clean
    DataFrame with exactly the columns Delivery Date, Supplier Name,
    Item Description, Qty, UOM, PO Number.

    These exports typically have a merged title row ("HOTEL NAME PENDING
    MARKET LIST" + a date) above the real column headers, so rather than
    assuming a fixed header row index, this scans the first few rows for
    whichever one contains "delivery date" as a cell value.
    """
    raw = pd.read_excel(file, header=None)

    header_row_idx = None
    for i in range(min(5, len(raw))):
        row_values = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
        if "delivery date" in row_values:
            header_row_idx = i
            break

    if header_row_idx is None:
        raise ValueError(
            "Couldn't find a header row containing 'Delivery date' in the first "
            "5 rows of the uploaded file — check it matches the expected format."
        )

    headers = [str(v).strip() for v in raw.iloc[header_row_idx].tolist()]
    data = raw.iloc[header_row_idx + 1:].copy()
    data.columns = headers

    normalized = {str(c).strip().lower(): c for c in data.columns}
    missing = [k for k in REQUIRED_COLUMNS if k not in normalized]
    if missing:
        raise ValueError(f"Missing expected column(s) in the uploaded file: {', '.join(missing)}")

    selected = data[[normalized[k] for k in REQUIRED_COLUMNS]].copy()
    selected.columns = list(REQUIRED_COLUMNS.values())

    # Drop blank spacer rows and rows with no supplier name.
    selected = selected.dropna(how="all")
    selected["Supplier Name"] = selected["Supplier Name"].astype(str).str.strip()
    selected = selected[(selected["Supplier Name"] != "") & (selected["Supplier Name"].str.lower() != "nan")]

    selected["Delivery Date"] = selected["Delivery Date"].apply(_format_date)
    selected["Item Description"] = selected["Item Description"].astype(str).str.strip()
    selected["Qty"] = selected["Qty"]
    selected["UOM"] = selected["UOM"].astype(str).str.strip()
    selected["PO Number"] = selected["PO Number"].astype(str).str.strip()

    return selected.reset_index(drop=True)


def match_supplier_emails(supplier_names: list) -> dict:
    """
    For each unique supplier name, looks up a case-insensitive exact match
    against vendors.name and returns {supplier_name: email_or_None}. Reads
    vendor_emails (a vendor can have several on file — the first one is
    used to address the draft) rather than the legacy vendors.email
    column, so a supplier added only through Manage Suppliers still
    matches automatically.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    result = {}
    for name in supplier_names:
        cur.execute(
            """
            SELECT ve.email FROM vendors v
            JOIN vendor_emails ve ON v.vendor_id = ve.vendor_id
            WHERE LOWER(TRIM(v.name)) = LOWER(TRIM(?))
            ORDER BY ve.email_id
            LIMIT 1
            """,
            (name,),
        )
        row = cur.fetchone()
        result[name] = row[0] if row else None
    conn.close()
    return result


def suggest_test_email(supplier_name: str) -> str:
    """Deterministic synthetic placeholder for a supplier with no DB match —
    same fictional quotewell.test domain used for the seeded vendor emails."""
    slug = re.sub(r"[^a-z0-9]+", "", supplier_name.lower())[:30] or "supplier"
    return f"{slug}@quotewell.test"


def _build_subject() -> str:
    return "Pending Delivery [TEST MODE]" if is_test_mode() else "Pending Delivery"


# Explicit color + background on every element — some email clients (and
# Streamlit's own HTML preview, which renders in a transparent iframe)
# apply dark-mode auto-inversion per-element, so relying on inheritance
# from an outer wrapper isn't enough on its own.
_TEXT_STYLE = "font-family:Arial,sans-serif;font-size:14px;color:#111111;background-color:#ffffff;"
_CELL_STYLE = "border:1px solid #999;padding:6px 10px;font-family:Arial,sans-serif;font-size:13px;color:#111111;background-color:#ffffff;"
_HEADER_CELL_STYLE = _CELL_STYLE.replace("background-color:#ffffff;", "background-color:#cfe2f3;") + "text-align:left;"


def _build_table_html(rows: pd.DataFrame) -> str:
    header_cells = "".join(f'<th style="{_HEADER_CELL_STYLE}">{col}</th>' for col in DISPLAY_COLUMNS)
    body_rows = ""
    for _, row in rows.iterrows():
        cells = "".join(f'<td style="{_CELL_STYLE}">{row[col]}</td>' for col in DISPLAY_COLUMNS)
        body_rows += f"<tr>{cells}</tr>"
    return f'<table style="border-collapse:collapse;background-color:#ffffff;">' \
           f"<tr>{header_cells}</tr>{body_rows}</table>"


def _build_body(rows: pd.DataFrame) -> str:
    table_html = _build_table_html(rows)
    company = get_company_name()
    intro = f'<p style="{_TEXT_STYLE}">We are reaching out from {company}.</p>' if company else ""
    return (
        '<div style="background-color:#ffffff;padding:4px;">'
        f'<p style="{_TEXT_STYLE}">Dear Team,</p>'
        f"{intro}"
        f'<p style="{_TEXT_STYLE}">Kindly advise for the below pending items:</p>'
        f"{table_html}"
        f'<p style="{_TEXT_STYLE}">Thank You<br>Purchasing Team</p>'
        "</div>"
    )


def draft_pending_market_list(df: pd.DataFrame, email_overrides: dict = None) -> list:
    """
    Groups the parsed market-list rows by Supplier Name (one supplier can
    have many pending rows), cross-checks each supplier against the
    vendors table for an email, and builds one draft per supplier — a
    fixed-template email whose body is an HTML table of only that
    supplier's rows. No LLM involved.

    email_overrides lets the caller supply/override an email per supplier
    (e.g. a human-entered address for a supplier not found in the vendors
    table) — used as-is instead of the database lookup when provided.

    Returns a list of {supplier_name, email, matched, rows, subject, body}
    dicts. Sends nothing — sending is a separate, human-triggered step.
    """
    email_overrides = email_overrides or {}
    supplier_names = sorted(df["Supplier Name"].unique())
    db_emails = match_supplier_emails(supplier_names)

    drafts = []
    for name in supplier_names:
        supplier_rows = df[df["Supplier Name"] == name].drop(columns=["Supplier Name"]).reset_index(drop=True)
        matched_email = db_emails.get(name)
        email = email_overrides.get(name) or matched_email or suggest_test_email(name)

        drafts.append({
            "supplier_name": name,
            "email": email,
            "matched": matched_email is not None,
            "rows": supplier_rows,
            "subject": _build_subject(),
            "body": _build_body(supplier_rows),
        })

    return drafts
