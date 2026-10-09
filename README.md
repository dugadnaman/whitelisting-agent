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
   - **RCS destination safety**: Account labels and bot IDs come from the effective backend configuration, including overrides. Spreadsheet RCS submission keeps the selected account (no automatic re-routing) and rejects a submission if its bot changed since preview; an account without a verified bot cannot be submitted from the UI.
   - **SMS**: End-to-end DLT template compliance, AES-256 CBC PII encryption (`sms_crypto.py`), and real-time DLR forwarding callbacks.
   - **Dashboard resilience**: When Karix's WhatsApp inventory is unavailable,
     the dashboard keeps tenant-scoped local submission history visible and marks
     the provider connection as degraded. An unavailable local history is reported
     as an error rather than shown as an empty template catalog.

3. **Phase 3 — Operational Work Management & Sync**:
   - Bi-directional Jira integration for campaign briefs, attachment parsing, and task handoffs.
   - Mixed Wealth briefs can submit WhatsApp to `tcl_promo` and RCS to `wealth` in one request. The confirmation shows both destinations; the backend authorizes each account and rejects a changed RCS bot before either channel is submitted.
   - Jira Briefs CTA previews support WhatsApp API buttons with `text` and legacy fallback buttons with `label`/`text`. Both shapes are type-checked by the production frontend build.
   - Jira Briefs has **Add template content** in WhatsApp, RCS, and SMS panels, including empty channels. Use it to separate two messages incorrectly parsed into one template, then edit the original. New drafts have unique names, open in edit mode, and remain unchecked for whitelisting. Changes are local to the loaded brief until WhatsApp/RCS submission; reloading reparses Jira and discards unsent edits. SMS remains review/edit-only.
   - Jira Briefs counts Push / App only when the parsed brief identifies a Push campaign (`channel_counts.push`). MoEngage staging metadata may exist for SMS or Email tickets and does not imply a Push campaign; Push title/body are empty when no Push campaign was identified.
   - Jira brief-status filters (including the chat prompt "Show pending Jira briefs") scan successive Jira search pages until the requested number of matching briefs is found or Jira has no more pages. Results remain newest-first; unfiltered listings use a single page.
   - MoEngage attribute resolver and automated template catalog sync.
   - **Tata Click Counts** (`/tata/click-count`): choose an authorized MoEngage workspace and up to 10 imported bases. The UI loads each base's automatic start date, accepts one inclusive end date valid for every selected base, and starts the selected queries simultaneously. Each base keeps an independent result because the same user may belong to multiple bases; counts are never summed. Every result counts unique users matching **WhatsApp OR Email OR SMS OR Android push OR iOS push clicks, AND that base's membership**. Users are deduplicated across channels within each base; reachable users remain a separate metric. Workspace/base/date changes clear stale results. The date limit refreshes at workspace midnight, and double-clicking cannot submit a second batch.
   - Click counts use Tata's portal session, not the public MoEngage API workspace IDs. In Tata **Settings → MoEngage**, supply the Bearer token, `refreshtoken` request header, and session cookies from the logged-in dashboard, or configure the `TATA_MOENGAGE_*` variables in `.env.example`. Workspace switching uses request-local credentials and never saves a different workspace's tokens. Expired sessions require manual credential replacement. Counting adds one MoEngage query-history entry per selected base; it does not save a segment, export users, or send a campaign. Bajaj and Apparel users cannot access these endpoints.
   - Imported-base creation dates come from `cs_details`; MoEngage may omit `cs_meta` when no cached base-count metadata exists. Naive creation timestamps are UTC before conversion to the workspace calendar date. Query bounds preserve the portal's literal `00:00:00.000Z`–`23:59:59.999Z` calendar-date convention rather than converting them to UTC instants. Signed query tickets expire after 24 hours and bind the workspace and its `/getLoggedInUserData` database identity, with Tata account validation on status checks. Metadata errors are distinct from session-expiry errors.
   - Click-count recovery is independent per selected base: one success or provider failure does not hide the other results. Load failures and empty lists offer reload controls. Each status request is serialized per query while queries poll concurrently; network failures, HTTP 408/429 and 5xx continue polling, while malformed responses and other 4xx pause only the affected query. MoEngage's `received` state becomes `queued` without exposing stale counts; terminal `failure` and `failed` statuses both become `failed`, and no count is invented or credential expiry assumed. **Stop checking** aborts local polling for that base but does not cancel its MoEngage query; **Check status again** resumes GET-only polling without another submission. A timed-out, disconnected, 5xx or malformed-success query-start response is never automatically retried and must be acknowledged before another batch can start.
   - SLA kickoff/checkpoint/escalation alerts omit due-today tickets in **Base Pending** or **Content Pending**: these are client-side dependencies, not operator-owned pending work. They are excluded from Google Chat mentions/counts and operator emails until the status changes; if no operator-owned work remains, no Chat webhook is sent. The alert dispatcher does not change Jira assignees.
   - Google Chat SLA webhooks are skipped on Saturdays and Sundays in IST, including manual `force` dispatches. The work-management preview marks Chat as paused and disables Chat-only live dispatch; direct email and dry-run previews remain available. Dispatch summaries distinguish skipped Chat alerts from posted or simulated ones.


4. **Phase 4 — Apparel Multi-Channel Attribution Reporting**:
   - Dedicated `/apparel/attribution` portal under the Apparel account scope.
   - Multi-channel support (WhatsApp, SMS, RCS) with campaign date-range filtering, preview validation, and warnings.
   - Integrates with an isolated worker service deployed on Railway with dedicated persistent MoEngage Chromium browser.
   - Browser attribution waits for the current MoEngage page's `load` event before opening a saved Behavior report. Navigating at `DOMContentLoaded` can interrupt dashboard startup and leave the report stuck in its navigation shell, even when the workspace label is visible.
   - Strict tenant isolation: Karix users from Tata or Bajaj cannot access Apparel attribution; authentication is fail-closed.
   - Login offers Bajaj Finserv, Tata Capital, and Apparel, with automatic organization selection retained as the default. An explicit choice must match the authenticated user's organization (or platform-superadmin access); mismatches clear the returned token and stay on login. Apparel sign-ins open `/apparel/attribution` directly. Accounts still require administrator provisioning; the selector does not grant permissions.
   - Overwrite protection (off by default) ensures existing completed attribution figures are never overwritten unintentionally.
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

### Apparel on a local Windows laptop — no Docker

Install [Git](https://git-scm.com/downloads/win), [Python 3.12](https://www.python.org/downloads/windows/), [Node.js 22+](https://nodejs.org/en/download), and [Google Chrome](https://www.google.com/chrome/) once. Open **PowerShell normally, not as administrator**, and run:

```powershell
git clone https://github.com/dugadnaman/whitelisting-agent.git
cd whitelisting-agent
py -3.12 scripts/apparel_local.py setup
py -3.12 scripts/apparel_local.py start
```

Setup installs both Python dependency sets and the frontend, creates private local secrets, and asks for the first Apparel administrator's name, email and password. Password entry is hidden. Do not copy someone else's `.env`, browser profile or Bajaj/Tata credentials. The launcher must be committed and pushed before another laptop can clone it.

Start opens the portal in a **separate Apparel Chrome window** and runs the API, worker and frontend in one terminal. It uses installed Chrome; it does not download Chromium or require Docker/WSL. Keep the terminal open; **Ctrl+C** stops only this launcher's services and preserves its accounts, Google key and browser profile.

One-time administrator steps in the portal:

1. Sign in using the account created during setup; select **Apparel**.
2. Upload the authorized Google service-account JSON key in **Admin setup**. Share the approved sheet with that service account as an editor, then click **Connect approved sheet**. Report mappings and `Mastersheet` are already bundled.
3. Click **Start login**, complete corporate MoEngage sign-in/MFA in the dedicated window, then refresh status.
4. Create marketing accounts in **Settings → Organization Team Directory → Add Colleague**, using **Operator**. Operators do not see Admin setup.

For later use:

```powershell
cd ~/whitelisting-agent
py -3.12 scripts/apparel_local.py start
```

Local state lives under `%LOCALAPPDATA%/Karix/Apparel/<checkout-id>`; secrets remain in the checkout's private `.env`. Use a local filesystem supporting Windows ACLs, such as NTFS, not FAT/exFAT. This is a per-device setup, not a public hosted service. Do not process the same shared-sheet rows from multiple laptops simultaneously. Browser sessions may require renewed human login.

Verification: isolated native startup, hidden-password onboarding, SSO start and real operator UI exercised on macOS. Windows ACLs, `msvcrt` locking and Windows process-job handling still require execution on Windows.

### 1. Environment Configuration

Copy the example environment configuration:
```bash
cp .env.example .env
```
Fill in the credentials for your tenant (`BAJAJ_*` or `TATA_*`). Non-secret defaults allow local development out of the box with SQLite.
When a workflow uses file-backed credentials, load `.env` before creating queue
records so all queue writes and result updates use the same active database
backend. The application handles this for autonomous remediation flows.

### Production authentication on Render

Configure these service environment variables before deploying:

- `DATABASE_URL`: a persistent PostgreSQL connection URL, such as a dedicated Neon database with TLS enabled. SQLite files on Render Free are ephemeral and do not preserve accounts across redeploys.
- `JWT_SECRET`: a strong, private signing key generated once (for example, `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`). Keep it stable across redeploys; changing it invalidates existing sessions.

Database initialization creates the schema, not a default login. Provision accounts through the administrator flow, or restore existing user records from a trusted backup while preserving their IDs, password hashes, tenant assignments, roles, and active status. Do not enable public signup or bypass password verification to recover access.

Verification must include a real login after redeployment and confirmation that its `last_login` update reaches PostgreSQL. Persistent application authentication does not refresh MoEngage portal sessions; expired Tata bearer/refresh tokens and cookies still require manual reconnection in **Settings → MoEngage**.

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
