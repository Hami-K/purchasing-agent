"""
Backend for the "Manage Suppliers" UI: add a new supplier, or update an
existing one. No delete — by design, only add and update are exposed.
"""

import re
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "purchasing.db")


def list_vendors():
    """[(vendor_id, name), ...] ordered by name — for the "edit existing" picker."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT vendor_id, name FROM vendors ORDER BY name")
    rows = cur.fetchall()
    conn.close()
    return rows


def list_categories():
    """Distinct categories already in use, for autocomplete-by-example in the UI."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT category FROM vendor_categories ORDER BY category")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def list_vendors_by_category(category: str):
    """[(vendor_id, name), ...] of vendors linked to this product category
    (via vendor_categories — a vendor can be in more than one), for the
    RFQ tab's default vendor selection."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT v.vendor_id, v.name FROM vendors v
        JOIN vendor_categories vc ON v.vendor_id = vc.vendor_id
        WHERE vc.category = ?
        ORDER BY v.name
        """,
        (category,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_vendor(vendor_id: str) -> dict:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT vendor_id, name, payment_terms, rating, lead_time_days FROM vendors WHERE vendor_id = ?",
        (vendor_id,),
    )
    row = cur.fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"No vendor found with id {vendor_id}")

    cur.execute("SELECT category FROM vendor_categories WHERE vendor_id = ? ORDER BY category", (vendor_id,))
    categories = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT email FROM vendor_emails WHERE vendor_id = ? ORDER BY email_id", (vendor_id,))
    emails = [r[0] for r in cur.fetchall()]

    conn.close()
    return {
        "vendor_id": row[0],
        "name": row[1],
        "payment_terms": row[2],
        "rating": row[3],
        "lead_time_days": row[4],
        "categories": categories,
        "emails": emails,
    }


def _next_vendor_id(cur) -> str:
    cur.execute("SELECT vendor_id FROM vendors")
    max_n = 0
    for (vendor_id,) in cur.fetchall():
        m = re.fullmatch(r"V-(\d+)", vendor_id)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"V-{max_n + 1:03d}"


def create_vendor(name: str, categories: list, payment_terms: str, rating, lead_time_days, emails: list) -> str:
    """
    Inserts a new vendor plus its categories and emails. The legacy
    vendors.category/email columns (kept only for Pending Market List) are
    left blank/null — vendor_categories/vendor_emails are this vendor's
    real data going forward.

    Returns the newly assigned vendor_id.
    """
    name = name.strip()
    if not name:
        raise ValueError("Supplier name is required.")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    vendor_id = _next_vendor_id(cur)
    cur.execute(
        """
        INSERT INTO vendors (vendor_id, name, category, payment_terms, rating, lead_time_days, email)
        VALUES (?, ?, '', ?, ?, ?, NULL)
        """,
        (vendor_id, name, payment_terms or None, rating, lead_time_days),
    )

    for category in categories:
        category = category.strip()
        if category:
            cur.execute(
                "INSERT INTO vendor_categories (vendor_id, category) VALUES (?, ?)",
                (vendor_id, category),
            )

    for email in emails:
        email = email.strip()
        if email:
            cur.execute(
                "INSERT INTO vendor_emails (vendor_id, email) VALUES (?, ?)",
                (vendor_id, email),
            )

    conn.commit()
    conn.close()
    return vendor_id


def update_vendor(vendor_id: str, name: str, categories: list, payment_terms: str, rating, lead_time_days, emails: list):
    """
    Updates a vendor's core fields, and replaces its categories/emails
    entirely with the given lists (delete-then-reinsert — simplest correct
    behavior for a low-frequency admin edit, not a high-churn table).
    """
    name = name.strip()
    if not name:
        raise ValueError("Supplier name is required.")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM vendors WHERE vendor_id = ?", (vendor_id,))
    if cur.fetchone() is None:
        conn.close()
        raise ValueError(f"No vendor found with id {vendor_id}")

    cur.execute(
        """
        UPDATE vendors SET name = ?, payment_terms = ?, rating = ?, lead_time_days = ?
        WHERE vendor_id = ?
        """,
        (name, payment_terms or None, rating, lead_time_days, vendor_id),
    )

    cur.execute("DELETE FROM vendor_categories WHERE vendor_id = ?", (vendor_id,))
    for category in categories:
        category = category.strip()
        if category:
            cur.execute(
                "INSERT INTO vendor_categories (vendor_id, category) VALUES (?, ?)",
                (vendor_id, category),
            )

    cur.execute("DELETE FROM vendor_emails WHERE vendor_id = ?", (vendor_id,))
    for email in emails:
        email = email.strip()
        if email:
            cur.execute(
                "INSERT INTO vendor_emails (vendor_id, email) VALUES (?, ?)",
                (vendor_id, email),
            )

    conn.commit()
    conn.close()
