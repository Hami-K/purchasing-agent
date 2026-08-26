-- Synthetic purchasing-agent schema.
-- NOT tied to any real employer system — all names, prices, and vendors are fictional.

PRAGMA foreign_keys = ON;

-- Vendor master list. `email` here is a legacy single-value field still
-- used by the Pending Market List feature's auto-match. `category` is
-- fully vestigial — nothing reads it anymore, kept only because it's
-- NOT NULL and seed.py still populates it. vendor_categories and
-- vendor_emails below are the real, current source of truth for a
-- vendor's categories/emails, since a vendor can have more than one of each.
CREATE TABLE vendors (
    vendor_id       TEXT PRIMARY KEY,      -- e.g. 'V-101'
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,         -- vestigial, unused — see note above
    payment_terms   TEXT,                  -- e.g. 'Net 30'
    rating          REAL,                  -- 1.0 - 5.0, synthetic reliability score
    lead_time_days  INTEGER,
    email           TEXT                   -- legacy single email, kept for Pending Market List
);

-- A vendor can sell more than one product category — this is what the RFQ
-- category dropdown actually queries (not vendors.category above).
CREATE TABLE vendor_categories (
    vendor_id  TEXT NOT NULL REFERENCES vendors(vendor_id),
    category   TEXT NOT NULL,
    PRIMARY KEY (vendor_id, category)
);

-- A vendor can have more than one contact email — RFQs are sent "To" every
-- email on file for that vendor.
CREATE TABLE vendor_emails (
    email_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id  TEXT NOT NULL REFERENCES vendors(vendor_id),
    email      TEXT NOT NULL
);

-- One row per "Draft RFQs" click — assigns a sequential RFQ number
-- (formatted "RFQ-0001") shared by every vendor emailed in that batch, so
-- quote replies referencing the number can be correlated back to one
-- request. Products are free text (never looked up against an item
-- catalog), so they're logged as JSON rather than an item_id/quantity pair.
CREATE TABLE rfq_log (
    rfq_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    products    TEXT NOT NULL,   -- JSON list of {description, qty, uom}
    vendor_ids  TEXT NOT NULL,   -- comma-separated vendor_id list requested in this RFQ
    created_at  TEXT NOT NULL
);
