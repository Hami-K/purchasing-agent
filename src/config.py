"""
Central config reader. Every setting in this app is read via
get_setting(): checks .streamlit/secrets.toml (via st.secrets) first,
falls back to os.getenv (populated from .env by python-dotenv).
"""

import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def get_setting(key: str, default=None):
    """
    Checks st.secrets[key] first, then falls back to os.getenv(key, default).
    .streamlit/secrets.toml is read whenever it's present, in local
    development or on Streamlit Cloud. Accessing st.secrets with no
    secrets.toml file present raises in some Streamlit versions — an
    .env-only local setup has no such file, so that case is caught and
    treated as "key not found here", falling through to os.getenv.
    """
    try:
        value = st.secrets.get(key)
        if value:
            return value
    except Exception:
        pass
    return os.getenv(key, default)
