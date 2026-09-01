"""
Shared admin-password gate for a fixed set of actions: sending real
email, running AI extraction, and creating/updating a supplier (see
src/app.py for the exact call sites). Not a user-account system and not a
login gate on the app itself — browsing and viewing every tab requires no
password.
"""

import streamlit as st

from src.config import get_setting


def require_admin(action_label: str) -> bool:
    """
    Returns True if the gated action may proceed, False otherwise. Call
    immediately before the action runs and skip it when this returns False.

    Prompts for the admin password once per browser session (tracked in
    st.session_state); after one correct entry, every gated action
    returns True for the rest of the session with no further prompting.

    Renders its own inline password prompt when locked — no separate UI
    is needed at the call site beyond checking the return value. If
    ADMIN_PASSWORD isn't configured, shows an error and returns False.
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
