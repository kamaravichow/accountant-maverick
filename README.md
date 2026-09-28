# Accountant Maverick

An agentic workspace for Indian accountants and CA firms. A LangChain agent works inside each client's
organised document store (S3 or local disk) and does the work that eats an accountant's week:

| Where the time goes | What the harness does |
|---|---|
| **Typing 50+ fields per invoice** | Reads digital PDFs, scanned PDFs and phone photos (vision OCR), extracts a Rule 46 GST invoice (GSTINs, POS, IRN, e-way bill, every line with HSN/qty/rate/tax, Udyam no., bank details), validates it, and appends it to the FY register, skipping duplicates. |
| **Scanned PDFs with poor formatting** | Detects pages with no text layer and renders them for a vision model. Unreadable fields are marked `illegible` instead of being guessed. Messy bank/Tally exports are cleaned: header detection, Indian number formats, `Dr/Cr`, wrapped narrations, totals rows, duplicates. |
| **Fixing HSN code mismatches** | HSN/SAC validation (format, digits needed for the AATO, goods vs service), a rate check that knows the **GST 2.0** change of 22-Sep-2025 (5/18/40%), register-wide consistency checks and code suggestions from descriptions. |
| **Multi-layered compliance & reconciliation** | GSTR-2B vs books (exact → fuzzy → same-PAN matching, ITC at risk, IMS actions, RCM, `itcavl`), bank reconciliation with a BRS, 26AS/AIS vs books TDS, 43B(h) MSME payments, TDS section/threshold/rate, and a compliance calendar. |
| **Chasing clients for missing bills** | Finds bank payments with no bill and 2B invoices missing from the books, tracks requests in `_context/requests.json`, and drafts one consolidated email/WhatsApp message per client. Nothing is sent automatically. |
| **Tax arithmetic** | 28 preset formulas based on the law (below). The agent is told never to do tax maths in its head. Each result comes with a step-by-step working and its legal basis. |

Other features:
- **Live web research** through TinyFish Search and Fetch, limited to trusted government and professional sources, for notifications, circulars, rate changes and due-date extensions.
- **Spreadsheets in the browser**. The agent builds workpapers with *real Excel formulas*: openpyxl writes them and the `formulas` engine evaluates them server-side. The accountant opens them in an in-browser Excel-like editor (FortuneSheet + ExcelJS), edits them and saves back to S3.
- **Skills**: 15 India-specific playbooks, loaded on demand (progressive disclosure).

> ⚠️ **Professional-use tool, not advice.** Rates and thresholds come from versioned tables (see
> `backend/app/formulas/rates.py`) that were researched up to Sept 2026. Law changes often, so the agent is instructed to
> verify with live search and flag "CA review" items. It prepares filings but never files them.

---

## Architecture

```
Browser (React + Vite)
 ├─ File explorer ── drag & drop upload ─┐   presigned PUT for big files ─► S3
 ├─ Viewer: PDF / image / text / Excel editor (FortuneSheet + ExcelJS)
 ├─ Calculators (same formula registry the agent uses)
 └─ Chat (SSE stream: tokens, tool calls, plan/todos)
                │ /api
FastAPI ────────┴──────────────────────────────────────────────────────────
 ├─ Storage: S3 (boto3; AWS / MinIO / R2) or local disk, scoped per company
 ├─ Workspace: companies/<id>/{_context,_inbox,Permanent,FY2025-26/...}
 └─ LangChain `create_agent` (LangGraph)
      middleware: dynamic company prompt · tool-error→model · todo planner ·
                  summarisation · model-call limit
      checkpointer: SQLite (threads persist) or in-memory
      tools (32):
        files     list/search/read(OCR)/write/move/mkdir, company profile, remember→NOTES.md
        documents extract_invoice_data, batch_extract_invoices, classify_inbox
        compliance calculate + list_formulas, validate_ids, check_hsn, audit_hsn_register,
                  clean_table, reconcile_gstr2b, reconcile_bank, reconcile_tds_26as,
                  find_missing_bills
        workbench read_spreadsheet, write_spreadsheet_table, set_spreadsheet_cells (evaluated),
                  web_search / web_fetch (TinyFish), document-request tracker, load_skill
```

### Company folder layout (the agent's context)

Every client gets the same structure. The agent learns it from its system prompt and files documents into it:

```
_context/company.json     PAN, GSTINs, state, regime, GST filing type, books software, contacts
_context/NOTES.md         long-term client memory (agent appends via `remember`)
_context/requests.json    documents requested from the client
_context/skills/*.md      optional firm/client-specific playbooks (override built-ins)
_inbox/                   unsorted uploads → agent classifies, renames, files
Permanent/                KYC, registrations, deeds, agreements
FY2025-26/01_Sales/…  02_Purchases/…  03_Banking/…  04_GST/{GSTR-1,GSTR-2B,GSTR-3B,GSTR-9_9C,Notices}
          05_TDS_TCS/…  06_Payroll  07_Income_Tax/…  08_Books_Ledgers  09_Fixed_Assets
          10_ROC_MCA  11_Correspondence  12_Workpapers
```

## Preset formulas (`backend/app/formulas`)

All maths uses `Decimal` with Indian rounding rules (288A/288B, Rule 119A). Every result has `steps`.

| Area | Formulas |
|---|---|
| Income tax | individual/HUF (old & new regime, FY 2024-25 → 2026-27, special-rate CG, 87A rebate + marginal relief, surcharge + marginal relief, cess), regime comparison, firm/LLP/company incl. 115BAA/115BAB + MAT, 234A/234B/234C, advance-tax schedule, capital gains (holding period, grandfathering, 50C, post-23-Jul-2024 rates, indexation option with CII), 44AD/44ADA, 43B(h) + MSMED interest |
| TDS | section/threshold/rate incl. 206AA and 194Q excess logic, 201(1A) interest (TRACES calendar-month rule), 234E fee, 40(a)(ia) |
| GST | IGST vs CGST/SGST by place of supply + back-calculation, sec 50 interest, GSTR-3B/1/9/4 late fees with caps, 16(4) ITC time limit, Rule 37 reversal, HSN digits / e-invoice applicability |
| Depreciation | IT Act WDV blocks (180-day rule, additional depreciation, sec 50), Companies Act Schedule II SLM/WDV |
| Payroll | EPF/EPS/EDLI/admin, ESI, gratuity + 10(10), HRA 10(13A), labour-code "wages" (50% rule) |
| Compliance | statutory due-date calendar (GST, TDS, PF/ESI, advance tax, ITR, audit, ROC, MSME-1) |

The Income-tax Act 2025 is in force from 1-Apr-2026. The prompt and skills cite both section numbers
(for example 194J ↔ 393).

## Skills (`backend/skills/*/SKILL.md`)

`invoice-data-entry`, `inbox-organizer`, `gst-2b-reconciliation`, `hsn-correction`, `bank-reconciliation`,
`data-cleaning`, `missing-documents-chase`, `tds-compliance`, `income-tax-computation`, `advance-tax-interest`,
`gst-return-preparation`, `msme-43bh`, `tax-audit-3cd`, `notice-response`, `month-end-close`.

To add a skill, create a folder with a `SKILL.md` (front-matter `name` and `description`, then the playbook). To make
one for a single client, put `<name>.md` in that client's `_context/skills/`.

---

## Running it

### Local development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements-dev.txt
cp .env.example backend/.env         # set ANTHROPIC_API_KEY (or another provider) and TINYFISH_API_KEY
cd backend && uvicorn app.main:app --reload --port 8000

# in another shell
cd frontend && npm install && npm run dev    # http://localhost:5173 (proxies /api to :8000)
```

Run `npm run build` to write the UI into `backend/app/static`, so FastAPI serves everything on :8000.

### Docker (app + MinIO as S3)

```bash
cp .env.example .env    # fill in the API keys
docker compose up --build
# app: http://localhost:8000   MinIO console: http://localhost:9001
```

### Production on AWS

- Build the `Dockerfile` image and run it on ECS Fargate, App Runner or any container host. Set
  `STORAGE_BACKEND=s3`, `S3_BUCKET`, `S3_REGION=ap-south-1` and give the task an IAM role with
  `s3:GetObject/PutObject/DeleteObject/ListBucket` on the bucket.
- Set `APP_TOKEN` (or put the app behind your SSO proxy). Enable bucket encryption and block public access.
- Large uploads go straight from the browser to S3 through presigned PUT URLs. The bucket needs a CORS rule
  allowing `PUT` from your app origin.
- Chat threads are stored in SQLite (`CHECKPOINT_DB`) on a persistent volume. With several replicas, switch to
  a shared LangGraph checkpointer such as Postgres.

### Bring your own model (OpenAI-compatible)

Click **⚙ Model** in the top bar and enter a base URL, API key and model. Presets are included for OpenAI,
OpenRouter, Groq, Together, DeepSeek, Ollama and LM Studio. **List models** and **Test connection** check the
endpoint, including that it can make tool calls.

- The settings live only in the browser tab's `sessionStorage`, which is cleared when the tab closes.
- They are sent as `X-LLM-Base-URL` / `X-LLM-API-Key` / `X-LLM-Model` / `X-LLM-Vision-Model` headers, and
  only to the chat and `/api/llm/*` endpoints.
- The server builds a per-request `ChatOpenAI` for the agent and its OCR/extraction tools. It never stores or
  logs the key; tests check that the key doesn't reach the chat database or client files.
- A server-side `LLM_MODEL` is therefore optional. Without one, each user brings their own endpoint.
- The model must support tool/function calling. `localhost` base URLs are resolved on the server, not on the
  user's machine.

### Configuration

| Variable | Purpose |
|---|---|
| `LLM_MODEL` | Any LangChain `init_chat_model` id, e.g. `anthropic:claude-sonnet-5`, `openai:gpt-5` |
| `LLM_VISION_MODEL` | Optional separate model for OCR/extraction of scans |
| `TINYFISH_API_KEY` | Enables `web_search` / `web_fetch` (free tier is rate-limited to about 5 requests/min) |
| `STORAGE_BACKEND`, `S3_*`, `LOCAL_STORAGE_ROOT` | Where client files live |
| `APP_TOKEN` | Bearer token required on `/api/*` |
| `CHECKPOINTER`, `CHECKPOINT_DB` | Chat persistence |

## Tests

```bash
cd backend && python -m pytest -q
```

The 62 tests cover the formula expectations (hand-verified), the GSTIN checksum, the HSN/GST 2.0 rate logic, the
data cleaners, the GSTR-2B, bank, 26AS and missing-bill engines, S3 storage (moto), the TinyFish client (mock
transport), the invoice-extraction pipeline, and a full agent run over SSE with a scripted tool-calling model, and a bring-your-own-model run against a fake
OpenAI-compatible server. No API key is needed.

## Extending

- **Rates change** → add a new FY key in `formulas/rates.py` (never edit past years) and add a test.
- **New formula** → write a function with a pydantic input model and register it in `formulas/__init__.py`. It
  shows up in the agent's `calculate` tool and in the Calculators tab automatically.
- **HSN master** → extend `validators/data/hsn_rates.json`. Only a starter set of common items is included,
  and the agent confirms other codes via live search.

## CI

A GitHub Actions workflow (backend tests plus a frontend type-check and build) is in `docs/ci.yml`. Copy it to
`.github/workflows/ci.yml` to turn it on.
