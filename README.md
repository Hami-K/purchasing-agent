# Purchasing Agent

A Streamlit-based purchasing assistant for hotel/hospitality procurement teams. It drafts and sends RFQ (Request for Quotation) emails, turns pending-delivery Excel exports into per-supplier emails, digitizes photographed supplier price-comparison sheets into a downloadable spreadsheet, and manages your supplier directory — all from one browser UI, backed by a local SQLite database.

> 100% synthetic sample data. Nothing in this repo is tied to any real company, hotel, or supplier — seed data is fictional and email addresses use the `.test` TLD, which never resolves on the real internet.

## Test the app out!!

- **Link** — [purchasing-agent.streamlit.app](https://purchasing-agent.streamlit.app)

## Features

- **Send RFQs** — build a free-text list of products (description / qty / UOM), pick a product category to auto-populate matching suppliers (or add any supplier manually), and draft one RFQ email per supplier. The RFQ number is pre-filled with the next sequential value and editable before drafting, and appears in both the subject and body of every generated email. Review the generated subject/body, then explicitly click **Send All** — nothing is emailed automatically. No LLM involved; it's a fixed template.
- **Pending Market List** — upload a "pending deliveries" Excel export. It's split by supplier, matched against your Manage Suppliers vendor database for emails, and turned into one email per supplier containing only their own rows as an HTML table. You can optionally also upload a separate supplier-database spreadsheet (a name column plus an email column) for this draft only — nothing from it is saved, and matches from it take priority over the vendor database. Matching normalizes formatting differences in supplier names — a trailing "(UAE)" qualifier, punctuation in a legal suffix ("L.L.C" vs "LLC"), and text after a legal suffix are all ignored — while still keeping different entity types distinct (e.g. an "LLC" and an "FZE" with the same base name are never matched as one supplier). All emails on file for a matched supplier are used as recipients, not just one. A supplier with no match anywhere gets a suggested placeholder address and its "include" checkbox starts unchecked, so sending or downloading for it requires deliberately opting in; a matched supplier's checkbox starts checked. For multi-property operations, each supplier's rows are further grouped and labeled by property based on the PO number prefix — see `IS_CLUSTER` under [Environment variables](#environment-variables).
- **Digitize Comparison Sheet** — upload one photographed/scanned quote per supplier (image or PDF). Gemini's vision model reads each one and extracts item rows (packing/brand/origin/price). The extractions are merged into a single side-by-side comparison and offered as a downloadable `.xlsx` — nothing is written to the database.
- **Manage Suppliers** — add a new supplier or update an existing one: name, product categories (a supplier can belong to more than one), payment terms, rating, lead time, and any number of contact emails. No delete, by design.

Both **Send RFQs** and **Pending Market List** also let you download the reviewed drafts as email files instead of (or in addition to) sending: select which ones — individually or with **Select All** — then generate `.msg` (opens directly in desktop Outlook) or `.eml` (opens in any mail client — Outlook, Thunderbird, Apple Mail, Gmail import). Downloaded files always show the real recipient, independent of TEST_MODE, so you can review exactly what would be sent, send it yourself, or keep it as a record. `.msg` needs Windows with desktop (classic) Outlook installed — the button is hidden automatically if unavailable; `.eml` always works.

All outgoing-email features share one safety rail: **TEST_MODE**. While it's on (the default), every email is redirected to your own inbox instead of a real supplier address, with `[TEST MODE]` marked in the subject — see [Environment variables](#environment-variables).

## Tech stack

- [Streamlit](https://streamlit.io/) — the UI, single-page app with a bottom navigation bar
- [SQLite](https://www.sqlite.org/) — local database, no server to run
- [LangChain](https://python.langchain.com/) + [Gemini](https://ai.google.dev/) (`gemini-3.6-flash`) — vision-based extraction for the comparison-sheet feature (the only place an LLM is used)
- [openpyxl](https://openpyxl.readthedocs.io/) — reading uploaded Excel files and building the downloadable comparison workbook
- [pandas](https://pandas.pydata.org/) — tabular data handling for the uploaded/previewed tables
- `smtplib` + `python-dotenv` (Python standard library / lightweight helper) — sending email via Gmail SMTP and loading `.env`
- `email` (standard library) — building `.eml` downloads
- [pywin32](https://github.com/mhammond/pywin32) — Windows-only, drives desktop Outlook via COM automation for `.msg` downloads; skipped entirely on install elsewhere (see `requirements.txt`'s platform marker)

## Getting started

### Prerequisites

- Python 3.10+
- A [Google AI Studio](https://aistudio.google.com/) API key (for the comparison-sheet vision feature)
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords) (only needed once you're ready to actually send email — you can explore the whole app with TEST_MODE on and no Gmail credentials at all, except the "Send All" buttons themselves)

### Installation

```bash
git clone <this-repo-url>
cd purchasing-agent
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configure environment variables

```bash
cp .env.example .env
```

Then fill in `.env` — see the [Environment variables](#environment-variables) table below. At minimum, set `GOOGLE_API_KEY` to explore the Digitize Comparison Sheet feature; the RFQ/Pending Market List features work without it.

### Build the database

```bash
python data/seed.py
```

This creates `data/purchasing.db` from `data/schema.sql` plus a small set of synthetic seed vendors. Safe to re-run any time — it drops and rebuilds the file from scratch. The seeded vendors have placeholder data only; add your real suppliers via the **Manage Suppliers** tab once the app is running.

### Run the app

```bash
streamlit run src/app.py
```

If `streamlit` isn't on your PATH, run it as a module instead: `python -m streamlit run src/app.py`.

## Environment variables

Every setting below is read the same explicit way (`src/config.py`): `.streamlit/secrets.toml` first, then `.env` as a fallback (see `.env.example` for the full template with inline comments).

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GOOGLE_API_KEY` | For the comparison-sheet feature | — | Gemini API key used for vision-based extraction |
| `TEST_MODE` | No | `true` | Safety switch. Anything other than the exact string `false` keeps it on. While on, every outgoing email is redirected to `DEV_EMAIL` regardless of the real supplier address, and marked `[TEST MODE]` in the subject |
| `DEV_EMAIL` | While `TEST_MODE=true` | — | Your own inbox; every email lands here while testing |
| `GMAIL_ADDRESS` | To send any email | — | The Gmail account emails are sent *from* |
| `GMAIL_APP_PASSWORD` | To send any email | — | A Gmail [App Password](https://myaccount.google.com/apppasswords) — never your real account password |
| `COMPANY_NAME` | No | — | Your hotel/company name. RFQ emails always use this. Pending Market List uses it too, unless `IS_CLUSTER` is on. When set, outgoing emails add a line like "We are reaching out from [your company name]." When unset, that line is simply omitted |
| `IS_CLUSTER` | No | `false` | Enables per-property name resolution for Pending Market List, for multi-property operations. When `true`, each row's PO number prefix is matched against the `CLUSTER_N_CODE` values below to choose that property's name; a PO number matching no configured code falls back to `COMPANY_NAME` |
| `CLUSTER_1_CODE` / `CLUSTER_1_NAME`, `CLUSTER_2_CODE` / `CLUSTER_2_NAME`, ... | While `IS_CLUSTER=true` | — | Each pair maps a PO number's first 2 characters (case-insensitive) to a property name. Add more numbered pairs for additional properties |
| `ADMIN_PASSWORD` | To use any of the four gated actions | — | A single shared password — see [Access control](#access-control) below |

**Before your first real send:** confirm `TEST_MODE` is unset or `true` and `DEV_EMAIL` is your own address. Only set `TEST_MODE=false` once you're deliberately ready to email real suppliers.

## Access control

Browsing and viewing every tab requires no login at all. Four specific actions are gated behind a single shared password, set via `ADMIN_PASSWORD`:

- **Send All** in Send RFQs
- **Send All** in Pending Market List
- **Extract** in Digitize Comparison Sheet
- Creating or updating a supplier in Manage Suppliers

The first time any of these is used in a browser session, the app prompts for `ADMIN_PASSWORD` inline. A correct entry unlocks all four actions for the rest of that session — it isn't asked again per click. Drafting, previewing, and downloading `.msg`/`.eml` files are never gated.

This is a single shared password, not a per-user account system — there's no username, and everyone who has the password has the same access. It's checked in this order: `.streamlit/secrets.toml` first (this works for local development too, not just Streamlit Cloud), then `.env` as a fallback.

## Project structure

```
purchasing-agent/
├── data/
│   ├── schema.sql              # database schema (source of truth)
│   ├── seed.py                 # rebuilds data/purchasing.db from schema.sql + synthetic vendors
│   └── purchasing.db           # generated — not committed, see .gitignore
├── src/
│   ├── app.py                  # the whole Streamlit UI (bottom nav + all 4 pages)
│   ├── config.py               # get_setting() — single source of truth for every config value
│   ├── auth.py                 # require_admin() — the shared-password gate on 4 specific actions
│   ├── db_init.py              # ensure_db_initialized() — self-heals data/purchasing.db if missing
│   ├── vendor_admin.py         # add/update supplier backend
│   ├── comparison_sheet.py     # merges per-supplier extractions, builds the downloadable .xlsx
│   ├── email_utils.py          # SMTP sending + the TEST_MODE safety rail (single choke point)
│   ├── email_export.py         # builds downloadable .msg/.eml files — never sends anything
│   └── nodes/
│       ├── draft_rfq.py                # builds RFQ email drafts (template only, no LLM)
│       ├── draft_pending_market_list.py # parses the pending-deliveries Excel + builds per-supplier drafts
│       └── extract_quote.py            # sends an image/PDF to Gemini vision, returns structured JSON
├── requirements.txt
├── .env.example
└── .gitignore
```

## Database schema

Four tables, all in `data/schema.sql`:

- **`vendors`** — one row per supplier. `category` and `email` are legacy single-value columns — both fully vestigial at this point, nothing reads either anymore (kept only because `category` is `NOT NULL` and `seed.py` still populates both). Real current category/email data lives in the two tables below.
- **`vendor_categories`** — many-to-many: a supplier can belong to more than one product category. Drives the RFQ tab's category dropdown.
- **`vendor_emails`** — one-to-many: a supplier can have more than one contact email. Every email on file for a supplier is used as a recipient, both for RFQs and for Pending Market List matches.
- **`rfq_log`** — one row per "Draft RFQ" click, logged for audit history regardless of whether the RFQ number used was this row's sequential `RFQ-0001`-style suggestion or a manually entered one. Products are logged as JSON (they're free text, never matched against an items catalog).

## Notes / known limitations

- **Storage is local SQLite, not guaranteed to persist.** `data/purchasing.db` is generated (via `data/seed.py`), gitignored, and auto-built on first run if missing — including automatically on a fresh Streamlit Cloud deployment, so a missing file never crashes the app. But Streamlit Community Cloud does not guarantee local file storage survives a redeploy or a wake-from-sleep restart, so any supplier added via **Manage Suppliers** (or any other write) could be lost the next time the app restarts. The app shows a caption about this in the UI itself. See also [Future work](#future-work) — this and the lack of authentication both stem from the same underlying gap: this isn't yet a durable multi-user deployment.
- The Digitize Comparison Sheet feature extracts item rows only — a document's totals block (if present) is deliberately ignored, since vision extraction of that section proved unreliable. Nothing from that feature is persisted to the database; it's a pure upload → preview → download flow.
- `.msg` download requires *classic* (desktop) Outlook, driven via COM automation — Microsoft's newer "New Outlook" app has no automation API at all, so `.msg` generation only works if classic Outlook is installed and reachable, even on a machine where New Outlook is the one actually signed in and used day to day. `.eml` has no such requirement and always works.
- The very first `.msg` generation in a session may trigger a Windows security prompt ("a program is trying to access Outlook") that needs a manual click — later generations in the same session are fast.

## Future work

Both items below stem from the same underlying gap: this app isn't yet a durable, multi-user deployment.

- Multi-user authentication — a single shared admin password currently gates 
  Manage Suppliers, both "Send All" actions, and AI extraction (see 
  [Access control](#access-control)). There's no per-user identity, so any 
  action taken while unlocked can't be attributed to a specific person. 
  A future version could give each user their own login and log who 
  performed each gated action, not just that it happened.
- Durable storage — data lives in a local SQLite file (see 
  [Notes / known limitations](#notes--known-limitations)), which Streamlit 
  Community Cloud doesn't guarantee survives a redeploy or wake-from-sleep 
  restart. A future version could move to a hosted database (e.g. Postgres) 
  so supplier data and RFQ history persist reliably regardless of where 
  it's deployed — a deliberate, separate decision, not a quick swap.
