# Karix WhatsApp Template Whitelisting — Project Rules

## What this project is

Automated WhatsApp template whitelisting for **Bajaj**, built on top of
Karix (a WhatsApp Business Solution Provider). Before Bajaj can send a
WhatsApp message using a given template, that template must be submitted
to Karix → forwarded to Meta → approved ("whitelisted"). This project
automates that submission and status-tracking flow.

## Two-phase architecture

- **Phase 1 — Identification:** compare a master list of templates that
  *should* exist against what Karix currently has, classify each as
  Whitelisted or Not Whitelisted. **Not built yet.** Will be added when
  the "which templates need whitelisting" question needs automation
  instead of a human-curated list.

- **Phase 2 — Submission:** take a list of templates that need
  whitelisting, submit each via Karix's API, and track each outcome
  (Pending → Approved/Rejected) over time. **This is what's built and
  working right now.**

## Bajaj vs Tata Capital — strict separation

There is a separate, completely independent project for Tata Capital
using Tata's own Karix credentials, WABA IDs, and entity IDs. **Never
mix Bajaj and Tata Capital credentials, WABA IDs, or template data
across the two.** They share the same Karix platform and the same
two-phase architecture but are otherwise fully separate codebases.

## Scope boundaries

- **In scope now:** WhatsApp template submission and status tracking only.
- **Out of scope:** SMS (DLT-based, completely different fields/endpoints),
  RCS (undocumented on Karix's side), message sending (separate API surface).

## Karix API quirks — do NOT "clean up"

These inconsistencies are real platform behaviours confirmed against live
data, not bugs in our code:

- **`wabaId` (camelCase) in `/getAllTemplates`** vs **`waba_id` (snake_case)
  in `/create`** — two different endpoints expect different casing for the
  same field.
- **`esmeaddr` (`72148300000000`) and `template_namespace_id`
  (`42eec6e7_6287_4b1d_8ec8_52f4a80c23b5`)** are account-wide constants,
  not per-template values. Same on every request.
- **`"sessionId": "12345"`** in the `/create` body is a literal hardcoded
  placeholder observed in real production traffic — not a real session
  value, not related to the auth `Session` header.
- **Two different API surfaces exist** with different URL patterns:
  - Portal API (currently used): `https://rcsgui.karix.solutions/v1.0/templates/...`
    — requires session-based auth (Bearer + Session + User headers from a
    logged-in browser session). This is what `submission_client.py` calls.
  - Official API (from Bajaj docs): `https://rcsgui.karix.solutions/api/v1.0/template`
    — uses static `WABA_AUTH_TOKEN`. Status of this endpoint is TBD.

## Auth model — known limitation

The current implementation uses session-bound credentials from the Karix
portal (Bearer token + Session ID + User header). These expire when the
browser session does. There is **no auto-refresh/re-login step yet** — a
human must periodically grab fresh credentials from DevTools. This is
flagged as a deliberate Phase 2 limitation.

## Bajaj account constants

| Constant | Value | Notes |
|----------|-------|-------|
| `BAJAJ_WABA_ID` | `286109054585247` | Same as `WABA_ID` in official creds |
| `BAJAJ_ESMEADDR` | `72148300000000` | Account-wide, not per-template |
| `BAJAJ_TEMPLATE_NAMESPACE_ID` | `42eec6e7_6287_4b1d_8ec8_52f4a80c23b5` | Account-wide |

## File responsibilities

- **`config.py`** — loads secrets from env, defines constants. Auth headers
  are built fresh per call (not cached at import time).
- **`submission_client.py`** — the only file that talks to Karix's HTTP API.
  Everything else goes through `submit_template()` and `check_status()`.
- **`models.py`** — plain dataclasses, storage-agnostic. Do not add
  API-specific or storage-specific logic here.
- **`loader.py`** — turns raw input (CSV/JSON/dicts) into `TemplateSubmission`
  objects. Does not change when the API changes.
- **`tracker.py`** — appends `SubmissionResult` entries to a JSONL log.
- **`runner.py`** — wires loader → client → tracker. Entry point.

## Likely next steps (for planning context)

1. Batch submission from a real CSV/sheet source.
2. Phase 1 identification (automated diff against Karix's live list).
3. Automated session credential refresh (eliminate manual DevTools step).
4. Possibly switching from portal API to official API if the
   `WABA_AUTH_TOKEN` + `/api/v1.0/template` endpoint proves functional.
