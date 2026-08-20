# Graph Report - karix  (2026-08-19)

## Corpus Check
- 42 files · ~36,818 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 479 nodes · 964 edges · 26 communities (19 shown, 7 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 12 edges (avg confidence: 0.65)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `dc380ea9`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- loader.py
- rcs_client.py
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
- load_rcs_from_excel
- rcs_tracker.py
- rcs_runner.py
- Quick Start
- Web Application Testing
- Frontend Design
- CLAUDE.md
- Karpathy Guidelines
- RcsSuggestion

## God Nodes (most connected - your core abstractions)
1. `getApiUrl()` - 17 edges
2. `fetchWithRetry()` - 17 edges
3. `getErrorMessage()` - 16 edges
4. `compilerOptions` - 16 edges
5. `TemplateSubmission` - 15 edges
6. `RcsTemplateSubmission` - 15 edges
7. `log_activity()` - 14 edges
8. `submit_file()` - 14 edges
9. `load_rcs_from_excel()` - 14 edges
10. `_load_env_file()` - 13 edges

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

## Communities (26 total, 7 thin omitted)

### Community 0 - "loader.py"
Cohesion: 0.06
Nodes (61): _detect_media_kind(), _extract_images_from_xlsx(), _extract_media_from_xlsx(), _flat_row_to_components(), infer_whatsapp_cta(), load_from_csv(), load_from_excel(), load_from_json() (+53 more)

### Community 1 - "rcs_client.py"
Cohesion: 0.13
Nodes (23): patch, _build_rcs_save_payload(), _build_single_suggestion(), _ensure_url_variable(), _extract_and_number_rcs_variables(), Client for Karix RCS Bot Builder Template Management API. Sends…, Ensure URL has sequential variable at the end: e.g.…, Helper to convert flat button fields on a payload into suggestions array. (+15 more)

### Community 2 - "submission_client.py"
Cohesion: 0.06
Nodes (59): get_credentials(), Return saved credentials from the server so any device/operator on the team…, _account_prefix(), get_esmeaddr(), get_official_auth_headers(), get_portal_auth_headers(), get_template_namespace_id(), get_waba_id() (+51 more)

### Community 3 - "devDependencies"
Cohesion: 0.07
Nodes (29): autoprefixer, dependencies, next, react, react-dom, devDependencies, autoprefixer, postcss (+21 more)

### Community 4 - "compilerOptions"
Cohesion: 0.07
Nodes (26): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+18 more)

### Community 5 - "api.ts"
Cohesion: 0.09
Nodes (52): ActivityLogsPage(), formatTimestamp(), inter, metadata, DashboardPage(), Banner, SettingsPage(), ACCEPTED_EXTENSIONS (+44 more)

### Community 6 - "api.py"
Cohesion: 0.08
Nodes (58): get_activity_summary(), get_all_users(), _get_db(), init_store(), load_activities(), log_activity(), _migrate_jsonl_to_sqlite(), Activity tracker & User Identity Manager: Stores all user operations (template… (+50 more)

### Community 7 - "Karix WhatsApp Template Whitelisting — Project Rules"
Cohesion: 0.18
Nodes (10): Auth model — known limitation, Bajaj account constants, Bajaj vs Tata Capital — strict separation, File responsibilities, Karix API quirks — do NOT "clean up", Karix WhatsApp Template Whitelisting — Project Rules, Likely next steps (for planning context), Scope boundaries (+2 more)

### Community 8 - "rcs_loader.py"
Cohesion: 0.11
Nodes (19): _build_carousel_cards_from_row(), _build_suggestions_from_row(), _ensure_aspect_ratio(), _extract_images_from_xlsx(), infer_cta_link_and_button(), _normalize_row_keys(), _parse_sender_ids(), parse_single_cell_card_block() (+11 more)

### Community 9 - "Frontend Design"
Cohesion: 0.29
Nodes (6): Design principles, Frontend Design, Ground it in the subject, More on writing in design, Process: brainstorm, explore, plan, critique, build, critique again, Restraint and self-critique

### Community 10 - "AGENTS.md"
Cohesion: 0.40
Nodes (4): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution

### Community 17 - "load_rcs_from_excel"
Cohesion: 0.18
Nodes (16): fetch_rcs_templates(), Upload a binary image to Karix RCS media storage (gRBM). Returns the generated…, Fetch all live RCS templates for the bot ID from official Karix RCS endpoint:…, upload_rcs_media(), _account_prefix(), get_rcs_auth_headers(), get_rcs_bot_id(), get_rcs_entity_id() (+8 more)

### Community 18 - "rcs_tracker.py"
Cohesion: 0.24
Nodes (12): load_rcs_log(), _lock(), log_rcs_result(), Tracker for RCS template registration results. Appends each RcsSubmissionResult…, Append one RCS submission result as a JSON line., Read back all logged RCS results., Patch one entry (matched by source_ref or template_name). Returns True if found., Apply many updates in ONE locked read-modify-write pass. Returns updated count. (+4 more)

### Community 19 - "rcs_runner.py"
Cohesion: 0.22
Nodes (9): load_rcs_from_csv(), load_rcs_from_list(), Load RCS templates from a CSV file., Load from a list of dicts already in memory., RCS Runner: wires rcs_loader -> rcs_client -> rcs_tracker together. Entry point…, Submit each RCS DLT template, log the attempt., Load RCS templates from CSV or Excel file, submit each, and log attempt., run_rcs() (+1 more)

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

## Knowledge Gaps
- **95 isolated node(s):** `inter`, `metadata`, `Banner`, `State`, `links` (+90 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_esmeaddr()` connect `submission_client.py` to `rcs_client.py`, `load_rcs_from_excel`?**
  _High betweenness centrality (0.012) - this node is a cross-community bridge._
- **Why does `load_rcs_from_excel()` connect `load_rcs_from_excel` to `rcs_loader.py`, `rcs_client.py`, `rcs_runner.py`, `api.py`?**
  _High betweenness centrality (0.011) - this node is a cross-community bridge._
- **Why does `RcsTemplateSubmission` connect `rcs_client.py` to `rcs_loader.py`, `load_rcs_from_excel`, `rcs_runner.py`?**
  _High betweenness centrality (0.011) - this node is a cross-community bridge._
- **What connects `inter`, `metadata`, `Banner` to the rest of the system?**
  _95 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `loader.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05721153846153846 - nodes in this community are weakly interconnected._
- **Should `rcs_client.py` be split into smaller, more focused modules?**
  _Cohesion score 0.12962962962962962 - nodes in this community are weakly interconnected._
- **Should `submission_client.py` be split into smaller, more focused modules?**
  _Cohesion score 0.060814383923849816 - nodes in this community are weakly interconnected._