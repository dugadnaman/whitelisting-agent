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
