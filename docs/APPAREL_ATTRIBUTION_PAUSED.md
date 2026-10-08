# Apparel attribution — paused

Paused at the user's request on 2026-10-07 while moving to a separate Tata Capital segment-count workflow. Do not reuse Apparel credentials, spreadsheet, browser session, workspace IDs or reports for Tata.

## Resume point

- Local portal: `/apparel/attribution`; gateway uses port 8000; local worker launcher `run-worker-local.sh` uses port 8001 and expects dedicated Chrome CDP on loopback port 9222.
- Report settings are in `agents/apparel-attribution/Backend/app/config/settings.py` and local private `agents/apparel-attribution/data/setup.json`.
- Approved source: Agent Apparel Master Sheet_2026, worksheet Mastersheet. The previous session observed 2,900 parsed rows and a successful Google connection. No completed live MoEngage metrics run or sheet-write verification has been observed.
- Next behavior proof: administrator signs into the dedicated local Chrome profile, refreshes session status, previews one approved campaign, and verifies metrics before an intentional sheet write. Leave overwrite off unless replacement is explicitly approved.

## Known gaps before calling it deployment-ready

- AGIPL currently points to Aldo's chart while naming AGIPL_Master_DB as its workspace. This is not a verified AGIPL report mapping; obtain its own report before enabling AGIPL processing.
- The supplied Crocs screenshot did not show Txn_Channel, which the worker expects to toggle for online/offline queries. Verify the saved report structure before running it.
- Docker/Oracle deployment has not been smoke-tested. Earlier promises of permanent zero cost, permanent login cookies and automatic deployment success were not verified.
- Deployment files introduced a fixed browser password and shared-token defaults, public HTTP browser access, and a login URL that opens MoEngage rather than the protected automation desktop. Replace these before any internet deployment; do not expose CDP ports.
- Local secrets, database files, browser profiles and private setup data must not be committed. A clone does not include ignored credentials or local state. Review files individually rather than `git add .`.
- The worker admits only one active job and rejects overlapping runs; it does not queue 20 simultaneous jobs.

## Separate Tata requirement

Tata needs a distinct-user segment count for members of an imported base who clicked at least one selected channel between the base import creation date and a user-selected end date. This is not Apparel purchase/revenue attribution. Investigate official MoEngage segmentation/count and import metadata APIs before implementation.

## Simplified native local setup

- Added `scripts/apparel_local.py`: clone → `setup` → `start`, using installed Chrome, Python and Node rather than WSL/Docker or downloaded Chromium. Windows onboarding uses PowerShell and `py -3.12`; full commands are in README.
- Setup installs root and worker requirements, preserves existing `.env` values, generates absent private secrets, and provisions the first Apparel admin through the existing hidden-password auth CLI. Fresh private backend/worker/browser state does not import Bajaj/Tata/cloud credentials or another person's Chrome profile.
- Worker startup locking and credential/setup writes now have native Windows implementations: `msvcrt` exclusive locks, protected current-user/SYSTEM DACLs, fail-closed ACL filesystem checks, and private atomic replacements. Diagnostic screenshots use private platform-neutral paths.
- Verification on macOS: **13 worker regressions and 7 launcher regressions passed**. Real isolated startup used portal 13000, API 18000, worker 18001 and CDP 19222. Hidden-password onboarding persisted a real Apparel admin without echo; restart retained the account/secrets. Ctrl+C released all four listeners.
- The startup smoke found **Start login HTTP 503** because the native helper omitted the required login URL. Native login and dashboard now both use `https://dashboard-03.moengage.com/`, matching bundled reports. After the fix, the live API returned **200**, opened that actual regional MoEngage page and honestly remained `waiting_for_login`.
- Real browser verification: a provisioned Operator signed in through the portal and saw attribution controls but no Admin setup, key upload or corporate-login controls. Anonymous access returned 401; Operator setup/login requests returned 403; the machine endpoint required its separate token.
- Windows runtime remains unverified here, including DACLs, native locking, dependency installation and Windows child-job cleanup. The isolated fresh profile had no Google key or completed human MFA; this smoke did not write any attribution results or replace prior live-brand evidence. The Crocs and cloud verification gaps listed above remain unchanged.
- The native setup is published separately on `apparel-local-setup`; main and unrelated pending work are unchanged. No local Docker builds, browser downloads or dependency installs were performed for this smoke.

