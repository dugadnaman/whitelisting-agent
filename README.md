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

3. **Phase 3 — Operational Work Management & Sync**:
   - Bi-directional Jira integration for campaign briefs, attachment parsing, and task handoffs.
   - MoEngage attribute resolver and automated template catalog sync.

---

## 📁 Repository Directory Structure

```
karix/
├── api.py                     # FastAPI core backend service and routing endpoints
├── auth.py                    # Multi-tenant authentication, RBAC, and JWT tokens
├── db.py                      # Database models (SQLite / PostgreSQL dual adapter)
├── db_queue.py                # Persistent task queue implementation
├── queue_manager.py           # Background queue workers, retry logic, rate governor
├── work_manager.py            # Jira workflow dispatcher & operational balancer
├── activity_tracker.py        # Audit logging engine
├── error_tracker.py           # Real-time error telemetry and classification
│
├── config.py                  # WhatsApp Karix configuration & credential loaders
├── models.py                  # WhatsApp template data models
├── loader.py                  # WhatsApp CSV/Excel/dynamic spreadsheet parser
├── submission_client.py       # WhatsApp Karix API HTTP client & media upload
├── tracker.py                 # WhatsApp JSONL submission logging
├── runner.py                  # WhatsApp CLI batch runner
├── template_identifier.py     # WhatsApp Phase 1 catalog diffing engine
├── template_validator.py      # Meta WhatsApp pre-submission compliance validator
│
├── rcs_config.py              # RCS carrier endpoints and account configuration
├── rcs_models.py              # RCS Rich Card and Carousel dataclasses
├── rcs_loader.py              # RCS spreadsheet ingestion parser
├── rcs_client.py              # RCS Karix API client
├── rcs_runner.py              # RCS CLI runner
├── rcs_tracker.py             # RCS submission log manager
│
├── sms_config.py              # SMS endpoints, DLT entity IDs, and headers
├── sms_models.py              # SMS message and DLR models
├── sms_loader.py              # SMS batch message loader
├── sms_client.py              # SMS submission API client
├── sms_crypto.py              # AES-256-CBC PII encryption engine (Karix spec)
├── sms_runner.py              # SMS batch delivery CLI runner
├── sms_tracker.py             # SMS delivery outcome tracker
│
├── jira_client.py             # Atlassian Jira Cloud REST API client
├── jira_extractor.py          # Jira ticket content & document extractor
├── briefing_parser.py         # DOCX/Excel campaign briefing document parser
├── moengage_ops_client.py     # MoEngage campaign operations client
├── moengage_resolver.py       # MoEngage parameter mapping engine
├── moengage_sync.py           # MoEngage template synchronization engine
├── gemini_intelligence.py     # Gemini AI brief extraction & category classification
│
├── frontend/                  # Next.js 14 Web Application (Tailwind CSS, React 18)
│   ├── app/                   # App Router pages (Submit, Work Mgmt, Briefs, Settings)
│   ├── components/            # Reusable UI components (AppShell, Nav, ChatWidget)
│   └── lib/                   # API client, Auth Context, Formatters
│
├── samples/                   # Standard sample template spreadsheets
│   ├── templates_sample.csv   # WhatsApp sample template catalog
│   ├── rcs_templates_sample.csv # RCS sample Rich Card & Carousel templates
│   └── sms_sample.csv         # SMS sample DLT messages
│
├── docs/                      # Technical documentation & vendor carrier guides
│   ├── vendor/                # Karix, DLT, RCS, and SMS official PDF & docx specifications
│   ├── frontend.md            # Frontend application design & route specs
│   └── karpathy-guidelines.md # Engineering guidelines
│
├── media_cache/               # Local cache for sample headers (PNG, MP4, PDF)
├── scripts/                   # Utility scripts (e.g. SQLite to PostgreSQL migration)
├── tests/                     # 25+ automated Pytest test suites
├── Dockerfile                 # Multi-stage production container (FastAPI + Next.js)
└── docker-compose.yml         # Local and production container orchestration
```

---

## 🚀 Getting Started

### 1. Environment Configuration

Copy the example environment configuration:
```bash
cp .env.example .env
```
Fill in the credentials for your tenant (`BAJAJ_*` or `TATA_*`). Non-secret defaults allow local development out of the box with SQLite.

### 2. Local Development

**Python Backend (FastAPI):**
```bash
# Setup virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start backend on http://localhost:8000
python3 -m uvicorn api:app --reload --port 8000
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
