# Apparel attribution — direct HTTP in the main application

## Current implementation — 2026-11-02

Attribution no longer uses Playwright, UI selectors, remote CDP, a corporate-browser profile, a Railway browser host or a separate worker deployment. The incomplete earlier analytics import/mode branches have been replaced, not retained as fallbacks. The main Karix application's authenticated Apparel routes embed the existing sheet/job module and own its lifespan, storage lock and shutdown.

The root Docker image now includes `agents/apparel-attribution/Backend/app` and the Google dependencies. Compose and the native launcher run the main application without attribution worker/browser services. Browser deployment files, browser execution code and obsolete browser-grid regressions were removed. Other integrations' use of Playwright is outside this attribution cutover and remains independent.

## Genuine provider contract

Captured from the live Apparel MoEngage dashboard and independently exercised with direct HTTP:

1. `GET /dash/auth/listApps`: authorize active, non-test workspaces in Apparel organization `678e128849349be3423d6fc6`.
2. `GET /dash/auth/changeApp?sls_enabled=true&app_id=...`: obtain request-local workspace credentials. Validate `/getLoggedInUserData?api=1` against the selected organization/database. Never overwrite another tenant's saved session.
3. `POST /v1/segmentation/metadata/user-event-attrs` for `Sale_Array`: validate the required purchase attributes.
4. `POST /api/analytics/v4/behavior`: submit a fresh query with no inherited saved campaign/segment filters. The response supplies `request_id`.
5. `GET /api/analytics/v4/query/{request_id}/status` until `SUCCESSFUL`, then `GET /api/analytics/v4/query/{request_id}/results`.

Channel events are `MOE_WHATSAPP_DELIVERED`, `SMS_DELIVERED` and `MOE_RCS_DELIVERED`. The readable campaign-ID attribute is `moe_campaign_id`, not `cid`. Delivery lookback remains the existing 120 days. The goal date window comes from each sheet row's `Track Goals for`, independently of the portal's sent-date row-selection filter.

Online purchases use `Txn_Channel exists`; Offline uses its negation. Revenue is the sum of `Sale_Array.Order_Net_Val`. CIS also requires `Brand_PM` (any of) contains `SP`. AGIPL requires an explicit supported target mapped to `Txn_Brand contains <brand>` in its own `AGIPL_Master_DB` workspace.

Customer-count semantics are intentionally unchanged: sum daily unique-user counts, then add Online and Offline for Overall campaigns. This is **not** a deduplicated distinct-person count over the entire goal window or across purchase channels. A normal Online/Offline campaign needs two queries; Overall needs four.

Results must contain exactly one finite numeric metric per requested calendar day for the expected event/segment, with no split/grouping. Missing days, duplicates, unexpected series, invalid counts and inconsistent zero/nonzero customer-revenue pairs fail without sheet writes. Query submission is not automatically retried after an ambiguous timeout. Expired authentication stops the job before later campaigns are processed.

## Authentication and configuration

- Reuse only Apparel's existing encrypted Settings/Auth Sync session through `get_moengage_config("apparel")`, or exact `APPAREL_MOENGAGE_*` environment configuration. No unscoped `MOENGAGE_*`, Tata or Bajaj credential fallback exists.
- Auth Sync still runs in the human operator's normal browser. No browser runs on the attribution server. Sessions can expire and must then be reconnected; HTTP execution does not make them permanent.
- Operators can connect the approved sheet, preview, run, cancel and download results. Only Apparel admins/platform superadmins can change setup or install a Google key. Hosted-browser start/reset/profile controls and their routes were removed.
- `ui_config` now holds only `workspace_map` and optional `agipl_attribution_brand_values`. Existing saved setup is projected onto those mappings when loaded; obsolete workflow/selectors/report URLs are not used for execution.
- `APPAREL_ATTRIBUTION_STORAGE_DIR` defaults beside `KARIX_DB_PATH`. Keep that directory on a persistent disk for durable uploaded Google credentials and edited setup. Existing ignored browser profiles/old worker data were not deleted.
- On a diskless/ephemeral Render service, supply `APPAREL_GOOGLE_SERVICE_ACCOUNT_JSON`, `APPAREL_GOOGLE_SPREADSHEET_URL` and `APPAREL_GOOGLE_WORKSHEET_NAME` as deployment configuration. Uploaded files on an ephemeral filesystem will not survive redeployment. Environment-installed Google keys are sealed against portal replacement.
- Keep a stable private `JWT_SECRET` and persistent credential database. No fixed worker secret or separately configured worker URL is required by the main app.

Run one backend process and deployment replica. Jobs/connections remain memory-only; the existing storage lock prevents overlapping processes sharing one attribution directory, not independently scaled hosts with separate filesystems. Wait for active jobs before deploying: rolling releases can overlap on separate filesystems. Existing sheet values are the recovery checkpoint. After restart reconnect, preview, and rerun with overwrite disabled.

## Adversarial hardening — 2026-11-03

- Recheck normalized campaign identity and current metrics immediately before each write. Changed IDs, moved/deleted rows, edited names/goals and invalid headers fail without writing stale results. If another actor completes the row while a query runs, overwrite-off preserves those current values. Google Sheets does not offer atomic compare-and-set here: do not edit/rearrange source rows during a job.
- Retry only the original failed campaign snapshots, not whatever currently occupies those row numbers. Retain the original overwrite choice rather than forcing overwrite on retry.
- Parse ISO source dates and ISO goal ranges without day/month reversal; reject reversed ranges. Reject boolean series indices, malformed purchase-attribute metadata, unsafe integer counts and overflowing totals without raw provider-error disclosure.
- Expired authentication stops before later campaigns. Invalid private attribution setup produces an attribution-only 503 instead of preventing unrelated main-app routes from starting.
- Session polling is serialized, abortable and time-bounded. Source changes invalidate the UI's cached connection/preview; auto-connect failures are visible rather than console-only. Frontend sent-date bounds match the backend's 366-day limit.
- Google API requests now have 10-second connect / 45-second read timeouts. The previous actual client reported `timeout=None`. A controlled stalled HTTP write verified timeout propagation and zero automatic write replays; the probe accelerated the configured timeout to 50 ms rather than waiting 45 seconds. Cancellation still waits for an in-flight Google RPC to settle before admitting another job.
- Repeated genuine HTTP queries and Google writes on isolated worksheet **`HTTP Hardening 2026-11-03 6aa045`**. Verified all 10 output cells, refusal after a real source-name edit, preservation after another actor completed the row, unchanged nonmetric inputs/provenance and three-row rerun preservation. The completed-row preservation phase also verified the full Mastersheet digest was unchanged. No test writes targeted Mastersheet.

## Live cutover verification

Actual main backend ran on loopback port 18000 and the built production frontend on 13000, with private disposable identities/database/setup. Attribution used real Apparel session credentials and real Google access, not mocked provider responses. No report-browser process/CDP endpoint was started. The unrelated scheduler was disabled in the disposable smoke launcher.

Created worksheet **`HTTP Attribution Verification 2026-11-02 6195ca`** in the approved agent spreadsheet. Copied two real VS/SMS campaigns from Mastersheet rows 3148–3149, plus a third already-complete campaign to prove preservation. Cleared metric cells only in the first two verification rows; source-row provenance is in column AG. Neither Mastersheet was used for test writes.

The actual portal previewed and started job `0adcfe68aba34e3c9ce2390d47cf72a4`: **3 processed, 2 successful, 0 failed, 1 skipped**.

| Verification row | Campaign type | Purchased customers | Revenue | Online customers / revenue | Offline customers / revenue |
|---|---|---:|---:|---|---|
| 2 | Online | 9 | 44,424 | 9 / 44,424 | Not applicable; cells left blank |
| 3 | Overall | 8 | 63,275 | 5 / 41,278 | 3 / 21,997 |
| 4 | Online, existing values preserved | 8 | 42,626 | 8 / 42,626 | Existing blank cells preserved |

- Independently captured direct HTTP and the new Python implementation both returned 9 / 44,424 for the first campaign. Current live data differs from its October snapshot; overwrite-off correctly preserved the older completed copy rather than silently replacing it.
- Verified every one of the **10 written attribution cells** against returned metrics, all copied campaign inputs/provenance unchanged, and the completed third row unchanged. Compared a full `Mastersheet!A:AF` digest before/after: unchanged. The team's original spreadsheet was not a write target.
- Preservation job `359025e34b4344cfa9e4f93b29fb0f54`: **3 skipped, 0 successful, 0 failed**; the entire verification worksheet exactly unchanged. Actual CSV download returned HTTP 200 with all three row results.
- Additional real read-only HTTP queries succeeded for **Aldo, BBW, CIS, CK, R&B, AGIPL (target BBW), and VS**, using the older isolated verification worksheet as input. Exercised SMS/RCS plus a separate AGIPL WhatsApp/BBW query. These are HTTP read proofs; only the VS/SMS cases above were written during this cutover.
- Crocs' live metadata again lacked `Txn_Channel`. It failed before submitting a metrics query, not as fabricated zeroes. A confirmed replacement classification rule remains required.
- Restarted the actual main backend: saved JWT/session/setup remained usable, job history was empty as documented, and the actual operator portal recovered/reconnected the three-row sheet. Operator Admin setup was absent and its protected setup endpoint returned 403. Admin UI and completed job/results were visually inspected.
- Production Next.js build/type validation passed and generated `/apparel/attribution` among all 16 application pages.
- **515 regression checks plus 48 subtests passed** on the isolated release based on current remote `main` (`c7f9faf`), including attribution, tenant/session validation, Auth Sync browser-capture logic, Tata click counts and the native launcher. The production frontend build/type validation passed. Three existing warnings remain: deprecated main scheduler startup hooks and an intentionally incompatible JWT-algorithm test key length.

Regression command:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=backend:agents/apparel-attribution/Backend:scripts \
  .venv/bin/python -m pytest tests/test_apparel_attribution_gateway.py \
  agents/apparel-attribution/Backend/tests scripts/test_apparel_local.py \
  tests/test_karix_extension.py tests/test_portal_credential_validation.py \
  tests/test_moengage_click_count.py tests/test_moengage_click_count_api.py \
  tests/test_extension_browser_capture.py -q
```

Temporary smoke scripts, captured credentials, identities and services are not deployment artifacts. The Google verification worksheet remains the inspectable result artifact. Live credentials, profiles and keys must never be committed.

## Deployment status and remaining constraints

The browser-free main-app path is locally verified; **a new Render release has not been deployed by this cutover**. Deploy the root image/source with the persistent configuration described above. No Oracle/Railway browser infrastructure is required for attribution. Existing instructions against local Docker builds/large browser-image downloads remain respected: this verification used native Python and the production Node frontend, not Docker builds.

The actual native CLI also reached `Ready: http://127.0.0.1:13001/apparel/attribution` with only the main API on 18001 and the frontend on 13001. Its own readiness checks observed API health and the real login page returning 200; no Chrome or worker subprocess was launched.

Crocs' replacement classification rule is still a business/data prerequisite. Windows ACLs/native process supervision have regression coverage here but were not executed on Windows. MoEngage's portal HTTP endpoints are the observed dashboard contract, not a promise of permanent vendor support or permanent sessions.

Historical context: the prior browser implementation verified 39 of 42 copied cases across seven brands and 190 written cells on `Attribution Verification 2026-10-07`; its three Crocs failures were already unresolved. That worksheet was read, not changed, during the new HTTP multi-brand smoke. The agent master is a separate snapshot of the team's source, not an automatically synchronized mirror.

Tata's imported-base unique-click count remains separate from Apparel purchase/revenue attribution. Never share their sessions, organization/workspace IDs or spreadsheet data.
