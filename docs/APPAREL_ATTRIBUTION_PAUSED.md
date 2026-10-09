# Apparel attribution — local verified; cloud verification blocked

Cloud verification resumed at the user's request. Repository deployment issues are corrected, but a live cloud deployment remains unverified because Oracle access is unavailable. Local storage has been recovered; the user requires future Docker builds to run on the cloud VM, not this laptop. Tata Capital remains separate: never reuse Apparel credentials, spreadsheet, browser session, workspace IDs or reports for Tata.

## Resume point

- Local portal: `/apparel/attribution`; gateway uses port 8000; local worker launcher `run-worker-local.sh` uses port 8001 and expects dedicated Chrome CDP on loopback port 9222.
- Report settings are in `agents/apparel-attribution/Backend/app/config/settings.py` and local private `agents/apparel-attribution/data/setup.json`.
- Approved source: Agent Apparel Master Sheet_2026, worksheet Mastersheet. The portal observes 3,140 parsed campaigns through 2026-10-04. Seven brands have now passed the isolated multi-brand verification below; Crocs still requires its confirmed online/offline classification rule.
- For another run, reconnect the approved agent sheet after a worker restart and preview the intended campaigns. Keep overwrite off to preserve completed results. Do not include Crocs until its missing classification prerequisite is resolved. Cloud deployment remains unverified.

## Local testing resumed — 2026-10-07

- Installed the worker's pinned requirements into the repository `.venv`, including missing `gspread` and Google auth dependencies, using `uv pip install --python .venv/bin/python -r agents/apparel-attribution/Backend/requirements.txt`.
- Corrected `run-worker-local.sh` to prefer the repository `.venv` and use `http://127.0.0.1:9222`. The previous `localhost` setting resolved to `::1`, which the current CDP validator rejects; the dedicated Chrome debugger listens on IPv4 loopback.
- Restarted only the idle local attribution worker. Its `/healthz` returned `ok`, and its session endpoint and authenticated portal both reported MoEngage `connected`.
- Connected the approved sheet in the portal: 2,900 parsed campaigns, with parsed sent dates from 2026-01-01 through 2026-09-13. The selected October dates were outside this range.
- Verified a VS/SMS preview for 2026-01-09: four matching campaigns, row limit one, no parsing warnings for that date, and the Run attribution button enabled. First preview row: sheet row 46, goal range 2026-01-09 through 2026-01-22.
- No attribution job was started and no metrics were written to the sheet. Browser attachment and preview readiness are verified; metric extraction and sheet-write completion remain unverified.

## Agent source refresh — 2026-10-07

- The user selected a separate agent copy rather than writes to the team's original master. The original is `Apparel Master Sheet_2026` (`1mUIaH3poCoAFEObVrSUPb1O_CDrA5YBeQbNnkyUK7DY`); the configured destination remains `Agent Apparel Master Sheet_2026`.
- The September cutoff was stale-copy data, not an October date-parsing failure. Read-only inspection of the original found 83 processable October rows and sent dates through 2026-10-04.
- Appended 241 newer source rows into the agent copy at `Mastersheet!A2939:AF3179`. Verified all 2,937 pre-existing data rows, including attribution values, remained unchanged; appended values matched the source snapshot, and the original contents remained unchanged.
- Some older campaign inputs differ between the original and agent copy. These were intentionally left untouched; this refresh appended newer rows rather than replacing historical data.
- Verified the refreshed agent copy contains 83 processable October rows with no October parsing warnings. In the authenticated portal, VS/SMS sent dates 2026-10-03 through 2026-10-06 yielded four matches, row limit one, and Run attribution enabled. First preview row: 3148, `Reminder_on_App (SMS FB)`, goal range 2026-10-03 through 2026-10-04.
- No attribution run was started during this refresh. User-created jobs visible at inspection were completed skips of existing values, not proof of live metric extraction. The copy is a refreshed snapshot, not an automatic ongoing sync; future master additions require another refresh.

## Successful live October run — 2026-10-07

- Fixed `moengage_browser_service.py` to distinguish the outer Filter Users accordion from the nested condition and dispatch the toggle on the actual nested icon. Verified collapsed outer, collapsed nested and already-open states against the live browser.
- Replaced the React-internals duration setter with the visible Custom Range calendar. Verified the retained 2026-10-03 through 2026-10-04 range and the already-selected path.
- Restricted result extraction to date-headed table columns, excluding event labels and selectable summaries regardless of whether the event column is pinned. The expected-day completeness guard remains active.
- Browser attachment now chooses a tab on the configured MoEngage host rather than the first portal or sheet tab. Serialized connection initialization: three simultaneous status calls previously started three real Playwright drivers; the same probe now starts one and returns three connected results.
- Retried the same four VS/SMS campaigns through the authenticated portal with overwrite disabled. Job `05dcc7a83fc847ebb30a343dcb23c130` completed with four successful, zero failed and zero skipped rows.
- Verified actual agent-sheet writes match the returned metrics: row 3148, 8 users / INR 42,626; row 3149, 8 / INR 63,275; row 3150, 25 / INR 241,232; row 3151, 35 / INR 407,186. Online/offline breakdowns were also checked against the written cells.
- Exactly 22 attribution cells changed on rows 3148–3151. All other agent-sheet values and the original master contents were unchanged. Confirmed the successful counts and values in the actual portal.
- That run proved VS/SMS for the retained 3–4 October goal range. The later multi-brand verification below extends the exercised coverage.

## Multi-brand live verification — 2026-10-08

- Created `Attribution Verification 2026-10-07` inside the agent spreadsheet using 42 real source campaigns. Source-row references and prior values are retained in columns AG:AI; attribution cells were cleared only in these copied verification rows. Neither Mastersheet was used for test writes.
- Fixed the shared Sale_Array label locator, exact `exists` versus `does not exist` selection, and scoped attribute/dropdown handling. CIS retains its saved `Brand_PM contains SP` condition; delivery campaign filters no longer confuse it with an unrelated open dropdown.
- Replaced AGIPL's incorrect Aldo alias with its observed report in `AGIPL_Master_DB`: `https://dashboard-03.moengage.com/v4/analytics/v2/behavior?did=6901ead8da0afc9260fdb19f&chartId=6901ebd529fb3c6e959e3d65`. Verified the same live AGIPL WhatsApp campaign with BBW and Aldo targets: 96 users / INR 440,322 versus 22 / INR 221,899. Its stale Campaign Name filter is replaced by the selected Readable Campaign Id.
- Fixed dead-driver cleanup and cached-tab ownership. A live stopped-driver probe reattached without terminating persistent Chromium or losing the connected session; offline browser regressions also prove unrelated tabs are retained.
- Earlier runs exposed native macOS Chromium aborts and automation transport/dialog errors. Final verification used installed Chrome for Testing 151 in headless mode with a 1920×1080 desktop viewport, a private dedicated profile, and only the worker controlling the report browser. Portal inspection used a separate browser. Do not attach another automation client to the active report browser.
- The current local report profile is `~/Desktop/moengage-playwright-profile`; the earlier `~/Desktop/moengage-profile` remains intact. The worker still connects to loopback CDP `127.0.0.1:9222`. The successful report browser is headless; if human reauthentication becomes necessary, stop the idle worker before opening that same dedicated profile in headed Chrome for Testing, then resume single-controller operation. Profiles and sessions are private local state, not cloneable repository files.

| Brand | Real campaign rows successfully extracted and written |
|---|---:|
| Aldo | 6 |
| BBW | 6 |
| CIS | 3 |
| CK | 6 |
| R&B | 4 |
| AGIPL, target BBW | 5 |
| VS | 9 |
| Crocs | 0; all 3 cases blocked by the absent classification field |

- All 42 cases were exercised. Across the preserved runs, 39 rows succeeded; verified all 190 attribution cells against returned metrics, all copied inputs and source references unchanged, and both original and agent Mastersheets unchanged.
- Final full job `51c03752c1c749669bf4e50cbb9bce21`: 42 processed, 14 newly successful, 25 preserved/skipped, and 3 failed Crocs rows. Its actual CSV contains all 42 results; failed Crocs metrics remain blank, not fabricated zeroes.
- Preservation job `86c2c5367f494be49142c9442f69192d` selected all 39 completed rows: 39 skipped, zero failed, zero new writes, and the entire verification worksheet exactly unchanged. VS/SMS reproduced the earlier October values, including 8 users / INR 42,626 and 35 / INR 407,186.
- Restored the approved worksheet to `Mastersheet` through the authenticated admin form and reconnected it. The actual portal shows 3,140 parsed campaigns and connected Google/MoEngage status. The isolated verification worksheet remains as the result artifact.
- Regression checks: 104 passed across `tests/test_apparel_attribution_behavior_grid.py` and `tests/test_apparel_attribution_gateway.py`, using an actual installed Chromium executable; 9 worker contract tests passed with `python -m unittest discover -s tests -p 'test_*.py'` from the worker Backend directory.
- Crocs' live `Sale_Array` attribute catalog does not contain `Txn_Channel`. `Txn_Type` suggests `Sale`, and `Txn_Store_Name` contains store names; neither establishes a confirmed online/offline rule. The user chose to retain split-metric semantics using another confirmed field/rule rather than assume every purchase is offline or change to total-only reporting. Obtain that exact rule or a saved report using it before completing the three Crocs cases.

## Cloud deployment verification

- Both recorded Render sites, `https://whitelisting-agent-1.onrender.com` and `https://whitelisting-agent.onrender.com`, returned HTTP 404 for `/apparel/attribution`. The browser's dedicated Render login redirected to GitHub sign-in; no authenticated Render management session, Oracle SSH host/key configuration, or OCI credentials were available. No cloud service was redeployed.
- Reproduced the Compose gateway's genuine HTTP 503: its plaintext `apparel-worker` hostname is rejected by the existing secure-origin validator. Added private `.internal` network aliases and changed the gateway/CDP origins accordingly. Rendered Compose configuration now passes the actual gateway and browser startup validators; gateway and worker receive the same required secret without tracked defaults.
- Removed fixed worker-token/browser-password defaults and public backend/plaintext desktop bindings. Only frontend `127.0.0.1:3000` and browser HTTPS `127.0.0.1:3001` are published. The protected admin login link points to the actual SSH-forwarded HTTPS desktop, not MoEngage's ordinary website. CDP 9222/9223 remain unexposed; the browser retains its persistent profile path.
- Browser readiness now checks real private Chromium discovery rather than merely a live relay process. Compose waits for healthy browser/worker dependencies; main-image health traverses the frontend-to-backend proxy. Desktop sharing/collaboration switches are locked off.
- Main image uses supported Node 22 consistently at build/runtime and lockfile installation, same-origin browser API requests, and runtime `BACKEND_INTERNAL_URL` routing. Removed embedded account credentials/live acknowledgements and excluded private JWT, SQLite, credential/config and log artifacts from image context. Supply unrelated account integrations through their own runtime configuration, never through the Apparel worker/browser.
- Added `docker-entrypoint.py`: missing, short or low-entropy JWT secrets fail before supervisord; a strong persistent runtime secret preserves child-process exit status. Local-development authentication behavior is unchanged. Previously published credentials must be rotated independently before internet deployment.
- The real ARM64 production frontend build initially failed on `briefs/page.tsx`'s union button type; narrowed optional `label` access without a type assertion. The next production build compiled, completed type checking, generated all 14 static pages and listed `/apparel/attribution`. This is frontend build proof, not successful full-image/runtime proof.
- Full image construction then failed with Docker/containerd and pip filesystem I/O errors. The host filesystem initially measured 100% capacity with 141 MiB available; after recovery attempts it still measured 100%, with 708 MiB available. Approved unused-build-cache cleanup attempts through both Docker contexts timed out, and Docker Desktop restart failed to stop its processes. No successful cache-prune result or container runtime proof was obtained. Do not delete project data, volumes or the Docker VM to bypass this blocker.
- Regression verification: **123 tests passed, plus 25 subtests**: 119 existing grid/gateway/worker/browser-guard checks and four new cloud-startup security regressions. The startup regressions prove invalid signing configuration prevents the application child process and does not echo the supplied secret. Ran with explicit worker `PYTHONPATH` and plugin autoload disabled to avoid unrelated environment metadata reads. The actual entrypoint rejection/exec smoke and deployment shell syntax check also passed. The existing local frontend `/healthz` returned 200 with `status: ok`; this is not cloud verification.
- `deploy-free.sh` now requires an operational Linux Docker host, private runtime configuration and correct bind-mount ownership, waits for real container health, and distinguishes that result from Google/MoEngage readiness. It no longer promises permanent zero cost, permanent login sessions, or success without health checks.

### Cloud completion prerequisites

1. Provide the existing Oracle VM IP/SSH alias, SSH username and private-key **file path**, or authenticated access to the existing deployment account. Do not paste private keys or passwords into chat. Existing provider eligibility, quotas and billing must be checked before creating resources.
2. Build and verify Docker images on the accessible cloud VM, not this laptop. The user explicitly rejected further local disk growth. Do not resume local Docker builds or large image downloads; retain native local testing only. Full cloud images, browser TLS/auth/WebSocket access, worker CDP attachment and persistence across recreation remain unverified.
3. On the deployment host, populate `.env` from `.env.example`: independent random `JWT_SECRET`, matching `APPAREL_ATTRIBUTION_TOKEN`, non-default ASCII browser username of at least eight characters, and a random browser password of at least 32 characters. Keep chosen secrets persistent and private. No secret is cloned from Git.
4. On a fresh database, explicitly provision an Apparel admin using the existing `python -m auth` CLI, then use that account to configure the approved sheet/key. Finish corporate MoEngage sign-in/MFA in the protected browser. Team access requires HTTPS ingress to the frontend; keep desktop access SSH/VPN-only.
5. Run cloud portal → gateway → worker → browser → Google-sheet jobs only against an isolated verification worksheet. Verify exact metrics/writes, account isolation and preservation/restart behavior, then restore the approved Mastersheet. Crocs still requires its confirmed classification rule before all-brand completion.

## Laptop storage recovery

- Force-stopped the unresponsive Docker Desktop, restarted it only for cleanup, and successfully reclaimed **2.108 GB** of unused build cache.
- Removed the worker image produced by this session and, with separate user approval, the unused **5.83 GB** Strix sandbox image. There were no Docker containers or volumes before cleanup, and none were deleted.
- Verified zero Docker images/build cache remained. Actual Docker VM allocation fell from **8.6 GiB to 796 MiB**; host free space reached **8.5 GiB**, with 96% filesystem usage. Project files, native browser profiles, secrets and databases were not targeted.
- Force-stopped Docker again after cleanup. Do not run further local Docker builds or large image downloads. Cloud build/runtime verification must resume on the VM once access is supplied.



## Zero-cost hosting decision

- Use one eligible Oracle Always Free `VM.Standard.A1.Flex` Ubuntu ARM VM in the tenancy's home region; build and run the entire Compose stack on that VM, not the laptop. Current [Oracle documentation](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) lists **1,500 OCPU-hours / 9,000 GB-hours per month**, equivalent to **2 OCPUs / 12 GB RAM**, not the older 4 OCPU / 24 GB guidance. Start with a 50 GB boot disk; all tenancy boot/block volumes together must remain within the 200 GB free allowance. Free outbound transfer is 10 TB/month. Confirm remaining eligibility and quotas in the actual account before provisioning.
- Keep a standard Free Tier account unupgraded and create only resources eligible for ongoing Always Free usage, not resources funded only by trial credits. Oracle requires payment-card identity verification and may place temporary authorization holds; these are not actual charges. Free capacity may be unavailable, idle instances may be reclaimed, and there is no free-tier SLA. See [Oracle's FAQ](https://www.oracle.com/cloud/free/faq/). [Budgets](https://docs.oracle.com/en-us/iaas/Content/Billing/Concepts/budgetsoverview.htm) are alerts/soft limits, not hard billing caps.
- No domain purchase is required: an authorized existing company subdomain is preferable, otherwise use the VM's public IP with a free [Let's Encrypt IP certificate](https://letsencrypt.org/2026/03/11/shorter-certs-certbot.html). Certbot 5.4+ supports the webroot flow; IP certificates last about six days and require working automatic renewal plus a webserver reload deploy hook. Configure Nginx certificate paths manually; do not assume the Certbot nginx installer supports IP certificates. This ingress is a deployment step, not an already-applied or cloud-verified repository feature.
- Public HTTPS must proxy only the frontend's loopback port 3000. Permit public 80/443 as needed for HTTP validation and HTTPS; restrict SSH to administrators. Keep browser desktop 3001, backend 8000, worker and CDP ports private. Administrators use SSH forwarding for corporate sign-in/MFA. Users receive organization/role-scoped portal accounts, with no fixed team size or hard-coded individual-user allowlist. One active attribution job remains a worker concurrency limit, not a user-count limit.
- Clone the actual repository `https://github.com/dugadnaman/whitelisting-agent.git` after the deployment fixes are pushed. Install Docker Engine/Compose on the VM, create a private `.env` with independent secrets, run `bash deploy-free.sh`, provision an Apparel admin with the existing auth CLI, configure Google/sheet/report mapping, finish MoEngage login, then verify an isolated worksheet before opening team access. No credentials or browser profile are supplied by a Git clone.
- [Render free services](https://render.com/docs/free) lack persistent disks and lose local state on restart/sleep; they are unsuitable for this durable browser/SQLite stack. [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) are temporary development tools, not the permanent production URL.
- This is a zero-hosting-bill plan subject to account eligibility, capacity and quotas, not a promise of unlimited traffic/users, guaranteed uptime or free MoEngage licensing. No Oracle VM has been provisioned, no cloud ingress has been configured, and full cloud end-to-end verification still awaits access.

## Simplified native local setup

- Added `scripts/apparel_local.py`: clone → `setup` → `start`, using installed Chrome, Python and Node rather than WSL/Docker or downloaded Chromium. Windows onboarding uses PowerShell and `py -3.12`; full commands are in README.
- Setup installs root and worker requirements, preserves existing `.env` values, generates absent private secrets, and provisions the first Apparel admin through the existing hidden-password auth CLI. Fresh private backend/worker/browser state does not import Bajaj/Tata/cloud credentials or another person's Chrome profile.
- Worker startup locking and credential/setup writes now have native Windows implementations: `msvcrt` exclusive locks, protected current-user/SYSTEM DACLs, fail-closed ACL filesystem checks, and private atomic replacements. Diagnostic screenshots use private platform-neutral paths.
- Verification on macOS: **13 worker regressions and 7 launcher regressions passed**. Real isolated startup used portal 13000, API 18000, worker 18001 and CDP 19222. Hidden-password onboarding persisted a real Apparel admin without echo; restart retained the account/secrets. Ctrl+C released all four listeners.
- The startup smoke found **Start login HTTP 503** because the native helper omitted the required login URL. Native login and dashboard now both use `https://dashboard-03.moengage.com/`, matching bundled reports. After the fix, the live API returned **200**, opened that actual regional MoEngage page and honestly remained `waiting_for_login`.
- Real browser verification: a provisioned Operator signed in through the portal and saw attribution controls but no Admin setup, key upload or corporate-login controls. Anonymous access returned 401; Operator setup/login requests returned 403; the machine endpoint required its separate token.
- Windows runtime remains unverified here, including DACLs, native locking, dependency installation and Windows child-job cleanup. The isolated fresh profile had no Google key or completed human MFA; this smoke did not write any attribution results or replace prior live-brand evidence. Crocs and cloud verification gaps below remain unchanged.
- The helper changes are local repository changes, not an already-pushed release. No local Docker builds, browser downloads or dependency installs were performed for this smoke.

## Known gaps before calling it deployment-ready

- Crocs remains blocked by the confirmed absence of Txn_Channel and the unprovided replacement classification rule. Do not infer splits or insert zeroes.
- Full Docker/Oracle runtime and cloud end-to-end verification await deployment access. Local storage is recovered, but further Docker builds on this laptop are disallowed. Production frontend compilation alone does not prove cloud runtime; cost and session permanence are not guaranteed.
- The repository no longer has the fixed Compose secrets or public plaintext browser/backend bindings. HTTPS team ingress and the actual deployment's secret/auth configuration still need live verification.
- Local secrets, database files, browser profiles and private setup data must not be committed. A clone does not include ignored credentials or local state. Review files individually rather than `git add .`.
- The worker admits only one active job and rejects overlapping runs; it does not queue concurrent jobs. Account access is organization/role-based, not tied to a fixed user count.

## Separate Tata requirement

Tata needs a distinct-user segment count for members of an imported base who clicked at least one selected channel between the base import creation date and a user-selected end date. This is not Apparel purchase/revenue attribution. Investigate official MoEngage segmentation/count and import metadata APIs before implementation.
