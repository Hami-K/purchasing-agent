"""
Generates a fresh purchasing.db from schema.sql + synthetic data below.
100% synthetic — vendor names/categories are inspired by generic hospitality
purchasing workflows, not any real employer's data or systems.

Run:
    python data/seed.py
"""

import sqlite3
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "purchasing.db")
SCHEMA_PATH = os.path.join(HERE, "schema.sql")


def build_db():
    # Always start fresh — this script should be safe to re-run anytime.
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    with open(SCHEMA_PATH, "r") as f:
        cur.executescript(f.read())

    # --- Vendors -------------------------------------------------------
    # Emails are 100% synthetic placeholders on a fictional "quotewell.test"
    # domain — deliberately not a real company's domain, and ".test" is the
    # IANA-reserved TLD for exactly this purpose (never resolves on the
    # real internet). Only used as the RFQ send target, and only ever
    # actually reached when TEST_MODE=false.
    vendors = [
        ("V-101", "Gulf Linen Supplies",        "Housekeeping",    "Net 30", 4.5, 5,  "sales@gulflinen.quotewell.test"),
        ("V-102", "Emirates F&B Distributors",   "Food & Beverage", "Net 15", 4.2, 3,  "orders@emiratesfnb.quotewell.test"),
        ("V-103", "Al Futtaim Office Supplies",  "Operations",      "Net 45", 4.0, 4,  "quotes@alfuttaimoffice.quotewell.test"),
        ("V-104", "Desert Rose Amenities",       "Housekeeping",    "Net 30", 3.8, 6,  "sales@desertroseamenities.quotewell.test"),
        ("V-105", "Prime Kitchen Equipment",     "Food & Beverage", "Net 60", 4.6, 10, "quotes@primekitchen.quotewell.test"),
        ("V-106", "Sahara Textile Co.",          "Housekeeping",    "Net 30", 4.1, 7,  "sales@saharatextile.quotewell.test"),
        ("V-107", "Royal Grocers Wholesale",     "Food & Beverage", "Net 30", 4.4, 2,  "orders@royalgrocers.quotewell.test"),
        ("V-108", "TechDesk IT Supplies",        "Operations",      "Net 15", 4.3, 3,  "sales@techdesk.quotewell.test"),
    ]
    cur.executemany(
        "INSERT INTO vendors (vendor_id, name, category, payment_terms, rating, lead_time_days, email) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        vendors,
    )

    # vendor_categories / vendor_emails are the real source of truth the
    # app reads (a vendor can have more than one of each) — seed each
    # vendor's single legacy category/email above as their first entry.
    for vendor_id, _name, category, _terms, _rating, _lead, email in vendors:
        cur.execute("INSERT INTO vendor_categories (vendor_id, category) VALUES (?, ?)", (vendor_id, category))
        cur.execute("INSERT INTO vendor_emails (vendor_id, email) VALUES (?, ?)", (vendor_id, email))

    conn.commit()
    conn.close()
    print(f"Built {DB_PATH}")


def sanity_check():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("\n--- vendors ---")
    for row in cur.execute("SELECT vendor_id, name, category, rating FROM vendors"):
        print(row)

    print("\n--- vendor categories ---")
    for row in cur.execute("SELECT vendor_id, category FROM vendor_categories ORDER BY vendor_id"):
        print(row)

    print("\n--- vendor emails ---")
    for row in cur.execute("SELECT vendor_id, email FROM vendor_emails ORDER BY vendor_id"):
        print(row)

    conn.close()


if __name__ == "__main__":
    build_db()
    sanity_check()
