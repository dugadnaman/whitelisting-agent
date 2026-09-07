# Graph Report - karix  (2026-09-07)

## Corpus Check
- 127 files · ~210,571 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1282 nodes · 2443 edges · 95 communities (84 shown, 11 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 114 edges (avg confidence: 0.63)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c6c4b991`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- rcs_client.py
- auth.py
- get_waba_id
- devDependencies
- compilerOptions
- api.ts
- activity_tracker.py
- Karix WhatsApp Template Whitelisting — Project Rules
- agent.py
- _inspect_single_submission
- AGENTS.md
- rules/graphify.md
- workflows/graphify.md
- next.config.mjs
- next-env.d.ts
- postcss.config.mjs
- tailwind.config.ts
- submit_rcs_template
- rcs_tracker.py
- KarixHealthGovernor
- Quick Start
- Web Application Testing
- Frontend Design
- CLAUDE.md
- Frontend Design
- submission_client.py
- loader.py
- ApprovalStatus
- api.py
- Karpathy Guidelines
- route.ts
- RcsTemplateSubmission
- New Microsoft Excel Worksheet (2)_814d7980.md
- tata_whatsapp_50_templates_7397df5c.md
- whatsapp_templates_sample (2) (2)_6fa27684.md
- test_production_smoke.py
- Issue tracker: GitHub
- test_enterprise_queue.py
- ._process_job_tasks
- .sse_event_stream
- Triage
- SubmissionResult
- teach/SKILL.md
- Process
- Codebase Design
- During the session
- test_rcs.py
- HTML Report Format
- template.sh
- Ask Matt
- log_activity
- Diagnosing Bugs
- Steps
- Test-Driven Development
- Process
- writing-for-agents/SKILL.md
- Steps
- wayfinder/SKILL.md
- Migrate to Shoehorn
- Steps
- Scaffold Exercises
- to-spec/SKILL.md
- Process
- <Questionnaire title>
- writing-shape/SKILL.md
- Process
- writing-beats/SKILL.md
- get
- loop-me/SKILL.md
- Reference
- hitl-loop.template.sh
- GLOSSARY.md Format
- writing-fragments/SKILL.md
- test_integration.py
- block-dangerous-git.sh
- implement-spec/SKILL.md
- _row_to_rcs_submission
- db_queue.py
- _submit_official_template
- test_agent_remediation.py
- TemplateSubmission
- rcs_models.py

## God Nodes (most connected - your core abstractions)
1. `SubmissionResult` - 32 edges
2. `TemplateSubmission` - 31 edges
3. `RcsTemplateSubmission` - 29 edges
4. `fetchWithRetry()` - 28 edges
5. `getApiUrl()` - 27 edges
6. `getErrorMessage()` - 26 edges
7. `ApprovalStatus` - 26 edges
8. `log_activity()` - 22 edges
9. `get_waba_id()` - 22 edges
10. `_json_safe()` - 21 edges

## Surprising Connections (you probably didn't know these)
- `WhitelistingAgent` --uses--> `RcsTemplateSubmission`  [INFERRED]
  agent.py → rcs_models.py
- `AccountCreate` --uses--> `SubmissionResult`  [INFERRED]
  api.py → models.py
- `UserRegister` --uses--> `SubmissionResult`  [INFERRED]
  api.py → models.py
- `CredentialUpdate` --uses--> `ApprovalStatus`  [INFERRED]
  api.py → models.py
- `CredentialUpdate` --uses--> `SubmissionResult`  [INFERRED]
  api.py → models.py

## Import Cycles
- None detected.

## Communities (95 total, 11 thin omitted)

### Community 0 - "rcs_client.py"
Cohesion: 0.29
Nodes (13): _build_rcs_carousel_vi_template(), _build_rcs_clean_suggestions(), _build_rcs_richcard_vi_template(), _build_rcs_save_payload(), _build_rcs_text_vi_template(), _build_single_suggestion(), _ensure_url_variable(), _extract_and_number_rcs_variables() (+5 more)

### Community 1 - "auth.py"
Cohesion: 0.11
Nodes (28): get_team_endpoint(), List team members within user's assigned organization., authenticate_user(), create_access_token(), decode_access_token(), get_current_user(), _get_db(), get_user_profile() (+20 more)

### Community 2 - "get_waba_id"
Cohesion: 0.11
Nodes (35): _account_prefix(), _esmeaddr_from_session_token(), get_esmeaddr(), get_official_auth_headers(), get_portal_auth_headers(), get_template_namespace_id(), get_waba_id(), _load_env_file() (+27 more)

### Community 3 - "devDependencies"
Cohesion: 0.07
Nodes (29): autoprefixer, dependencies, next, react, react-dom, devDependencies, autoprefixer, postcss (+21 more)

### Community 4 - "compilerOptions"
Cohesion: 0.07
Nodes (26): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+18 more)

### Community 5 - "api.ts"
Cohesion: 0.05
Nodes (87): ActivityLogsPage(), formatTimestamp(), inter, metadata, LoginPage(), DashboardPage(), Banner, SettingsPage() (+79 more)

### Community 6 - "activity_tracker.py"
Cohesion: 0.14
Nodes (20): get_activity_summary(), get_all_users(), _get_db(), init_store(), load_activities(), _migrate_jsonl_to_sqlite(), Connection, Activity tracker & User Identity Manager: Stores all user operations (template… (+12 more)

### Community 7 - "Karix WhatsApp Template Whitelisting — Project Rules"
Cohesion: 0.18
Nodes (10): Auth model — known limitation, Bajaj account constants, Bajaj vs Tata Capital — strict separation, File responsibilities, Karix API quirks — do NOT "clean up", Karix WhatsApp Template Whitelisting — Project Rules, Likely next steps (for planning context), Scope boundaries (+2 more)

### Community 8 - "agent.py"
Cohesion: 0.07
Nodes (44): _check_agent_tenant_isolation(), _handle_agent_copy_lint(), _handle_agent_fallback_guidance(), _handle_agent_help_inquiry(), _handle_agent_list_templates(), _handle_agent_rejection_diagnosis(), _handle_agent_session_refresh(), _handle_agent_status_poll() (+36 more)

### Community 9 - "_inspect_single_submission"
Cohesion: 0.33
Nodes (6): _inspect_image_aspect_ratio(), _inspect_single_submission(), Validate technical Meta WhatsApp and RCS compliance rules (Semantic Memory).…, validate_meta_technical_compliance(), Verify validate_meta_technical_compliance detects word ratio limits (Meta Error…, test_preflight_technical_compliance_validator()

### Community 10 - "AGENTS.md"
Cohesion: 0.40
Nodes (4): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution

### Community 17 - "submit_rcs_template"
Cohesion: 0.23
Nodes (14): fetch_rcs_templates(), Submit one RCS template to the official Karix RCS Bot Builder Template API., Fetch all live RCS templates for the bot ID from official Karix RCS endpoint:…, submit_rcs_template(), _account_prefix(), get_rcs_auth_headers(), get_rcs_bot_id(), get_rcs_entity_id() (+6 more)

### Community 18 - "rcs_tracker.py"
Cohesion: 0.16
Nodes (17): load_rcs_from_list(), Load from a list of dicts already in memory., RCS Runner: wires rcs_loader -> rcs_client -> rcs_tracker together. Entry point…, Submit each RCS DLT template, log the attempt., Load RCS templates from CSV or Excel file, submit each, and log attempt., run_rcs(), run_rcs_file(), _lock() (+9 more)

### Community 19 - "KarixHealthGovernor"
Cohesion: 0.20
Nodes (7): KarixHealthGovernor, Working Memory: Tracks real-time Karix API response latency and error rates to…, Dynamically calculate optimal worker pool size: - Healthy (< 1.8s avg latency,…, Return an optional inter-request delay in seconds based on server load., Return real-time working memory metrics., Verify KarixHealthGovernor tracks latency and throttles concurrency during high…, test_adaptive_rate_limiting_and_governor()

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

### Community 24 - "Frontend Design"
Cohesion: 0.29
Nodes (6): Design principles, Frontend Design, Ground it in the subject, More on writing in design, Process: brainstorm, explore, plan, critique, build, critique again, Restraint and self-critique

### Community 25 - "submission_client.py"
Cohesion: 0.13
Nodes (26): _build_official_create_body(), _download_remote_media(), _ensure_default_sample_image(), _ensure_default_sample_pdf(), _ensure_default_sample_video(), _handle_portal_media_auto_recovery(), _is_tata_group(), normalize_image_16_9() (+18 more)

### Community 26 - "loader.py"
Cohesion: 0.07
Nodes (34): _bind_embedded_media_to_row(), _build_single_cell_card_submission(), _detect_media_kind(), _extract_images_from_xlsx(), _extract_media_from_xlsx(), _flat_row_to_components(), infer_whatsapp_cta(), load_from_csv() (+26 more)

### Community 27 - "ApprovalStatus"
Cohesion: 0.15
Nodes (24): AccountCreate, AgentChatRequest, DeleteTemplatesRequest, LoginRequest, SignupRequest, TeamInviteRequest, UserRegister, BaseModel (+16 more)

### Community 28 - "api.py"
Cohesion: 0.12
Nodes (29): _build_wa_credentials_mapping(), _commit_credentials_to_github(), create_account(), CredentialUpdate, delete_account(), get_account_name(), get_accounts(), get_me_endpoint() (+21 more)

### Community 29 - "Karpathy Guidelines"
Cohesion: 0.33
Nodes (5): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution, Karpathy Guidelines

### Community 30 - "route.ts"
Cohesion: 0.33
Nodes (4): DELETE, GET, POST, PUT

### Community 31 - "RcsTemplateSubmission"
Cohesion: 0.13
Nodes (21): Upload a binary image or video to Karix RCS media storage (gRBM). Returns the…, upload_rcs_media(), _ensure_aspect_ratio(), _extract_images_from_xlsx(), _fit_rcs_image(), infer_cta_link_and_button(), load_rcs_from_excel(), parse_single_cell_card_block() (+13 more)

### Community 38 - "test_production_smoke.py"
Cohesion: 0.15
Nodes (12): Production Deployment & Docker Configuration Smoke Tests. Validates: - Health…, Verify production webhook connectivity: - Rejects unauthorized calls without…, Verify production uptime monitor endpoints respond with 200 OK., - Multi-stage build (frontend-builder + Python runner) - Supervisord running…, Verify signup creates a user and login returns a usable JWT., Verify SQLite store runs in WAL mode with normal sync and 5000ms busy timeout,…, setup_module(), test_auth_signup_and_login_contract() (+4 more)

### Community 40 - "Issue tracker: GitHub"
Cohesion: 0.06
Nodes (30): Before exploring, read these, Domain Docs, File structure, Flag ADR conflicts, Use the glossary's vocabulary, Conventions, Issue tracker: GitHub, Pull requests as a triage surface (+22 more)

### Community 41 - "test_enterprise_queue.py"
Cohesion: 0.19
Nodes (15): create_job_with_tasks(), get_job_tasks(), Atomically creates an ingestion_job and enqueues all template tasks in one…, Fetch all tasks for a specific job., Monotonic approval state machine: Only advances state forward. Rejects…, update_template_approval_monotonic(), Tests for Enterprise Hardened Queue, Per-WABA Rate Limiter, Circuit Breaker,…, Verify POST /api/webhooks/karix/{tenant} - 401 on invalid/missing secret token… (+7 more)

### Community 42 - "._process_job_tasks"
Cohesion: 0.14
Nodes (12): Update high-level job lifecycle status (e.g. RUNNING, PAUSED_FOR_AUTH)., update_job_status(), Any, Check if tenant's circuit breaker is currently active (paused on 401)., Trip the circuit breaker on 401 Session Expired: - Halts tenant's queue - Flips…, Event-bus auto-resume trigger called when operator updates/tests credentials in…, Broadcast an SSE event payload to all active client listeners., Spawn asynchronous background task to execute all pending tasks in the job. (+4 more)

### Community 43 - ".sse_event_stream"
Cohesion: 0.33
Nodes (4): Queue, Subscribe an SSE connection to live job events., Remove an SSE connection subscriber., Yield Server-Sent Events for a job until it settles or client disconnects.

### Community 44 - "Triage"
Cohesion: 0.06
Nodes (29): Bad agent brief, Behavioral, not procedural, Complete acceptance criteria, Durability over precision, Examples, Explicit scope boundaries, Good agent brief (bug), Good agent brief (enhancement) (+21 more)

### Community 45 - "SubmissionResult"
Cohesion: 0.14
Nodes (19): Outcome of attempting to submit one template, plus its latest known review…, SubmissionResult, patch, Verify that duplicate template names within the same uploaded batch/spreadsheet…, Verify that when skip_duplicates is enabled, templates already active on WABA…, test_duplicate_submission_skipping(), test_in_batch_duplicate_skipping_and_row_order(), Missing portal credentials raise OSError naming the exact env keys. (+11 more)

### Community 46 - "teach/SKILL.md"
Cohesion: 0.07
Nodes (25): Learning Record Format, Numbering, Optional sections, Supersession, Template, What does _not_ qualify, When to write a learning record, MISSION.md Format (+17 more)

### Community 47 - "Process"
Cohesion: 0.07
Nodes (25): 1. State the question, 2. Isolate the logic in a portable module, 3. Build the shareable HTML file, 4. Hand it over, 5. Capture the answer and the prototype, Anti-patterns, Logic Prototype, Process (+17 more)

### Community 48 - "Codebase Design"
Cohesion: 0.09
Nodes (21): 1. In-process, 2. Local-substitutable, 3. Remote but owned (Ports & Adapters), 4. True external (Mock), Deepening, Dependency categories, Seam discipline, Testing strategy: replace, don't layer (+13 more)

### Community 49 - "During the session"
Cohesion: 0.09
Nodes (19): ADR Format, Numbering, Optional sections, Template, What qualifies, When to offer an ADR, CONTEXT.md Format, Rules (+11 more)

### Community 50 - "test_rcs.py"
Cohesion: 0.19
Nodes (8): load_rcs_from_csv(), _normalize_row_keys(), _parse_sender_ids(), Normalize spreadsheet header keys: strip whitespace, map common aliases to…, Parse sender IDs from a pipe/comma-separated string, list, or None., Load RCS templates from a CSV file., Unit tests for the RCS Bot Builder template pipeline (current architecture).…, TestRcsPipeline

### Community 51 - "HTML Report Format"
Cohesion: 0.10
Nodes (18): Call-graph collapse, Candidate card, Cross-section (good for layered shallowness), Diagram patterns, Hand-built boxes-and-arrows (when Mermaid's layout fights you), Header, HTML Report Format, Mass diagram (good for "interface as wide as implementation") (+10 more)

### Community 52 - "template.sh"
Cohesion: 0.22
Nodes (16): ask(), ask_secret(), banner(), _clear(), finish(), note(), open_url(), pause() (+8 more)

### Community 53 - "Ask Matt"
Cohesion: 0.12
Nodes (14): Phase boundaries, Primary and secondary sources, The five options, The tree, These are judgement calls, Ask Matt, Codebase health, Context hygiene (+6 more)

### Community 54 - "log_activity"
Cohesion: 0.11
Nodes (30): log_activity(), Log an event permanently into SQLite and append to JSONL. Automatically updates…, agent_chat_endpoint(), delete_templates_endpoint(), delete_templates_from_file(), _inspect_template_quality_and_warnings(), invite_team_member(), _json_safe() (+22 more)

### Community 55 - "Diagnosing Bugs"
Cohesion: 0.13
Nodes (14): Completion criterion: a tight loop that goes red, Diagnosing Bugs, Minimise, Non-deterministic bugs, Phase 1: Build a feedback loop, Phase 2: Reproduce + minimise, Phase 3: Hypothesise, Phase 4: Instrument (+6 more)

### Community 56 - "Steps"
Cohesion: 0.15
Nodes (12): 1. Detect package manager, 2. Install dependencies, 3. Initialize Husky, 4. Create `.husky/pre-commit`, 5. Create `.lintstagedrc`, 6. Create `.prettierrc` (if missing), 7. Verify, 8. Commit (+4 more)

### Community 57 - "Test-Driven Development"
Cohesion: 0.15
Nodes (10): Designing for Mockability, When to Mock, Anti-patterns, Rules of the loop, Seams: where tests go, Test-Driven Development, What a good test is, Bad Tests (+2 more)

### Community 58 - "Process"
Cohesion: 0.15
Nodes (12): 1. Gather context, 2. Explore the codebase (optional), 3. Draft vertical slices, 4. Quiz the user, 5. Publish the tickets to the configured tracker, Acceptance criteria, Blocked by, <NN>: <Ticket title> (+4 more)

### Community 59 - "writing-for-agents/SKILL.md"
Cohesion: 0.15
Nodes (11): Context pointers, Information hierarchy, Leading words, Invocation, Router skills, Skill mechanics, Splitting by invocation, Pruning (+3 more)

### Community 60 - "Steps"
Cohesion: 0.17
Nodes (11): 1. Detect the environment, 2. Install dependency-cruiser, 3. Write the config, 4. Wire it into the checks, 5. Scaffold the example package, 6. Prove the rules bite, 7. Document the convention, Notes (+3 more)

### Community 61 - "wayfinder/SKILL.md"
Cohesion: 0.17
Nodes (11): Chart the map, Fog of war, Invocation, Out of scope, Plan, don't do, Refer by name, The Map, The map body (+3 more)

### Community 62 - "Migrate to Shoehorn"
Cohesion: 0.20
Nodes (9): `as Type` → `fromPartial()`, `as unknown as Type` → `fromAny()`, Install, Large objects with few needed properties, Migrate to Shoehorn, Migration patterns, When to use each, Why shoehorn? (+1 more)

### Community 63 - "Steps"
Cohesion: 0.22
Nodes (8): 1. Ask scope, 2. Copy the hook script, 3. Add hook to settings, 4. Ask about customization, 5. Verify, Setup Git Guardrails, Steps, What Gets Blocked

### Community 64 - "Scaffold Exercises"
Cohesion: 0.22
Nodes (8): Directory naming, Example: stubbing from a plan, Exercise variants, Lint rules summary, Moving/renaming exercises, Required files, Scaffold Exercises, Workflow

### Community 65 - "to-spec/SKILL.md"
Cohesion: 0.22
Nodes (8): Further Notes, Implementation Decisions, Out of Scope, Problem Statement, Process, Solution, Testing Decisions, User Stories

### Community 67 - "Process"
Cohesion: 0.25
Nodes (7): 1. Pin the fixed point, 2. Identify the spec source, 3. Identify the standards sources, 4. Spawn both sub-agents in parallel, 5. Aggregate, Process, Why two axes

### Community 68 - "<Questionnaire title>"
Cohesion: 0.25
Nodes (7): Anything else?, Context, Document structure, How to answer, <Questionnaire title>, <Theme heading>, What load is the system expected to handle at launch?

### Community 69 - "writing-shape/SKILL.md"
Cohesion: 0.25
Nodes (7): Conversational feel, Format arguments to actually have, Grounding, Out of scope, Pulling from the pile, The loop, Writing rhythm

### Community 70 - "Process"
Cohesion: 0.29
Nodes (6): 1. Scope the procedure, 2. Map each stage's journey, 3. Author the wizard, 4. Verify and hand off, Process, Wizard

### Community 71 - "writing-beats/SKILL.md"
Cohesion: 0.33
Nodes (5): Ending the journey, Grounding, Pulling from the pile, What is a beat, Writing rhythm

### Community 72 - "get"
Cohesion: 0.16
Nodes (24): _clean_error_message(), fetch_whatsapp_templates(), _filter_and_sort_templates(), get_credentials(), get_job_endpoint(), get_stats(), get_templates(), _merge_rcs_templates() (+16 more)

### Community 73 - "loop-me/SKILL.md"
Cohesion: 0.40
Nodes (4): Definition of done, The loop lens, The workspace, Vocabulary

### Community 74 - "Reference"
Cohesion: 0.40
Nodes (4): Files, Implementation vs Review, Reference, Steps

### Community 75 - "hitl-loop.template.sh"
Cohesion: 0.83
Nodes (3): capture(), hitl-loop.template.sh script, step()

### Community 76 - "GLOSSARY.md Format"
Cohesion: 0.50
Nodes (3): GLOSSARY.md Format, Rules, Structure

### Community 77 - "writing-fragments/SKILL.md"
Cohesion: 0.50
Nodes (3): File format, What is a fragment, Writing rhythm

### Community 78 - "test_integration.py"
Cohesion: 0.14
Nodes (23): classify_template_category_sla(), get_pending_templates_sla_insights(), poll_pending(), Runner: wires loader -> client -> tracker together for WhatsApp templates.…, Phase 2, step 2: check approval status for everything still pending. ONE remote…, Classify a pending template into its SLA tier based on category and media…, Procedural Memory: Evaluate pending templates against their SLA windows.…, check_status() (+15 more)

### Community 91 - "_row_to_rcs_submission"
Cohesion: 0.33
Nodes (6): _build_carousel_cards_from_row(), _build_suggestions_from_row(), Parse button columns into Karix RCS suggestion dictionaries., Parse multiple cards for carousel templates from pipe-separated columns or JSON., Convert a normalized dict to an RcsTemplateSubmission., _row_to_rcs_submission()

### Community 92 - "db_queue.py"
Cohesion: 0.18
Nodes (15): get_db(), get_job_task(), list_paused_jobs(), migrate_legacy_jsonl_if_needed(), Any, Connection, Database Queue and State Engine for Karix Template Ingestion. Manages…, Fetch a single task by ID. (+7 more)

### Community 93 - "_submit_official_template"
Cohesion: 0.17
Nodes (13): Exception, Response, _evaluate_portal_create_response(), _is_duplicate_or_exists_error(), _is_retryable(), Submit a text-only template through the verified official Karix API., Check if an error string/dict from Karix or Meta indicates the template already…, When Karix or Meta indicates that a template already exists on the WABA, self-… (+5 more)

### Community 97 - "test_agent_remediation.py"
Cohesion: 0.18
Nodes (12): get_job(), init_queue_db(), Fetch job summary by ID., Initialize jobs and tasks tables and run legacy JSONL migration., fixture, Tests for Autonomous AI Copilot Auto-Remediation Engine and Meta Policy…, Verify conversational chat interaction for rejection diagnosis and 1-click…, Verify full diagnose and auto-resubmit workflow: - Enqueues into ingestion_jobs… (+4 more)

### Community 98 - "TemplateSubmission"
Cohesion: 0.09
Nodes (23): load_from_list(), Shared data models for the Phase-2 (submission-only) pipeline. Kept…, One block of a template: HEADER, BODY, FOOTER, or BUTTONS., One template to be submitted for whitelisting., TemplateComponent, TemplateSubmission, QueueManager, Queue Manager, Per-WABA Rate Limiter, Circuit Breaker, and SSE Event Hub.… (+15 more)

### Community 100 - "rcs_models.py"
Cohesion: 0.40
Nodes (3): Data models for Karix RCS Bot Builder & DLT template submissions. Storage-…, One suggested reply or action for an RCS template., RcsSuggestion

## Knowledge Gaps
- **389 isolated node(s):** `block-dangerous-git.sh script`, `GET`, `POST`, `PUT`, `DELETE` (+384 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `RcsTemplateSubmission` connect `RcsTemplateSubmission` to `rcs_client.py`, `TemplateSubmission`, `rcs_models.py`, `agent.py`, `_row_to_rcs_submission`, `submit_rcs_template`, `test_rcs.py`, `rcs_tracker.py`, `ApprovalStatus`?**
  _High betweenness centrality (0.013) - this node is a cross-community bridge._
- **Why does `TemplateSubmission` connect `TemplateSubmission` to `get_waba_id`, `test_integration.py`, `KarixHealthGovernor`, `submission_client.py`, `loader.py`, `ApprovalStatus`, `_submit_official_template`?**
  _High betweenness centrality (0.012) - this node is a cross-community bridge._
- **Why does `SubmissionResult` connect `SubmissionResult` to `test_agent_remediation.py`, `TemplateSubmission`, `get_waba_id`, `get`, `test_integration.py`, `KarixHealthGovernor`, `submission_client.py`, `ApprovalStatus`, `api.py`, `_submit_official_template`?**
  _High betweenness centrality (0.010) - this node is a cross-community bridge._
- **Are the 25 inferred relationships involving `Path` (e.g. with `_migrate_jsonl_to_sqlite()` and `_commit_credentials_to_github()`) actually correct?**
  _`Path` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `SubmissionResult` (e.g. with `AccountCreate` and `AgentChatRequest`) actually correct?**
  _`SubmissionResult` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `TemplateSubmission` (e.g. with `QueueManager` and `WabaTokenBucket`) actually correct?**
  _`TemplateSubmission` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `RcsTemplateSubmission` (e.g. with `WhitelistingAgent` and `QueueManager`) actually correct?**
  _`RcsTemplateSubmission` has 4 INFERRED edges - model-reasoned connections that need verification._