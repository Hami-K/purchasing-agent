"""
Single, explicit source of truth for reading configuration values —
checks .streamlit/secrets.toml (via st.secrets) first, falls back to
os.getenv (loaded from .env via python-dotenv) for local dev. This is the
same pattern src/auth.py's require_admin() already used for
ADMIN_PASSWORD, generalized here so every setting in this app goes
through one explicit place instead of relying on Streamlit Cloud's
implicit "secrets are also exposed as environment variables" behavior.
"""

import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def get_setting(key: str, default=None):
    """
    Checks st.secrets[key] first (this works for local development too,
    not just Streamlit Cloud — .streamlit/secrets.toml is read whenever
    it exists, wherever the app is running), then falls back to
    os.getenv(key, default). Wrapped defensively: accessing st.secrets
    when no secrets.toml exists at all raises in some Streamlit versions,
    and that's a normal, expected state for an .env-only local setup.
    """
    try:
        value = st.secrets.get(key)
        if value:
            return value
    except Exception:
        pass
    return os.getenv(key, default)
