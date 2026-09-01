"""
Database bootstrap for data/purchasing.db.

data/purchasing.db is gitignored — it's generated data, built from
data/schema.sql plus seed vendors (see data/seed.py), not source. Local
development builds it once via `python data/seed.py`. Streamlit Community
Cloud does not guarantee local file storage survives a redeploy or a
sleep/wake cycle, so a fresh deployment can find no purchasing.db at any
point during the app's lifetime, not only on first install; the first
query against a missing vendors table raises
sqlite3.OperationalError("no such table: vendors").

ensure_db_initialized() rebuilds the database whenever it's missing or
incomplete, reusing data/seed.py's build_db() rather than a separate copy
of the schema/seed logic.

The initialization check is "can the vendors table be queried", not file
presence alone. sqlite3.connect() creates an empty file as a side effect
of the call itself, independent of whether a later query on that
connection succeeds — so a crash against a missing database (e.g. the
"no such table" error above) leaves a stray, schema-less purchasing.db
file behind. A presence-only check treats that stray file as already
initialized and never rebuilds it. Checking for the vendors table
specifically means a present-but-schemaless file is treated the same as a
missing one.
"""

import os
import sqlite3

import streamlit as st

from data.seed import build_db, DB_PATH


def _is_initialized() -> bool:
    if not os.path.exists(DB_PATH):
        return False
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("SELECT 1 FROM vendors LIMIT 1")
            return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False


@st.cache_resource
def ensure_db_initialized() -> None:
    """
    Builds data/purchasing.db (schema + synthetic seed vendors) unless it
    already exists and has a working vendors table.

    Decorated with st.cache_resource, which caches the *result* for the
    life of the running process: the existence/schema check and the build
    it may trigger run once per process, not on every script rerun. A
    fresh process (redeploy, wake-from-sleep) starts with an empty cache,
    so the check runs again there and rebuilds if the file is missing or
    schema-less.
    """
    if not _is_initialized():
        build_db()
