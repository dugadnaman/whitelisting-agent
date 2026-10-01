# Graph Report - karix  (2026-10-01)

## Corpus Check
- 123 files · ~293,103 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2244 nodes · 5520 edges · 111 communities (99 shown, 12 thin omitted)
- Extraction: 85% EXTRACTED · 15% INFERRED · 0% AMBIGUOUS · INFERRED: 813 edges (avg confidence: 0.61)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e22be872`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- briefing_parser.py
- auth.py
- submission_client.py
- devDependencies
- compilerOptions
- app/page.tsx
- compute_ops_dashboard_metrics
- Karix WhatsApp Template Whitelisting — Project Rules
- moengage_mcp.py
- moengage_preview.py
- AGENTS.md
- rules/graphify.md
- workflows/graphify.md
- next.config.mjs
- next-env.d.ts
- postcss.config.mjs
- tailwind.config.ts
- TemplateSubmission
- rcs_loader.py
- KarixHealthGovernor
- Quick Start
- api.py
- Frontend Design
- CLAUDE.md
- QueueManager
- test_moengage_draft_creation.py
- TestMultiTenantAuth
- MoEngage Campaign Creation Agent — Architectural Specification & Research Dossier
- db.py
- _load_env_file
- route.ts
- sms_loader.py
- moengage_sync.py
- require_tenant_access
- send_sms
- list_jira_issues
- jira_extractor.py
- test_production_smoke.py
- template_validator.py
- extract_template_from_jira_text
- fetchWithRetry
- get_db
- is_valid_template_copy
- api.ts
- test_moengage_ops.py
- TestSmsApiEndpoints
- sms_models.py
- sms_tracker.py
- test_template_identifier.py
- transfer_jira_ticket
- fetch_assignable_jira_users
- agent.py
- DraftWriter
- get_job_tasks
- 4. Historical Error Incident Catalog
- DBConnection
- test_work_manager.py
- submit_rcs_template
- submit/page.tsx
- _parse_excel_channel_sheets
- useApp
- context.tsx
- normalize_placeholders
- extract_and_strip_cta
- work-management/page.tsx
- _parse_raw_sheet_rows
- work_manager.py
- moengage_ops_client.py
- fetch_workspace_campaigns
- log_error
- test_jira_brief_endpoint.py
- find_template_by_content
- dispatch_due_today_alerts
- .sse_event_stream
- loader.py
- fetch_mcp_ops_records
- _build_official_create_body
- runner.py
- datetime
- RcsSuggestion
- decrypt_dlr_gcm
- validate_template_semantic_quality
- update_moengage_ops_workspace
- AlertEmailDraft
- get_job
- NormalizedOpsRecord
- infer_channel_from_name_or_raw
- _is_retryable
- derive_clean_card_title
- test_email_campaign_separation.py
- extract_templates_from_excel_file
- OperatorTicketSummary
- test_agent_remediation.py
- TestCredentialContract
- AlertSchedulerState
- sms_client.py
- Karix Multi-Channel Template Whitelisting & Automation Platform
- infer_channel_from_summary
- fetch_template_list
- Web Application Testing
- Karpathy Guidelines
- test_dashboard_data.py
- run_scheduler_loop
- email_notifier.py
- compute_timeline_bucket
- .is_delivered
- .is_failed
- mcp.json
- .mcp.json

## God Nodes (most connected - your core abstractions)
1. `_json_safe()` - 71 edges
2. `TemplateSubmission` - 71 edges
3. `getApiUrl()` - 68 edges
4. `fetchWithRetry()` - 68 edges
5. `getErrorMessage()` - 65 edges
6. `RcsTemplateSubmission` - 60 edges
7. `SmsMessage` - 57 edges
8. `SubmissionResult` - 51 edges
9. `parse_jira_brief()` - 48 edges
10. `TemplateComponent` - 46 edges

## Surprising Connections (you probably didn't know these)
- `test_email_brief_does_not_stage_push_but_explicit_push_brief_does()` --calls--> `parse_jira_brief()`  [INFERRED]
  tests/test_jira_brief_endpoint.py → backend/briefing_parser.py
- `setup_module()` --calls--> `init_queue_db()`  [INFERRED]
  tests/test_production_smoke.py → backend/db_queue.py
- `test_remediate_header_length_limit()` --calls--> `remediate_template_rejection()`  [INFERRED]
  tests/test_agent_remediation.py → backend/agent.py
- `test_remediate_non_sequential_variables()` --calls--> `remediate_template_rejection()`  [INFERRED]
  tests/test_agent_remediation.py → backend/agent.py
- `test_remediate_promotional_in_utility()` --calls--> `remediate_template_rejection()`  [INFERRED]
  tests/test_agent_remediation.py → backend/agent.py

## Import Cycles
- None detected.

## Communities (111 total, 12 thin omitted)

### Community 0 - "briefing_parser.py"
Cohesion: 0.10
Nodes (35): clean_safelink(), _clean_template_name(), detect_ticket_month(), _extract_images_from_zip(), _extract_links_from_adf_node(), extract_templates_from_docx_file(), _extract_text_from_adf_node(), _find_adf_tables() (+27 more)

### Community 1 - "auth.py"
Cohesion: 0.13
Nodes (21): authenticate_user(), create_access_token(), decode_access_token(), get_current_user(), get_user_profile(), hash_password(), Any, Multi-Tenant Authentication & Strict Tenant Isolation Engine. Provides secure… (+13 more)

### Community 2 - "submission_client.py"
Cohesion: 0.09
Nodes (38): _init_media_cache(), check_whatsapp_image_aspect_ratio(), _download_remote_media(), _ensure_default_sample_image(), _ensure_default_sample_pdf(), _ensure_default_sample_video(), _evaluate_portal_create_response(), _handle_portal_media_auto_recovery() (+30 more)

### Community 3 - "devDependencies"
Cohesion: 0.07
Nodes (29): autoprefixer, dependencies, next, react, react-dom, devDependencies, autoprefixer, postcss (+21 more)

### Community 4 - "compilerOptions"
Cohesion: 0.07
Nodes (26): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+18 more)

### Community 5 - "app/page.tsx"
Cohesion: 0.15
Nodes (20): ActivityLogsPage(), formatTimestamp(), DashboardPage(), ActivityLog, ActivityStats, deleteTemplates(), deleteTemplatesFromFile(), fetchActivityLogs() (+12 more)

### Community 6 - "compute_ops_dashboard_metrics"
Cohesion: 0.17
Nodes (12): get_moengage_ops_dashboard(), Get aggregated MoEngage Operations KPI metrics, channel breakdowns, and…, Upload and ingest a raw campaign export file (ZIP/CSV/XLSX) downloaded directly…, upload_moengage_export_endpoint(), compute_ops_dashboard_metrics(), Compute executive overview, channel breakdown, and vertical breakdowns…, Verify exact match to user's MoEngage screenshot counts: SMS 15, WA 13, RCS 4,…, Verify parse_moengage_export_file extracts and parses all CSVs in a MoEngage… (+4 more)

### Community 7 - "Karix WhatsApp Template Whitelisting — Project Rules"
Cohesion: 0.18
Nodes (10): Auth model — known limitation, Bajaj account constants, Bajaj vs Tata Capital — strict separation, File responsibilities, Karix API quirks — do NOT "clean up", Karix WhatsApp Template Whitelisting — Project Rules, Likely next steps (for planning context), Scope boundaries (+2 more)

### Community 8 - "moengage_mcp.py"
Cohesion: 0.07
Nodes (53): call_mcp_tool(), complete_mcp_oauth(), ensure_mcp_initialized(), extract_moe_bearer_from_mcp_token(), get_mcp_config(), get_mcp_status(), get_or_refresh_moe_bearer(), list_mcp_tools() (+45 more)

### Community 9 - "moengage_preview.py"
Cohesion: 0.14
Nodes (31): preview_moengage_drafts_file_endpoint(), Preview CSV/XLSX rows in memory, preserving their physical source identities., _parse_excel_key_value_blocks(), Parse Excel sheets with Title: and Body: message blocks. e.g. RCS App…, _asset(), _audience(), _email(), _https_url() (+23 more)

### Community 10 - "AGENTS.md"
Cohesion: 0.40
Nodes (4): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution

### Community 17 - "TemplateSubmission"
Cohesion: 0.17
Nodes (71): AccountCreate, AgentChatRequest, AiRebalanceRequest, BulkTicketTransferRequest, DeleteTemplatesRequest, DispatchAlertsRequest, GeminiTestRequest, IdentifyJsonRequest (+63 more)

### Community 18 - "rcs_loader.py"
Cohesion: 0.05
Nodes (60): _build_rcs_carousel_vi_template(), _build_rcs_clean_suggestions(), _build_rcs_richcard_vi_template(), _build_rcs_save_payload(), _build_rcs_text_vi_template(), _build_single_suggestion(), _ensure_url_variable(), _extract_and_number_rcs_variables() (+52 more)

### Community 19 - "KarixHealthGovernor"
Cohesion: 0.22
Nodes (7): KarixHealthGovernor, Working Memory: Tracks real-time Karix API response latency and error rates to…, Dynamically calculate optimal worker pool size: - Healthy (< 1.8s avg latency,…, Return an optional inter-request delay in seconds based on server load., Return real-time working memory metrics., Verify KarixHealthGovernor tracks latency and throttles concurrency during high…, test_adaptive_rate_limiting_and_governor()

### Community 20 - "Quick Start"
Cohesion: 0.20
Nodes (9): Design & Style Guidelines, Quick Start, Reference, Step 1: Initialize Project, Step 2: Develop Your Artifact, Step 3: Bundle to Single HTML File, Step 4: Share Artifact with User, Step 5: Testing/Visualizing the Artifact (Optional) (+1 more)

### Community 21 - "api.py"
Cohesion: 0.03
Nodes (147): Register a new operator profile or update timestamp., register_or_update_user(), agent_chat_endpoint(), ai_rebalance_workload_endpoint(), assign_unassigned_to_neel_endpoint(), _authorize_moengage_preview(), _build_rcs_credentials_mapping(), _build_sms_credentials_mapping() (+139 more)

### Community 22 - "Frontend Design"
Cohesion: 0.29
Nodes (6): Design principles, Frontend Design, Ground it in the subject, More on writing in design, Process: brainstorm, explore, plan, critique, build, critique again, Restraint and self-critique

### Community 23 - "CLAUDE.md"
Cohesion: 0.33
Nodes (4): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution

### Community 24 - "QueueManager"
Cohesion: 0.12
Nodes (12): Any, QueueManager, Get or initialize the isolated token bucket for a tenant's WABA., Check if tenant's circuit breaker is currently active (paused on 401)., Trip the circuit breaker on 401 Session Expired: - Halts tenant's queue - Flips…, Broadcast an SSE event payload to all active client listeners., Spawn asynchronous background task to execute all pending tasks in the job., Background worker processing tasks through fair-share rate limiter and handling… (+4 more)

### Community 25 - "test_moengage_draft_creation.py"
Cohesion: 0.24
Nodes (14): FakeWriter, offline_db(), fixture, Offline V5 draft-create lifecycle: durability, read-back, validation and no-…, service(), test_create_route_requires_owner_approval_and_uses_server_catalog(), test_rate_limit_is_shared_by_workspace_not_account(), test_readback_failure_resumes_without_another_create() (+6 more)

### Community 26 - "TestMultiTenantAuth"
Cohesion: 0.13
Nodes (7): Comprehensive Multi-Tenant Authentication & Strict Tenant Isolation Tests.…, AI Copilot blocks cross-tenant query attempts for locked operators., Verify user signup binds to selected tenant and login returns signed JWT., Invalid credentials return 401 Unauthorized., Attempting to signup with existing email returns 400 Bad Request., Critical Multi-Tenant Isolation Check: Bajaj operator CANNOT access Tata…, TestMultiTenantAuth

### Community 27 - "MoEngage Campaign Creation Agent — Architectural Specification & Research Dossier"
Cohesion: 0.04
Nodes (43): 1.1 What This System Is, 1.2 Strict Separation from WhatsApp Whitelisting, 1.3 Inviolable Safety Constraint: STRICTLY DRAFT-ONLY, 1. Executive Summary & Scope Boundaries, 2.1 Channel Capability Matrix, 2.2 API Rate Limits (Enforced by MoEngage Gateway), 2. MoEngage Primary API & MCP Research Findings, 3.1 OAuth 2.0 (MCP Server — 30-Day Session) (+35 more)

### Community 28 - "db.py"
Cohesion: 0.18
Nodes (15): get_activity_summary(), init_store(), load_activities(), Activity tracker & User Identity Manager: Stores all user operations (template…, Query activities from SQLite with filtering, search, and unlimited pagination., Calculate instant live metrics across all team members and activities., Initialize database tables, indexes, and migrate existing JSONL logs., init_auth_db() (+7 more)

### Community 29 - "_load_env_file"
Cohesion: 0.08
Nodes (40): get_credentials(), _account_prefix(), _esmeaddr_from_session_token(), get_esmeaddr(), get_official_auth_headers(), get_portal_auth_headers(), get_template_namespace_id(), get_waba_id() (+32 more)

### Community 30 - "route.ts"
Cohesion: 0.25
Nodes (6): DELETE, dynamic, GET, maxDuration, POST, PUT

### Community 31 - "sms_loader.py"
Cohesion: 0.10
Nodes (32): preview_sms_file_endpoint(), Send single or batch SMS messages directly via JSON. Supports plain or AES-256…, Preview SMS messages from uploaded CSV or Excel file., send_sms_api_endpoint(), get_sms_dlt_entity_id(), get_sms_sender_id(), Return the registered DLT sender ID / header name for this account., Return the DLT Entity ID for this client. (+24 more)

### Community 32 - "moengage_sync.py"
Cohesion: 0.06
Nodes (50): AttributeMappingResult, check_semantic_duplicate_pair(), DuplicateCheckResult, find_semantic_duplicate(), MoEngageTemplateTranslation, Any, Evaluate whether a candidate template semantically duplicates an existing…, Search a list of existing MoEngage templates to find if candidate template is a… (+42 more)

### Community 33 - "require_tenant_access"
Cohesion: 0.10
Nodes (34): log_activity(), Log an event permanently into SQLite and append to JSONL. Automatically updates…, _clean_error_message(), delete_templates_from_file(), _fetch_whatsapp_inventory(), fetch_whatsapp_templates(), _filter_and_sort_templates(), get_stats() (+26 more)

### Community 34 - "send_sms"
Cohesion: 0.27
Nodes (6): Session, Send a batch of SMS messages to the Karix SMS JSON API., send_sms(), patch, Test SMS client sending with mocked HTTP., TestSmsClient

### Community 35 - "list_jira_issues"
Cohesion: 0.12
Nodes (27): api_route, _handle_agent_jira_inquiry(), get_public_media(), Serve cached template header images/videos/documents directly to Karix, Meta,…, add_jira_comment(), adf_to_text(), compute_brief_status(), download_jira_attachment() (+19 more)

### Community 36 - "jira_extractor.py"
Cohesion: 0.15
Nodes (12): ExtractedTemplateComponent, JiraExtractionResult, JiraRoutingDecision, Any, TypeSafe AI Semantic Jira Brief & Template Extractor. Analyzes free-form Jira…, Parse free-form text into Header, Body, Footer, and Button components using…, Channel and purpose routing determination for a Jira brief., Structured components extracted from a Jira description. (+4 more)

### Community 38 - "test_production_smoke.py"
Cohesion: 0.15
Nodes (12): Production Deployment & Docker Configuration Smoke Tests. Validates: - Health…, Verify production webhook connectivity: - Rejects unauthorized calls without…, Verify production uptime monitor endpoints respond with 200 OK., - Multi-stage build (frontend-builder + Python runner) - Supervisord running…, Verify signup creates a user and login returns a usable JWT., Verify SQLite store runs in WAL mode with normal sync and 5000ms busy timeout,…, setup_module(), test_auth_signup_and_login_contract() (+4 more)

### Community 39 - "template_validator.py"
Cohesion: 0.17
Nodes (15): async_validate_template_semantic_quality(), _build_typesafe_questions(), _determine_risk_level(), _process_typesafe_response(), Any, TypeSafe AI Semantic Template Validator for Meta WhatsApp & RCS. Uses TypeSafe…, Detailed outcome of a TypeSafe System One pre-submission inspection., Perform asynchronous pre-submission validation with TypeSafe System One.… (+7 more)

### Community 40 - "extract_template_from_jira_text"
Cohesion: 0.12
Nodes (19): extract_template_from_jira_text(), generate_compliant_variable_samples(), Determine target channel (WHATSAPP, RCS, SMS, MULTI_CHANNEL) and campaign…, Generate calibrated, Meta-compliant sample values for variables ({{1}}, {{2}},…, Extract structured template components, routing decision, and variable samples…, route_jira_brief(), Unit and integration tests for TypeSafe AI Jira Description & Template…, Verify briefing_parser.parse_jira_brief processes free-form description end-to-… (+11 more)

### Community 41 - "fetchWithRetry"
Cohesion: 0.13
Nodes (42): ChannelCounts, DashboardData, MoEngageOpsPage(), VerticalData, WorkspaceItem, callMoEngageMcpTool(), createAccount(), deleteAccount() (+34 more)

### Community 42 - "get_db"
Cohesion: 0.14
Nodes (22): get_all_users(), Return all registered operator accounts sorted by last active., get_db(), _clean_sql_str(), create_job_with_tasks(), get_job_task(), list_paused_jobs(), migrate_legacy_jsonl_if_needed() (+14 more)

### Community 43 - "is_valid_template_copy"
Cohesion: 0.10
Nodes (26): Test connectivity to Google Gemini 3.1 Flash-Lite AI Studio API., test_gemini_endpoint(), decompose_content(), detect_category(), detect_language(), is_valid_template_copy(), Validate that a spreadsheet cell contains genuine customer-facing template…, Detect language code (e.g. 'en', 'gu', 'hi', 'pa', 'mr', 'bn', 'ta', 'te',… (+18 more)

### Community 44 - "api.ts"
Cohesion: 0.10
Nodes (26): JiraBriefsPage(), AccountDetection, AlertsDispatchOptions, AspectRatioWarning, AuthResponse, ComplianceWarning, delay(), DeleteTemplatesResult (+18 more)

### Community 45 - "test_moengage_ops.py"
Cohesion: 0.17
Nodes (11): Unit and integration tests for MoEngage Operations Dashboard & Scoping Engine.…, Verify test, copy, and duplicate keywords are flagged as test campaigns., Verify zip parsing skips __MACOSX, .DS_Store, and non-CSV files., Verify ingest_moengage_export_file processes zip archive and updates…, Verify POST /api/moengage/ops/upload-export accepts ZIP file and returns…, Verify campaign naming conventions accurately resolve to target business…, test_infer_vertical_from_name(), test_ingest_moengage_export_file_zip() (+3 more)

### Community 46 - "TestSmsApiEndpoints"
Cohesion: 0.15
Nodes (9): Convenience helper to send a single message to one or more mobile numbers., send_quick_sms(), Outcome of sending an SMS request to Karix., SmsSendResponse, Test FastAPI SMS endpoints via TestClient., Test Karix plain JSON DLR callback., Test Karix SMS Click report callback., Test downloading sample CSV for channel=sms. (+1 more)

### Community 47 - "sms_models.py"
Cohesion: 0.08
Nodes (22): decrypt_sms_pii(), _derive_aes_key(), encrypt_sms_pii(), Cryptographic utilities for Karix SMS API integration. Implements: 1. AES-256…, Encrypt a text string (mobile number or message content) using AES-256 CBC.…, Decrypt an encrypted PII string (mobile number or message content). Matches…, StrEnum, Data models for the Karix SMS JSON API integration. Includes dataclasses and… (+14 more)

### Community 48 - "sms_tracker.py"
Cohesion: 0.11
Nodes (30): get_sms_logs_endpoint(), _merge_sms_templates(), Karix SMS Delivery Report (DLR) Forwarding via HTTPs Callback API. Supports…, Karix SMS Click Report Webhook Callback. Logs URL link clicks from shortened…, Query logged SMS submissions, delivery reports (DLR), and click events., Initiate OAuth 2.0 + PKCE flow against https://moeauth.moengage.com for…, receive_sms_click_webhook(), receive_sms_dlr_webhook() (+22 more)

### Community 49 - "test_template_identifier.py"
Cohesion: 0.14
Nodes (13): Tests for Phase 1 WhatsApp & RCS Template Identification Engine. Verifies…, Verify templates existing on WABA but with modified body classify as…, Verify live PENDING and REJECTED statuses are classified correctly., Verify POST /api/templates/identify-json returns expected identification…, Verify POST /api/templates/search-by-content endpoint returns matching template…, Verify master templates matching live approved templates classify as…, Verify templates not present on live WABA classify as NOT_WHITELISTED., test_api_identify_json_endpoint() (+5 more)

### Community 50 - "transfer_jira_ticket"
Cohesion: 0.18
Nodes (14): bulk_transfer_jira_tickets(), clear_operational_assignment(), Reassign a ticket: - If target is Soham Das or Aadya (or any user without a…, Reassign multiple Jira tickets in batch and post audit handover notes., save_operational_assignment(), transfer_jira_ticket(), Verify transfer_jira_ticket calls Atlassian API for licensed Jira users., Verify bulk_transfer_jira_tickets iterates across issues, reassigns, and audits. (+6 more)

### Community 51 - "fetch_assignable_jira_users"
Cohesion: 0.18
Nodes (12): assign_unassigned_tickets_to_neel(), fetch_assignable_jira_users(), get_all_allocation_settings(), JiraUser, Return dictionary of member_name -> is_active_for_allocation (defaulting to…, Team member profile and active capacity metrics., Fetch assignable users strictly scoped to the active team members., Find all unassigned tickets in Jira across project(s) and reassign them to Neel… (+4 more)

### Community 52 - "agent.py"
Cohesion: 0.09
Nodes (36): _check_agent_tenant_isolation(), _handle_agent_content_search(), _handle_agent_copy_lint(), _handle_agent_fallback_guidance(), _handle_agent_help_inquiry(), _handle_agent_learning_inquiry(), _handle_agent_list_templates(), _handle_agent_rejection_diagnosis() (+28 more)

### Community 53 - "DraftWriter"
Cohesion: 0.09
Nodes (24): get_database_url(), is_postgres(), Retrieve normalized PostgreSQL database URL or empty string if using SQLite., Check if PostgreSQL driver is actively configured., _matches(), Any, Single-row V5 draft creation with durable identity, conservative rate caps, and…, Never reissue an attempted POST, including after timeout or process crash. (+16 more)

### Community 54 - "get_job_tasks"
Cohesion: 0.10
Nodes (21): get_job_endpoint(), Fetch status and per-template tasks for an asynchronous ingestion job., get_job_tasks(), Fetch all tasks for a specific job., Monotonic approval state machine: Only advances state forward. Rejects…, update_template_approval_monotonic(), Verify full diagnose and auto-resubmit workflow: - Enqueues into ingestion_jobs…, test_copilot_diagnose_and_auto_resubmit_integration() (+13 more)

### Community 55 - "4. Historical Error Incident Catalog"
Cohesion: 0.10
Nodes (19): 1. How to View & Inspect Errors, 2. How the AI Agent Uses the Error Log, 3. How Errors Are Recorded Over Time, 4. Historical Error Incident Catalog, Central Error Log & Diagnostic Engine, Incident 10: `Text Template Overridden to Rich Card Stand Alone with Image`, Incident 11: `PostbackData Lowercasing and Underscore Mismatch`, Incident 12: `Hashtag Variables (#var#) Not Extracted as Placeholders` (+11 more)

### Community 56 - "DBConnection"
Cohesion: 0.08
Nodes (14): DBConnection, DBCursor, migrate_sqlite_to_postgres(), Any, Path, Unified cursor wrapper supporting dict and tuple indexing., Unified database connection wrapper across SQLite and PostgreSQL., Copy all table data from a local SQLite database file into PostgreSQL. Safely… (+6 more)

### Community 57 - "test_work_manager.py"
Cohesion: 0.07
Nodes (27): categorize_status(), Classify arbitrary Jira status into PENDING, BLOCKED, or DONE., Unit and integration tests for Jira Work Management & Autonomous Workload…, Verify TATA Service and wealth Campaign Manager (SWCM) project queries and…, Verify combined querying across all Tata projects (ALL)., Verify cycle time calculations, operator turnaround velocity, and roadblock…, Verify GET /api/work-management/turnaround-analytics returns expected analytics…, Verify POST /api/work-management/bulk-transfer accepts batch reassignments. (+19 more)

### Community 58 - "submit_rcs_template"
Cohesion: 0.10
Nodes (23): Submit extracted WhatsApp and/or RCS templates from a Jira brief directly to…, submit_jira_brief_endpoint(), Submit one RCS template to the official Karix RCS Bot Builder Template API., submit_rcs_template(), load_rcs_from_list(), Load from a list of dicts already in memory., Data models for Karix RCS Bot Builder & DLT template submissions. Storage-…, RCS Runner: wires rcs_loader -> rcs_client -> rcs_tracker together. Entry point… (+15 more)

### Community 59 - "submit/page.tsx"
Cohesion: 0.17
Nodes (16): ACCEPTED_EXTENSIONS, formatBytes(), isAcceptedFile(), State, SubmitPage(), fetchJob(), getSampleCsvUrl(), IdentificationReport (+8 more)

### Community 60 - "_parse_excel_channel_sheets"
Cohesion: 0.14
Nodes (13): detect_sheet_month(), _match_sheet_channel(), _parse_excel_channel_sheets(), _parse_excel_grid_messages(), Parse Excel sheets where copy spans multiple contiguous rows and Column 0…, should_skip_sheet(), Unit tests for Excel spreadsheet parser enhancements in briefing_parser.py.…, Verify sheet channel matcher recognizes common client naming variations. (+5 more)

### Community 61 - "useApp"
Cohesion: 0.12
Nodes (18): inter, metadata, LoginPage(), SignupPage(), AppShell(), ChatMessage, ChatWidget(), DEFAULT_SUGGESTED_PROMPTS (+10 more)

### Community 62 - "context.tsx"
Cohesion: 0.18
Nodes (15): Banner, SettingsPage(), Account, AccountItem, AuthUser, Channel, clearAuthToken(), fetchTeam() (+7 more)

### Community 63 - "normalize_placeholders"
Cohesion: 0.19
Nodes (13): normalize_placeholders(), Convert informal Jira placeholders (<xxx>, <name>, [Loan Amount], [ROI],…, Unit tests for placeholder normalization in briefing_parser.py. Verifies: 1.…, Verify various square bracket parameters are converted to sequential {{1}},…, Verify that existing {{1}} placeholders mixed with <name> do not produce…, Verify duplicate and out-of-order placeholders are re-indexed strictly 1..N., Verify markdown links and CTA keywords in brackets are not replaced with {{1}}., Verify {#alphanumeric#} and DLT hash placeholders are converted to {{1}}. (+5 more)

### Community 64 - "extract_and_strip_cta"
Cohesion: 0.12
Nodes (21): extract_and_strip_cta(), Identify and extract the Call-to-Action (CTA) line from a message body,…, Unit tests for CTA extraction, removal from body, and default URL fallback…, Verify CTA line with variable (e.g. 'CTA {{4}}') is extracted and stripped from…, Verify exact body from TCN-524 screenshot removes CTA line and sets button URL…, Verify 'CTA: Apply Online -> https://tatacapital.com/pl' extracts label and URL., Verify 'CTA: Apply Now' without URL extracts label and uses default URL., Verify 'Tap to proceed ⬇' is stripped from body and populates button. (+13 more)

### Community 65 - "work-management/page.tsx"
Cohesion: 0.12
Nodes (23): JiraUserItem, OperatorVelocityItem, RoadblockTicketItem, TransferProposal, TurnaroundAnalyticsData, WorkItem, WorkManagementData, WorkManagementPage() (+15 more)

### Community 66 - "_parse_raw_sheet_rows"
Cohesion: 0.17
Nodes (12): _identify_sheet_columns(), is_cta_cell(), is_pure_cta_cell(), _is_targeting_or_planner_row(), _normalize_channel_tag(), _parse_raw_sheet_rows(), Check if a cell is purely a CTA button or link without body copy., Normalize any string (e.g. 'WhatsApp', 'WA', 'RCS', 'SMS Promotional') to… (+4 more)

### Community 67 - "work_manager.py"
Cohesion: 0.14
Nodes (22): ai_rebalance_workload(), get_all_operational_assignments(), get_turnaround_and_bottleneck_analytics(), get_work_management_dashboard(), _init_operational_assignments_db(), OperatorVelocity, Any, Jira Work Management & Autonomous Workload Dispatcher Engine. Connects to… (+14 more)

### Community 68 - "moengage_ops_client.py"
Cohesion: 0.20
Nodes (15): _extract_rows_from_file_bytes(), _infer_vertical_from_context(), ingest_moengage_export_file(), _is_attributics_author(), parse_moengage_export_file(), _parse_single_moengage_data_rows(), Any, Path (+7 more)

### Community 69 - "fetch_workspace_campaigns"
Cohesion: 0.21
Nodes (10): fetch_workspace_campaigns(), fetch_workspace_flows(), _infer_vertical_from_name(), _is_test_campaign(), Check if campaign name indicates a test, copy, or duplicate., Infer vertical from campaign naming patterns matching Excel formulas., Fetch campaigns and flow nodes from a MoEngage workspace using POST…, Fetch automated customer journey flows from MoEngage using POST… (+2 more)

### Community 70 - "log_error"
Cohesion: 0.08
Nodes (41): _handle_agent_error_inquiry(), get_system_errors(), Retrieve error logs for debugging and agent remediation., diagnose_error_with_learning(), learn_from_error(), LearnedPattern, load_learned_patterns(), _lock() (+33 more)

### Community 71 - "test_jira_brief_endpoint.py"
Cohesion: 0.09
Nodes (25): patch, Tests for Jira brief inspection endpoint (/api/jira/brief/{issue_key}).…, Verify that submit endpoint preserves TEXT headers, footers, and…, Verify /api/jira/projects returns full Tata Capital project catalog., Verify SWCM-59 parses .docx into 3 UTILITY WhatsApp templates with headers and…, Verify SWCM-61 key-value metadata table emits 0 WhatsApp templates and…, Verify channel_counts breakdown is computed on Jira briefs., Verify SWCM-85 single-header execution table extracts WhatsApp template even… (+17 more)

### Community 72 - "find_template_by_content"
Cohesion: 0.12
Nodes (18): compute_text_similarity(), evaluate_semantic_equivalence_typesafe(), find_template_by_content(), normalize_template_text(), Normalize template text for comparison: - Collapses variable placeholders…, Compute normalized text similarity ratio (0.0 to 1.0)., Use TypeSafe System One (Noul primitive) to determine if two template bodies…, Search Karix / WABA live inventory to detect if the given body text or content… (+10 more)

### Community 73 - "dispatch_due_today_alerts"
Cohesion: 0.16
Nodes (14): dispatch_due_today_alerts(), Dispatch SLA alerts strictly via Google Chat Space and/or Direct Email.…, Unit and API integration tests for the Automated 3-Stage Daily SLA Email…, Verify dispatch_due_today_alerts in dry-run mode returns draft summaries…, Client-owned blockers must not count against an operator at any SLA checkpoint., Verify FastAPI preview, dispatch, and scheduler endpoints., Verify dispatch_due_today_alerts rejects out-of-window requests unless…, Verify incomplete tickets are grouped by assignee and resolved to corporate… (+6 more)

### Community 74 - ".sse_event_stream"
Cohesion: 0.25
Nodes (6): Server-Sent Events (SSE) stream yielding real-time per-task progress and job…, stream_job_endpoint(), Subscribe an SSE connection to live job events., Remove an SSE connection subscriber., Yield Server-Sent Events for a job until it settles or client disconnects., Queue

### Community 75 - "loader.py"
Cohesion: 0.07
Nodes (50): _bind_embedded_media_to_row(), _build_single_cell_card_submission(), _canonicalize_dynamic_row(), _detect_media_kind(), _dynamic_body_value(), _dynamic_key(), _dynamic_row_to_submission(), _dynamic_template_name() (+42 more)

### Community 76 - "fetch_mcp_ops_records"
Cohesion: 0.23
Nodes (12): _compute_week_start(), fetch_mcp_ops_records(), get_date_range_bounds(), _parse_flex_date(), Compute the Monday work-week start for a given date., Fetch campaigns and flows via the MoEngage MCP Server…, Calculate effective start and end dates matching the Excel Dashboard formulas., Parse various date formats from MoEngage exports into a datetime.date. (+4 more)

### Community 77 - "_build_official_create_body"
Cohesion: 0.25
Nodes (8): _build_official_create_body(), normalize_whatsapp_text_variables(), Build the documented JSON body for POST /api/v1.0/template/{wabaId}. Portal-…, Normalize non-standard variable tags into official WhatsApp sequential…, Ensure any BODY or BUTTON component containing variables ({{1}}, {{2}}, <name>,…, _resolve_body_variables(), _resolve_button_cta_variables(), Verify that variable normalization and CTA examples generate Tata Capital…

### Community 78 - "runner.py"
Cohesion: 0.11
Nodes (29): poll(), load_from_list(), classify_template_category_sla(), get_pending_templates_sla_insights(), poll_pending(), Runner: wires loader -> client -> tracker together for WhatsApp templates.…, Phase 2, step 1: submit each template, log the attempt., Phase 2, step 2: check approval status for everything still pending. ONE remote… (+21 more)

### Community 79 - "datetime"
Cohesion: 0.22
Nodes (13): Get current state of the automated 10am/1pm/4pm IST alert scheduler., scheduler_status_endpoint(), determine_current_stage(), get_current_ist_time(), is_stage_within_window(), Return the current time in Indian Standard Time (IST, UTC+5:30)., Check whether the requested stage is currently within its scheduled delivery…, Determine the appropriate stage based on current IST time: - Before 11:30 AM… (+5 more)

### Community 81 - "decrypt_dlr_gcm"
Cohesion: 0.20
Nodes (10): decrypt_dlr_gcm(), encrypt_dlr_gcm(), _normalize_iv_bytes(), _normalize_key_bytes(), Normalize key string or bytes to standard AES key length (16, 24, or 32 bytes)., Normalize IV string or bytes for GCM (standard 12 or 16 bytes)., Encrypt JSON DLR payload string using AES in GCM mode. Per Karix DLR…, Decrypt an AES-GCM encrypted DLR payload from Karix. - Base64 decodes the… (+2 more)

### Community 82 - "validate_template_semantic_quality"
Cohesion: 0.10
Nodes (28): _inspect_single_submission(), lint_and_fix_body(), _lint_meta_variable_rules(), _lint_punctuation_and_caps(), _lint_repeated_and_typos(), Grammar, Spelling & Meta Template Quality Linter. Detects repeated words,…, Analyze text for grammatical mistakes, repeated words, spelling typos,…, Validate technical Meta WhatsApp and RCS compliance rules (Semantic Memory).… (+20 more)

### Community 83 - "update_moengage_ops_workspace"
Cohesion: 0.25
Nodes (8): get_moengage_ops_workspaces(), List registered MoEngage workspaces for ops reporting., Add or update a MoEngage workspace configuration., update_moengage_ops_workspace(), load_workspace_configs(), Load configured MoEngage workspaces from disk or fall back to defaults., Save workspace configs to disk., save_workspace_configs()

### Community 84 - "AlertEmailDraft"
Cohesion: 0.28
Nodes (8): AlertEmailDraft, Prepared email ready for dispatch., Send one draft email via SMTP. Falls back gracefully to simulation if SMTP is…, Unified outbound email delivery: 1. Resend API (HTTPS Port 443) if…, send_email_dispatcher(), send_email_smtp(), Verify safe fallback to simulation mode when SMTP credentials are not…, test_send_email_smtp_simulation_fallback()

### Community 85 - "get_job"
Cohesion: 0.29
Nodes (7): Resume a job currently paused due to auth expiration (PAUSED_FOR_AUTH)., resume_job_endpoint(), get_job(), Fetch job summary by ID., Event-bus auto-resume trigger called when operator updates/tests credentials in…, Verify PAUSED_FOR_AUTH circuit tripping and event-bus auto-resume., test_circuit_breaker_paused_for_auth_and_auto_resume()

### Community 86 - "NormalizedOpsRecord"
Cohesion: 0.31
Nodes (9): export_ops_dashboard_excel(), load_cached_ops_records(), NormalizedOpsRecord, Fetch all campaigns and flows across MoEngage MCP and registered workspaces and…, Load cached operations records, or trigger sync if cache is empty., Populate Master Data sheet in MoEngage_Ops_Dashboard.xlsx with live normalized…, sync_all_moengage_ops(), Verify live export into Master Data sheet of MoEngage_Ops_Dashboard.xlsx. (+1 more)

### Community 87 - "infer_channel_from_name_or_raw"
Cohesion: 0.33
Nodes (6): infer_channel_from_name_or_raw(), _normalize_channel_name(), Map MoEngage channel strings and node labels to standard dashboard channels., Map channel using both MoEngage raw channel tag and standard campaign name…, Verify raw MoEngage channel strings map to canonical dashboard channels., test_normalize_channel_name()

### Community 88 - "_is_retryable"
Cohesion: 0.50
Nodes (4): _is_retryable(), Exception, Response, Return True only for transport-level failures we should retry.

### Community 89 - "derive_clean_card_title"
Cohesion: 0.40
Nodes (5): derive_clean_card_title(), Derive card title / header title directly from the first line of the content…, Verify first line headline (e.g. '⚡ Funds in 24 Hours!') is used directly as…, test_rcs_card_title_derived_cleanly_from_body_topic(), test_rcs_card_title_uses_first_line_headline_without_fallback()

### Community 90 - "test_email_campaign_separation.py"
Cohesion: 0.33
Nodes (5): Unit tests for Email campaign separation from WhatsApp, RCS, and SMS. Verifies:…, Verify list_jira_issues tags email vs messaging campaigns., Verify parse_jira_brief isolates email templates from WhatsApp/RCS/SMS., test_list_jira_issues_separates_email_and_messaging(), test_parse_jira_brief_separates_email_templates()

### Community 91 - "extract_templates_from_excel_file"
Cohesion: 0.10
Nodes (24): extract_templates_from_excel_file(), _is_dlt_sms_sheet(), _parse_dlt_sms_sheet(), Detect if an Excel spreadsheet is an official DLT SMS template export., Parse official DLT SMS template spreadsheet rows into canonical SMS template…, Inspect and extract template items from any client spreadsheet (.xlsx, .csv,…, Path, Unit tests for universal attached spreadsheet parser and Jira comments revision… (+16 more)

### Community 92 - "OperatorTicketSummary"
Cohesion: 0.21
Nodes (12): build_stage_email(), OperatorTicketSummary, Group of due-today incomplete tickets assigned to an operator., Generate HTML and plain text email content tailored to the stage., Send an interactive rich card to Google Chat Space via Incoming Webhook. Uses…, send_google_chat_sla_alert(), Verify Google Chat fallback simulation when no webhook URL is configured., Verify Google Chat webhook POST request structure. (+4 more)

### Community 93 - "test_agent_remediation.py"
Cohesion: 0.10
Nodes (21): ContentSearchResult, Outcome of searching Karix template inventory by body copy / content., Tests for Autonomous AI Copilot Auto-Remediation Engine and Meta Policy…, Verify conversational chat interaction for rejection diagnosis and 1-click…, Verify AI Copilot can search existing Karix templates by body copy in natural…, Verify word-to-variable ratio remediation (Meta Error 2388293)., Pasting template copy alone should search the live Karix catalog., Plain sentence copy should also be treated as pasted template content. (+13 more)

### Community 95 - "AlertSchedulerState"
Cohesion: 0.25
Nodes (6): AlertSchedulerState, Persistent state of the automated daily alert scheduler backed by…, Verify AlertSchedulerState prevents duplicate sends for the same slot on the…, Verify AlertSchedulerState persists to DB and prevents duplicate dispatch on…, test_scheduler_db_persistence_deduplication(), test_scheduler_state_deduplication()

### Community 96 - "sms_client.py"
Cohesion: 0.12
Nodes (29): _prepare_payload_messages(), Any, Client for Karix SMS JSON API. Sends SMS messages (One-to-One, One-to-Many,…, Check configuration and reachability for the given account's SMS integration.…, Validate and sanitize a single message, returning cleaned destinations and…, Prepare all messages for the API request payload., _sanitize_message(), test_sms_connection() (+21 more)

### Community 97 - "Karix Multi-Channel Template Whitelisting & Automation Platform"
Cohesion: 0.22
Nodes (8): 1. Environment Configuration, 2. Local Development, 3. Docker Deployment, 🚀 Getting Started, Karix Multi-Channel Template Whitelisting & Automation Platform, 🏛 Multi-Channel Architecture, 📁 Repository Directory Structure, 🧪 Testing & Security Verification

### Community 98 - "infer_channel_from_summary"
Cohesion: 0.50
Nodes (4): infer_channel_from_summary(), Infer target messaging channel from ticket summary., Verify target channel is inferred from ticket title keywords., test_channel_inference_from_summary()

### Community 100 - "fetch_template_list"
Cohesion: 0.12
Nodes (18): get_jira_brief_endpoint(), karix_webhook_endpoint(), Real-time webhook receiver for Karix WhatsApp template status updates. Enforces…, Fetch and parse a Jira campaign brief into multi-channel template drafts., check_status(), fetch_template_list(), _match_template(), Fetch the full template list for a client's WABA (supports Portal API and… (+10 more)

### Community 101 - "Web Application Testing"
Cohesion: 0.25
Nodes (7): Best Practices, Common Pitfall, Decision Tree: Choosing Your Approach, Example: Using with_server.py, Reconnaissance-Then-Action Pattern, Reference Files, Web Application Testing

### Community 104 - "Karpathy Guidelines"
Cohesion: 0.33
Nodes (5): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution, Karpathy Guidelines

### Community 105 - "test_dashboard_data.py"
Cohesion: 0.33
Nodes (3): parametrize, Dashboard must distinguish an empty WABA from an unavailable Karix inventory., test_dashboard_retains_tenant_local_history_when_inventory_unavailable()

### Community 106 - "run_scheduler_loop"
Cohesion: 0.40
Nodes (5): Start the background scheduler task for 10am, 1pm, 4pm IST alert runs., start_alert_scheduler_task(), Background continuous scheduler loop. Checks IST time every 30 seconds and…, run_scheduler_loop(), on_event

### Community 108 - "email_notifier.py"
Cohesion: 0.22
Nodes (12): get_brevo_event_logs(), get_due_today_incomplete_tickets(), get_smtp_sender_info(), group_tickets_by_operator(), preview_due_today_alerts(), Any, Automated 3-Stage Daily SLA Email Dispatcher & Scheduler. Schedules &…, Return due-today operator work, excluding client-owned base/content blockers. (+4 more)

### Community 109 - "compute_timeline_bucket"
Cohesion: 0.50
Nodes (4): compute_timeline_bucket(), Calculate timeline bucket relative to today's date., Verify relative due dates are bucketed accurately relative to today., test_timeline_bucket_calculation()

## Knowledge Gaps
- **180 isolated node(s):** `moengage`, `moengage`, `dynamic`, `maxDuration`, `GET` (+175 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `parse_jira_brief()` connect `briefing_parser.py` to `extract_and_strip_cta`, `list_jira_issues`, `fetch_template_list`, `test_email_campaign_separation.py`, `test_jira_brief_endpoint.py`, `extract_template_from_jira_text`, `is_valid_template_copy`, `agent.py`, `api.py`, `derive_clean_card_title`, `submit_rcs_template`, `extract_templates_from_excel_file`, `normalize_placeholders`?**
  _High betweenness centrality (0.085) - this node is a cross-community bridge._
- **Why does `_load_env_file()` connect `_load_env_file` to `moengage_sync.py`, `list_jira_issues`, `jira_extractor.py`, `moengage_ops_client.py`, `work_manager.py`, `template_validator.py`, `moengage_mcp.py`, `is_valid_template_copy`, `email_notifier.py`, `agent.py`, `api.py`?**
  _High betweenness centrality (0.024) - this node is a cross-community bridge._
- **Why does `TemplateSubmission` connect `TemplateSubmission` to `submission_client.py`, `get_db`, `loader.py`, `_build_official_create_body`, `runner.py`, `test_template_identifier.py`, `KarixHealthGovernor`, `test_agent_remediation.py`, `api.py`, `QueueManager`, `submit_rcs_template`, `_load_env_file`, `TestCredentialContract`?**
  _High betweenness centrality (0.019) - this node is a cross-community bridge._
- **Are the 44 inferred relationships involving `TemplateSubmission` (e.g. with `AccountCreate` and `AgentChatRequest`) actually correct?**
  _`TemplateSubmission` has 44 INFERRED edges - model-reasoned connections that need verification._
- **What connects `moengage`, `moengage`, `dynamic` to the rest of the system?**
  _180 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `briefing_parser.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10476190476190476 - nodes in this community are weakly interconnected._
- **Should `auth.py` be split into smaller, more focused modules?**
  _Cohesion score 0.1341991341991342 - nodes in this community are weakly interconnected._