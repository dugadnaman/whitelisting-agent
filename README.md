# Karix Multi-Channel Template Whitelisting & Automation Platform

Automated enterprise messaging template submission, validation, and lifecycle status tracking for **Bajaj** and **Tata Capital**. WhatsApp/RCS use Karix; Tata SMS DLT registration uses **VILPOWER**.

Before enterprise messages can be sent via WhatsApp, RCS, or SMS, templates must be registered and approved ("whitelisted") across regulatory registries (DLT) and carrier/meta platforms. This platform automates the end-to-end ingestion, compliance validation, API submission, Jira workflow tracking, and MoEngage synchronization.

## Tata Capital SMS DLT — VILPOWER portal

SMS whitelisting registers **content templates**, not messages to recipients. Choose
**Whitelisting for → Tata Capital (SMS DLT) → SMS** (`account=tata`).
Tata's Karix WhatsApp/RCS sub-accounts and Bajaj do not inherit this connection.

Tata organization admins and operators can use this destination. If an older
selection shows “not integrated”, use **Change → Tata Capital → SMS**, not a
Promotional/Transactional or other Karix sub-account. The picker no longer assumes
SMS support for accounts without channel metadata; changing channels never
silently redirects credentials or submissions to another account.

1. Open **Settings → VILPOWER · SMS DLT**. Download Auth Sync **2.0.5**, unzip it,
   load the folder in Chrome's **Load unpacked**, then reload Settings.
2. **Detect extension → Connect extension** for Tata Capital / SMS. Sign into
   VILPOWER normally, including CAPTCHA/mobile OTP when required. Verify the
   profile identifies **TATA CAPITAL LIMITED · 1101637310000019220**.
3. Reload VILPOWER **Content Templates**. The extension captures the Cookie from
   that successful inventory request and the backend verifies the live principal
   entity before encrypted storage. No credential copying is required. Captured
   cookies stay in extension session storage, never persistent local storage or
   Settings responses; device pairings remain account/integration-scoped.
   **Manual portal-session override** remains available for replacing the complete
   request Cookie and entity ID. Keep the application's JWT encryption secret stable.
4. On **Submit Templates**, download the SMS DLT CSV sample and upload CSV,
   XLSX or XLS containing `template_name` and `text`. Optional import columns:
   `template_type`, `category_id`, `header_id`, `header`, `brand_id`,
   `message_type`, `sample_message`, `service_type`. No phone numbers are needed.
   Choose missing category/header/type fields from live portal options.
   **Native client brief workbooks:** Alternatively, upload multi-sheet `.xlsx` or `.xls`
   campaign briefs directly under **Import native client brief**. The parser extracts
   only SMS / SMS-retargeting rows across personas, product blocks and language columns;
   skips planner and non-SMS channels; detects script mismatches; and presents each
   candidate with its sheet/cell provenance. Select between 1 and 500 candidates, then
   decide every placeholder as literal text or a typed variable with explicit samples
   before confirming registration.
5. Alternatively, in **Jira Briefs → SMS**, select drafts and choose **Review
   selected SMS for DLT whitelisting**. The same DLT editor and confirmation
   are used; edits are retained in the current tab until cleared or the
   destination changes.
6. Use exact lowercase typed variables: `{#num#}`, `{#alp#}`, `{#urg#}`,
   `{#uro#}`, `{#cbn#}`, `{#eml#}` (maximum 15). Supply a complete sample with
   valid example values. Legacy `{#var#}` and WhatsApp `{{1}}` must be edited
   explicitly. Copy, whitespace, punctuation and variable types are never
   normalized or grammar-corrected.
7. **Validate and review DLT drafts**, check the destination/header/category/body/
   sample confirmation, then **Confirm and queue DLT whitelisting**. A successful
   registration can still be **pending**; it is not approval.
8. Use the dashboard's **Refresh DLT Approvals** to reconcile exact DLT IDs.
   The identification panel compares exact copy and can hand missing templates
   directly into review. Identical names with different DLT IDs remain separate.

The portal session expires and requires normal human sign-in again. Reloading the
inventory then captures the renewed session; reconnecting the extension is not
required. There is no automatic login, paid API activation, or automatic registration replay.
Timeouts and unverified outcomes stay failed/unknown: inspect VILPOWER/history
before creating another reviewed batch. Full historical inventory reads can take
several minutes; unavailable or incomplete data is not treated as an empty catalog.
The client reads all dates using count-verified disjoint date windows because
VILPOWER's default date range is only a week and offset pagination can skip rows
with identical request dates.

Single-template registration mirrors the portal's multipart form, including empty
consent/LOB and upload controls. HTTP 200/302 alone is not registration proof:
the catalog must return a DLT ID with the exact name, body and sender header.

Implementation: `backend/vilpower_client.py` owns portal HTTP and identity checks;
`sms_dlt.py` owns draft loading, exact comparison and history reconciliation;
`sms_dlt_api.py` exposes authenticated session/options/review/queue endpoints.
Queue results use tenant-scoped `job_tasks` with `channel=sms`; approval polling
updates only matching DLT IDs. Existing dedicated `/api/sms/send` and delivery
report endpoints remain separate Karix message-sending functionality.

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
                        │ (VILPOWER registration)      │         │
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
   - **WhatsApp**: Submits via Karix Portal API or Official WABA API with parameter checking. Template whitelisting (including spreadsheet and Jira previews/submissions) imposes no image dimension or aspect-ratio requirements and preserves supplied creatives unchanged. An IMAGE header without an attached creative uses a placeholder sample for review; explicitly supplied unreadable or inaccessible Jira creatives still fail validation. This does not change message sending or RCS media requirements.
   - **RCS**: Submits Rich Cards and Carousels (Google RCS / Jio) with compliant aspect ratio and button validation.
   - **Always-dynamic URL CTAs**: WhatsApp and RCS whitelisting imports and submissions require a URL variable, including CSV/Excel sheets, Jira briefs, multiple buttons and RCS carousel cards. Static CTA destinations retain their URL prefix and gain a runtime suffix; existing variables are not duplicated. WhatsApp emits `{{1}}` with a concrete URL example; RCS emits sequential `[n]` variables included in its parameter list. Final submission reapplies the policy after edits. Reply/call buttons and links inside message copy are unchanged.
   - **One whitelisting destination**: the persistent **Whitelisting for** header combines the account/sub-account and channel. Use **Change → account → channel → Use this destination**; the sidebar and Settings no longer maintain competing selections. For example, select **Tata Capital · Promotional · WhatsApp**, then switch to **Tata Capital · Wealth · RCS** for the next batch.
   - **Reviewed destination safety**: previews and submit buttons name the destination; results and queue records retain the actual submitted account/channel. Switching with current work requires confirmation, clears old drafts/previews and returns to the top; upload and preview again before sending a new batch. Late callbacks cannot restore or erase work after a destination change. Spreadsheet account/channel/WABA conflicts are rejected rather than silently rerouted. Detected accounts are suggestions only.
   - **RCS destination safety**: account labels and bot IDs come from effective backend configuration, including overrides. Submission rejects a bot changed since preview; an account without a verified bot cannot submit from the UI.
   - **API cutover**: `/api/submit` requires explicit `account`, `channel`, `expected_account`, and `expected_channel`; a changed reviewed scope returns HTTP 409. The obsolete `auto_route` parameter is removed. **All accounts** is read-only overview: select one account before uploading, whitelisting or managing connections.
   - **SMS**: Tata Capital DLT content-template identification, VILPOWER portal registration, and approval tracking. Legacy Karix SMS delivery/encryption and DLR callbacks remain separate from whitelisting.
   - **Dashboard resilience**: When Karix's WhatsApp inventory is unavailable,
     the dashboard keeps tenant-scoped local submission history visible and marks
     the provider connection as degraded. An unavailable local history is reported
     as an error rather than shown as an empty template catalog.

3. **Phase 3 — Operational Work Management & Sync**:
   - Bi-directional Jira integration for campaign briefs, attachment parsing, and task handoffs.
   - Jira Briefs follows the same shared destination and opens its selected channel for messaging briefs. Other channel drafts remain available to review, but cannot be submitted through the wrong channel's action. Wealth WhatsApp is no longer silently redirected to Promotional: choose Promotional WhatsApp explicitly, review, then submit. Jira preview/submit requests require one `account`; submission also requires explicit `channels`. The obsolete `whatsapp_account` split-routing field is rejected.
   - Jira Briefs CTA previews support WhatsApp API buttons with `text` and legacy fallback buttons with `label`/`text`. Both shapes are type-checked by the production frontend build.
   - Jira Briefs has **Add template content** in WhatsApp, RCS, and SMS panels, including empty channels. Use it to separate two messages incorrectly parsed into one template, then edit the original. New drafts have unique names, open in edit mode, and remain unchecked for whitelisting. Unsent source edits are local to the loaded brief. Tata SMS selections can enter the dedicated VILPOWER DLT review flow; reloading Jira reparses its source.
   - Jira WhatsApp/RCS drafts use the same pre-submission inspection as Excel uploads: image dimensions/ratios, grammar, compliance and duplicate warnings are visible before whitelisting. Copy, CTA, channel and creative changes trigger fresh validation; unavailable validation or invalid media cannot be bypassed by submitting stale browser flags. Carousel images are checked individually.
   - Jira draft warnings belong only to the current validated copy and creative. Editing a template name or other field clears the previous inspection's warnings while a fresh preview runs; failed preview shows **Retry validation**, not errors from the old draft. Whitelisting remains disabled until current validation succeeds. RCS names still require letters or numbers and at most 25 normalized characters.
   - Automatically generated RCS names reserve room within the 25-character limit for the channel and numeric suffix, including carousels, manual additions and moves from WhatsApp/SMS. Truncation preserves distinct draft names; explicit spreadsheet names and operator edits are never silently shortened and remain subject to provider validation.
   - Jira brief loading parses each byte-identical spreadsheet/document attachment once and reuses its extracted creatives. Parsing is deterministic by default; remote semantic enrichment is available to parser callers with `use_ai=True`, rather than blocking the browser on one AI call per copy. Required creative, grammar and technical checks remain enabled. WhatsApp/RCS inventory lookups run concurrently; unavailable inventory is reported separately from an attachment download failure.
   - Jira Briefs RCS carousels have per-card whitelisting checkboxes, initially checked. Unchecked cards remain available for editing but are excluded from validation and submission; selected cards keep their original order. The panel and confirmation show the selected count and original card numbers. A carousel requires 2–10 selected cards; empty or one-card selections cannot be whitelisted. Rechecking a card triggers fresh validation. Reloading the brief resets card choices along with unsent edits.
   - Jira creative galleries, template thumbnails, carousel cards, full-size previews and downloads use authenticated binary requests, not JWTs in image URLs. Failed previews stay visible with **Retry preview**; replacing a creative refreshes its image and warnings.
   - **Report validation errors to Jira** prepares a ticket-scoped comment for human review. Only **Yes, post comment** posts it; Cancel and ordinary whitelisting never post comments. The server rechecks current errors and rejects an approval if the reviewed comment has changed.
   - Jira Briefs counts Push / App only when the parsed brief identifies a Push campaign (`channel_counts.push`). MoEngage staging metadata may exist for SMS or Email tickets and does not imply a Push campaign; Push title/body are empty when no Push campaign was identified.
   - Jira brief-status filters (including the chat prompt "Show pending Jira briefs") scan successive Jira search pages until the requested number of matching briefs is found or Jira has no more pages. Results remain newest-first; unfiltered listings use a single page.
   - MoEngage attribute resolver and automated template catalog sync.
   - **MoEngage RCS sync** resolves the Karix bot ID or configured sender name against the selected workspace's Karix RCS sender settings, then submits the MoEngage sender-record ID. Missing or ambiguous matches stop registration. An explicit `<ACCOUNT>_MOENGAGE_SENDER_ID` override takes precedence; Tata's shared override remains supported, but is never inherited by Bajaj or Apparel.
   - Single-template, selected-template and inventory RCS sync convert `[1]` → `{{1}}` and `[name]` → `{{name}}` in standalone/carousel titles, descriptions and suggestion text, postbacks and URLs. Repeated variable identifiers, existing MoEngage personalization tags and Markdown links are preserved.
   - **MoEngage Ops** (`/moengage-ops`) is Tata-only: company Operators/Admins can report and manage workspaces; Bajaj, Apparel and unassigned identities cannot access its data or keys. Workspace responses mask API keys and omit report keys; blank or masked edits retain existing credentials.
   - Ops reads and imports use the local cache without contacting MoEngage. **Sync from MoEngage** is the explicit provider-read action; failed or truncated provider fetches do not replace the last good cache. Atomic, serialized merges preserve concurrent imports and update existing report metadata without duplicating campaigns or collapsing different flows' action nodes.
   - On direct Ops page loads, the authenticated dashboard read starts alongside session verification rather than afterward. Concurrent session checks share only their in-flight request; completed profiles are never cached, and a token change rejects an older session response. The initial dashboard handoff is token/filter scoped, single-use, expires five seconds after completion, and is discarded on failure, logout or successful import/sync. Data remains hidden until the session is verified.
   - Imports display the metrics already returned by the API without another dashboard GET when filters are unchanged. Default last-week/all-workspace sync does the same; changed filters trigger a fresh read for the current selection.
   - Import CSV, TSV, XLSX or ZIP reports up to **20 MiB**. XLSX worksheets and report preambles, quoted CSV newlines, and nested ZIP reports are supported; filenames retain vertical/type context. Convert legacy XLS to XLSX or CSV first. Invalid reports fail before cache mutation; archive expansion is limited to 1,000 members, 100 MiB total, and three nested ZIP levels. Unknown dates/channels are not invented.
   - Custom Ops dates require both endpoints in order. Filter changes discard obsolete responses and hide stale metrics; date controls wrap on narrower screens. Import feedback distinguishes parsed, added and updated records. **Manage Workspaces** opens a keyboard-accessible dialog with saved-key preservation and inline save feedback.
   - **Export to Excel** sends authenticated requests and honors the selected date/workspace filters, using a request-private workbook that is deleted after download. Master Data contains real Excel dates; the numeric **Ops Summary** is immediately readable without formula recalculation. Combined totals include TCL, Services, Wealth and Moneyfy; TCHFL/Collections remain separately reported, and Collections flows retain their active-snapshot rule.
   - **Tata Click Counts** (`/tata/click-count`): choose an authorized MoEngage workspace and any number of imported bases. The UI fetches each base's creation date as its default reporting start; operators can edit each start independently or reset it to automatic, and select one inclusive end date valid for every base. Manual starts may precede import creation, but must be valid calendar dates no later than the end date; end dates cannot exceed today in the workspace timezone. All selected queries start together. Each base keeps an independent result because the same user may belong to multiple bases; counts are never summed. Every result counts unique users matching **WhatsApp OR Email OR SMS OR Android push OR iOS push clicks, AND that base's membership**. Users are deduplicated across channels within each base; reachable users remain a separate metric. Workspace/base/date changes clear stale results without automatically submitting another query. The date limit refreshes at workspace midnight, and double-clicking cannot submit a second batch.
   - Click counts use the saved MoEngage portal session for the selected Tata account (for example, `tcl_promo`), matching **Settings → MoEngage**. The page names that session source; changing accounts clears selections/results and aborts old requests. Every click-count endpoint accepts an `account` query parameter (default `tata` for the root account); only Tata accounts are accepted, with no cross-account credential fallback. Supply the complete bearer token, `refreshtoken` request header, and cookies through Auth Sync or manual replacement for that same account, or configure its exact `<ACCOUNT>_MOENGAGE_*` environment variables. These are portal credentials, not public API workspace IDs. MoEngage workspace switching uses request-local credentials and never overwrites a saved session. Expired sessions require reconnection. Counting adds one MoEngage query-history entry per selected base; it does not save a segment, export users, or send a campaign. Bajaj and Apparel users cannot access these endpoints.
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
│   ├── vilpower_client.py     # Tata VILPOWER DLT inventory and registration
│   ├── sms_dlt.py             # Exact DLT comparison, drafts and approval history
│   ├── sms_dlt_api.py         # Authenticated Tata DLT session and review endpoints
│   ├── sms_config.py          # Separate legacy Karix SMS delivery configuration
│   ├── sms_client.py          # Separate Karix SMS message-sending client
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

PowerShell uses `cd "C:\path\to\checkout"` (not Command Prompt's `cd /d`). Keep each Python invocation on one logical line, including the path after `--data-dir` and the final `setup` or `start`. If using a custom `--data-dir`, reuse it for both commands to retain the same accounts, secrets and browser profile.

The launcher accepts its exact state marker with LF or Windows CRLF line endings and writes it as LF bytes, so Windows-created state can be reopened. Missing or unrecognized markers in nonempty state folders are still refused; do not create a marker for an unknown folder or delete existing state to bypass that protection.

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

Deploy/restart the updated backend and frontend together. Choose an account and delivery channel using **Whitelisting for → Change** at the top of the app, then open **Settings → Connections**. Manage the selected Karix channel or open the separate **MoEngage integration** panel; neither opening Settings nor viewing an integration activates extension capture or changes your whitelisting destination. Unsaved connection edits require confirmation before changing destination or integration. **Team & administration** is collapsed below the connection controls.

1. Click **Download extension ZIP** and unzip it into a permanent local folder.
2. Open `chrome://extensions` in Chrome 124 or newer, enable **Developer mode**, click
   **Load unpacked**, and select the folder containing `manifest.json`.
3. Reload Settings, click **Detect extension**, then **Connect extension** for the selected account and integration.
   Each account/integration is paired separately with a five-minute single-use code.
4. For a previously paired scope, click **Use this target in browser** to switch capture without
   reconnecting or opening the popup. Use **Open Karix/MoEngage portal** if needed, or reload the
   existing logged-in provider tab. Login/OTP is needed only if that session has expired;
   installing or pairing the extension does not replay requests made earlier.
   - **WhatsApp (Karix)**: Open or reload the matching template list (`/getAllTemplates`).
     The extension requires the exact WABA; Karix's WhatsApp-only `esmeaddr: 0` inventory sentinel is
     accepted, while conflicting real ESME identities are rejected. Authorization, Session and User
     must come from one successful inventory request, then the backend validates the configured identity.
   - **RCS (Karix)**: Open **Template Management**, select the configured **Sender ID**,
     then reload that inventory (`/api/rcstemplate/fetchTemplates` or `/getTemplatesWithFilter`).
     The campaign screen and a different bot's inventory do not match the paired target.
   - **MoEngage**: Configure the account's exact dashboard origin and internal 24-character alphanumeric workspace ID (case-sensitive)
     once, then connect or activate that account's MoEngage target and reload the configured workspace
     dashboard. The backend verifies `/dash/auth/listApps` and binds via `/changeApp`;
     it never guesses account-to-workspace mappings from a login.
5. Settings automatically refreshes backend status after a newly validated browser sync.
   **Refresh capabilities / status** also refreshes it manually; **Check saved session** performs
   a fresh provider validation check. Historical backend validation and this browser's pairing
   are shown separately.

**Updating an unpacked extension:** use version **2.0.5**, replace its files in the same folder, then click
its reload icon in `chrome://extensions` and reload Settings and the provider inventory. Keeping the
same unpacked folder preserves device pairings. The downloaded ZIP retains the exact Karix frontend
permission (`https://rcmui.instaalerts.zone/*`) as well as the API host: Chrome requires both.
Version 2.0.5 also requires the exact VILPOWER host permission
(`https://www.vilpower.in/*`) for Tata SMS. Grant the updated permission, reload
Settings, and select the Tata/SMS target before reloading Content Templates.
Only its successful inventory POST is captured; login, CAPTCHA, OTP and template
registration requests are excluded. The backend verifies the real principal
entity even though the request itself has no entity ID.
The MV3 worker preserves the first matching request while restoring stored pairings.
Capture switches wait for an in-flight provider check rather than timing out after 2.5 seconds
while the extension is busy. Scoped status reads remain available while validation is running.

**Capture vs validation:** Settings shows the current browser's scoped pairing, pending capture and
safe error category separately from server-side device registrations and saved-session history.
**Retry captured session** resends only that target's pending snapshot without replacing its device
pairing. Provider rejection does not mean the Chrome pairing or OTP expired. RCS validation uses the
same portal POST `/api/rcstemplate/fetchTemplates` as normal inventory reads, with exact bot and ESME
checks; it does not try the incompatible GET surface. MoEngage must be paired separately even when
the popup already has an RCS target. No saved MoEngage session is shown as **not connected**, not expired.
Health responses expose counts and state, never saved bearer tokens, refresh tokens, cookies, or raw
provider error bodies.
Identical recaptures are revalidated rather than permanently suppressed, so an expired/revoked
capability or deleted saved session is detected. Switching targets while a request is in flight
never reassigns that request's credentials to the newly selected target.
Token expiry alone is not a connection check. Settings uses the scoped backend validation result and
timestamp; the current browser's pairing and active capture target remain separate. Dashboard/Settings
do not display a green connection claim just because a stored JWT has not expired.

MoEngage MCP tokens use encrypted, exact-account settings, independently of portal Auth Sync snapshots.
Saving or rotating MCP credentials never replaces portal bearer/cookie/refresh headers or another
account's tokens. Configure exact `<ACCOUNT>_MOENGAGE_MCP_*` environment defaults or reconnect that
account's MCP integration; legacy unscoped token slots are not adopted across accounts. OAuth PKCE
state is encrypted, one-use, survives process restarts, and expires after ten minutes.
Manual MCP token replacement discards the previous token's expiry instead of marking the new token
expired using stale metadata.



If the initial agent session check fails while the API is starting, protected pages retain the
existing sign-in but keep workspace data hidden. Use **Retry session verification**; an actual
401/403 authentication rejection still clears the session.

**Static vs Browser Credentials**:
- **Renewable browser sessions** (Karix WhatsApp, Karix RCS, MoEngage, and Tata VILPOWER SMS DLT) sync automatically from their matching inventory requests.
- **Static credentials** (official WABA API token, Karix SMS key/encryption key/DLT ID, Gemini platform key)
  are configured once and stored in encrypted database storage. Auth Sync cannot create service keys.
- **Jira Cloud credentials** and **Google service-account JSON** remain deployment-level configurations.

**Security & Isolation**:
- Credentials and device pairing are strictly isolated per `(account, integration)`. Tokens never cross-contaminate accounts.
- All captured sessions and Settings overrides are encrypted in PostgreSQL/SQLite using a key derived from `JWT_SECRET`.
  No credentials are written to `.env`, `credentials.json`, source code, or Git.
- Settings leaves secret fields blank on load; blank drafts preserve saved values. Manual overrides require an explicit checkbox
  and a complete valid snapshot.
- Device tokens expire in 90 days and are strictly scoped to extension synchronization. **Disconnect my devices** revokes
  all devices for that account/integration without affecting other accounts or operators.

**Connection checks and media creation:**
- An entered official API token is tested only against the official API, never reinterpreted as a
  portal JWT or silently replaced by a different saved session. Blank fields test saved credentials.
  Invalid official-key replacements are rejected before persistence; **Discard unsaved edits**
  reloads this scope's settings without changing stored credentials or another account's pairing.
- The Settings layout keeps the sidebar off the content area on small screens. **Menu** opens mobile
  navigation; closing it or pressing Escape restores access to the page. Installation instructions
  collapse after detecting the extension, while connection and recovery controls remain visible.
- WhatsApp PNG/JPEG, video and PDF headers retain their original creative and MIME type. Official
  media upload accepts valid `fileHandle`/`file_handle` handles, including nested `response` envelopes.
  Missing/corrupt uploads or rejected handles do not silently substitute sample media.
- Creation requires an actual provider ID. A timeout, upstream failure or malformed success is not
  automatically replayed or switched to another create transport: inspect the account's live
  inventory before retrying. Duplicate replies are reconciled only to a matching live
  name/language/WABA/provider ID; unavailable or conflicting inventory leaves approval unknown.
- Text, media and buttons use the existing supported WhatsApp creation contract. WhatsApp carousel
  creation is explicitly rejected rather than silently discarding cards; it requires a verified
  Karix WhatsApp carousel contract. RCS carousel support is unchanged.


### WhatsApp batch results and stalled submissions

- Each uploaded row has a durable task ID. Provider outcomes update that row and its batch counters directly; results are never inferred by slicing shared submission history.
- A completed HTTP request returns the batch's own task snapshot, including failures, blocked rows and skipped duplicates. The results screen also rebuilds an initially empty response from the authenticated job snapshot, so a finished batch does not remain on “Processing”.
- WhatsApp template definitions require a sample media handle during Meta whitelisting. When a spreadsheet specifies an `IMAGE`, `VIDEO` or `DOCUMENT` header without an attached file or URL, the submission automatically uploads the Meta-required sample placeholder to obtain the review handle. Specific creatives can still be provided via `header_media_url`, `header_media_file`, or embedded Excel images.
- Before retrying an older zero-result batch, reconcile its names with that account's Karix inventory. A missing local result does not prove the provider rejected the original request.

### RCS submission safety and recovery

- Configure the selected account's `<PREFIX>_RCS_AUTH_TOKEN` or `<PREFIX>_KARIX_BEARER_TOKEN`, bot ID, and ESME address. Tokens, bots and spreadsheet row ownership never fall back to another company. `tata` requires its explicit ESME configuration; subaccounts retain their existing account-specific constants.
- Accepted submission is not approval. A successful save must return an actual provider reference; it remains pending until a matching, account-scoped inventory entry reports approval or rejection.
- A timeout, upstream error, malformed success response or missing provider reference can mean Karix accepted the request but the response was lost. Results preserve `outcome_uncertain` and an error rather than inventing an ID, showing zero metrics or automatically replaying the save. Check the selected bot's Karix inventory before resubmitting that row.
- Queue consumers claim rows atomically across processes. Expired-session refusals pause the account queue until credentials are refreshed. Worker cancellation waits for an already-dispatched request's outcome before recording it.
- A crashed process can leave a row `PROCESSING`. It is deliberately not failed or retried merely because a fixed number of minutes elapsed. An administrator must reconcile the task with the provider, then record the confirmed outcome; do not restart the same row blindly.
- An unavailable RCS catalog is an error, not an empty list or proof a template is missing. Duplicate-skipping submission stops on lookup failure. Concurrent dashboard requests share an in-flight lookup for the same account/bot, without retaining a stale success cache.
- Embedded media keeps its local filename separate from the provider upload reference. Media is validated before saving; corrupt/truncated images and invalid aspect ratios are rejected. Preview cache files are content-addressed and account-scoped. The loader does not insert invented CTA destinations or change malformed JSON into empty content.
- Existing SQLite queues upgrade their task-state checks while preserving rows and custom columns/indexes/triggers. Initialization is cached by the actual database/schema; PostgreSQL cold starts take a cross-process migration lock before DDL. A configured PostgreSQL outage fails closed by default instead of silently creating a separate local queue.


### Independent Attributics leave deployment

The Attributics leave app has moved to its own private GitHub repository, [dugadnaman/attributics-leave-management](https://github.com/dugadnaman/attributics-leave-management), with local checkout `/Users/naman/Desktop/Projects/attributics-leave-management`. Source, tests and deployment configuration are no longer maintained inside Karix. Its standalone README/HANDOFF describe independent releases, permanent-domain HTTPS and production setup.

Only private leave runtime state remains under the former `agents/leave-management/data/` location, with a relocation handoff and exclusion rules. The root Docker build context excludes that directory. Do not delete it: the running standalone trial uses its existing database, keys, Google grants and references through explicit external paths. No leave secrets/state were copied into the new Git repository, and Karix credentials/databases remain separate. Live private-state relocation and public production deployment are separate controlled operations, not completed by extracting source.

### Production authentication on Render

**Current Karix frontend:** https://whitelisting-agent.onrender.com. Google sign-in release **`8170c3d`** is live on Render service `srv-da1e05ojo6nc738fig60`, deployment `dep-dbcgodm7bikc7398b82g`. The separate Google Web client in project `karix-whitlelisting` has this exact Authorized JavaScript origin saved. All three `KARIX_GOOGLE_*` variables were saved and read back in Render; only those new variables were added, with the 25 existing environment rows retained. Local private `.env` is configured too and was not committed. The release contains only Google-specific code/config/docs/tests; unrelated local changes remain unstaged.

Live verification: `/api/auth/google/start` returns 200 with Google enabled and the supplied client ID; its cookie is Secure/HttpOnly/SameSite=Lax and the response is no-store. Unauthenticated profile and malformed Google credentials return 401. A separate unauthenticated Chrome profile displayed the official Google button with the correct client ID alongside password login. The owner's existing authenticated Karix session survived deployment and was not cleared to force a test. First real Google-account selection/consent and successful account exchange remain a human check; use the same work email as an existing active Karix account. No employee was provisioned, promoted or impersonated. Google audience remains External/Testing, unchanged; this identity-only flow requests basic scopes, not Gmail/Calendar access.

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

The production Next build and TypeScript check passed using the exact frontend source in a disposable checkout with clean `npm ci` dependencies. The existing workspace dependency installation blocked reads of `next/headers.d.ts`, causing its initial build/type-check attempts to time out; it was not replaced or modified. Browser/API issuer keys, identities and disposable build/state were removed afterward. These fixture checks preceded the live Render release recorded above and do not establish a real Google-account login. The required Karix client/origin environment configuration has now been saved on Render.

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

Focused Auth Sync and WhatsApp HTTP/browser regressions:
```bash
pytest tests/test_extension_browser_capture.py tests/test_karix_extension.py tests/test_portal_credential_validation.py tests/test_whatsapp_media_transport.py -q
```
These launch isolated Chromium with the downloaded MV3 extension, loopback TLS portals and real HTTP
provider simulators. They cover capture/pairing/selection/retry/revocation/isolation and template/media
success, failure and duplicate reconciliation without creating production templates or sending messages.
Install the frontend dependencies with `npm ci` in `frontend/` first: the slow capture-switch
regression runs the actual TypeScript website bridge against the queued MV3 worker.

Reliability verification (23 October 2026): the complete default backend suite passed **1,405 tests**
plus four subtests; three opt-in live checks were deselected. **58 frontend behavioral tests** and the
production Next.js build/type check passed. Real isolated Chrome exercised scoped capture activation,
credential rejection/discard recovery, automatic sync-status refresh, and desktop/mobile layouts;
the 390px layout had no horizontal overflow and mobile navigation supported Escape/focus restoration.
Separate authorized TCHFL uploads returned valid handles for PNG, JPEG, MP4 and PDF. The actual
frontend proxy → API → loader → media upload → creation → persisted batch-result flow completed for
CSV text, CSV image and Excel image inputs against a loopback provider. These checks did not create
production templates, send customer messages, prove Meta approval, or deploy the working-tree changes.


Focused RCS and shared-queue regressions:
```bash
pytest tests/test_rcs*.py tests/test_enterprise_queue.py tests/test_database_schema_lifecycle.py -v
```

Focused offline MoEngage Ops, MCP and company-access regressions:
```bash
pytest tests/test_moengage_ops.py tests/test_moengage_ops_engine.py tests/test_moengage_ops_api.py tests/test_moengage_mcp.py tests/test_auth_multi_tenant.py -q
```
The default selection excludes live MoEngage checks; these suites do not prove current provider credentials or live campaign counts.

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
