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
   - Jira WhatsApp/RCS drafts use the same pre-submission inspection as Excel uploads: image dimensions/ratios, grammar, compliance and duplicate warnings are visible before whitelisting. Copy, CTA, channel and creative changes trigger fresh validation; unavailable validation or invalid media cannot be bypassed by submitting stale browser flags. Carousel images are checked individually.
   - Jira Briefs RCS carousels have per-card whitelisting checkboxes, initially checked. Unchecked cards remain available for editing but are excluded from validation and submission; selected cards keep their original order. The panel and confirmation show the selected count and original card numbers. A carousel requires 2–10 selected cards; empty or one-card selections cannot be whitelisted. Rechecking a card triggers fresh validation. Reloading the brief resets card choices along with unsent edits.
   - Jira creative galleries, template thumbnails, carousel cards, full-size previews and downloads use authenticated binary requests, not JWTs in image URLs. Failed previews stay visible with **Retry preview**; replacing a creative refreshes its image and warnings.
   - **Report validation errors to Jira** prepares a ticket-scoped comment for human review. Only **Yes, post comment** posts it; Cancel and ordinary whitelisting never post comments. The server rechecks current errors and rejects an approval if the reviewed comment has changed.
   - Jira Briefs counts Push / App only when the parsed brief identifies a Push campaign (`channel_counts.push`). MoEngage staging metadata may exist for SMS or Email tickets and does not imply a Push campaign; Push title/body are empty when no Push campaign was identified.
   - Jira brief-status filters (including the chat prompt "Show pending Jira briefs") scan successive Jira search pages until the requested number of matching briefs is found or Jira has no more pages. Results remain newest-first; unfiltered listings use a single page.
   - MoEngage attribute resolver and automated template catalog sync.
   - **Tata Click Counts** (`/tata/click-count`): choose an authorized MoEngage workspace and any number of imported bases. The UI fetches each base's creation date as its default reporting start; operators can edit each start independently or reset it to automatic, and select one inclusive end date valid for every base. Manual starts may precede import creation, but must be valid calendar dates no later than the end date; end dates cannot exceed today in the workspace timezone. All selected queries start together. Each base keeps an independent result because the same user may belong to multiple bases; counts are never summed. Every result counts unique users matching **WhatsApp OR Email OR SMS OR Android push OR iOS push clicks, AND that base's membership**. Users are deduplicated across channels within each base; reachable users remain a separate metric. Workspace/base/date changes clear stale results without automatically submitting another query. The date limit refreshes at workspace midnight, and double-clicking cannot submit a second batch.
   - Click counts use Tata's portal session, not the public MoEngage API workspace IDs. In Tata **Settings → MoEngage**, supply the Bearer token, `refreshtoken` request header, and session cookies from the logged-in dashboard, or configure the `TATA_MOENGAGE_*` variables in `.env.example`. Workspace switching uses request-local credentials and never saves a different workspace's tokens. Expired sessions require manual credential replacement. Counting adds one MoEngage query-history entry per selected base; it does not save a segment, export users, or send a campaign. Bajaj and Apparel users cannot access these endpoints.
   - Base lists supply optional creation timestamps for instant date display without one metadata request per selected base. Inline `created_at`/`start_date` pairs are trusted only when both are valid and match the selected workspace timezone; missing or invalid pairs use sequential `/meta` lookups. Every submission still verifies workspace membership and authoritative `cs_details` before using its creation date; invalid timestamps/ranges are rejected before fetching database metadata. MoEngage may omit `cs_meta` when no cached base-count metadata exists. Naive creation timestamps are UTC before conversion to the workspace calendar date. Query bounds preserve the portal's literal `00:00:00.000Z`–`23:59:59.999Z` calendar-date convention rather than converting them to UTC instants. Signed query tickets expire after 24 hours and bind the workspace and its `/getLoggedInUserData` database identity, with Tata account validation on status checks. Request-local base caches are cleared before workspace switches, including failed switches. Metadata errors are distinct from session-expiry errors.
   - Click-count recovery is independent per selected base: one success or provider failure does not hide the other results. Load failures and empty lists offer reload controls. Each status request is serialized per query while queries poll concurrently; network failures, HTTP 408/429 and 5xx continue polling, while malformed responses and other 4xx pause only the affected query. MoEngage's `received` state becomes `queued` without exposing stale counts; terminal `failure` and `failed` statuses both become `failed`, and no count is invented or credential expiry assumed. **Stop checking** aborts local polling for that base but does not cancel its MoEngage query; **Check status again** resumes GET-only polling without another submission. Caller cancellation/deadlines also cover response-body reads. A timed-out, disconnected, 5xx or malformed-success query-start response is never automatically retried and must be acknowledged before another batch can start. The submission lock prevents duplicate concurrent batches but releases after submission completes, allowing **Count again** once no query is actively checked or awaiting acknowledgement. There is no application selection limit; large batches remain subject to MoEngage rate limits and server capacity.
   - The Tata Click Counter separates workspace selection, searchable imported bases, and a date-and-run panel. Selected bases remain visible during search; a horizontally scrollable results table shows each base's start date, end date, query status, unique clickers, reachable users, and recovery actions. Wide screens place selection and date controls side by side; narrower screens stack them.
   - RCS clicks are not yet included in click counting. MoEngage distinguishes [RCS URL and suggestion clicks](https://www.moengage.com/docs/user-guide/campaigns-and-channels/sms-mms-and-rcs/rcs/analyze-rcs-campaigns), but their internal event codes must be verified against a current Tata event catalog or actual query payload before extending the query.
   - SLA kickoff/checkpoint/escalation alerts omit due-today tickets in **Base Pending** or **Content Pending**: these are client-side dependencies, not operator-owned pending work. They are excluded from Google Chat mentions/counts and operator emails until the status changes; if no operator-owned work remains, no Chat webhook is sent. The alert dispatcher does not change Jira assignees.
   - Google Chat SLA webhooks are skipped on Saturdays and Sundays in IST, including manual `force` dispatches. The work-management preview marks Chat as paused and disables Chat-only live dispatch; direct email and dry-run previews remain available. Dispatch summaries distinguish skipped Chat alerts from posted or simulated ones.


4. **Phase 4 — Apparel Multi-Channel Attribution Reporting**:
   - Dedicated `/apparel/attribution` portal under the Apparel account scope.
   - Multi-channel support (WhatsApp, SMS, RCS) with campaign date-range filtering, preview validation, and warnings.
   - Integrates with an isolated worker service deployed on Railway with dedicated persistent MoEngage Chromium browser.
   - Browser attribution waits for the current MoEngage page's `load` event before opening a saved Behavior report. Navigating at `DOMContentLoaded` can interrupt dashboard startup and leave the report stuck in its navigation shell, even when the workspace label is visible.
   - Strict tenant isolation: Karix users from Tata or Bajaj cannot access Apparel attribution; authentication is fail-closed.
   - Login offers Bajaj Finserv, Tata Capital, and Apparel, with automatic organization selection retained as the default. An explicit choice must match an assigned user's organization (or platform-superadmin access); mismatches clear the returned token and stay on login. Apparel sign-ins open `/apparel/attribution` directly. Pending users sign in to `/signup` to request company access; the selector itself never grants permissions.
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

### Enterprise Multi-Channel Auth Sync (no credential copy-paste)

Deploy/restart the updated backend and frontend together. In **Settings**, choose any account and channel:

1. Click **Download extension ZIP** and unzip it into a permanent local folder.
2. Open `chrome://extensions` in Chrome 124 or newer, enable **Developer mode**, click
   **Load unpacked**, and select the folder containing `manifest.json`.
3. Reload Settings, click **Detect extension**, then **Connect extension** for the selected account and integration.
   Each account/integration is paired separately with a five-minute single-use code.
4. Use your existing logged-in provider tab. Login/OTP is needed only if that session has expired;
   installing or pairing the extension does not replay requests made earlier.
   - **WhatsApp (Karix)**: Open or reload the matching template list (`/getAllTemplates`).
     The extension matches exact WABA and ESME identity and captures Authorization, Session, and User.
   - **RCS (Karix)**: Open **Template Management**, select the configured **Sender ID**,
     then reload that inventory (`/api/rcstemplate/fetchTemplates` or `/getTemplatesWithFilter`).
     The campaign screen and a different bot's inventory do not match the paired target.
   - **MoEngage**: Configure the account's exact dashboard origin and internal 24-hex workspace app ID
     once, then connect that account's MoEngage target. Select it in the extension popup and reload the
     configured workspace dashboard. The backend verifies `/dash/auth/listApps` and binds via `/changeApp`;
     it never guesses account-to-workspace mappings from a login.
5. Return to Settings and **Refresh status**. **Check saved session** performs a fresh
   provider validation check.

**Updating an unpacked extension:** use version **2.0.2**, replace its files in the same folder, then click
its reload icon in `chrome://extensions` and reload Settings and the provider inventory. Keeping the
same unpacked folder preserves device pairings. The downloaded ZIP retains the exact Karix frontend
permission (`https://rcmui.instaalerts.zone/*`) as well as the API host: Chrome requires both.
The MV3 worker preserves the first matching request while restoring stored pairings.

**Capture vs validation:** Settings shows the current browser's scoped pairing, pending capture and
safe error category separately from server-side device registrations and saved-session history.
**Retry captured session** resends only that target's pending snapshot without replacing its device
pairing. Provider rejection does not mean the Chrome pairing or OTP expired. RCS validation uses the
same portal POST `/api/rcstemplate/fetchTemplates` as normal inventory reads, with exact bot and ESME
checks; it does not try the incompatible GET surface. MoEngage must be paired separately even when
the popup already has an RCS target. No saved MoEngage session is shown as **not connected**, not expired.
Health responses expose counts and state, never saved bearer tokens, refresh tokens, cookies, or raw
provider error bodies.

If the initial agent session check fails while the API is starting, protected pages retain the
existing sign-in but keep workspace data hidden. Use **Retry session verification**; an actual
401/403 authentication rejection still clears the session.

**Static vs Browser Credentials**:
- **Renewable browser sessions** (Karix WhatsApp, Karix RCS, MoEngage) sync automatically from real browser requests.
- **Static credentials** (Karix SMS key/encryption key/DLT ID, Gemini platform key) are configured once in Settings
  and stored in encrypted database storage. The browser extension does not generate or infer static keys.
- **Jira Cloud credentials** and **Google service-account JSON** remain deployment-level configurations.

**Security & Isolation**:
- Credentials and device pairing are strictly isolated per `(account, integration)`. Tokens never cross-contaminate accounts.
- All captured sessions and Settings overrides are encrypted in PostgreSQL/SQLite using a key derived from `JWT_SECRET`.
  No credentials are written to `.env`, `credentials.json`, source code, or Git.
- Settings leaves secret fields blank on load; blank drafts preserve saved values. Manual overrides require an explicit checkbox
  and a complete valid snapshot.
- Device tokens expire in 90 days and are strictly scoped to extension synchronization. **Disconnect my devices** revokes
  all devices for that account/integration without affecting other accounts or operators.

### RCS submission safety and recovery

- Configure the selected account's `<PREFIX>_RCS_AUTH_TOKEN` or `<PREFIX>_KARIX_BEARER_TOKEN`, bot ID, and ESME address. Tokens, bots and spreadsheet row ownership never fall back to another company. `tata` requires its explicit ESME configuration; subaccounts retain their existing account-specific constants.
- Accepted submission is not approval. A successful save must return an actual provider reference; it remains pending until a matching, account-scoped inventory entry reports approval or rejection.
- A timeout, upstream error, malformed success response or missing provider reference can mean Karix accepted the request but the response was lost. Results preserve `outcome_uncertain` and an error rather than inventing an ID, showing zero metrics or automatically replaying the save. Check the selected bot's Karix inventory before resubmitting that row.
- Queue consumers claim rows atomically across processes. Expired-session refusals pause the account queue until credentials are refreshed. Worker cancellation waits for an already-dispatched request's outcome before recording it.
- A crashed process can leave a row `PROCESSING`. It is deliberately not failed or retried merely because a fixed number of minutes elapsed. An administrator must reconcile the task with the provider, then record the confirmed outcome; do not restart the same row blindly.
- An unavailable RCS catalog is an error, not an empty list or proof a template is missing. Duplicate-skipping submission stops on lookup failure. Concurrent dashboard requests share an in-flight lookup for the same account/bot, without retaining a stale success cache.
- Embedded media keeps its local filename separate from the provider upload reference. Media is validated before saving; corrupt/truncated images and invalid aspect ratios are rejected. Preview cache files are content-addressed and account-scoped. The loader does not insert invented CTA destinations or change malformed JSON into empty content.
- Existing SQLite queues upgrade their task-state checks while preserving rows and custom columns/indexes/triggers. Initialization is cached by the actual database/schema; PostgreSQL cold starts take a cross-process migration lock before DDL. A configured PostgreSQL outage fails closed by default instead of silently creating a separate local queue.


### Production authentication on Render

Configure these service environment variables before deploying:

- `DATABASE_URL`: a persistent PostgreSQL connection URL, such as a dedicated Neon database with TLS enabled. SQLite files on Render Free are ephemeral and do not preserve accounts across redeploys.
- `JWT_SECRET`: a strong, private signing key generated once (for example, `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`). Keep it stable across redeploys; changing it invalidates existing sessions.

Database initialization creates the schema, not a default login. Bootstrap the first company administrator explicitly. Public signup creates only a password-protected, unassigned Operator account requesting a company; an authorized administrator must approve it before any company data is available. Do not bypass password verification or promote legacy global accounts to recover access.

Verification must include a real login after redeployment and confirmation that its `last_login` update reaches PostgreSQL. Persistent application authentication does not refresh MoEngage portal sessions; expired Tata bearer/refresh tokens and cookies still require manual reconnection in **Settings → MoEngage**.

#### Login, signup and existing-account recovery

- `/signup` accepts a name, work email, password and requested company. Passwords require at least 12 characters and at most 72 UTF-8 bytes; spaces are preserved. Duplicate registration never overwrites an existing account or password.
- A company administrator approves applicants in **Settings → Organization Team Directory → Pending company access requests**. Approval grants only that requested company's Operator access. Operators cannot approve requests; company admins cannot approve another company's applicants.
- Approved company Operators and Admins can read, test, and save their own organization's WhatsApp/RCS/SMS and MoEngage credentials in Settings. Updates are shared with colleagues; no admin-role promotion is needed to replace an expired portal session. Pending and cross-company users remain blocked. Team provisioning/approvals remain admin-only, and the shared Gemini key remains platform-superadmin-only.
- WhatsApp **Test Connection** validates an entered Portal Bearer Token against the portal's read-only `/getAllTemplates` endpoint with the matching Session ID and User. It does not test the unrelated official WABA token instead or fall back to it after a portal rejection. Portal header construction accepts a raw token, `Bearer …`, or `Authorization: Bearer …`, including values already saved in the environment. Unsaved token/session/user overrides are request-local; **Save Credentials** persists them and then verifies, displaying a verification failure as an error rather than a success. An explicitly supplied official WABA token without a portal token still uses the official API.
- RCS **Test Connection** checks the entered bearer token against the read-only RCS template inventory for the selected account and bot, not the Lounge/DLT page. Raw tokens, `Bearer …`, and `Authorization: Bearer …` are accepted for testing and saved credentials. Testing is request-local and does not replace colleagues' saved tokens; use **Save Credentials** after verification. Entity IDs or a populated token field are not evidence of valid authentication.
- Older `all` / `Operator` identities are normalized on backend startup without resetting passwords, replacing IDs or reactivating disabled accounts. They can sign in, but must request and receive a concrete company assignment before accessing data. Existing valid company assignments and platform-superadmin accounts remain intact.
- Pending users can refresh approval status or sign out from `/signup`; successful approval opens their assigned workspace. Requests and approvals do not replace the administrator's session.
- Default local SQLite selection is repository-anchored rather than dependent on the terminal's folder. Existing nonempty stores are preferred in `data/karix_store.db`, then repository-root `karix_store.db`, then `backend/karix_store.db`; fresh installs use `data/karix_store.db`. `KARIX_DB_PATH` explicitly selects a different store. Stores are not merged, and local accounts are not automatically copied to another laptop or a cloud database.
- For deployed account recovery, inspect the database actually configured on Render before changing credentials. Restore only confirmed missing staff identities from a trusted backup, preserving IDs, password hashes, company permissions and active/deactivated state; never overwrite existing cloud accounts or import demo/test/default-admin identities. Verify login against the live site and confirm `last_login` reaches that same database.
- Keep connection strings masked in screenshots and logs. If a database password is exposed, rotate the Neon role password and update Render's `DATABASE_URL` (and any other authorized clients) together; changing an application's account password does not revoke the exposed database credential.
- Missing or weak `JWT_SECRET` produces an authentication-configuration error, not a replacement signing key. The native local setup generates its key once; deployed services must keep their configured key persistent.


#### Google sign-in for Karix

Google sign-in is an additional way to authenticate an **existing active Karix account**; password login remains available. It does not create an account, approve a company request, choose a tenant from an email domain, promote a role or refresh Karix/MoEngage provider credentials. Unregistered users must request company access through the existing signup process; pending accounts remain pending after Google login. Disabled accounts and ambiguous duplicate email identities cannot sign in.

Configure a **separate Karix Google Cloud OAuth Web application client**. Do not copy the leave application's client, Gmail/Calendar grants or private state.

1. Configure Google's consent screen for the intended workforce/audience.
2. Add the exact Karix frontend origin(s) to the client's **Authorized JavaScript origins**, including the port for development. Use HTTPS in production; only loopback development can use HTTP.
3. Set these variables on the backend/container and restart it:

   ```dotenv
   KARIX_GOOGLE_CLIENT_ID=YOUR-KARIX-WEB-CLIENT.apps.googleusercontent.com
   KARIX_GOOGLE_ALLOWED_ORIGINS=https://YOUR-KARIX-HOSTNAME
   KARIX_GOOGLE_ALLOWED_DOMAINS=attributics.com
   ```

   Multiple origins/domains are comma-separated. For local development, register and configure `http://localhost:3000` and/or `http://127.0.0.1:3000` exactly as used in the browser. Keep the existing persistent `JWT_SECRET`. The client ID is public configuration; this popup flow requires no client secret and no new Gmail/Calendar scopes.
4. Reload `/login`; the official **Sign in with Google** button appears when configuration is valid. Its result follows the same selected-organization checks and routing as password login.

This uses the [Google Identity Services JavaScript popup flow](https://developers.google.com/identity/gsi/web/reference/js-reference), not the leave application's redirect flow: do **not** register the leave `/auth/google/callback` as a Karix callback. The browser submits the Google ID credential to Karix's own same-origin `/api/auth/google` endpoint. Google credentials are not stored in localStorage or URLs; only the normal Karix session JWT is retained using the existing session mechanism.

The backend binds each attempt to a short-lived HttpOnly nonce cookie and checks an exact allowed Origin before validating Google's fixed-endpoint signing keys, issuer, audience, expiry, nonce and verified authoritative email/domain. Hosted-domain restrictions are identity admission only, never company authorization. No configured client means the Google button is hidden; invalid partial configuration, blocked Google scripts or verification outages must not disable password login. See [Google's server-side verification requirements](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).

Verification (22 October 2026): **157 backend authentication/security tests** and **20 frontend authentication tests** passed. A real localhost HTTP/JWKS/RSA issuer smoke exercised Google exchange, normal app JWTs, cross-company denial, pending-account restrictions, hostile-Origin rejection, missing post-success challenge rejection and retained password login. Isolated Chromium loaded the official GIS button on desktop and 390px mobile without page overflow; signed fixture callbacks through the actual Next proxy proved organization-mismatch session clearing, fresh-challenge retry and routing to Awaiting company approval. A disabled-config browser fixture hid Google without disabling password sign-in. No real Google identity, Karix provider request, live account, leave credential or production configuration was used.

The production Next build and TypeScript check passed using the exact frontend source in a disposable checkout with clean `npm ci` dependencies. The existing workspace dependency installation blocked reads of `next/headers.d.ts`, causing its initial build/type-check attempts to time out; it was not replaced or modified. Browser/API issuer keys, identities and disposable build/state were removed afterward. Enabling real Google login still requires the Karix-specific Web client and authorized origin configuration above; fixture success is not proof of a real Google login or deployed configuration.

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

Run the default isolated suites (temporary databases; external network blocked):
```bash
pytest tests/ -v
```

Focused RCS and shared-queue regressions:
```bash
pytest tests/test_rcs*.py tests/test_enterprise_queue.py tests/test_database_schema_lifecycle.py -v
```

Two read-only live Karix inventory/status checks are excluded by default. Run them only with authorized account credentials and explicit opt-in:
```bash
pytest tests/test_integration.py -m live_karix -v
```
These checks do not prove carrier approval or exercise production template creation. Local HTTP simulators cover save/upload failures without creating real templates.

Run SAST security scans:
```bash
# Bandit security audit
bandit -r . -x ./.venv,./tests,./frontend,./media_cache,./scratch -s B101,B110,B112

# Semgrep code analysis
semgrep scan --config auto --exclude "tests" --exclude "frontend" --exclude ".venv"

# Code formatting and linting
ruff check . && ruff format --check .
```
