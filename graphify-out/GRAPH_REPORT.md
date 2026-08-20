# Graph Report - karix  (2026-08-20)

## Corpus Check
- 46 files · ~142,709 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 494 nodes · 989 edges · 34 communities (25 shown, 9 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 14 edges (avg confidence: 0.67)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7069547f`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- runner.py
- activity_tracker.py
- submission_client.py
- devDependencies
- compilerOptions
- api.ts
- api.py
- Karix WhatsApp Template Whitelisting — Project Rules
- rcs_loader.py
- Frontend Design
- AGENTS.md
- rules/graphify.md
- workflows/graphify.md
- next.config.mjs
- next-env.d.ts
- postcss.config.mjs
- tailwind.config.ts
- rcs_client.py
- test_rcs.py
- RcsTemplateSubmission
- Quick Start
- Web Application Testing
- Frontend Design
- CLAUDE.md
- Karpathy Guidelines
- RcsSuggestion
- loader.py
- log_activity
- load_rcs_log
- poll_pending
- _is_retryable
- tata_whatsapp_50_templates_2206035a.md
- whatsapp_templates_sample (2) (2)_06f1eeb1.md

## God Nodes (most connected - your core abstractions)
1. `getApiUrl()` - 17 edges
2. `fetchWithRetry()` - 17 edges
3. `getErrorMessage()` - 16 edges
4. `compilerOptions` - 16 edges
5. `submit_file()` - 15 edges
6. `TemplateSubmission` - 15 edges
7. `RcsTemplateSubmission` - 15 edges
8. `log_activity()` - 14 edges
9. `load_rcs_from_excel()` - 14 edges
10. `get_waba_id()` - 13 edges

## Surprising Connections (you probably didn't know these)
- `AccountCreate` --uses--> `ApprovalStatus`  [INFERRED]
  api.py → models.py
- `UserRegister` --uses--> `ApprovalStatus`  [INFERRED]
  api.py → models.py
- `CredentialUpdate` --uses--> `ApprovalStatus`  [INFERRED]
  api.py → models.py
- `preview_file()` --indirect_call--> `load_from_csv()`  [INFERRED]
  api.py → loader.py
- `preview_file()` --indirect_call--> `load_from_excel()`  [INFERRED]
  api.py → loader.py

## Import Cycles
- None detected.

## Communities (34 total, 9 thin omitted)

### Community 0 - "runner.py"
Cohesion: 0.12
Nodes (25): submit_file(), _flat_row_to_components(), load_from_csv(), load_from_excel(), Convert flat CSV columns into the Karix components array., Load templates from a CSV file for the specified client., Load templates from an Excel (.xlsx) file. Supports embedded…, Runner: wires loader -> client -> tracker together for WhatsApp templates.… (+17 more)

### Community 1 - "activity_tracker.py"
Cohesion: 0.17
Nodes (18): get_activity_summary(), get_all_users(), _get_db(), init_store(), load_activities(), _migrate_jsonl_to_sqlite(), Activity tracker & User Identity Manager: Stores all user operations (template…, Register a new operator profile or update last active timestamp. (+10 more)

### Community 2 - "submission_client.py"
Cohesion: 0.06
Nodes (65): _account_prefix(), get_official_auth_headers(), get_portal_auth_headers(), get_template_namespace_id(), get_waba_id(), Configuration for the Karix WhatsApp template submission pipeline. All secrets…, Build headers for the official WhatsApp Template API for the given client.…, Return WABA ID for the given client. Strictly isolated per account. Never uses… (+57 more)

### Community 3 - "devDependencies"
Cohesion: 0.07
Nodes (29): autoprefixer, dependencies, next, react, react-dom, devDependencies, autoprefixer, postcss (+21 more)

### Community 4 - "compilerOptions"
Cohesion: 0.07
Nodes (26): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+18 more)

### Community 5 - "api.ts"
Cohesion: 0.08
Nodes (54): ActivityLogsPage(), formatTimestamp(), inter, metadata, DashboardPage(), Banner, SettingsPage(), ACCEPTED_EXTENSIONS (+46 more)

### Community 6 - "api.py"
Cohesion: 0.13
Nodes (28): AccountCreate, create_account(), CredentialUpdate, delete_account(), get_account_name(), get_accounts(), get_credentials(), get_public_media() (+20 more)

### Community 7 - "Karix WhatsApp Template Whitelisting — Project Rules"
Cohesion: 0.18
Nodes (10): Auth model — known limitation, Bajaj account constants, Bajaj vs Tata Capital — strict separation, File responsibilities, Karix API quirks — do NOT "clean up", Karix WhatsApp Template Whitelisting — Project Rules, Likely next steps (for planning context), Scope boundaries (+2 more)

### Community 8 - "rcs_loader.py"
Cohesion: 0.11
Nodes (21): _build_carousel_cards_from_row(), _build_suggestions_from_row(), _ensure_aspect_ratio(), _extract_images_from_xlsx(), infer_cta_link_and_button(), load_rcs_from_excel(), _normalize_row_keys(), _parse_sender_ids() (+13 more)

### Community 9 - "Frontend Design"
Cohesion: 0.29
Nodes (6): Design principles, Frontend Design, Ground it in the subject, More on writing in design, Process: brainstorm, explore, plan, critique, build, critique again, Restraint and self-critique

### Community 10 - "AGENTS.md"
Cohesion: 0.40
Nodes (4): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution

### Community 17 - "rcs_client.py"
Cohesion: 0.13
Nodes (25): get_esmeaddr(), Return ESME address for the given client., _build_rcs_save_payload(), _build_single_suggestion(), _ensure_url_variable(), _extract_and_number_rcs_variables(), fetch_rcs_templates(), Client for Karix RCS Bot Builder Template Management API. Sends… (+17 more)

### Community 18 - "test_rcs.py"
Cohesion: 0.16
Nodes (19): Enum, str, Data models for Karix RCS Bot Builder & DLT template submissions. Storage-…, Outcome of the RCS template submission attempt., Outcome of attempting to submit one RCS template., RcsSubmissionResult, RcsSubmissionStatus, _lock() (+11 more)

### Community 19 - "RcsTemplateSubmission"
Cohesion: 0.16
Nodes (14): patch, Submit one RCS template to the official Karix RCS Bot Builder Template API., submit_rcs_template(), load_rcs_from_csv(), load_rcs_from_list(), Load RCS templates from a CSV file., Load from a list of dicts already in memory., One RCS template to be submitted to Karix RCS Bot Builder. (+6 more)

### Community 20 - "Quick Start"
Cohesion: 0.20
Nodes (9): Design & Style Guidelines, Quick Start, Reference, Step 1: Initialize Project, Step 2: Develop Your Artifact, Step 3: Bundle to Single HTML File, Step 4: Share Artifact with User, Step 5: Testing/Visualizing the Artifact (Optional) (+1 more)

### Community 21 - "Web Application Testing"
Cohesion: 0.25
Nodes (7): Best Practices, Common Pitfall, Decision Tree: Choosing Your Approach, Example: Using with_server.py, Reconnaissance-Then-Action Pattern, Reference Files, Web Application Testing

### Community 22 - "Frontend Design"
Cohesion: 0.29
Nodes (6): Design principles, Frontend Design, Ground it in the subject, More on writing in design, Process: brainstorm, explore, plan, critique, build, critique again, Restraint and self-critique

### Community 23 - "CLAUDE.md"
Cohesion: 0.33
Nodes (4): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution

### Community 24 - "Karpathy Guidelines"
Cohesion: 0.33
Nodes (5): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution, Karpathy Guidelines

### Community 26 - "loader.py"
Cohesion: 0.15
Nodes (18): _detect_media_kind(), _extract_images_from_xlsx(), _extract_media_from_xlsx(), infer_whatsapp_cta(), load_from_json(), load_from_list(), parse_single_cell_whatsapp_block(), Input loader: turns raw rows (CSV, JSON list, or Excel files) into validated… (+10 more)

### Community 27 - "log_activity"
Cohesion: 0.23
Nodes (12): log_activity(), Log an event permanently into SQLite and append to JSONL. Automatically updates…, _inspect_template_quality_and_warnings(), _json_safe(), preview_file(), Create or switch operator profile., Recursively coerce arbitrary values to plain JSON-safe primitives so the…, Inspect image dimensions and text grammar/spelling/Meta compliance across all… (+4 more)

### Community 28 - "load_rcs_log"
Cohesion: 0.29
Nodes (8): _clean_error_message(), fetch_whatsapp_templates(), get_stats(), get_templates(), Flatten error strings or nested error dictionaries into a clean message., Fetch live templates directly from Karix WhatsApp API., load_rcs_log(), Read back all logged RCS results.

### Community 29 - "poll_pending"
Cohesion: 0.33
Nodes (7): poll(), poll_pending(), Phase 2, step 2: check approval status for everything still pending. ONE remote…, _match_template(), Match a provider ref against fb_template_id, sno, or template name., pending_entries(), Entries still awaiting a final approval outcome.

### Community 30 - "_is_retryable"
Cohesion: 0.50
Nodes (4): Exception, Response, _is_retryable(), Return True only for transport-level failures we should retry.

## Knowledge Gaps
- **99 isolated node(s):** `inter`, `metadata`, `Banner`, `State`, `links` (+94 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `load_rcs_from_excel()` connect `rcs_loader.py` to `runner.py`, `api.py`, `rcs_client.py`, `RcsTemplateSubmission`, `log_activity`?**
  _High betweenness centrality (0.011) - this node is a cross-community bridge._
- **Why does `get_esmeaddr()` connect `rcs_client.py` to `submission_client.py`, `api.py`?**
  _High betweenness centrality (0.011) - this node is a cross-community bridge._
- **Why does `load_from_excel()` connect `runner.py` to `submission_client.py`, `loader.py`, `log_activity`, `api.py`?**
  _High betweenness centrality (0.010) - this node is a cross-community bridge._
- **What connects `inter`, `metadata`, `Banner` to the rest of the system?**
  _99 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `runner.py` be split into smaller, more focused modules?**
  _Cohesion score 0.1225071225071225 - nodes in this community are weakly interconnected._
- **Should `submission_client.py` be split into smaller, more focused modules?**
  _Cohesion score 0.056314699792960665 - nodes in this community are weakly interconnected._
- **Should `devDependencies` be split into smaller, more focused modules?**
  _Cohesion score 0.06666666666666667 - nodes in this community are weakly interconnected._