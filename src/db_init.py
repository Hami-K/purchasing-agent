"""
Self-healing database bootstrap for fresh containers.

data/purchasing.db is gitignored on purpose — it's generated data, not
source (see data/seed.py). That's fine for local development, where you run
`python data/seed.py` once. It's not fine as the whole story on Streamlit
Community Cloud: a fresh deployment has no purchasing.db at all, so the very
first query ("SELECT ... FROM vendors") would crash with
"OperationalError: no such table: vendors".

Worse, Streamlit Cloud does NOT guarantee local file storage survives —
files can be wiped on a redeploy or when the app sleeps and wakes from
inactivity. So this can't be a one-time fix; it has to re-heal every time
the file is found missing, not just on first install. ensure_db_initialized()
does exactly that, and reuses data/seed.py's own build_db() rather than
duplicating its schema/seed logic here.
"""

import os

import streamlit as st

from data.seed import build_db, DB_PATH


@st.cache_resource
def ensure_db_initialized() -> None:
    """
    Builds data/purchasing.db (schema + synthetic seed vendors) if it
    doesn't already exist. Safe to call on every script run — st.cache_resource
    caches the *result* for the life of the running process, so the actual
    existence check + build only really happens once per fresh container
    start, not on every page interaction. If the container later restarts
    fresh (redeploy, wake-from-sleep) this cache resets too, so the check
    naturally runs again and re-heals if the file is gone again.
    """
    if not os.path.exists(DB_PATH):
        build_db()
