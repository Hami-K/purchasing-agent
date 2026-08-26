import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.nodes.draft_rfq import draft_rfq, peek_next_rfq_number
from src.nodes.draft_pending_market_list import parse_market_list, draft_pending_market_list
from src.nodes.extract_quote import extract_quote
from src.comparison_sheet import merge_extractions, build_comparison_excel
from src.email_utils import send_email, is_test_mode
from src.email_export import (
    is_msg_supported_platform, build_eml_bytes, build_msg_bytes, build_zip, safe_filename,
)
from src.vendor_admin import (
    list_vendors as list_all_vendors,
    list_categories as list_product_categories,
    list_vendors_by_category,
    get_vendor,
    create_vendor,
    update_vendor,
)
from src.auth import require_admin
from src.db_init import ensure_db_initialized

# Must run before any tab below queries the database — builds
# data/purchasing.db from schema.sql + seed data if it's missing (e.g. a
# fresh Streamlit Cloud container). See src/db_init.py for why this has to
# self-heal on every fresh start, not just once.
ensure_db_initialized()

st.set_page_config(page_title="Purchasing Agent", layout="wide")
st.title("Purchasing Agent")
st.caption(
    "⚠️ This deployment stores data locally (SQLite) — Streamlit Community "
    "Cloud does not guarantee local storage survives a redeploy or a "
    "wake-from-sleep restart. Suppliers added via Manage Suppliers could be "
    "lost on a future restart."
)

# CSS only (no visible markup here, so no layout gap from this) — pins the
# nav bar (rendered at the very end of the script, see bottom of file) to
# the viewport bottom, and reserves matching space under the page content
# so the fixed bar never covers anything. Defined once, up top, since it
# has to apply regardless of where in the DOM the styled elements land.
st.markdown(
    """
    <style>
    .main .block-container {
        padding-bottom: 84px;
    }
    div[class*="st-key-bottom_nav"] {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        z-index: 999;
        display: flex !important;
        flex-direction: row !important;
        justify-content: center;
        align-items: center;
        background-color: #ffffff;
        border-top: 1px solid rgba(128, 128, 128, 0.35);
        padding: 10px 16px;
        box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.08);
    }
    /* Streamlit's own default themes are #ffffff (light) / #0e1117 (dark) —
       match whichever one the browser/OS reports, same as the rest of the
       app already does. A custom Streamlit theme beyond these two defaults
       won't be auto-matched here. */
    @media (prefers-color-scheme: dark) {
        div[class*="st-key-bottom_nav"] {
            background-color: #0e1117;
            border-top-color: rgba(250, 250, 250, 0.2);
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

NAV_PAGES = [
    ("rfq", "Send RFQs"),
    ("market_list", "Pending Market List"),
    ("comparison", "Digitize Comparison Sheet"),
    ("vendors", "Manage Suppliers"),
]
_label_by_id = dict(NAV_PAGES)
_id_by_label = {label: page_id for page_id, label in NAV_PAGES}

if "active_page" not in st.session_state:
    st.session_state.active_page = NAV_PAGES[0][0]

# The nav widget itself is instantiated at the bottom of this file (so it
# paints there, and so nothing about it adds height above the page
# content) — but its value, keyed as "nav_segmented", is already resolved
# in session_state by the time the script starts running each rerun, so
# reading it here to decide what to render is safe. st.segmented_control
# allows deselecting by clicking the active segment again (value becomes
# None) — when that happens, keep showing whatever page was last active
# rather than snapping back to the first tab.
_selected_label = st.session_state.get("nav_segmented")
if _selected_label is not None:
    st.session_state.active_page = _id_by_label.get(_selected_label, st.session_state.active_page)
active_page = st.session_state.active_page

# =====================================================================
# Tab 1: Send RFQs — free-text product list (never matched against the
# items catalog), a supplier picker seeded by product category, draft via
# plain code (no LLM), review, then explicitly send. Sending always
# requires the separate "Send All" click and goes through
# email_utils.send_email(), which enforces the TEST_MODE redirect.
# =====================================================================
if active_page == "rfq":
    if is_test_mode():
        st.info(
            "TEST_MODE is ON — every email sent below will actually go to "
            "DEV_EMAIL instead of the supplier's real address(es), marked "
            "'[TEST MODE]' in the subject. Set TEST_MODE=false in .env to "
            "send to real supplier addresses."
        )
    else:
        st.warning(
            "TEST_MODE is OFF — emails sent below go to suppliers' real "
            "addresses. Double-check the drafts before clicking Send All."
        )

    if "rfq_products" not in st.session_state:
        st.session_state.rfq_products = [{"description": "", "qty": 1, "uom": ""}]
    if "rfq_result" not in st.session_state:
        st.session_state.rfq_result = None
    if "rfq_send_results" not in st.session_state:
        st.session_state.rfq_send_results = None

    st.markdown("**Draft RFQ**")
    st.caption("Enter product details")

    header_cols = st.columns([6, 1, 1, 1])
    header_cols[0].markdown("**Product Description**")
    header_cols[1].markdown("**Qty**")
    header_cols[2].markdown("**UOM**")

    for idx, product in enumerate(st.session_state.rfq_products):
        row_cols = st.columns([6, 1, 1, 1])
        product["description"] = row_cols[0].text_input(
            "Product Description", value=product["description"], key=f"rfq_prod_desc_{idx}",
            label_visibility="collapsed", placeholder="e.g. Bread Flour T55 50KG",
        )
        product["qty"] = row_cols[1].number_input(
            "Qty", min_value=1, value=product["qty"] or 1, step=1,
            key=f"rfq_prod_qty_{idx}", label_visibility="collapsed",
        )
        product["uom"] = row_cols[2].text_input(
            "UOM", value=product["uom"], key=f"rfq_prod_uom_{idx}",
            label_visibility="collapsed", placeholder="e.g. KG",
        )
        if len(st.session_state.rfq_products) > 1:
            if row_cols[3].button("✕", key=f"rfq_prod_remove_{idx}"):
                st.session_state.rfq_products.pop(idx)
                st.rerun()

    if st.button("+", key="rfq_add_product"):
        st.session_state.rfq_products.append({"description": "", "qty": 1, "uom": ""})
        st.rerun()

    st.divider()

    all_vendors = list_all_vendors()
    vendor_label_map = {f"{name} ({vendor_id})": vendor_id for vendor_id, name in all_vendors}

    categories = list_product_categories()
    if categories:
        category = st.selectbox("Product category", categories, key="rfq_category")
    else:
        category = None
        st.caption("No product categories yet — add suppliers with categories in the Manage Suppliers tab.")

    default_vendor_ids = {vid for vid, _name in list_vendors_by_category(category)} if category else set()
    default_labels = [label for label, vid in vendor_label_map.items() if vid in default_vendor_ids]

    if st.session_state.get("rfq_last_category") != category:
        st.session_state.rfq_last_category = category
        st.session_state["rfq_vendor_select"] = default_labels

    selected_labels = st.multiselect(
        "Suppliers to request quotes from (defaults to suppliers in the chosen "
        "category — add more from any category as needed)",
        list(vendor_label_map.keys()),
        key="rfq_vendor_select",
    )
    selected_vendor_ids = [vendor_label_map[label] for label in selected_labels]

    # A widget's session_state key can't be reassigned in the same run once
    # the widget's already been instantiated — so "advance to the next
    # suggested number after drafting" goes through this pending flag,
    # applied here (before the widget exists this run) rather than
    # directly in the button handler below (after it already exists).
    if st.session_state.get("_rfq_number_advance"):
        st.session_state.rfq_number_input = st.session_state._rfq_number_advance
        st.session_state._rfq_number_advance = None
    elif "rfq_number_input" not in st.session_state:
        st.session_state.rfq_number_input = peek_next_rfq_number()
    rfq_number_input = st.text_input(
        "RFQ Number", key="rfq_number_input",
        help="Pre-filled with the next sequential number — edit it if you use your own numbering.",
    )

    if st.button("Draft RFQ", type="primary"):
        products = [
            {"description": p["description"].strip(), "qty": p["qty"], "uom": p["uom"].strip()}
            for p in st.session_state.rfq_products
            if p["description"].strip()
        ]
        if not products:
            st.error("Enter at least one product description.")
        elif not selected_vendor_ids:
            st.error("Select at least one supplier.")
        elif not rfq_number_input.strip():
            st.error("Enter an RFQ number.")
        else:
            with st.spinner("Drafting RFQ..."):
                st.session_state.rfq_result = draft_rfq(
                    products, selected_vendor_ids, rfq_number=rfq_number_input.strip()
                )
            for idx in range(len(st.session_state.rfq_result["drafts"])):
                st.session_state[f"rfq_dl_select_{idx}"] = True
            st.session_state.rfq_select_all = True
            st.session_state["_rfq_select_all_prev"] = True
            st.session_state._rfq_number_advance = peek_next_rfq_number()
            st.session_state.rfq_send_results = None
            st.session_state.rfq_dl_msg_zip = None
            st.session_state.rfq_dl_eml_zip = None
            st.rerun()

    result = st.session_state.rfq_result
    if result:
        st.markdown(f"**{result['rfq_number']} — {len(result['drafts'])} draft(s) — review before sending:**")

        if "rfq_select_all" not in st.session_state:
            st.session_state.rfq_select_all = True
        select_all = st.checkbox("Select All (for download)", key="rfq_select_all")
        if st.session_state.get("_rfq_select_all_prev") != select_all:
            st.session_state["_rfq_select_all_prev"] = select_all
            for idx in range(len(result["drafts"])):
                st.session_state[f"rfq_dl_select_{idx}"] = select_all
            st.rerun()

        for idx, draft in enumerate(result["drafts"]):
            with st.expander(draft["vendor_name"], expanded=True):
                if not draft["emails"]:
                    st.warning("No email on file for this supplier — enter one below before sending.")
                emails_input = st.text_input(
                    "Recipient email(s), comma-separated",
                    value=", ".join(draft["emails"]),
                    key=f"rfq_emails_{idx}",
                )
                draft["_emails_input"] = emails_input
                draft["subject"] = st.text_input("Subject", value=draft["subject"], key=f"rfq_subject_{idx}")
                st.caption("Body preview")
                components.html(draft["body"], height=150 + 40 * draft["body"].count("<tr>"), scrolling=True)
                draft["_download_selected"] = st.checkbox(
                    "Include in download", key=f"rfq_dl_select_{idx}"
                )

        if st.button("Send All", type="primary"):
            st.session_state["_rfq_sendall_pending"] = True

        if st.session_state.get("_rfq_sendall_pending") and require_admin("send real emails"):
            st.session_state["_rfq_sendall_pending"] = False
            missing = [d["vendor_name"] for d in result["drafts"] if not d.get("_emails_input", "").strip()]
            if missing:
                st.error(f"Missing recipient email for: {', '.join(missing)}")
            else:
                results = []
                with st.spinner("Sending..."):
                    for draft in result["drafts"]:
                        emails = [e.strip() for e in draft["_emails_input"].split(",") if e.strip()]
                        try:
                            r = send_email(emails, draft["subject"], draft["body"], is_html=True)
                            r["vendor_name"] = draft["vendor_name"]
                            r["rfq_number"] = result["rfq_number"]
                            r["status"] = "sent"
                        except Exception as e:
                            r = {
                                "vendor_name": draft["vendor_name"],
                                "rfq_number": result["rfq_number"],
                                "intended_recipient": draft["_emails_input"],
                                "actual_recipient": None,
                                "test_mode": is_test_mode(),
                                "status": "failed",
                                "error": str(e),
                            }
                        results.append(r)

                st.session_state.rfq_send_results = results
                st.session_state.rfq_result = None
                st.session_state.rfq_dl_msg_zip = None
                st.session_state.rfq_dl_eml_zip = None
                st.session_state.rfq_products = [{"description": "", "qty": 1, "uom": ""}]
                st.rerun()

        st.divider()
        st.markdown("**Download as email files**")
        st.caption(
            "Select suppliers above, then download as .msg (Outlook) or .eml (opens in any "
            "mail client) — a file you can send yourself, or keep as a record. These always "
            "show the real recipient, regardless of TEST_MODE, since nothing is sent from here."
        )

        selected_for_download = [d for d in result["drafts"] if d.get("_download_selected")]

        col_msg, col_eml = st.columns(2)
        with col_msg:
            if is_msg_supported_platform():
                if st.button("Generate .msg", key="rfq_dl_msg_btn", disabled=not selected_for_download):
                    with st.spinner("Generating via Outlook — the first time, check your taskbar "
                                     "for a Windows security prompt to allow it..."):
                        try:
                            files = [
                                (f"{result['rfq_number']}_{safe_filename(d['vendor_name'])}.msg",
                                 build_msg_bytes(
                                     [e.strip() for e in d["_emails_input"].split(",") if e.strip()],
                                     d["subject"], d["body"], is_html=True,
                                 ))
                                for d in selected_for_download
                            ]
                            st.session_state.rfq_dl_msg_zip = build_zip(files)
                            st.session_state.rfq_dl_msg_name = f"{result['rfq_number']}_msg.zip"
                        except RuntimeError as e:
                            st.error(str(e))
                if st.session_state.get("rfq_dl_msg_zip"):
                    st.download_button(
                        "Download .msg (.zip)", data=st.session_state.rfq_dl_msg_zip,
                        file_name=st.session_state.rfq_dl_msg_name, mime="application/zip",
                        key="rfq_dl_msg_dlbtn",
                    )
            else:
                st.caption("_.msg unavailable — requires Windows with Outlook installed._")
        with col_eml:
            if st.button("Generate .eml", key="rfq_dl_eml_btn", disabled=not selected_for_download):
                files = [
                    (f"{result['rfq_number']}_{safe_filename(d['vendor_name'])}.eml",
                     build_eml_bytes(
                         [e.strip() for e in d["_emails_input"].split(",") if e.strip()],
                         d["subject"], d["body"], is_html=True,
                     ))
                    for d in selected_for_download
                ]
                st.session_state.rfq_dl_eml_zip = build_zip(files)
                st.session_state.rfq_dl_eml_name = f"{result['rfq_number']}_eml.zip"
            if st.session_state.get("rfq_dl_eml_zip"):
                st.download_button(
                    "Download .eml (.zip)", data=st.session_state.rfq_dl_eml_zip,
                    file_name=st.session_state.rfq_dl_eml_name, mime="application/zip",
                    key="rfq_dl_eml_dlbtn",
                )

    if st.session_state.rfq_send_results:
        st.markdown("**Send results**")
        st.dataframe(pd.DataFrame(st.session_state.rfq_send_results), width='stretch', hide_index=True)

# =====================================================================
# Tab 2: Pending Market List — upload a pending-deliveries Excel export,
# split it by supplier, cross-check each supplier against the vendors
# table for an email, and draft one email per supplier (a fixed template
# with only that supplier's rows as an HTML table — no LLM). Review, fill
# in any missing emails, then explicitly send.
# =====================================================================
elif active_page == "market_list":
    st.markdown(
        "Upload a pending market list Excel file (delivery date, supplier name, "
        "item description, qty, uom, PO number columns). Each supplier gets one "
        "email containing only their own rows — nothing is sent until you click "
        "**Send All**."
    )

    if is_test_mode():
        st.info(
            "TEST_MODE is ON — every email sent below will actually go to "
            "DEV_EMAIL instead of the supplier's real address, marked "
            "'[TEST MODE]' in the subject."
        )
    else:
        st.warning(
            "TEST_MODE is OFF — emails sent below go to suppliers' real "
            "addresses. Double-check the drafts before clicking Send All."
        )

    if "ml_drafts" not in st.session_state:
        st.session_state.ml_drafts = None
    if "ml_send_results" not in st.session_state:
        st.session_state.ml_send_results = None

    uploaded_file = st.file_uploader("Pending market list (.xlsx)", type=["xlsx", "xls"], key="ml_uploader")

    if st.button("Create Draft", disabled=uploaded_file is None):
        try:
            with st.spinner("Parsing file and cross-checking supplier emails..."):
                df = parse_market_list(uploaded_file)
                if df.empty:
                    st.error("No valid rows found in the uploaded file.")
                else:
                    st.session_state.ml_drafts = draft_pending_market_list(df)
                    st.session_state.ml_send_results = None
                    st.session_state.ml_dl_msg_zip = None
                    st.session_state.ml_dl_eml_zip = None
                    for idx in range(len(st.session_state.ml_drafts)):
                        st.session_state[f"ml_dl_select_{idx}"] = True
                    st.session_state.ml_select_all = True
                    st.session_state["_ml_select_all_prev"] = True
                    st.rerun()
        except ValueError as e:
            st.error(str(e))

    drafts = st.session_state.ml_drafts
    if drafts:
        n_unmatched = sum(1 for d in drafts if not d["matched"])
        st.markdown(f"**{len(drafts)} supplier(s) — {len(drafts) - n_unmatched} matched in the vendor "
                    f"database, {n_unmatched} need an email confirmed below.**")

        if "ml_select_all" not in st.session_state:
            st.session_state.ml_select_all = True
        select_all = st.checkbox("Select All (for download)", key="ml_select_all")
        if st.session_state.get("_ml_select_all_prev") != select_all:
            st.session_state["_ml_select_all_prev"] = select_all
            for idx in range(len(drafts)):
                st.session_state[f"ml_dl_select_{idx}"] = select_all
            st.rerun()

        for idx, draft in enumerate(drafts):
            label = draft["supplier_name"]
            if draft.get("company"):
                label += f" — {draft['company']}"
            label += f" — {len(draft['rows'])} item(s)"
            with st.expander(label, expanded=not draft["matched"]):
                if draft["matched"]:
                    st.caption("Email matched from the vendor database.")
                else:
                    st.warning("No matching vendor found in the database — using a suggested test "
                               "address below. Edit it if you have the supplier's real email.")
                draft["email"] = st.text_input("Recipient email", value=draft["email"], key=f"ml_email_{idx}")
                st.dataframe(draft["rows"], width='stretch', hide_index=True)
                st.caption(f"Subject: {draft['subject']}")
                components.html(draft["body"], height=80 + 45 * (len(draft["rows"]) + 1), scrolling=True)
                draft["_download_selected"] = st.checkbox("Include in download", key=f"ml_dl_select_{idx}")

        if st.button("Send All", type="primary", key="ml_send_all"):
            st.session_state["_ml_sendall_pending"] = True

        if st.session_state.get("_ml_sendall_pending") and require_admin("send real emails"):
            st.session_state["_ml_sendall_pending"] = False
            missing = [d["supplier_name"] for d in drafts if not d["email"].strip()]
            if missing:
                st.error(f"Missing email for: {', '.join(missing)}")
            else:
                results = []
                with st.spinner("Sending..."):
                    for draft in drafts:
                        try:
                            result = send_email(draft["email"], draft["subject"], draft["body"], is_html=True)
                            result["supplier_name"] = draft["supplier_name"]
                            result["status"] = "sent"
                        except Exception as e:
                            result = {
                                "supplier_name": draft["supplier_name"],
                                "intended_recipient": draft["email"],
                                "actual_recipient": None,
                                "test_mode": is_test_mode(),
                                "status": "failed",
                                "error": str(e),
                            }
                        results.append(result)

                st.session_state.ml_send_results = results
                st.session_state.ml_drafts = None
                st.session_state.ml_dl_msg_zip = None
                st.session_state.ml_dl_eml_zip = None
                st.rerun()

        st.divider()
        st.markdown("**Download as email files**")
        st.caption(
            "Select suppliers above, then download as .msg (Outlook) or .eml (opens in any "
            "mail client) — a file you can send yourself, or keep as a record. These always "
            "show the real recipient, regardless of TEST_MODE, since nothing is sent from here."
        )

        selected_for_download = [d for d in drafts if d.get("_download_selected")]

        col_msg, col_eml = st.columns(2)
        with col_msg:
            if is_msg_supported_platform():
                if st.button("Generate .msg", key="ml_dl_msg_btn", disabled=not selected_for_download):
                    with st.spinner("Generating via Outlook — the first time, check your taskbar "
                                     "for a Windows security prompt to allow it..."):
                        try:
                            files = [
                                (f"PendingDelivery_{safe_filename(d['supplier_name'])}.msg",
                                 build_msg_bytes(d["email"], d["subject"], d["body"], is_html=True))
                                for d in selected_for_download
                            ]
                            st.session_state.ml_dl_msg_zip = build_zip(files)
                            st.session_state.ml_dl_msg_name = "pending_market_list_msg.zip"
                        except RuntimeError as e:
                            st.error(str(e))
                if st.session_state.get("ml_dl_msg_zip"):
                    st.download_button(
                        "Download .msg (.zip)", data=st.session_state.ml_dl_msg_zip,
                        file_name=st.session_state.ml_dl_msg_name, mime="application/zip",
                        key="ml_dl_msg_dlbtn",
                    )
            else:
                st.caption("_.msg unavailable — requires Windows with Outlook installed._")
        with col_eml:
            if st.button("Generate .eml", key="ml_dl_eml_btn", disabled=not selected_for_download):
                files = [
                    (f"PendingDelivery_{safe_filename(d['supplier_name'])}.eml",
                     build_eml_bytes(d["email"], d["subject"], d["body"], is_html=True))
                    for d in selected_for_download
                ]
                st.session_state.ml_dl_eml_zip = build_zip(files)
                st.session_state.ml_dl_eml_name = "pending_market_list_eml.zip"
            if st.session_state.get("ml_dl_eml_zip"):
                st.download_button(
                    "Download .eml (.zip)", data=st.session_state.ml_dl_eml_zip,
                    file_name=st.session_state.ml_dl_eml_name, mime="application/zip",
                    key="ml_dl_eml_dlbtn",
                )

    if st.session_state.ml_send_results:
        st.markdown("**Send results**")
        st.dataframe(pd.DataFrame(st.session_state.ml_send_results), width='stretch', hide_index=True)

# =====================================================================
# Tab 3: Digitize Comparison Sheet — upload a photographed/scanned
# multi-supplier price comparison sheet (image or PDF), extract structured
# pricing via Gemini vision, review it, then explicitly save to the
# database. Never auto-saves after extraction — always a separate click.
# =====================================================================
elif active_page == "comparison":
    st.markdown(
        "Upload one photographed or scanned quote per supplier (image or "
        "PDF each) — Gemini reads every file, then they're combined into a "
        "single side-by-side comparison. Nothing is saved to the database; "
        "**Extract** produces a preview, and **Download Excel** gives you "
        "the combined comparison sheet as a file."
    )

    if "cmp_merged" not in st.session_state:
        st.session_state.cmp_merged = None
    if "cmp_extract_errors" not in st.session_state:
        st.session_state.cmp_extract_errors = None

    uploaded_files = st.file_uploader(
        "Supplier quote files — one image or PDF per supplier",
        type=["png", "jpg", "jpeg", "webp", "pdf"],
        accept_multiple_files=True,
        key="cmp_uploader",
    )

    if uploaded_files:
        for f in uploaded_files:
            if f.type and f.type.startswith("image/"):
                st.image(f, caption=f.name, width=200)
            else:
                st.caption(f"Uploaded: {f.name}")

    if st.button("Extract", disabled=not uploaded_files):
        st.session_state["_extract_pending"] = True

    if st.session_state.get("_extract_pending") and require_admin("run AI extraction"):
        st.session_state["_extract_pending"] = False
        results = []
        errors = []
        with st.spinner(f"Reading {len(uploaded_files)} file(s) with Gemini vision — this can take a moment..."):
            for f in uploaded_files:
                suffix = os.path.splitext(f.name)[1] or ".png"
                tmp_path = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(f.getvalue())
                        tmp_path = tmp.name
                    results.append(extract_quote(tmp_path))
                except ValueError as e:
                    errors.append(f"{f.name}: {e}")
                finally:
                    if tmp_path and os.path.exists(tmp_path):
                        os.remove(tmp_path)

        st.session_state.cmp_merged = merge_extractions(results) if results else None
        st.session_state.cmp_extract_errors = errors or None

    if st.session_state.cmp_extract_errors:
        for err in st.session_state.cmp_extract_errors:
            st.error(f"Failed to extract {err}")

    merged = st.session_state.cmp_merged
    if merged:
        st.markdown(f"**Combined from {len(uploaded_files or [])} file(s):**")

        item_rows = []
        for item in merged.get("items", []):
            for supplier in item.get("suppliers", []):
                item_rows.append({
                    "Item": item.get("item_description"),
                    "Yearly Consumption": item.get("yearly_consumption"),
                    "Supplier": supplier.get("supplier_name"),
                    "Packing": supplier.get("packing"),
                    "Brand": supplier.get("brand"),
                    "Origin": supplier.get("origin"),
                    "Unit Price": supplier.get("unit_price"),
                    "Old Price": supplier.get("old_price"),
                    "% Change": supplier.get("percent_change"),
                })
        st.markdown("**Item / supplier prices**")
        st.dataframe(pd.DataFrame(item_rows), width='stretch', hide_index=True)

        xlsx_bytes = build_comparison_excel(merged.get("items", []))
        st.download_button(
            "Download Excel",
            data=xlsx_bytes,
            file_name="comparison_sheet.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

# =====================================================================
# Tab 4: Manage Suppliers — the only two things this UI can do to
# vendors.py data: add a brand new supplier, or update an existing one.
# No delete, by design. Categories/emails here are multi-value
# (vendor_categories / vendor_emails) and are what the Send RFQs tab
# actually reads — not the legacy single vendors.category/email columns.
# =====================================================================
elif active_page == "vendors":
    st.markdown(
        "Add a new supplier, or update an existing one. Categories and "
        "emails each accept multiple values — a supplier can be in more "
        "than one product category and have more than one contact email."
    )

    if "vendor_admin_message" not in st.session_state:
        st.session_state.vendor_admin_message = None

    if st.session_state.vendor_admin_message:
        kind, text = st.session_state.vendor_admin_message
        getattr(st, kind)(text)
        st.session_state.vendor_admin_message = None

    action = st.radio("Action", ["Add New Supplier", "Update Existing Supplier"], key="vendor_admin_action")
    existing_categories = list_product_categories()

    if action == "Add New Supplier":
        name = st.text_input("Supplier name", key="va_new_name")
        categories_input = st.text_input(
            "Categories (comma-separated)", key="va_new_categories",
            placeholder="e.g. Food & Beverage, Housekeeping",
        )
        if existing_categories:
            st.caption(f"Existing categories: {', '.join(existing_categories)}")
        payment_terms = st.text_input("Payment terms", key="va_new_payment_terms", placeholder="e.g. Net 30")
        col1, col2 = st.columns(2)
        with col1:
            rating = st.number_input("Rating (optional)", min_value=0.0, max_value=5.0, step=0.1, value=0.0, key="va_new_rating")
        with col2:
            lead_time_days = st.number_input("Lead time (days, optional)", min_value=0, step=1, value=0, key="va_new_lead_time")
        emails_input = st.text_area("Emails (one per line)", key="va_new_emails", height=100)

        if st.button("Create Supplier", type="primary"):
            st.session_state["_vendor_create_pending"] = True

        if st.session_state.get("_vendor_create_pending") and require_admin("edit supplier data"):
            st.session_state["_vendor_create_pending"] = False
            categories = [c.strip() for c in categories_input.split(",") if c.strip()]
            emails = [e.strip() for e in emails_input.splitlines() if e.strip()]
            try:
                new_id = create_vendor(
                    name=name,
                    categories=categories,
                    payment_terms=payment_terms,
                    rating=rating or None,
                    lead_time_days=lead_time_days or None,
                    emails=emails,
                )
                st.session_state.vendor_admin_message = ("success", f"Created supplier {new_id} — {name}.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    else:
        vendors = list_all_vendors()
        if not vendors:
            st.info("No suppliers yet — add one first.")
        else:
            vendor_options = {f"{name} ({vendor_id})": vendor_id for vendor_id, name in vendors}
            selected_label = st.selectbox("Supplier to update", list(vendor_options.keys()), key="va_edit_select")
            vendor_id = vendor_options[selected_label]
            detail = get_vendor(vendor_id)

            name = st.text_input("Supplier name", value=detail["name"], key=f"va_edit_name_{vendor_id}")
            categories_input = st.text_input(
                "Categories (comma-separated)", value=", ".join(detail["categories"]),
                key=f"va_edit_categories_{vendor_id}",
            )
            if existing_categories:
                st.caption(f"Existing categories: {', '.join(existing_categories)}")
            payment_terms = st.text_input(
                "Payment terms", value=detail["payment_terms"] or "", key=f"va_edit_payment_terms_{vendor_id}"
            )
            col1, col2 = st.columns(2)
            with col1:
                rating = st.number_input(
                    "Rating (optional)", min_value=0.0, max_value=5.0, step=0.1,
                    value=float(detail["rating"] or 0.0), key=f"va_edit_rating_{vendor_id}",
                )
            with col2:
                lead_time_days = st.number_input(
                    "Lead time (days, optional)", min_value=0, step=1,
                    value=int(detail["lead_time_days"] or 0), key=f"va_edit_lead_time_{vendor_id}",
                )
            emails_input = st.text_area(
                "Emails (one per line)", value="\n".join(detail["emails"]),
                key=f"va_edit_emails_{vendor_id}", height=100,
            )

            if st.button("Save Changes", type="primary"):
                st.session_state["_vendor_update_pending"] = True

            if st.session_state.get("_vendor_update_pending") and require_admin("edit supplier data"):
                st.session_state["_vendor_update_pending"] = False
                categories = [c.strip() for c in categories_input.split(",") if c.strip()]
                emails = [e.strip() for e in emails_input.splitlines() if e.strip()]
                try:
                    update_vendor(
                        vendor_id, name=name, categories=categories, payment_terms=payment_terms,
                        rating=rating or None, lead_time_days=lead_time_days or None, emails=emails,
                    )
                    st.session_state.vendor_admin_message = ("success", f"Updated supplier {vendor_id} — {name}.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

# =====================================================================
# Bottom navigation — rendered last so nothing about it adds height above
# the page content; CSS (defined at the top of the file) pins it to the
# viewport bottom regardless of where it sits in the DOM. A native
# segmented control gives each label its own auto-sized segment (no
# wrapping, no icons) instead of hand-rolled equal-width buttons.
# =====================================================================
with st.container(key="bottom_nav"):
    st.segmented_control(
        "Navigation",
        options=[label for _, label in NAV_PAGES],
        default=_label_by_id[active_page],
        label_visibility="collapsed",
        key="nav_segmented",
    )
