# Central Error Log & Diagnostic Engine

This repository maintains a centralized, persistent error log located at:
`error_log.jsonl`

It captures all system crashes, network timeouts, API rejections, validation failures, and platform incidents across **WhatsApp**, **RCS**, and **SMS**.

> **Note on Platform Visibility**: Per system requirements, this error log is **not exposed on the public platform UI**. It is strictly accessible to developers, operators via CLI, and the internal AI Agent for autonomous diagnosis and remediation.

---

## 1. How to View & Inspect Errors

You can inspect the central error log at any time using the bundled CLI viewer:

```bash
# View recent incidents
python view_errors.py

# Filter by channel (rcs, whatsapp, sms, system)
python view_errors.py --channel rcs

# Filter by account (tcl_promo, tchfl, wealth, moneyfy, tcl_trans)
python view_errors.py --account tcl_promo

# View full traceback and context for a specific incident
python view_errors.py --id <error_id>

# View breakdown summary of all incidents by category & severity
python view_errors.py --summary
```

---

## 2. How the AI Agent Uses the Error Log

The internal AI Agent (`agent.py`) is wired directly to `error_tracker.py`. When an operator asks questions like:
- *"What errors occurred?"*
- *"Why did the submission fail?"*
- *"Show error logs"*

The agent automatically retrieves the most recent incidents matching the active account and channel, explains the root cause in plain English, and suggests the appropriate remediation step.

---

## 3. How Errors Are Recorded Over Time

Future errors are automatically intercepted and recorded through three layers:

1. **Submission Pipeline Interceptor (`api.py`)**:
   - `submit_file`: Catches and logs any validation or ingestion errors.
   - `_submit_rcs_batch`, `_submit_wa_batch`, `_submit_sms_batch`: Log batch processing and duplicate-resolution failures.
2. **Preview Interceptor (`api.py`)**:
   - `preview_file`: Catches parsing, file format, or creative dimension extraction failures.
3. **HTTP Client & Gateway Retries (`rcs_client.py`, `sms_client.py`, `submission_client.py`)**:
   - Log network connection blips, expired bearer tokens, and Karix platform rejections.

---

## 4. Historical Error Incident Catalog

Below is the record of key error patterns faced and resolved in this project:

### Incident 1: `ModuleNotFoundError: No module named 'cryptography'`
* **Category**: `DEPENDENCY`
* **Symptoms**: Web app displayed `Sign in failed: TypeError: fetch failed` immediately after container deployment.
* **Root Cause**: `requirements.txt` lacked `cryptography>=42.0.0`, causing FastAPI (`uvicorn api:app`) to crash on boot inside the Docker container when importing `sms_crypto.py`.
* **Remediation**: Added `cryptography>=42.0.0` to `requirements.txt`.

---

### Incident 2: `RcsSubmissionResult.__init__() got unexpected keyword argument 'provider_ref_id'`
* **Category**: `VALIDATION`
* **Symptoms**: Submission failed on RCS templates when `Skip Duplicates` was enabled.
* **Root Cause**: `_submit_rcs_batch` checked duplicates against Karix's live catalog and attempted to instantiate `RcsSubmissionResult` with `provider_ref_id`, but the dataclass in `rcs_models.py` only defined `template_id`.
* **Remediation**: Added `provider_ref_id`, `approval_status`, and `approval_reason` to `RcsSubmissionResult` with automatic bi-directional mapping in `__post_init__`.

---

### Incident 3: `AbortError: signal error is aborted without any reason`
* **Category**: `NETWORK_TIMEOUT`
* **Symptoms**: Submitting large files or multi-card carousels failed after exactly 60 seconds with an abort error.
* **Root Cause**: `fetchWithRetry` in `frontend/lib/api.ts` had a hardcoded 60-second timeout (`timeoutMs = 60000`). Large batches with multiple images take longer to upload and register with Karix Bot Builder. When the timer expired, `controller.abort()` was invoked without an error reason.
* **Remediation**:
  1. Extended batch submission timeout in `submitFile` to **10 minutes** (`600,000 ms`).
  2. Extended preview timeout to **3 minutes** (`180,000 ms`).
  3. Disabled automatic retries on file submission (`retries = 0`) to prevent duplicate submissions.
  4. Passed descriptive error strings into `controller.abort(...)` so timeouts are explained clearly.

---

### Incident 4: `UnboundLocalError: cannot access local variable 'used_ids'`
* **Category**: `SYSTEM`
* **Symptoms**: Batch submission raised an `UnboundLocalError` when combining duplicate and new entries.
* **Root Cause**: Accidental duplicate block in `_submit_rcs_batch` where `used_ids` was scoped inside an `if` condition.
* **Remediation**: Cleaned up the list merge logic to mirror the stable WhatsApp batch deduplication.

---

### Incident 5: `SyntaxError: Unexpected token div`
* **Category**: `PARSER`
* **Symptoms**: Next.js production build (`npm run build`) failed during compilation of `settings/page.tsx`.
* **Root Cause**: Missing closing `</div>` tag after the Target Info Banner.
* **Remediation**: Balanced the JSX tags and verified via `npm run build`.

---

### Incident 6: `HTTP 401 Unauthorized: Session Token Expired`
* **Category**: `AUTH`
* **Symptoms**: Image/media uploads on WhatsApp portal API failed with 401.
* **Root Cause**: Karix browser session tokens (`KARIX_SESSION`, `KARIX_BEARER_TOKEN`) are session-bound and expire when the operator's browser session closes.
* **Remediation**: Updated session tokens from Karix portal DevTools under Settings.
