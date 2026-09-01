"""
Pending Market List: turns an uploaded "pending deliveries" Excel export
into one plain-code (no LLM) email draft per supplier, cross-checking
supplier names against the vendors table (and, optionally, a
this-session-only uploaded supplier directory) for contact emails.
"""

import re
import sqlite3
import os

import pandas as pd

from src.email_utils import is_test_mode, resolve_company_name_for_po

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

DIRECTORY_NAME_HEADERS = {"supplier name", "vendor", "vendor name", "name", "supplier"}
DIRECTORY_EMAIL_HEADERS = {"email", "email address", "emails", "email addresses", "contact email"}

# Legal-entity-suffix tokens normalize_supplier_name() truncates on. Order
# doesn't matter — matching stops at whichever one appears first in the name.
_SUFFIX_TOKENS = ("LLC", "FZE", "FZ-LLC", "LTD")
_TRAILING_UAE_RE = re.compile(r"\s*\(UAE\)\s*$")


def _format_date(value) -> str:
    if pd.isna(value):
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    return str(value).strip()


def normalize_supplier_name(name: str) -> str:
    """
    Normalizes a supplier name for cross-source matching. Applied in order:

    1. Uppercase.
    2. Strip periods, so "L.L.C" and "LLC" compare equal.
    3. Collapse whitespace runs to a single space, trim ends.
    4. Strip a trailing "(UAE)" qualifier.
    5. Merge consecutive single-letter tokens into one ("L L C" -> "LLC").
    6. Truncate at the first recognized legal-entity-suffix token
       (see _SUFFIX_TOKENS) — everything after that token is dropped, but
       the token itself is kept, so two names differing only in trailing
       branch/address text after the suffix normalize the same, while two
       different suffixes (e.g. LLC vs FZE) never normalize the same.

    Returns "" for a missing/blank input (including pandas NaN).
    """
    if pd.isna(name):
        return ""
    normalized = str(name).strip()
    if not normalized:
        return ""

    normalized = normalized.upper()
    normalized = normalized.replace(".", "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = _TRAILING_UAE_RE.sub("", normalized).strip()

    tokens = normalized.split(" ") if normalized else []
    merged = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if len(token) == 1 and token.isalpha():
            run = token
            j = i + 1
            while j < len(tokens) and len(tokens[j]) == 1 and tokens[j].isalpha():
                run += tokens[j]
                j += 1
            merged.append(run)
            i = j
        else:
            merged.append(token)
            i += 1
    tokens = merged

    for idx, token in enumerate(tokens):
        if token in _SUFFIX_TOKENS:
            tokens = tokens[:idx + 1]
            break

    return " ".join(tokens)


def _build_normalized_directory(entries) -> tuple:
    """
    Groups (name, emails) pairs by normalize_supplier_name(name).

    entries: iterable of (name, emails) pairs, emails a list of address
    strings for that name.

    Returns (index, collisions):
    - index: {normalized_name: [email, ...]} — one entry per normalized
      name that exactly one distinct original spelling maps to. Emails
      across repeated occurrences of that spelling are unioned,
      duplicates removed, order preserved.
    - collisions: [{"normalized": str, "names": [original_name, ...]}] —
      one entry per normalized name that two or more differently-spelled
      original names map to. These are left out of the index.
    """
    groups = {}
    for name, emails in entries:
        normalized = normalize_supplier_name(name)
        if not normalized:
            continue
        original = str(name).strip()
        by_original = groups.setdefault(normalized, {})
        email_list = by_original.setdefault(original, [])
        for email in emails or []:
            if email and email not in email_list:
                email_list.append(email)

    index = {}
    collisions = []
    for normalized, by_original in groups.items():
        if len(by_original) == 1:
            ((_, emails),) = by_original.items()
            index[normalized] = emails
        else:
            collisions.append({"normalized": normalized, "names": sorted(by_original.keys())})

    return index, collisions


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


def parse_supplier_directory(file) -> tuple:
    """
    Parses an uploaded supplier-directory Excel file (a supplier-name
    column plus an email column) into the (index, collisions) shape
    _build_normalized_directory returns.

    Scans the first 5 rows for a header row containing both a recognized
    name-column header and a recognized email-column header (see
    DIRECTORY_NAME_HEADERS / DIRECTORY_EMAIL_HEADERS), matched
    case-insensitively — same approach parse_market_list uses for its own
    header row. A cell with multiple addresses separated by ";" is split
    into a list.

    Reads entirely from the in-memory uploaded file object. Nothing is
    written to disk or the database — the returned directory exists only
    for the current session/run.
    """
    raw = pd.read_excel(file, header=None)

    header_row_idx = None
    name_col = None
    email_col = None
    for i in range(min(5, len(raw))):
        row_values = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
        found_name = next((c for c in row_values if c in DIRECTORY_NAME_HEADERS), None)
        found_email = next((c for c in row_values if c in DIRECTORY_EMAIL_HEADERS), None)
        if found_name and found_email:
            header_row_idx = i
            name_col = row_values.index(found_name)
            email_col = row_values.index(found_email)
            break

    if header_row_idx is None:
        raise ValueError(
            "Couldn't find a header row with both a supplier-name column "
            "(e.g. 'Supplier Name') and an email column (e.g. 'Email') in "
            "the first 5 rows of the uploaded file."
        )

    data = raw.iloc[header_row_idx + 1:]

    entries = []
    for _, row in data.iterrows():
        name = row.iloc[name_col]
        if pd.isna(name) or not str(name).strip():
            continue
        email_cell = row.iloc[email_col]
        emails = [] if pd.isna(email_cell) else [e.strip() for e in str(email_cell).split(";") if e.strip()]
        entries.append((str(name).strip(), emails))

    return _build_normalized_directory(entries)


def match_supplier_emails(supplier_names: list) -> tuple:
    """
    Looks up every email on file for each of supplier_names against the
    vendors table, matching on normalize_supplier_name() rather than exact
    string equality.

    Reads vendor_emails (a vendor can have several on file) rather than
    the legacy vendors.email column, so a supplier added only through
    Manage Suppliers still matches.

    Returns (result, collisions):
    - result: {supplier_name: [email, ...]} for a matched name, or
      {supplier_name: None} when no match or the vendors table has a
      collision at that normalized name.
    - collisions: entries from _build_normalized_directory(...) restricted
      to normalized names that at least one of supplier_names maps to.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT v.name, ve.email FROM vendors v
        JOIN vendor_emails ve ON v.vendor_id = ve.vendor_id
        ORDER BY v.name, ve.email_id
        """
    )
    rows = cur.fetchall()
    conn.close()

    emails_by_name = {}
    for name, email in rows:
        emails_by_name.setdefault(name, []).append(email)

    index, all_collisions = _build_normalized_directory(emails_by_name.items())

    requested_normalized = {normalize_supplier_name(name) for name in supplier_names}
    collisions = [c for c in all_collisions if c["normalized"] in requested_normalized]

    result = {name: index.get(normalize_supplier_name(name)) for name in supplier_names}
    return result, collisions


def suggest_test_email(supplier_name: str) -> str:
    """Deterministic synthetic placeholder for a supplier with no match —
    same fictional quotewell.test domain used for the seeded vendor emails."""
    slug = re.sub(r"[^a-z0-9]+", "", supplier_name.lower())[:30] or "supplier"
    return f"{slug}@quotewell.test"


def _build_subject() -> str:
    return "Pending Delivery [TEST MODE]" if is_test_mode() else "Pending Delivery"


# Color and background are set explicitly on every element, not just the
# wrapper: some email clients, and Streamlit's own HTML preview (rendered
# in a transparent iframe), apply dark-mode auto-inversion per element, so
# inheritance from an outer wrapper is not sufficient.
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


def _build_body(rows: pd.DataFrame, company: str) -> str:
    table_html = _build_table_html(rows)
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


def draft_pending_market_list(df: pd.DataFrame, uploaded_directory: dict = None, email_overrides: dict = None) -> tuple:
    """
    Groups the parsed market-list rows by (Supplier Name, resolved
    property name) — normally that's the same as grouping by supplier
    alone, since resolve_company_name_for_po() falls back to the single
    COMPANY_NAME when IS_CLUSTER is off. When IS_CLUSTER is on and one
    supplier's rows span more than one cluster property in a single
    upload, this gives that supplier one correctly labeled email per
    property instead of one email covering both.

    Email resolution per supplier, in priority order:
    1. email_overrides[supplier_name], if given (string or list of strings).
    2. uploaded_directory[normalize_supplier_name(supplier_name)], if
       present — a directory parsed this run via parse_supplier_directory().
    3. The vendors table (via match_supplier_emails()).
    4. A single deterministic synthetic placeholder (suggest_test_email()).

    "matched" is True when step 2 or 3 supplied the email(s); False when
    only the step-4 placeholder was used.

    Returns (drafts, warnings):
    - drafts: list of {supplier_name, company, emails, matched, rows,
      subject, body} dicts. "emails" is always a non-empty list. Sends
      nothing — sending is a separate, human-triggered step.
    - warnings: human-readable strings, one per vendors-table collision
      (see match_supplier_emails) relevant to this upload.
    """
    uploaded_directory = uploaded_directory or {}
    email_overrides = email_overrides or {}

    df = df.copy()
    df["_company"] = df["PO Number"].apply(resolve_company_name_for_po)

    supplier_names = sorted(df["Supplier Name"].unique())
    db_emails, db_collisions = match_supplier_emails(supplier_names)

    warnings = [
        f"\"{c['normalized']}\" matches more than one differently-spelled "
        f"supplier name in the vendor database ({', '.join(c['names'])}) — "
        f"resolve this in Manage Suppliers, then re-draft to match automatically."
        for c in db_collisions
    ]

    group_keys = (
        df[["Supplier Name", "_company"]]
        .drop_duplicates()
        .sort_values(["Supplier Name", "_company"])
        .itertuples(index=False, name=None)
    )

    drafts = []
    for name, company in group_keys:
        supplier_rows = (
            df[(df["Supplier Name"] == name) & (df["_company"] == company)]
            .drop(columns=["Supplier Name", "_company"])
            .reset_index(drop=True)
        )

        normalized_name = normalize_supplier_name(name)
        directory_emails = uploaded_directory.get(normalized_name)
        db_matched_emails = db_emails.get(name)
        matched = bool(directory_emails) or bool(db_matched_emails)

        override = email_overrides.get(name)
        if override:
            emails = [override] if isinstance(override, str) else list(override)
        elif directory_emails:
            emails = directory_emails
        elif db_matched_emails:
            emails = db_matched_emails
        else:
            emails = [suggest_test_email(name)]

        drafts.append({
            "supplier_name": name,
            "company": company,
            "emails": emails,
            "matched": matched,
            "rows": supplier_rows,
            "subject": _build_subject(),
            "body": _build_body(supplier_rows, company),
        })

    return drafts, warnings
