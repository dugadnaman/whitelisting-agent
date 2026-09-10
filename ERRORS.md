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

---

### Incident 7: `HTTP 400: Unable to read data from ...tata-capital-logo.png`
* **Category**: `CREATIVE_SPEC`
* **Symptoms**: Carousel templates failed submission with "Unable to read data from https://www.tatacapital.com/.../tata-capital-logo.png".
* **Root Cause**: When an uploaded card had no image, the loader fell back to an external URL on `tatacapital.com`. Tata Capital's enterprise Akamai/WAF blocked Karix's scraper bots with 403 Forbidden.
* **Remediation**:
  1. Swapped the fallback to the platform's own public media endpoint: `/api/media/default_rcs_3x4.png`.
  2. Added automatic local caching in `_upload_and_bind_rcs_images`: if Karix's portal `mediaUpload` endpoint is unavailable, extracted images are saved directly to `media_cache/` and served with 200 OK via `/api/media/{filename}`.

---

### Incident 8: `HTTP 400: Template with name [...] already exists (25-Char Limit Collision)`
* **Category**: `DUPLICATE_TEMPLATE`
* **Symptoms**: Re-submitting templates after deletion or with long names failed with Karix reporting the template already exists.
* **Root Cause**: Karix RCS Bot Builder truncates all template names to a hard 25-character limit (`[:25]`). Long template names with shared prefixes collided with existing templates. The pre-flight duplicate checker was comparing 32-character names against 25-character bot entries and missing the collision.
* **Remediation**:
  1. Updated the pre-flight duplicate checker in `api.py` to compare normalized 25-character safe keys against the bot's live catalog.
  2. Pre-emptively flags duplicates before making HTTP calls to Karix, reporting which bot already holds that template name.

---

### Incident 9: `NameError: name 'RcsSubmissionStatus' is not defined`
* **Category**: `DEPENDENCY`
* **Symptoms**: Web UI displayed `Submission failed for tcl_promo (rcs): name 'RcsSubmissionStatus' is not defined`.
* **Root Cause**: An error-logging block added to `rcs_runner.py` referenced `RcsSubmissionStatus` and `logger` without importing them at the top of the file.
* **Remediation**: Imported `RcsSubmissionStatus` and initialized `logger = logging.getLogger(__name__)`.

---

### Incident 10: `Text Template Overridden to Rich Card Stand Alone with Image`
* **Category**: `PARSER_SPEC`
* **Symptoms**: User specified `type: text` with a `card_title` in Excel, but Karix whitelisted it as a Rich Card with an unwanted image header.
* **Root Cause**: In `rcs_client.py`, `is_richcard` evaluated `bool(payload.card_title)`, hijacking text templates into rich cards and attaching fallback images.
* **Remediation**: Guarded `is_text` so that `type="text"` templates strictly remain text; prepended any `card_title` to the body text without generating images or standalone card structures.

---

### Incident 11: `PostbackData Lowercasing and Underscore Mismatch`
* **Category**: `CREATIVE_SPEC`
* **Symptoms**: Suggestion buttons had `postbackData: "apply_now"` while button text was `"Apply Now"`.
* **Root Cause**: Suggestion builders previously applied `.lower().replace(" ", "_")` to postbackData.
* **Remediation**: Set `postbackData` strictly identical to the suggestion button text without lowercase or underscore formatting.

---

### Incident 12: `Hashtag Variables (#var#) Not Extracted as Placeholders`
* **Category**: `PARSER_SPEC`
* **Symptoms**: Variables like `#urg#` were left as raw text instead of being converted to sequential `[N]` Karix placeholders.
* **Root Cause**: Variable extraction regex only looked for `<...>`, `[...]`, and `{...}`, ignoring bare hashtag tokens.
* **Remediation**: Updated regex to `(<[^>]+>|\[[^\]]+\]|\{[^}]+\}|\{#[^#]+#\}|#[a-zA-Z0-9_\-]+#)`.

---

### Incident 13: `Variables in Card Titles Unnumbered / Missing from templateParamNames`
* **Category**: `VALIDATION`
* **Symptoms**: Card titles like `{name}, Explore Our Offers` had brackets stripped instead of being numbered.
* **Root Cause**: `_build_rcs_carousel_vi_template` only ran variable numbering on `cardDescription`, leaving card titles unnumbered.
* **Remediation**: Sequentially process card titles through `_extract_and_number_rcs_variables` and include them in `templateParamNames`.
