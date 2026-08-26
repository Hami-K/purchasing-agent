"""
A single shared "owner password" gate for a handful of admin-style
actions — NOT a user-account system, and NOT a login gate on the app
itself. Browsing/viewing every tab always stays fully open with no
prompt; only the specific actions that send real email, spend an LLM
call, or change the supplier directory call require_admin() first (see
src/app.py for exactly which ones).
"""

import streamlit as st

from src.config import get_setting


def require_admin(action_label: str) -> bool:
    """
    Call this immediately before a gated action runs, and skip the action
    if it returns False.

    Prompts for the shared admin password once per browser session
    (tracked via st.session_state) — after one correct entry, this and
    every other gated action return True immediately for the rest of the
    session, with no further prompting.

    Renders its own small inline password prompt when locked, so callers
    don't need any UI of their own beyond checking the return value. If
    ADMIN_PASSWORD isn't configured anywhere, shows a clear error and
    denies access rather than silently letting the action through.
    """
    if st.session_state.get("_admin_unlocked"):
        return True

    correct_password = get_setting("ADMIN_PASSWORD")
    if not correct_password:
        st.error(
            "ADMIN_PASSWORD not configured — set it in .streamlit/secrets.toml "
            "or .env for local development, or in Streamlit Cloud's app "
            "secrets when deployed."
        )
        return False

    slug = "".join(c if c.isalnum() else "_" for c in action_label.strip().lower())
    st.info(f"Admin password required to {action_label}.")
    entered = st.text_input(
        f"Enter admin password to {action_label}",
        type="password",
        key=f"_admin_pw_input_{slug}",
    )
    if st.button("Unlock", key=f"_admin_unlock_btn_{slug}"):
        if entered == correct_password:
            st.session_state["_admin_unlocked"] = True
            return True
        st.error("Incorrect password.")
        return False

    return False
