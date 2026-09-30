# Graph Report - karix  (2026-09-30)

## Corpus Check
- 114 files · ~280,154 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2097 nodes · 5128 edges · 116 communities (105 shown, 11 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 710 edges (avg confidence: 0.62)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7c73ff78`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- briefing_parser.py
- auth.py
- submission_client.py
- devDependencies
- compilerOptions
- app/page.tsx
- test_moengage_ops.py
- Karix WhatsApp Template Whitelisting — Project Rules
- moengage_mcp.py
- validate_template_semantic_quality
- AGENTS.md
- rules/graphify.md
- workflows/graphify.md
- next.config.mjs
- next-env.d.ts
- postcss.config.mjs
- tailwind.config.ts
- TemplateSubmission
- rcs_runner.py
- KarixHealthGovernor
- Quick Start
- get
- Frontend Design
- CLAUDE.md
- rcs_loader.py
- dispatch_due_today_alerts
- TestMultiTenantAuth
- TestSmsModels
- api.py
- _load_env_file
- route.ts
- sms_client.py
- moengage_sync.py
- require_tenant_access
- db.py
- jira_client.py
- load_sms_from_csv
- test_production_smoke.py
- test_enterprise_queue.py
- jira_extractor.py
- fetchWithRetry
- get_db
- decompose_content
- api.ts
- work_manager.py
- send_sms
- sms_models.py
- sms_tracker.py
- test_work_manager.py
- RcsTemplateSubmission
- test_unstructured_spreadsheet_decomposition.py
- agent.py
- identify_master_templates
- post
- 4. Historical Error Incident Catalog
- DBConnection
- get_work_management_dashboard
- activity_tracker.py
- submit/page.tsx
- test_excel_parser_gaps.py
- useApp
- context.tsx
- normalize_placeholders
- extract_and_strip_cta
- work-management/page.tsx
- TestSmsTracker
- transfer_jira_ticket
- ._process_job_tasks
- NormalizedOpsRecord
- error_learning.py
- test_jira_brief_endpoint.py
- find_template_by_content
- email_notifier.py
- QueueManager
- loader.py
- fetch_assignable_jira_users
- download_jira_attachment
- runner.py
- log_activity
- load_errors
- tool_diagnose_and_fix
- lint_and_fix_body
- test_agent_remediation.py
- Any
- fetch_workspace_campaigns
- ai_rebalance_workload
- get_stats
- moengage_ops_client.py
- fetch_mcp_ops_records
- _parse_single_moengage_data_rows
- test_attached_sheets_and_comments.py
- OperatorTicketSummary
- check_status
- Any
- AlertSchedulerState
- log_error
- Karix Multi-Channel Template Whitelisting & Automation Platform
- submit_template
- TestSmsApiEndpoints
- init_database
- Web Application Testing
- bulk_transfer_jira_tickets_endpoint
- infer_channel_from_name_or_raw
- Karpathy Guidelines
- test_dashboard_data.py
- run_scheduler_loop
- _prepare_payload_messages
- group_tickets_by_operator
- compute_timeline_bucket
- infer_channel_from_summary
- .is_delivered
- .is_failed
- mcp.json
- .mcp.json

## God Nodes (most connected - your core abstractions)
1. `_json_safe()` - 71 edges
2. `TemplateSubmission` - 69 edges
3. `getApiUrl()` - 68 edges
4. `fetchWithRetry()` - 68 edges
5. `getErrorMessage()` - 65 edges
6. `RcsTemplateSubmission` - 58 edges
7. `SmsMessage` - 55 edges
8. `SubmissionResult` - 49 edges
9. `parse_jira_brief()` - 48 edges
10. `TemplateComponent` - 44 edges

## Surprising Connections (you probably didn't know these)
- `test_email_brief_does_not_stage_push_but_explicit_push_brief_does()` --calls--> `parse_jira_brief()`  [INFERRED]
  tests/test_jira_brief_endpoint.py → backend/briefing_parser.py
- `setup_module()` --calls--> `init_queue_db()`  [INFERRED]
  tests/test_production_smoke.py → backend/db_queue.py
- `test_copilot_diagnose_and_auto_resubmit_integration()` --calls--> `tool_diagnose_and_fix()`  [INFERRED]
  tests/test_agent_remediation.py → backend/agent.py
- `test_mcp_api_endpoints()` --indirect_call--> `get_current_user()`  [INFERRED]
  tests/test_moengage_mcp.py → backend/auth.py
- `test_cta_line_removed_from_body_and_moved_to_button()` --calls--> `normalize_placeholders()`  [INFERRED]
  tests/test_cta_extraction_and_fallback.py → backend/briefing_parser.py

## Import Cycles
- None detected.

## Communities (116 total, 11 thin omitted)

### Community 0 - "briefing_parser.py"
Cohesion: 0.07
Nodes (58): clean_safelink(), _clean_template_name(), detect_sheet_month(), detect_ticket_month(), _extract_images_from_zip(), _extract_links_from_adf_node(), extract_templates_from_docx_file(), extract_templates_from_excel_file() (+50 more)

### Community 1 - "auth.py"
Cohesion: 0.09
Nodes (29): get_team_endpoint(), invite_team_member(), login_endpoint(), Register a new user account bound to a specific tenant organization., Authenticate user with email & password, returning signed JWT with tenant claim., List team members within user's assigned organization., Organization admins can onboard colleagues to their organization., signup_endpoint() (+21 more)

### Community 2 - "submission_client.py"
Cohesion: 0.12
Nodes (28): _init_media_cache(), _build_official_create_body(), _download_remote_media(), _ensure_default_sample_image(), _ensure_default_sample_pdf(), _ensure_default_sample_video(), _handle_portal_media_auto_recovery(), _is_tata_group() (+20 more)

### Community 3 - "devDependencies"
Cohesion: 0.07
Nodes (29): autoprefixer, dependencies, next, react, react-dom, devDependencies, autoprefixer, postcss (+21 more)

### Community 4 - "compilerOptions"
Cohesion: 0.07
Nodes (26): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+18 more)

### Community 5 - "app/page.tsx"
Cohesion: 0.15
Nodes (20): ActivityLogsPage(), formatTimestamp(), DashboardPage(), ActivityLog, ActivityStats, deleteTemplates(), deleteTemplatesFromFile(), fetchActivityLogs() (+12 more)

### Community 6 - "test_moengage_ops.py"
Cohesion: 0.12
Nodes (15): Unit and integration tests for MoEngage Operations Dashboard & Scoping Engine.…, Verify exact match to user's MoEngage screenshot counts: SMS 15, WA 13, RCS 4,…, Verify parse_moengage_export_file extracts and parses all CSVs in a MoEngage…, Verify test, copy, and duplicate keywords are flagged as test campaigns., Verify zip parsing skips __MACOSX, .DS_Store, and non-CSV files., Verify ingest_moengage_export_file processes zip archive and updates…, Verify POST /api/moengage/ops/upload-export accepts ZIP file and returns…, Verify campaign naming conventions accurately resolve to target business… (+7 more)

### Community 7 - "Karix WhatsApp Template Whitelisting — Project Rules"
Cohesion: 0.18
Nodes (10): Auth model — known limitation, Bajaj account constants, Bajaj vs Tata Capital — strict separation, File responsibilities, Karix API quirks — do NOT "clean up", Karix WhatsApp Template Whitelisting — Project Rules, Likely next steps (for planning context), Scope boundaries (+2 more)

### Community 8 - "moengage_mcp.py"
Cohesion: 0.07
Nodes (55): call_mcp_tool(), complete_mcp_oauth(), ensure_mcp_initialized(), extract_moe_bearer_from_mcp_token(), get_mcp_config(), get_mcp_status(), get_or_refresh_moe_bearer(), list_mcp_tools() (+47 more)

### Community 9 - "validate_template_semantic_quality"
Cohesion: 0.10
Nodes (28): async_validate_template_semantic_quality(), _build_typesafe_questions(), _determine_risk_level(), _process_typesafe_response(), Any, TypeSafe AI Semantic Template Validator for Meta WhatsApp & RCS. Uses TypeSafe…, Perform synchronous pre-submission validation with TypeSafe System One.…, Detailed outcome of a TypeSafe System One pre-submission inspection. (+20 more)

### Community 10 - "AGENTS.md"
Cohesion: 0.40
Nodes (4): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution

### Community 17 - "TemplateSubmission"
Cohesion: 0.26
Nodes (53): AccountCreate, AgentChatRequest, AiRebalanceRequest, BulkTicketTransferRequest, CredentialUpdate, DeleteTemplatesRequest, DispatchAlertsRequest, GeminiTestRequest (+45 more)

### Community 18 - "rcs_runner.py"
Cohesion: 0.12
Nodes (21): load_rcs_from_csv(), load_rcs_from_list(), Load RCS templates from a CSV file., Load from a list of dicts already in memory., RCS Runner: wires rcs_loader -> rcs_client -> rcs_tracker together. Entry point…, Submit each RCS DLT template, log the attempt., Load RCS templates from CSV or Excel file, submit each, and log attempt., run_rcs() (+13 more)

### Community 19 - "KarixHealthGovernor"
Cohesion: 0.22
Nodes (7): KarixHealthGovernor, Working Memory: Tracks real-time Karix API response latency and error rates to…, Dynamically calculate optimal worker pool size: - Healthy (< 1.8s avg latency,…, Return an optional inter-request delay in seconds based on server load., Return real-time working memory metrics., Verify KarixHealthGovernor tracks latency and throttles concurrency during high…, test_adaptive_rate_limiting_and_governor()

### Community 20 - "Quick Start"
Cohesion: 0.20
Nodes (9): Design & Style Guidelines, Quick Start, Reference, Step 1: Initialize Project, Step 2: Develop Your Artifact, Step 3: Bundle to Single HTML File, Step 4: Share Artifact with User, Step 5: Testing/Visualizing the Artifact (Optional) (+1 more)

### Community 21 - "get"
Cohesion: 0.05
Nodes (54): download_jira_creative_endpoint(), export_moengage_ops_excel_endpoint(), get_delivery_logs_endpoint(), get_jira_brief_projects_endpoint(), get_jira_issues_endpoint(), get_me_endpoint(), get_moengage_credentials_endpoint(), get_moengage_mcp_status_endpoint() (+46 more)

### Community 22 - "Frontend Design"
Cohesion: 0.29
Nodes (6): Design principles, Frontend Design, Ground it in the subject, More on writing in design, Process: brainstorm, explore, plan, critique, build, critique again, Restraint and self-critique

### Community 23 - "CLAUDE.md"
Cohesion: 0.33
Nodes (4): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution

### Community 24 - "rcs_loader.py"
Cohesion: 0.08
Nodes (45): _test_rcs_channel(), fetch_rcs_templates(), Submit one RCS template to the official Karix RCS Bot Builder Template API., Upload a binary image or video to Karix RCS media storage (gRBM). Returns the…, Fetch all live RCS templates for the bot ID from official Karix RCS endpoint:…, submit_rcs_template(), upload_rcs_media(), _account_prefix() (+37 more)

### Community 25 - "dispatch_due_today_alerts"
Cohesion: 0.14
Nodes (16): dispatch_due_today_alerts(), get_due_today_incomplete_tickets(), Return due-today operator work, excluding client-owned base/content blockers., Dispatch SLA alerts strictly via Google Chat Space and/or Direct Email.…, Unit and API integration tests for the Automated 3-Stage Daily SLA Email…, Verify dispatch_due_today_alerts in dry-run mode returns draft summaries…, Client-owned blockers must not count against an operator at any SLA checkpoint., Verify FastAPI preview, dispatch, and scheduler endpoints. (+8 more)

### Community 26 - "TestMultiTenantAuth"
Cohesion: 0.13
Nodes (7): Comprehensive Multi-Tenant Authentication & Strict Tenant Isolation Tests.…, AI Copilot blocks cross-tenant query attempts for locked operators., Verify user signup binds to selected tenant and login returns signed JWT., Invalid credentials return 401 Unauthorized., Attempting to signup with existing email returns 400 Bad Request., Critical Multi-Tenant Isolation Check: Bajaj operator CANNOT access Tata…, TestMultiTenantAuth

### Community 28 - "api.py"
Cohesion: 0.11
Nodes (28): _build_rcs_credentials_mapping(), _build_sms_credentials_mapping(), _build_wa_credentials_mapping(), _commit_credentials_to_github(), create_account(), delete_account(), get_account_name(), get_accounts() (+20 more)

### Community 29 - "_load_env_file"
Cohesion: 0.09
Nodes (42): _account_prefix(), _esmeaddr_from_session_token(), get_esmeaddr(), get_official_auth_headers(), get_portal_auth_headers(), get_template_namespace_id(), get_waba_id(), _load_env_file() (+34 more)

### Community 30 - "route.ts"
Cohesion: 0.25
Nodes (6): DELETE, dynamic, GET, maxDuration, POST, PUT

### Community 31 - "sms_client.py"
Cohesion: 0.10
Nodes (40): Karix SMS Delivery Report (DLR) Forwarding via HTTPs Callback API. Supports…, receive_sms_dlr_webhook(), Client for Karix SMS JSON API. Sends SMS messages (One-to-One, One-to-Many,…, Check configuration and reachability for the given account's SMS integration.…, test_sms_connection(), _account_prefix(), get_sms_api_url(), get_sms_auth_headers() (+32 more)

### Community 32 - "moengage_sync.py"
Cohesion: 0.06
Nodes (51): AttributeMappingResult, check_semantic_duplicate_pair(), DuplicateCheckResult, find_semantic_duplicate(), MoEngageTemplateTranslation, Any, TypeSafe AI MoEngage Semantic Resolver. Enhances the Karix-to-MoEngage sync and…, Evaluate whether a candidate template semantically duplicates an existing… (+43 more)

### Community 33 - "require_tenant_access"
Cohesion: 0.06
Nodes (42): agent_chat_endpoint(), delete_templates_from_file(), get_job_endpoint(), get_moengage_rcs_templates_endpoint(), get_sms_logs_endpoint(), get_sms_stats_endpoint(), get_system_errors(), identify_templates_endpoint() (+34 more)

### Community 34 - "db.py"
Cohesion: 0.12
Nodes (10): get_database_url(), is_postgres(), Path, Unified Database Adapter for Karix Whitelisting. Provides seamless dual-driver…, Retrieve normalized PostgreSQL database URL or empty string if using SQLite., Check if PostgreSQL driver is actively configured., _resolve_default_db_path(), main() (+2 more)

### Community 35 - "jira_client.py"
Cohesion: 0.12
Nodes (19): add_jira_comment(), adf_to_text(), extract_issue_templates(), fetch_jira_issue(), is_explicit_push(), Any, Atlassian Jira REST API Integration Client for Karix Whitelisting & Briefing…, Recursively convert Atlassian Document Format (ADF) into readable text with… (+11 more)

### Community 36 - "load_sms_from_csv"
Cohesion: 0.20
Nodes (7): load_sms_from_csv(), preview_sms_rows(), Path, Read SMS messages from a CSV file., Generate preview summaries for UI preview and validation., Test input normalization and loading from list/CSV., TestSmsLoader

### Community 38 - "test_production_smoke.py"
Cohesion: 0.15
Nodes (12): Production Deployment & Docker Configuration Smoke Tests. Validates: - Health…, Verify production webhook connectivity: - Rejects unauthorized calls without…, Verify production uptime monitor endpoints respond with 200 OK., - Multi-stage build (frontend-builder + Python runner) - Supervisord running…, Verify signup creates a user and login returns a usable JWT., Verify SQLite store runs in WAL mode with normal sync and 5000ms busy timeout,…, setup_module(), test_auth_signup_and_login_contract() (+4 more)

### Community 39 - "test_enterprise_queue.py"
Cohesion: 0.20
Nodes (9): Tests for Enterprise Hardened Queue, Per-WABA Rate Limiter, Circuit Breaker,…, Verify per-WABA token bucket consumption and dynamic 429 throttling., Verify POST /api/webhooks/karix/{tenant} - 401 on invalid/missing secret token…, Verify GET /api/jobs/{id} and POST /api/jobs/{id}/resume endpoints., Verify atomic creation of ingestion_jobs and job_tasks in SQLite., test_db_queue_atomic_job_and_tasks_creation(), test_job_management_endpoints(), test_rate_limiter_token_bucket_and_429_backoff() (+1 more)

### Community 40 - "jira_extractor.py"
Cohesion: 0.08
Nodes (31): extract_template_from_jira_text(), ExtractedTemplateComponent, generate_compliant_variable_samples(), JiraExtractionResult, JiraRoutingDecision, Any, TypeSafe AI Semantic Jira Brief & Template Extractor. Analyzes free-form Jira…, Parse free-form text into Header, Body, Footer, and Button components using… (+23 more)

### Community 41 - "fetchWithRetry"
Cohesion: 0.13
Nodes (42): ChannelCounts, DashboardData, MoEngageOpsPage(), VerticalData, WorkspaceItem, callMoEngageMcpTool(), createAccount(), deleteAccount() (+34 more)

### Community 42 - "get_db"
Cohesion: 0.12
Nodes (30): get_db(), _clean_sql_str(), create_job_with_tasks(), get_job(), get_job_task(), get_job_tasks(), list_paused_jobs(), migrate_legacy_jsonl_if_needed() (+22 more)

### Community 43 - "decompose_content"
Cohesion: 0.10
Nodes (27): decompose_content(), derive_clean_card_title(), detect_category(), detect_language(), Detect language code (e.g. 'en', 'gu', 'hi', 'pa', 'mr', 'bn', 'ta', 'te',…, Determine WhatsApp template category (UTILITY, AUTHENTICATION, MARKETING)., Decompose any raw template content into structured, ready-to-whitelist…, Derive card title / header title directly from the first line of the content… (+19 more)

### Community 44 - "api.ts"
Cohesion: 0.10
Nodes (26): JiraBriefsPage(), AccountDetection, AlertsDispatchOptions, AspectRatioWarning, AuthResponse, ComplianceWarning, delay(), DeleteTemplatesResult (+18 more)

### Community 45 - "work_manager.py"
Cohesion: 0.24
Nodes (11): get_jira_auth_headers(), get_jira_credentials(), list_jira_issues(), List issues in project (e.g. TCN) using Atlassian's /rest/api/3/search/jql API., Load Jira base URL, email, and API token from environment / credentials.json., Build Basic Auth headers for Atlassian Jira Cloud REST API v3., assign_unassigned_tickets_to_neel(), Jira Work Management & Autonomous Workload Dispatcher Engine. Connects to… (+3 more)

### Community 46 - "send_sms"
Cohesion: 0.19
Nodes (10): Session, Convenience helper to send a single message to one or more mobile numbers., Send a batch of SMS messages to the Karix SMS JSON API., send_quick_sms(), send_sms(), Outcome of sending an SMS request to Karix., SmsSendResponse, patch (+2 more)

### Community 47 - "sms_models.py"
Cohesion: 0.09
Nodes (23): decrypt_dlr_gcm(), decrypt_sms_pii(), _derive_aes_key(), encrypt_dlr_gcm(), encrypt_sms_pii(), _normalize_iv_bytes(), _normalize_key_bytes(), Cryptographic utilities for Karix SMS API integration. Implements: 1. AES-256… (+15 more)

### Community 48 - "sms_tracker.py"
Cohesion: 0.14
Nodes (24): Any, SMS Runner: orchestrates loading -> client submission -> tracker logging. Entry…, Load raw message dictionaries, submit them via Karix SMS API, and log the…, run_sms(), get_sms_stats(), load_sms_clicks(), load_sms_dlrs(), load_sms_submissions() (+16 more)

### Community 49 - "test_work_manager.py"
Cohesion: 0.12
Nodes (15): Unit and integration tests for Jira Work Management & Autonomous Workload…, Verify cycle time calculations, operator turnaround velocity, and roadblock…, Verify GET /api/work-management/turnaround-analytics returns expected analytics…, Verify bulk_transfer_jira_tickets iterates across issues, reassigns, and audits., Verify POST /api/work-management/bulk-transfer accepts batch reassignments., Verify POST /api/work-management/assign-unassigned reassigns unassigned tickets…, Verify only Dnyanesh, Neel, Mrunalini (and admin) are authorized to transfer…, Verify AI workload dispatcher evaluates context and proposes ticket… (+7 more)

### Community 50 - "RcsTemplateSubmission"
Cohesion: 0.11
Nodes (24): _build_rcs_carousel_vi_template(), _build_rcs_clean_suggestions(), _build_rcs_richcard_vi_template(), _build_rcs_save_payload(), _build_rcs_text_vi_template(), _build_single_suggestion(), _ensure_url_variable(), _extract_and_number_rcs_variables() (+16 more)

### Community 51 - "test_unstructured_spreadsheet_decomposition.py"
Cohesion: 0.25
Nodes (8): Path, Unit tests for Universal Unstructured Spreadsheet Decomposition Engine ("Arrive…, Verify that a single cell containing Header, Body, T&C, and CTA is decomposed., Verify arbitrary grid with no headers (A1, A2, B1, B2) extracts all templates., Verify CTA in a separate adjacent cell (B1 or A2) is attached to the body in A1., test_everything_in_one_cell_decomposition(), test_neighbor_cell_cta_attachment(), test_unformatted_grid_of_templates()

### Community 52 - "agent.py"
Cohesion: 0.12
Nodes (28): _check_agent_tenant_isolation(), _handle_agent_content_search(), _handle_agent_copy_lint(), _handle_agent_fallback_guidance(), _handle_agent_help_inquiry(), _handle_agent_jira_inquiry(), _handle_agent_learning_inquiry(), _handle_agent_list_templates() (+20 more)

### Community 53 - "identify_master_templates"
Cohesion: 0.15
Nodes (15): identify_master_templates(), Core identification engine: compares master templates against live Karix WABA…, Tests for Phase 1 WhatsApp & RCS Template Identification Engine. Verifies…, Verify templates existing on WABA but with modified body classify as…, Verify live PENDING and REJECTED statuses are classified correctly., Verify POST /api/templates/identify-json returns expected identification…, Verify POST /api/templates/search-by-content endpoint returns matching template…, Verify master templates matching live approved templates classify as… (+7 more)

### Community 54 - "post"
Cohesion: 0.06
Nodes (36): ai_rebalance_workload_endpoint(), assign_unassigned_to_neel_endpoint(), call_moengage_mcp_tool_endpoint(), dispatch_alerts_endpoint(), identify_templates_json_endpoint(), karix_webhook_endpoint(), Search Karix / Meta live template inventory by message body copy. Returns…, Resume a job currently paused due to auth expiration (PAUSED_FOR_AUTH). (+28 more)

### Community 55 - "4. Historical Error Incident Catalog"
Cohesion: 0.10
Nodes (19): 1. How to View & Inspect Errors, 2. How the AI Agent Uses the Error Log, 3. How Errors Are Recorded Over Time, 4. Historical Error Incident Catalog, Central Error Log & Diagnostic Engine, Incident 10: `Text Template Overridden to Rich Card Stand Alone with Image`, Incident 11: `PostbackData Lowercasing and Underscore Mismatch`, Incident 12: `Hashtag Variables (#var#) Not Extracted as Placeholders` (+11 more)

### Community 56 - "DBConnection"
Cohesion: 0.14
Nodes (9): DBConnection, DBCursor, migrate_sqlite_to_postgres(), Any, Unified cursor wrapper supporting dict and tuple indexing., Unified database connection wrapper across SQLite and PostgreSQL., Copy all table data from a local SQLite database file into PostgreSQL. Safely…, Translate SQLite-dialect SQL statements into PostgreSQL-compliant syntax. (+1 more)

### Community 57 - "get_work_management_dashboard"
Cohesion: 0.11
Nodes (18): categorize_status(), get_work_management_dashboard(), Categorized work ticket from Jira., Classify arbitrary Jira status into PENDING, BLOCKED, or DONE., Build the complete Work Management Dashboard: - Ingests Jira issues. -…, WorkItem, Verify TATA Service and wealth Campaign Manager (SWCM) project queries and…, Verify combined querying across all Tata projects (ALL). (+10 more)

### Community 58 - "activity_tracker.py"
Cohesion: 0.12
Nodes (19): get_activity_summary(), get_all_users(), init_store(), load_activities(), Activity tracker & User Identity Manager: Stores all user operations (template…, Query activities from SQLite with filtering, search, and unlimited pagination., Calculate instant live metrics across all team members and activities., Initialize database tables, indexes, and migrate existing JSONL logs. (+11 more)

### Community 59 - "submit/page.tsx"
Cohesion: 0.17
Nodes (16): ACCEPTED_EXTENSIONS, formatBytes(), isAcceptedFile(), State, SubmitPage(), fetchJob(), getSampleCsvUrl(), IdentificationReport (+8 more)

### Community 60 - "test_excel_parser_gaps.py"
Cohesion: 0.14
Nodes (13): _match_sheet_channel(), _parse_excel_grid_messages(), _parse_excel_key_value_blocks(), Parse Excel sheets where copy spans multiple contiguous rows and Column 0…, Parse Excel sheets with Title: and Body: message blocks. e.g. RCS App…, Unit tests for Excel spreadsheet parser enhancements in briefing_parser.py.…, Verify sheet channel matcher recognizes common client naming variations., Verify _parse_excel_channel_sheets extracts templates from varied sheet names. (+5 more)

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

### Community 66 - "TestSmsTracker"
Cohesion: 0.22
Nodes (7): StrEnum, Karix SMS content types., Normalized SMS Delivery Status., SmsDeliveryStatus, SmsMessageType, Test process-safe JSONL log tracker and stats aggregation., TestSmsTracker

### Community 67 - "transfer_jira_ticket"
Cohesion: 0.21
Nodes (12): bulk_transfer_jira_tickets(), clear_operational_assignment(), Reassign a ticket: - If target is Soham Das or Aadya (or any user without a…, Reassign multiple Jira tickets in batch and post audit handover notes., save_operational_assignment(), transfer_jira_ticket(), Verify transfer_jira_ticket calls Atlassian API for licensed Jira users., Verify transfers to Soham Das or Aadya execute virtual operational assignments… (+4 more)

### Community 68 - "._process_job_tasks"
Cohesion: 0.12
Nodes (12): Any, Check if tenant's circuit breaker is currently active (paused on 401)., Trip the circuit breaker on 401 Session Expired: - Halts tenant's queue - Flips…, Event-bus auto-resume trigger called when operator updates/tests credentials in…, Broadcast an SSE event payload to all active client listeners., Spawn asynchronous background task to execute all pending tasks in the job., Background worker processing tasks through fair-share rate limiter and handling…, Throttle this WABA bucket upon carrier 429 rate limit notification. (+4 more)

### Community 69 - "NormalizedOpsRecord"
Cohesion: 0.15
Nodes (19): get_moengage_ops_dashboard(), Get aggregated MoEngage Operations KPI metrics, channel breakdowns, and…, Trigger live sync of campaigns and flows across all registered MoEngage…, Upload and ingest a raw campaign export file (ZIP/CSV/XLSX) downloaded directly…, sync_moengage_ops_endpoint(), upload_moengage_export_endpoint(), compute_ops_dashboard_metrics(), export_ops_dashboard_excel() (+11 more)

### Community 70 - "error_learning.py"
Cohesion: 0.18
Nodes (17): diagnose_error_with_learning(), learn_from_error(), LearnedPattern, load_learned_patterns(), _lock(), Any, BaseException, Autonomous Error Learning and Self-Healing Diagnostic Engine. Synthesizes error… (+9 more)

### Community 71 - "test_jira_brief_endpoint.py"
Cohesion: 0.11
Nodes (21): patch, Tests for Jira brief inspection endpoint (/api/jira/brief/{issue_key}).…, Verify that submit endpoint preserves TEXT headers, footers, and…, Verify /api/jira/projects returns full Tata Capital project catalog., Verify SWCM-61 key-value metadata table emits 0 WhatsApp templates and…, Verify SWCM-85 single-header execution table extracts WhatsApp template even…, Verify that a ticket with both Email and WhatsApp identifies both channels…, Verify compute_brief_status accurately classifies ticket stages and… (+13 more)

### Community 72 - "find_template_by_content"
Cohesion: 0.12
Nodes (18): compute_text_similarity(), evaluate_semantic_equivalence_typesafe(), find_template_by_content(), normalize_template_text(), Normalize template text for comparison: - Collapses variable placeholders…, Compute normalized text similarity ratio (0.0 to 1.0)., Use TypeSafe System One (Noul primitive) to determine if two template bodies…, Search Karix / WABA live inventory to detect if the given body text or content… (+10 more)

### Community 73 - "email_notifier.py"
Cohesion: 0.21
Nodes (16): build_stage_email(), determine_current_stage(), get_current_ist_time(), get_smtp_sender_info(), is_stage_within_window(), preview_due_today_alerts(), Automated 3-Stage Daily SLA Email Dispatcher & Scheduler. Schedules &…, Generate HTML and plain text email content tailored to the stage. (+8 more)

### Community 74 - "QueueManager"
Cohesion: 0.14
Nodes (10): QueueManager, Get or initialize the isolated token bucket for a tenant's WABA., Subscribe an SSE connection to live job events., Remove an SSE connection subscriber., Yield Server-Sent Events for a job until it settles or client disconnects., Run single template submission in threadpool to avoid blocking event loop., Token bucket rate limiter isolated per WABA ID. Enforces requests/sec quota and…, Central coordinator for multi-tenant rate limits, circuit breakers,… (+2 more)

### Community 75 - "loader.py"
Cohesion: 0.07
Nodes (48): _bind_embedded_media_to_row(), _build_single_cell_card_submission(), _canonicalize_dynamic_row(), _detect_media_kind(), _dynamic_body_value(), _dynamic_key(), _dynamic_row_to_submission(), _dynamic_template_name() (+40 more)

### Community 76 - "fetch_assignable_jira_users"
Cohesion: 0.29
Nodes (6): fetch_assignable_jira_users(), JiraUser, Team member profile and active capacity metrics., Fetch assignable users strictly scoped to the active team members., Verify team members and interns are parsed with appropriate roles., test_assignable_users_and_capacity_tracking()

### Community 77 - "download_jira_attachment"
Cohesion: 0.33
Nodes (6): api_route, get_public_media(), Serve cached template header images/videos/documents directly to Karix, Meta,…, download_jira_attachment(), Path, Download an attachment file from Jira and cache it in media_cache/.

### Community 78 - "runner.py"
Cohesion: 0.07
Nodes (40): Shared data models for the Phase-2 (submission-only) pipeline. Kept…, classify_template_category_sla(), get_pending_templates_sla_insights(), poll_pending(), Runner: wires loader -> client -> tracker together for WhatsApp templates.…, Phase 2, step 1: submit each template, log the attempt., Phase 2, step 2: check approval status for everything still pending. ONE remote…, Phase 2, step 1 (from CSV or XLSX): load templates from file, submit in… (+32 more)

### Community 79 - "log_activity"
Cohesion: 0.12
Nodes (16): log_activity(), Log an event permanently into SQLite and append to JSONL. Automatically updates…, delete_templates_endpoint(), poll(), Bulk-delete WhatsApp templates by name list, or all templates on the WABA., Send single or batch SMS messages directly via JSON. Supports plain or AES-256…, Submit extracted WhatsApp and/or RCS templates from a Jira brief directly to…, Register an approved RCS template into MoEngage Settings -> RCS Template… (+8 more)

### Community 80 - "load_errors"
Cohesion: 0.29
Nodes (14): _handle_agent_error_inquiry(), get_error_summary(), load_errors(), Any, Load logged errors in reverse-chronological order (newest first) with optional…, Return summary statistics of all logged errors., _fmt_ts(), main() (+6 more)

### Community 81 - "tool_diagnose_and_fix"
Cohesion: 0.14
Nodes (15): _handle_agent_rejection_diagnosis(), Analyze template components and rejection reason against Meta WhatsApp…, Diagnose why a template was rejected or has quality issues, apply automated…, Find a template by name or ID across live WABA and local submission logs., remediate_template_rejection(), tool_diagnose_and_fix(), tool_inspect_template(), Verify word-to-variable ratio remediation (Meta Error 2388293). (+7 more)

### Community 82 - "lint_and_fix_body"
Cohesion: 0.18
Nodes (14): lint_and_fix_body(), _lint_meta_variable_rules(), _lint_punctuation_and_caps(), _lint_repeated_and_typos(), Grammar, Spelling & Meta Template Quality Linter. Detects repeated words,…, Analyze text for grammatical mistakes, repeated words, spelling typos,…, Validate technical Meta WhatsApp and RCS compliance rules (Semantic Memory).…, Complete pre-submission audit combining: 1. Grammar & spelling linter with… (+6 more)

### Community 83 - "test_agent_remediation.py"
Cohesion: 0.18
Nodes (13): ContentSearchResult, Outcome of searching Karix template inventory by body copy / content., Tests for Autonomous AI Copilot Auto-Remediation Engine and Meta Policy…, Verify conversational chat interaction for rejection diagnosis and 1-click…, Verify AI Copilot can search existing Karix templates by body copy in natural…, Pasting template copy alone should search the live Karix catalog., Plain sentence copy should also be treated as pasted template content., A catalog/API failure must not be presented as a missing template. (+5 more)

### Community 84 - "Any"
Cohesion: 0.21
Nodes (11): AlertEmailDraft, get_brevo_event_logs(), Any, Prepared email ready for dispatch., Send one draft email via SMTP. Falls back gracefully to simulation if SMTP is…, Unified outbound email delivery: 1. Resend API (HTTPS Port 443) if…, Fetch live transactional delivery events from Brevo API., send_email_dispatcher() (+3 more)

### Community 85 - "fetch_workspace_campaigns"
Cohesion: 0.21
Nodes (10): fetch_workspace_campaigns(), fetch_workspace_flows(), _infer_vertical_from_name(), _is_test_campaign(), Check if campaign name indicates a test, copy, or duplicate., Infer vertical from campaign naming patterns matching Excel formulas., Fetch campaigns and flow nodes from a MoEngage workspace using POST…, Fetch automated customer journey flows from MoEngage using POST… (+2 more)

### Community 86 - "ai_rebalance_workload"
Cohesion: 0.19
Nodes (12): ai_rebalance_workload(), get_all_allocation_settings(), Return dictionary of member_name -> is_active_for_allocation (defaulting to…, Toggle a team member's eligibility for ticket assignment and workload…, AI Workload Rebalancing transfer recommendation., Autonomous AI Workload Balancing Agent. Evaluates operator capacity, deadlines,…, Deterministic rule-based rebalancing fallback., _rule_based_rebalance() (+4 more)

### Community 87 - "get_stats"
Cohesion: 0.21
Nodes (12): _clean_error_message(), _fetch_whatsapp_inventory(), fetch_whatsapp_templates(), _filter_and_sort_templates(), get_stats(), get_templates(), _merge_rcs_templates(), _merge_sms_templates() (+4 more)

### Community 88 - "moengage_ops_client.py"
Cohesion: 0.18
Nodes (11): Add or update a MoEngage workspace configuration., update_moengage_ops_workspace(), _infer_vertical_from_context(), _is_attributics_author(), load_workspace_configs(), MoEngage Operations Dashboard Client & Aggregation Engine. Directly connects to…, Load configured MoEngage workspaces from disk or fall back to defaults., Save workspace configs to disk. (+3 more)

### Community 89 - "fetch_mcp_ops_records"
Cohesion: 0.23
Nodes (12): _compute_week_start(), fetch_mcp_ops_records(), get_date_range_bounds(), _parse_flex_date(), Compute the Monday work-week start for a given date., Fetch campaigns and flows via the MoEngage MCP Server…, Calculate effective start and end dates matching the Excel Dashboard formulas., Parse various date formats from MoEngage exports into a datetime.date. (+4 more)

### Community 90 - "_parse_single_moengage_data_rows"
Cohesion: 0.29
Nodes (10): _extract_rows_from_file_bytes(), ingest_moengage_export_file(), parse_moengage_export_file(), _parse_single_moengage_data_rows(), Any, Path, Extract row dictionaries from CSV or Excel file bytes., Parse a campaign export file downloaded directly from MoEngage. Supports: - ZIP… (+2 more)

### Community 91 - "test_attached_sheets_and_comments.py"
Cohesion: 0.22
Nodes (10): Path, Unit tests for universal attached spreadsheet parser and Jira comments revision…, Verify campaign targeting/cohort sheets do not hallucinate audience segment…, Verify attached spreadsheets cleanly map template names, categories, headers,…, Verify spreadsheet parser extracts from channel column and section header rows., Verify parse_jira_brief stores comments and extracts revised copy from comments., test_attached_spreadsheet_comprehensive_content_mapping(), test_comments_and_revision_parsing() (+2 more)

### Community 92 - "OperatorTicketSummary"
Cohesion: 0.24
Nodes (10): OperatorTicketSummary, Group of due-today incomplete tickets assigned to an operator., Send an interactive rich card to Google Chat Space via Incoming Webhook. Uses…, send_google_chat_sla_alert(), Verify Google Chat fallback simulation when no webhook URL is configured., Verify Google Chat webhook POST request structure., Verify stage-specific messaging for morning kickoff, midday, and EOD urgent…, test_build_stage_email_messages() (+2 more)

### Community 93 - "check_status"
Cohesion: 0.13
Nodes (15): check_status(), _evaluate_portal_create_response(), _is_duplicate_or_exists_error(), _is_retryable(), Response, Read the latest approval status from the official Karix template list.…, Check if an error string/dict from Karix or Meta indicates the template already…, When Karix or Meta indicates that a template already exists on the WABA, self-… (+7 more)

### Community 94 - "Any"
Cohesion: 0.29
Nodes (8): get_all_operational_assignments(), get_turnaround_and_bottleneck_analytics(), OperatorVelocity, Any, Calculate operator cycle times (turnaround velocity) and diagnose roadblock…, Operator turnaround speed and cycle time metrics., Detailed diagnosis of a stalled or blocked ticket., RoadblockTicket

### Community 95 - "AlertSchedulerState"
Cohesion: 0.25
Nodes (6): AlertSchedulerState, Persistent state of the automated daily alert scheduler backed by…, Verify AlertSchedulerState prevents duplicate sends for the same slot on the…, Verify AlertSchedulerState persists to DB and prevents duplicate dispatch on…, test_scheduler_db_persistence_deduplication(), test_scheduler_state_deduplication()

### Community 96 - "log_error"
Cohesion: 0.31
Nodes (8): _lock(), log_error(), BaseException, Centralized Error Logging and Diagnostic Engine. Records all system, API,…, Detailed record of an error event., Record an error to the central error log. Automatically extracts exception type…, SystemErrorRecord, _unlock()

### Community 97 - "Karix Multi-Channel Template Whitelisting & Automation Platform"
Cohesion: 0.22
Nodes (8): 1. Environment Configuration, 2. Local Development, 3. Docker Deployment, 🚀 Getting Started, Karix Multi-Channel Template Whitelisting & Automation Platform, 🏛 Multi-Channel Architecture, 📁 Repository Directory Structure, 🧪 Testing & Security Verification

### Community 98 - "submit_template"
Cohesion: 0.12
Nodes (11): Submit one template to Karix and return the result. If portal session…, submit_template(), client(), fixture, Tests for credential handling after Playwright removal. The Karix portal…, A 401 from the portal API fails the template with a clear message — no browser,…, Missing portal credentials raise OSError naming the exact env keys., PUT /api/credentials writes credentials.json and returns github_persisted… (+3 more)

### Community 99 - "TestSmsApiEndpoints"
Cohesion: 0.22
Nodes (5): Test FastAPI SMS endpoints via TestClient., Test Karix plain JSON DLR callback., Test Karix SMS Click report callback., Test downloading sample CSV for channel=sms., TestSmsApiEndpoints

### Community 100 - "init_database"
Cohesion: 0.25
Nodes (8): init_database(), init_queue_db(), Initialize jobs and tasks tables and run legacy JSONL migration., Initialize database tables and indexes for active driver (PostgreSQL or SQLite)., _init_operational_assignments_db(), setup_module(), fixture, setup_db()

### Community 101 - "Web Application Testing"
Cohesion: 0.25
Nodes (7): Best Practices, Common Pitfall, Decision Tree: Choosing Your Approach, Example: Using with_server.py, Reconnaissance-Then-Action Pattern, Reference Files, Web Application Testing

### Community 102 - "bulk_transfer_jira_tickets_endpoint"
Cohesion: 0.29
Nodes (7): bulk_transfer_jira_tickets_endpoint(), Any, Authorization policy: Only three people have the power to transfer tickets that…, Transfer/reassign a Jira ticket to another team member or intern. Strictly…, Bulk transfer/reassign multiple Jira tickets to another team member or intern.…, require_transfer_authorization(), transfer_jira_ticket_endpoint()

### Community 103 - "infer_channel_from_name_or_raw"
Cohesion: 0.33
Nodes (6): infer_channel_from_name_or_raw(), _normalize_channel_name(), Map MoEngage channel strings and node labels to standard dashboard channels., Map channel using both MoEngage raw channel tag and standard campaign name…, Verify raw MoEngage channel strings map to canonical dashboard channels., test_normalize_channel_name()

### Community 104 - "Karpathy Guidelines"
Cohesion: 0.33
Nodes (5): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution, Karpathy Guidelines

### Community 105 - "test_dashboard_data.py"
Cohesion: 0.33
Nodes (3): parametrize, Dashboard must distinguish an empty WABA from an unavailable Karix inventory., test_dashboard_retains_tenant_local_history_when_inventory_unavailable()

### Community 106 - "run_scheduler_loop"
Cohesion: 0.40
Nodes (5): Start the background scheduler task for 10am, 1pm, 4pm IST alert runs., start_alert_scheduler_task(), Background continuous scheduler loop. Checks IST time every 30 seconds and…, run_scheduler_loop(), on_event

### Community 107 - "_prepare_payload_messages"
Cohesion: 0.40
Nodes (5): _prepare_payload_messages(), Any, Validate and sanitize a single message, returning cleaned destinations and…, Prepare all messages for the API request payload., _sanitize_message()

### Community 108 - "group_tickets_by_operator"
Cohesion: 0.50
Nodes (4): group_tickets_by_operator(), Group tickets by assignee and resolve their verified corporate email., Verify incomplete tickets are grouped by assignee and resolved to corporate…, test_group_tickets_by_operator()

### Community 109 - "compute_timeline_bucket"
Cohesion: 0.50
Nodes (4): compute_timeline_bucket(), Calculate timeline bucket relative to today's date., Verify relative due dates are bucketed accurately relative to today., test_timeline_bucket_calculation()

### Community 110 - "infer_channel_from_summary"
Cohesion: 0.50
Nodes (4): infer_channel_from_summary(), Infer target messaging channel from ticket summary., Verify target channel is inferred from ticket title keywords., test_channel_inference_from_summary()

## Knowledge Gaps
- **150 isolated node(s):** `moengage`, `moengage`, `dynamic`, `maxDuration`, `GET` (+145 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `parse_jira_brief()` connect `briefing_parser.py` to `extract_and_strip_cta`, `jira_client.py`, `test_jira_brief_endpoint.py`, `jira_extractor.py`, `decompose_content`, `download_jira_attachment`, `log_activity`, `agent.py`, `test_attached_sheets_and_comments.py`, `api.py`, `normalize_placeholders`?**
  _High betweenness centrality (0.084) - this node is a cross-community bridge._
- **Why does `analyze_template_semantics()` connect `decompose_content` to `briefing_parser.py`, `api.py`, `post`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._
- **Why does `TemplateSubmission` connect `TemplateSubmission` to `submission_client.py`, `submit_template`, `get_db`, `loader.py`, `QueueManager`, `runner.py`, `log_activity`, `KarixHealthGovernor`, `check_status`, `test_agent_remediation.py`, `identify_master_templates`, `api.py`, `_load_env_file`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Are the 42 inferred relationships involving `TemplateSubmission` (e.g. with `AccountCreate` and `AgentChatRequest`) actually correct?**
  _`TemplateSubmission` has 42 INFERRED edges - model-reasoned connections that need verification._
- **What connects `moengage`, `moengage`, `dynamic` to the rest of the system?**
  _150 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `briefing_parser.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06604324956165984 - nodes in this community are weakly interconnected._
- **Should `auth.py` be split into smaller, more focused modules?**
  _Cohesion score 0.09195402298850575 - nodes in this community are weakly interconnected._