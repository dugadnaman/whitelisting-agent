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

For brands other than Crocs, Online purchases use `Txn_Channel exists`; Offline uses its negation. Crocs is confirmed offline-only: all its purchases are Offline, so no `Txn_Channel` filter is applied. Crocs Overall uses two queries, sets Online to zero and assigns the queried totals to Offline; Online-labelled source rows fail before provider requests. Revenue is the sum of `Sale_Array.Order_Net_Val`. CIS also requires `Brand_PM` (any of) contains `SP`. AGIPL requires an explicit supported target mapped to `Txn_Brand contains <brand>` in its own `AGIPL_Master_DB` workspace.

Customer counts use MoEngage's **entire-period** behavior query (`chart_type=bar`, `granularity=e`), so repeat purchasers count once across the complete goal window. Overall separately queries the distinct union of Online and Offline customers; the split counts can overlap and must not be added to derive its total. A normal Online/Offline campaign needs two queries; non-Crocs Overall needs five, while Crocs Overall needs two.

Results must contain exactly one finite numeric `granularity=entire` metric for event A and the expected segment, with no split/grouping. Daily-series, duplicate, unexpected-series and invalid-count responses fail without sheet writes. Overall's distinct total must lie between the larger split and the sum of both splits. Query submission is not automatically retried after an ambiguous timeout. Expired authentication stops the job before later campaigns are processed.

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

- Job history now identifies both the spreadsheet and worksheet. Switching approved tabs no longer leaves different sources with indistinguishable display names.
- Render readiness probes `/api/health`, so a listening Next.js port alone is insufficient. Supervisor writes its PID under `/tmp` for the non-root runtime user; the final live startup logged `supervisord started with pid 1` without the previous PID-file permission error.

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
- Before the offline-only business rule was confirmed, Crocs' missing `Txn_Channel` blocked its queries. That historical blocker is now replaced by the explicit offline-only rule above.
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

## Main Render verification — 2026-11-03

Live service: [Apparel attribution](https://whitelisting-agent.onrender.com/apparel/attribution). Earlier verified source: [`0c6e4db`](https://github.com/dugadnaman/whitelisting-agent/commit/0c6e4db6d8199679e0bd49841b922e86d6544bd2), following the HTTP cutover in `90a3456`. A platform superadmin must select **Apparel** in the account selector; selecting Tata does not grant an Apparel UI context.

The real production UI previewed and started the write run on [HTTP Hardening 2026-11-03 6aa045](https://docs.google.com/spreadsheets/d/1QTeoRx9gHNDNXmDYRCedTaH-QmTdjFnTOCz0YmQYSOw/edit#gid=1716957635). All test writes targeted that isolated worksheet, never Mastersheet. Used an isolated local Chrome profile only for portal verification; attribution executed as HTTP requests on the main Render service, without a hosted report browser.

| Live scenario | Processed | Successful | Failed | Preserved |
|---|---:|---:|---:|---:|
| Seven-brand, three-channel UI run | 9 | 8 | 0 | 1 |
| Immediate rerun, overwrite off | 9 | 0 | 0 | 9 |
| Crocs missing-classification check | 1 | 0 | 1 | 0 |
| Recovery after the final Render deployment | 9 | 0 | 0 | 9 |

- Covered **AGIPL, Aldo, BBW, CIS, CK, R&B and VS** across **WhatsApp, SMS and RCS**, including Online, Offline and Overall, multi-day windows, CIS's SP filter, AGIPL's explicit BBW target, and a genuine BBW/RCS zero-result campaign.
- Independently checked **all 38 written metric cells** against job results. Nonmetric cells/provenance and the already-complete row were unchanged. The verification worksheet was exactly unchanged by preservation, the Crocs failure and restart recovery. The complete `Mastersheet!A:AG` value digest remained unchanged.
- Four authenticated CSV exports returned the expected 9 / 9 / 1 / 9 rows. Checked unique sheet-row identities, campaign IDs, brand/channel/type, goal ranges, statuses and every metric; numeric zeroes remained zeroes and nonapplicable/missing metrics remained blank.
- The original write, preservation and Crocs jobs were `8991f67b442e4d7d9c3297af96a36f60`, `4527c6ff861145b090d822799615eec0` and `0f457b5a0bf149459f0870226ea7e8d5`. These predated the final deployment and were cleared from memory on restart. Recovery job **`30098b101428427ca7298065c5169b02`** confirmed all nine rows were preserved and its source label included the exact verification worksheet.
- New process startup retained the encrypted Apparel session, stable JWT authentication and environment-installed Google key, while job history reset as documented. Live health returned `moengage_mode=api`, Google configured, MoEngage connected and `mock_writes_enabled=false`. The actual portal recovered/reconnected after restart.
- Unauthenticated job access returned **401**. Replacing the sealed Google key returned **409**, with the correct `APPAREL_GOOGLE_*` configuration instructions. Setup changes during an active run also returned **409** rather than changing its write target.
- Restored the approved target to **Mastersheet** after each write/recovery phase. The user's existing browser remained on `tcl_promo` / RCS; no Tata/Bajaj destination or credentials were changed. Existing 29 Render variables were preserved when adding only the three Apparel Google variables. No local Docker build or browser download was used.

## Crocs, distinct counting and goal-text correction — 2026-11-03

- Crocs is **offline-only**, independent of whether its workspace exposes `Txn_Channel`. Offline queries use all attributed purchases; Overall combines those Offline totals with explicitly zero Online metrics. Explicitly Online Crocs source rows fail before provider requests and must be corrected in the source rather than silently relabeled.
- The shared Excel/Google date parser accepts the instruction prefix in `Track goals from 30th till 02nd Nov`. For the reported October 2026 campaigns this means **2026-10-30 through 2026-11-02**, including both endpoints. Existing month/year rollover rules remain in force; impossible dates and non-date annotations remain errors.
- A real read of Mastersheet recovered the reported rows **3600–3615**. The remaining selected-window input warning was row **3879**, whose goal text was `Incorrect brief`; no date was invented for it.
- Native HTTP verification used the cloned Overall, Offline and invalid Online rows on [Crocs Offline Verification 2026-11-03](https://docs.google.com/spreadsheets/d/1QTeoRx9gHNDNXmDYRCedTaH-QmTdjFnTOCz0YmQYSOw/edit#gid=1893146961). The corrected entire-period queries returned **361 distinct purchasers / 2,539,502 revenue** for both valid rows, versus the earlier daily-sum customer count of 438. Overall had zero Online share and the Online row was rejected. Mastersheet's full `A:AG` value digest was unchanged by both native smokes.
- The user confirmed that MoEngage deduplicates a customer across the entire goal range. Daily-sum customer semantics are removed. Revenue remains the entire-range sum; existing completed rows require an intentional overwrite run to recalculate rather than being silently replaced.
- Regression verification: **521 tests and 92 subtests passed** across attribution, account isolation, extension/session capture, credential validation, Tata click counts and native startup. The production Next.js build passed compilation, lint/type checks and static generation. Live read-only queries also exercised VS, Aldo, BBW, CIS, CK, R&B and AGIPL/BBW, including genuine zero results, before deployment.

## Deployment status and remaining constraints

The browser-free implementation is deployed and verified on the existing main Render service. No Oracle/Railway attribution browser or worker infrastructure is required. Render's Free service can still cold-start, portal credentials can expire and jobs remain memory-only; HTTP execution does not remove those platform constraints. Production setup uses the existing credential database and a sealed Google key in Render configuration rather than ephemeral uploaded credentials.

The actual native CLI also reached `Ready: http://127.0.0.1:13001/apparel/attribution` with only the main API on 18001 and the frontend on 13001. Its own readiness checks observed API health and the real login page returning 200; no Chrome or worker subprocess was launched.

Crocs' offline-only rule is confirmed; missing `Txn_Channel` is no longer a blocker. Existing completed rows remain protected unless overwrite is explicitly enabled. Windows ACLs/native process supervision have regression coverage here but were not executed on Windows. MoEngage's portal HTTP endpoints are the observed dashboard contract, not a promise of permanent vendor support or permanent sessions.

Historical context: the prior browser implementation verified 39 of 42 copied cases across seven brands and 190 written cells on `Attribution Verification 2026-10-07`; its three Crocs failures were already unresolved. That worksheet was read, not changed, during the new HTTP multi-brand smoke. The agent master is a separate snapshot of the team's source, not an automatically synchronized mirror.

Tata's imported-base unique-click count remains separate from Apparel purchase/revenue attribution. Never share their sessions, organization/workspace IDs or spreadsheet data.
