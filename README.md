# Karix Multi-Channel Template Whitelisting & Automation Platform

Automated enterprise messaging template submission, validation, and lifecycle status tracking for **Bajaj** and **Tata Capital**, built on top of the Karix Business Solution Provider (BSP) platform.

Before enterprise messages can be sent via WhatsApp, RCS, or SMS, templates must be registered and approved ("whitelisted") across regulatory registries (DLT) and carrier/meta platforms. This platform automates the end-to-end ingestion, compliance validation, API submission, Jira workflow tracking, and MoEngage synchronization.

---

## 🏛 Multi-Channel Architecture

```
                    ┌───────────────────────────────────────────────┐
                    │            Next.js Web Frontend               │
                    │   (Submit, Briefs, Work Mgmt, Settings, DLR)  │
                    └───────────────────────┬───────────────────────┘
                                            │ HTTP / JSON
                                            ▼
                    ┌───────────────────────────────────────────────┐
                    │               FastAPI Backend                 │
                    │   (Multi-Tenant Auth, Queue, Rate Governors)  │
                    └───┬─────────────┬─────────────┬───────────┬───┘
                        │             │             │           │
          ┌─────────────▼─┐     ┌─────▼───────┐     │           │
          │ WhatsApp      │     │ RCS         │     │           │
          │ (WABA / Meta) │     │ (Google/Jio)│     │           │
          └───────────────┘     └─────────────┘     │           │
                        ┌───────────────────────────▼─┐         │
                        │ SMS & DLT                   │         │
                        │ (AES-256 PII, DLR Callbacks)│         │
                        └─────────────────────────────┘         │
                        ┌───────────────────────────────────────▼─┐
                        │ Integrations & Intelligence             │
                        │ (Jira Briefs, MoEngage Sync, Gemini AI) │
                        └─────────────────────────────────────────┘
```

1. **Phase 1 — Identification & Semantic Diffing**:
   - Compares master template catalogs (CSV, Excel, JSON) against live WABA/Karix inventories (`/getAllTemplates`).
   - Classifies templates into *Approved*, *Missing*, *Content Drift*, *Pending*, or *Rejected*.
   - Uses semantic equivalence and fuzzy normalization to detect variable drift.

2. **Phase 2 — Multi-Channel Submission & Tracking**:
   - **WhatsApp**: Submits via Karix Portal API or Official WABA API with parameter checking and aspect-ratio validation.
   - **RCS**: Submits Rich Cards and Carousels (Google RCS / Jio) with compliant aspect ratio and button validation.
   - **SMS**: End-to-end DLT template compliance, AES-256 CBC PII encryption (`sms_crypto.py`), and real-time DLR forwarding callbacks.
   - **Dashboard resilience**: When Karix's WhatsApp inventory is unavailable,
     the dashboard keeps tenant-scoped local submission history visible and marks
     the provider connection as degraded. An unavailable local history is reported
     as an error rather than shown as an empty template catalog.

3. **Phase 3 — Operational Work Management & Sync**:
   - Bi-directional Jira integration for campaign briefs, attachment parsing, and task handoffs.
   - Jira Briefs counts Push / App only when the parsed brief identifies a Push campaign (`channel_counts.push`). MoEngage staging metadata may exist for SMS or Email tickets and does not imply a Push campaign; Push title/body are empty when no Push campaign was identified.
   - Jira brief-status filters (including the chat prompt "Show pending Jira briefs") scan successive Jira search pages until the requested number of matching briefs is found or Jira has no more pages. Results remain newest-first; unfiltered listings use a single page.
   - MoEngage attribute resolver and automated template catalog sync.
   - SLA kickoff/checkpoint/escalation alerts omit due-today tickets in **Base Pending** or **Content Pending**: these are client-side dependencies, not operator-owned pending work. They are excluded from Google Chat mentions/counts and operator emails until the status changes; if no operator-owned work remains, no Chat webhook is sent. The alert dispatcher does not change Jira assignees.

---

## 📁 Repository Directory Structure

```
karix/
├── backend/                   # FastAPI Python backend service and multi-channel modules
│   ├── api.py                 # Core FastAPI REST routes and lifecycle handlers
│   ├── auth.py                # Multi-tenant authentication, RBAC, and JWT tokens
│   ├── db.py                  # Dual SQLite / PostgreSQL database adapters
│   ├── db_queue.py            # Persistent SQLite / PostgreSQL ingestion queue engine
│   ├── queue_manager.py       # Background worker and rate governor
│   ├── work_manager.py        # Jira workflow dispatcher & task balancer
│   │
│   ├── config.py              # WhatsApp Karix configuration & credential loaders
│   ├── models.py              # WhatsApp dataclasses & schemas
│   ├── loader.py              # WhatsApp CSV & dynamic spreadsheet parser
│   ├── submission_client.py   # WhatsApp Karix API HTTP client & media upload
│   ├── runner.py              # WhatsApp CLI runner
│   │
│   ├── rcs_config.py          # RCS carrier endpoints and account configuration
│   ├── rcs_models.py          # RCS Rich Card and Carousel models
│   ├── rcs_client.py          # RCS Karix API client
│   ├── rcs_loader.py          # RCS spreadsheet parser
│   │
│   ├── sms_config.py          # SMS DLT entity configuration
│   ├── sms_client.py          # SMS submission API client
│   ├── sms_crypto.py          # AES-256-CBC PII encryption engine
│   │
│   ├── jira_client.py         # Jira Cloud REST client
│   ├── moengage_sync.py       # MoEngage catalog sync engine
│   └── gemini_intelligence.py # Gemini AI extractor and validator
│
├── frontend/                  # Next.js 14 App Router Web Application
│   ├── app/                   # App Router pages (Submit, Work Mgmt, Briefs, Settings)
│   ├── components/            # Reusable UI components (AppShell, Nav, ChatWidget)
│   └── lib/                   # API client, Auth Context, Formatters
│
├── data/                      # Local persistent SQLite databases (karix_store.db)
├── docs/                      # Documentation and official carrier PDF/docx specifications
├── samples/                   # Sample template catalogs, spreadsheets, and test data
├── scripts/                   # Migration & administration scripts
├── tests/                     # 25+ automated Pytest test suites
├── media_cache/               # Local cache for sample headers (PNG, MP4, PDF)
├── Dockerfile                 # Multi-stage production container (FastAPI + Next.js)
└── docker-compose.yml         # Container orchestration
```

---

## 🚀 Getting Started

### 1. Environment Configuration

Copy the example environment configuration:
```bash
cp .env.example .env
```
Fill in the credentials for your tenant (`BAJAJ_*` or `TATA_*`). Non-secret defaults allow local development out of the box with SQLite.
When a workflow uses file-backed credentials, load `.env` before creating queue
records so all queue writes and result updates use the same active database
backend. The application handles this for autonomous remediation flows.

### 2. Local Development

**Python Backend (FastAPI):**
```bash
# Setup virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start backend on http://localhost:8000
python3 -m uvicorn api:app --app-dir backend --reload --port 8000
```

**Frontend (Next.js):**
```bash
cd frontend
npm install
npm run dev
# Accessible on http://localhost:3000
```

### 3. Docker Deployment

Run both FastAPI and Next.js under Docker:
```bash
docker-compose up --build
```
- Web Application: `http://localhost:3000`
- API Health Endpoint: `http://localhost:8000/healthz`

---

## 🧪 Testing & Security Verification

Run all unit and integration test suites:
```bash
pytest tests/ -v
```

Run SAST security scans:
```bash
# Bandit security audit
bandit -r . -x ./.venv,./tests,./frontend,./media_cache,./scratch -s B101,B110,B112

# Semgrep code analysis
semgrep scan --config auto --exclude "tests" --exclude "frontend" --exclude ".venv"

# Code formatting and linting
ruff check . && ruff format --check .
```
