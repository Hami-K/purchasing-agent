# Purchasing Agent

A Streamlit-based purchasing assistant for hotel/hospitality procurement teams. It drafts and sends RFQ (Request for Quotation) emails, turns pending-delivery Excel exports into per-supplier emails, digitizes photographed supplier price-comparison sheets into a downloadable spreadsheet, and manages your supplier directory — all from one browser UI, backed by a local SQLite database.

> 100% synthetic sample data. Nothing in this repo is tied to any real company, hotel, or supplier — seed data is fictional and email addresses use the `.test` TLD, which never resolves on the real internet.

## Features

- **Send RFQs** — build a free-text list of products (description / qty / UOM), pick a product category to auto-populate matching suppliers (or add any supplier manually), and draft one RFQ email per supplier. Review the generated subject/body, then explicitly click **Send All** — nothing is emailed automatically. No LLM involved; it's a fixed template.
- **Pending Market List** — upload a "pending deliveries" Excel export. It's split by supplier, cross-checked against your supplier directory for an email, and turned into one email per supplier containing only their own rows as an HTML table.
- **Digitize Comparison Sheet** — upload one photographed/scanned quote per supplier (image or PDF). Gemini's vision model reads each one and extracts item rows (packing/brand/origin/price). The extractions are merged into a single side-by-side comparison and offered as a downloadable `.xlsx` — nothing is written to the database.
- **Manage Suppliers** — add a new supplier or update an existing one: name, product categories (a supplier can belong to more than one), payment terms, rating, lead time, and any number of contact emails. No delete, by design.

All outgoing-email features share one safety rail: **TEST_MODE**. While it's on (the default), every email is redirected to your own inbox instead of a real supplier address, with `[TEST MODE]` marked in the subject — see [Environment variables](#environment-variables).

## Tech stack

- [Streamlit](https://streamlit.io/) — the UI, single-page app with a bottom navigation bar
- [SQLite](https://www.sqlite.org/) — local database, no server to run
- [LangChain](https://python.langchain.com/) + [Gemini](https://ai.google.dev/) (`gemini-3.6-flash`) — vision-based extraction for the comparison-sheet feature (the only place an LLM is used)
- [openpyxl](https://openpyxl.readthedocs.io/) — reading uploaded Excel files and building the downloadable comparison workbook
- [pandas](https://pandas.pydata.org/) — tabular data handling for the uploaded/previewed tables
- `smtplib` + `python-dotenv` (Python standard library / lightweight helper) — sending email via Gmail SMTP and loading `.env`

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

All read from `.env` (see `.env.example` for the full template with inline comments).

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GOOGLE_API_KEY` | For the comparison-sheet feature | — | Gemini API key used for vision-based extraction |
| `TEST_MODE` | No | `true` | Safety switch. Anything other than the exact string `false` keeps it on. While on, every outgoing email is redirected to `DEV_EMAIL` regardless of the real supplier address, and marked `[TEST MODE]` in the subject |
| `DEV_EMAIL` | While `TEST_MODE=true` | — | Your own inbox; every email lands here while testing |
| `GMAIL_ADDRESS` | To send any email | — | The Gmail account emails are sent *from* |
| `GMAIL_APP_PASSWORD` | To send any email | — | A Gmail [App Password](https://myaccount.google.com/apppasswords) — never your real account password |
| `COMPANY_NAME` | No | — | Your hotel/company name. When set, outgoing emails add a line like "We are reaching out from [your company name]." When unset, that line is simply omitted |

**Before your first real send:** confirm `TEST_MODE` is unset or `true` and `DEV_EMAIL` is your own address. Only set `TEST_MODE=false` once you're deliberately ready to email real suppliers.

## Project structure

```
purchasing-agent/
├── data/
│   ├── schema.sql              # database schema (source of truth)
│   ├── seed.py                 # rebuilds data/purchasing.db from schema.sql + synthetic vendors
│   └── purchasing.db           # generated — not committed, see .gitignore
├── src/
│   ├── app.py                  # the whole Streamlit UI (bottom nav + all 4 pages)
│   ├── vendor_admin.py         # add/update supplier backend
│   ├── comparison_sheet.py     # merges per-supplier extractions, builds the downloadable .xlsx
│   ├── email_utils.py          # SMTP sending + the TEST_MODE safety rail (single choke point)
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
- **`vendor_emails`** — one-to-many: a supplier can have more than one contact email. Every email on file gets included when an RFQ is sent to that supplier.
- **`rfq_log`** — one row per "Draft RFQ" click, assigning the sequential `RFQ-0001`-style number shared by every supplier in that batch. Products are logged as JSON (they're free text, never matched against an items catalog).

## Notes / known limitations

- The Digitize Comparison Sheet feature extracts item rows only — a document's totals block (if present) is deliberately ignored, since vision extraction of that section proved unreliable. Nothing from that feature is persisted to the database; it's a pure upload → preview → download flow.

## Future work

- Authentication — this is currently a single-user local tool, not a multi-tenant deployment.
- Download a drafted email as a `.msg` file, so it can be sent manually through the user's own mail client, or kept as an offline reference/record without going through the app's own SMTP sending.
