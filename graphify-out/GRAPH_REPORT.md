# Graph Report - karix  (2026-09-26)

## Corpus Check
- 106 files · ~258,709 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1880 nodes · 4739 edges · 84 communities (76 shown, 8 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 383 edges (avg confidence: 0.53)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `6034d19c`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- rcs_client.py
- get_db
- submission_client.py
- devDependencies
- compilerOptions
- app/page.tsx
- moengage_ops_client.py
- Karix WhatsApp Template Whitelisting — Project Rules
- agent.py
- test_typesafe_validator.py
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
- email_notifier.py
- TestMultiTenantAuth
- SmsMessage
- update_credentials
- Karpathy Guidelines
- route.ts
- RcsTemplateSubmission
- moengage_sync.py
- log_error
- db.py
- briefing_parser.py
- sms_loader.py
- test_agent_remediation.py
- db_queue.py
- test_jira_extractor.py
- fetchWithRetry
- sms_client.py
- decompose_content
- api.ts
- _load_env_file
- send_sms
- TestSmsCrypto
- test_sms.py
- test_work_manager.py
- TestRcsPipeline
- extract_templates_from_excel_file
- loader.py
- test_template_identifier.py
- api.py
- 4. Historical Error Incident Catalog
- template_identifier.py
- get_work_management_dashboard
- work_manager.py
- submit/page.tsx
- test_excel_parser_gaps.py
- chat-widget.tsx
- context.tsx
- normalize_placeholders
- extract_and_strip_cta
- work-management/page.tsx
- sms_models.py
- transfer_jira_ticket
- moengage-ops/page.tsx
- rcs_runner.py
- WabaTokenBucket
- patch
- fetch_whatsapp_templates
- _parse_raw_sheet_rows
- useApp
- load_from_csv
- fetch_assignable_jira_users
- download_jira_attachment
- test_integration.py
- _extract_media_from_xlsx
- .is_delivered
- .is_failed
- _is_retryable
- TemplateSubmission

## God Nodes (most connected - your core abstractions)
1. `TemplateSubmission` - 67 edges
2. `fetchWithRetry()` - 59 edges
3. `_json_safe()` - 58 edges
4. `getApiUrl()` - 58 edges
5. `getErrorMessage()` - 56 edges
6. `RcsTemplateSubmission` - 54 edges
7. `SmsMessage` - 51 edges
8. `SubmissionResult` - 48 edges
9. `parse_jira_brief()` - 47 edges
10. `get_db()` - 43 edges

## Surprising Connections (you probably didn't know these)
- `WhitelistingAgent` --uses--> `RcsTemplateSubmission`  [INFERRED]
  agent.py → rcs_models.py
- `AccountCreate` --uses--> `TemplateSubmission`  [INFERRED]
  api.py → models.py
- `AccountCreate` --uses--> `RcsTemplateSubmission`  [INFERRED]
  api.py → rcs_models.py
- `UserRegister` --uses--> `TemplateSubmission`  [INFERRED]
  api.py → models.py
- `UserRegister` --uses--> `RcsTemplateSubmission`  [INFERRED]
  api.py → rcs_models.py

## Import Cycles
- None detected.

## Communities (84 total, 8 thin omitted)

### Community 0 - "rcs_client.py"
Cohesion: 0.24
Nodes (15): _build_rcs_carousel_vi_template(), _build_rcs_clean_suggestions(), _build_rcs_richcard_vi_template(), _build_rcs_save_payload(), _build_rcs_text_vi_template(), _build_single_suggestion(), _ensure_url_variable(), _extract_and_number_rcs_variables() (+7 more)

### Community 1 - "get_db"
Cohesion: 0.07
Nodes (46): get_activity_summary(), get_all_users(), init_store(), load_activities(), Activity tracker & User Identity Manager: Stores all user operations (template…, Query activities from SQLite with filtering, search, and unlimited pagination., Calculate instant live metrics across all team members and activities., Initialize database tables, indexes, and migrate existing JSONL logs. (+38 more)

### Community 2 - "submission_client.py"
Cohesion: 0.06
Nodes (75): _init_media_cache(), _account_prefix(), _esmeaddr_from_session_token(), get_esmeaddr(), get_official_auth_headers(), get_portal_auth_headers(), get_template_namespace_id(), get_waba_id() (+67 more)

### Community 3 - "devDependencies"
Cohesion: 0.07
Nodes (29): autoprefixer, dependencies, next, react, react-dom, devDependencies, autoprefixer, postcss (+21 more)

### Community 4 - "compilerOptions"
Cohesion: 0.07
Nodes (26): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+18 more)

### Community 5 - "app/page.tsx"
Cohesion: 0.15
Nodes (18): ActivityLogsPage(), formatTimestamp(), DashboardPage(), ActivityLog, ActivityStats, deleteTemplates(), deleteTemplatesFromFile(), fetchActivityLogs() (+10 more)

### Community 6 - "moengage_ops_client.py"
Cohesion: 0.06
Nodes (63): get_moengage_ops_dashboard(), Get aggregated MoEngage Operations KPI metrics, channel breakdowns, and…, Trigger live sync of campaigns and flows across all registered MoEngage…, Add or update a MoEngage workspace configuration., Upload and ingest a raw campaign export file (CSV/XLSX) downloaded directly…, sync_moengage_ops_endpoint(), update_moengage_ops_workspace(), upload_moengage_export_endpoint() (+55 more)

### Community 7 - "Karix WhatsApp Template Whitelisting — Project Rules"
Cohesion: 0.18
Nodes (10): Auth model — known limitation, Bajaj account constants, Bajaj vs Tata Capital — strict separation, File responsibilities, Karix API quirks — do NOT "clean up", Karix WhatsApp Template Whitelisting — Project Rules, Likely next steps (for planning context), Scope boundaries (+2 more)

### Community 8 - "agent.py"
Cohesion: 0.09
Nodes (37): _check_agent_tenant_isolation(), _handle_agent_copy_lint(), _handle_agent_fallback_guidance(), _handle_agent_help_inquiry(), _handle_agent_learning_inquiry(), _handle_agent_list_templates(), _handle_agent_rejection_diagnosis(), _handle_agent_session_refresh() (+29 more)

### Community 9 - "test_typesafe_validator.py"
Cohesion: 0.08
Nodes (38): Validate technical Meta WhatsApp and RCS compliance rules (Semantic Memory).…, Complete pre-submission audit combining: 1. Grammar & spelling linter with…, validate_meta_technical_compliance(), validate_template_pre_submission(), async_validate_template_semantic_quality(), _build_typesafe_questions(), _determine_risk_level(), _process_typesafe_response() (+30 more)

### Community 10 - "AGENTS.md"
Cohesion: 0.40
Nodes (4): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution

### Community 17 - "submit_rcs_template"
Cohesion: 0.20
Nodes (17): _test_rcs_channel(), fetch_rcs_templates(), Submit one RCS template to the official Karix RCS Bot Builder Template API., Fetch all live RCS templates for the bot ID from official Karix RCS endpoint:…, submit_rcs_template(), _account_prefix(), get_rcs_auth_headers(), get_rcs_bot_id() (+9 more)

### Community 18 - "rcs_tracker.py"
Cohesion: 0.16
Nodes (12): Data models for Karix RCS Bot Builder & DLT template submissions. Storage-…, One suggested reply or action for an RCS template., RcsSuggestion, _lock(), log_rcs_result(), Tracker for RCS template registration results. Directly persists to database…, Patch one RCS entry in the database (matched by source_ref or template_name)., Store RCS submission result directly into database (job_tasks) as single source… (+4 more)

### Community 19 - "KarixHealthGovernor"
Cohesion: 0.22
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

### Community 25 - "email_notifier.py"
Cohesion: 0.06
Nodes (57): Start the background scheduler task for 10am, 1pm, 4pm IST alert runs., start_alert_scheduler_task(), datetime, AlertEmailDraft, AlertSchedulerState, build_stage_email(), determine_current_stage(), dispatch_due_today_alerts() (+49 more)

### Community 26 - "TestMultiTenantAuth"
Cohesion: 0.13
Nodes (7): Comprehensive Multi-Tenant Authentication & Strict Tenant Isolation Tests.…, AI Copilot blocks cross-tenant query attempts for locked operators., Verify user signup binds to selected tenant and login returns signed JWT., Invalid credentials return 401 Unauthorized., Attempting to signup with existing email returns 400 Bad Request., Critical Multi-Tenant Isolation Check: Bajaj operator CANNOT access Tata…, TestMultiTenantAuth

### Community 27 - "SmsMessage"
Cohesion: 0.20
Nodes (49): AccountCreate, AgentChatRequest, AiRebalanceRequest, BulkTicketTransferRequest, CredentialUpdate, DeleteTemplatesRequest, DispatchAlertsRequest, GeminiTestRequest (+41 more)

### Community 28 - "update_credentials"
Cohesion: 0.20
Nodes (11): _build_rcs_credentials_mapping(), _build_sms_credentials_mapping(), _build_wa_credentials_mapping(), _commit_credentials_to_github(), _moengage_credential_keys(), Commit credentials.json to the configured GitHub repo. Returns status string or…, Map account to its MoEngage env keys. Tata sub-accounts share the global…, Persist an account's MoEngage workspace credentials to .env and… (+3 more)

### Community 29 - "Karpathy Guidelines"
Cohesion: 0.33
Nodes (5): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution, Karpathy Guidelines

### Community 30 - "route.ts"
Cohesion: 0.25
Nodes (6): DELETE, dynamic, GET, maxDuration, POST, PUT

### Community 31 - "RcsTemplateSubmission"
Cohesion: 0.11
Nodes (27): Upload a binary image or video to Karix RCS media storage (gRBM). Returns the…, upload_rcs_media(), _build_carousel_cards_from_row(), _build_suggestions_from_row(), check_rcs_image_aspect_ratio(), _extract_images_from_xlsx(), _extract_images_spatially(), infer_cta_link_and_button() (+19 more)

### Community 32 - "moengage_sync.py"
Cohesion: 0.06
Nodes (51): AttributeMappingResult, check_semantic_duplicate_pair(), DuplicateCheckResult, find_semantic_duplicate(), MoEngageTemplateTranslation, Any, TypeSafe AI MoEngage Semantic Resolver. Enhances the Karix-to-MoEngage sync and…, Evaluate whether a candidate template semantically duplicates an existing… (+43 more)

### Community 33 - "log_error"
Cohesion: 0.08
Nodes (41): _handle_agent_error_inquiry(), get_system_errors(), Retrieve error logs for debugging and agent remediation., diagnose_error_with_learning(), learn_from_error(), LearnedPattern, load_learned_patterns(), _lock() (+33 more)

### Community 34 - "db.py"
Cohesion: 0.08
Nodes (24): DBConnection, DBCursor, get_database_url(), is_postgres(), migrate_sqlite_to_postgres(), Any, Path, Unified Database Adapter for Karix Whitelisting. Provides seamless dual-driver… (+16 more)

### Community 35 - "briefing_parser.py"
Cohesion: 0.10
Nodes (36): clean_safelink(), _clean_template_name(), detect_ticket_month(), _extract_images_from_zip(), _extract_links_from_adf_node(), extract_templates_from_docx_file(), _extract_text_from_adf_node(), _find_adf_tables() (+28 more)

### Community 36 - "sms_loader.py"
Cohesion: 0.09
Nodes (32): Send single or batch SMS messages directly via JSON. Supports plain or AES-256…, send_sms_api_endpoint(), get_sms_dlt_entity_id(), get_sms_sender_id(), Return the registered DLT sender ID / header name for this account., Return the DLT Entity ID for this client., _clean_phone_number(), load_sms_from_csv() (+24 more)

### Community 38 - "test_agent_remediation.py"
Cohesion: 0.07
Nodes (28): init_queue_db(), Initialize jobs and tasks tables and run legacy JSONL migration., fixture, Tests for Autonomous AI Copilot Auto-Remediation Engine and Meta Policy…, Verify conversational chat interaction for rejection diagnosis and 1-click…, Verify word-to-variable ratio remediation (Meta Error 2388293)., Verify header text exceeding 60 characters is trimmed to compliant length., Verify templates with marketing language in UTILITY category are re-categorized… (+20 more)

### Community 39 - "db_queue.py"
Cohesion: 0.05
Nodes (60): get_job_endpoint(), Fetch status and per-template tasks for an asynchronous ingestion job., Server-Sent Events (SSE) stream yielding real-time per-task progress and job…, stream_job_endpoint(), _submit_rcs_batch(), _submit_wa_batch(), _clean_sql_str(), create_job_with_tasks() (+52 more)

### Community 40 - "test_jira_extractor.py"
Cohesion: 0.08
Nodes (31): extract_template_from_jira_text(), ExtractedTemplateComponent, generate_compliant_variable_samples(), JiraExtractionResult, JiraRoutingDecision, Any, TypeSafe AI Semantic Jira Brief & Template Extractor. Analyzes free-form Jira…, Parse free-form text into Header, Body, Footer, and Button components using… (+23 more)

### Community 41 - "fetchWithRetry"
Cohesion: 0.18
Nodes (34): Banner, SettingsPage(), WorkManagementPage(), aiRebalanceWorkload(), assignUnassignedTicketsToNeel(), bulkTransferJiraTickets(), createAccount(), deleteAccount() (+26 more)

### Community 42 - "sms_client.py"
Cohesion: 0.12
Nodes (31): Karix SMS Delivery Report (DLR) Forwarding via HTTPs Callback API. Supports…, receive_sms_dlr_webhook(), _prepare_payload_messages(), Any, Client for Karix SMS JSON API. Sends SMS messages (One-to-One, One-to-Many,…, Check configuration and reachability for the given account's SMS integration.…, Validate and sanitize a single message, returning cleaned destinations and…, Prepare all messages for the API request payload. (+23 more)

### Community 43 - "decompose_content"
Cohesion: 0.11
Nodes (28): decompose_content(), derive_clean_card_title(), detect_category(), detect_language(), is_valid_template_copy(), Detect language code (e.g. 'en', 'gu', 'hi', 'pa', 'mr', 'bn', 'ta', 'te',…, Determine WhatsApp template category (UTILITY, AUTHENTICATION, MARKETING)., Decompose any raw template content into structured, ready-to-whitelist… (+20 more)

### Community 44 - "api.ts"
Cohesion: 0.11
Nodes (27): JiraBriefsPage(), AccountDetection, AlertsDispatchOptions, AspectRatioWarning, AuthResponse, ComplianceWarning, delay(), DeleteTemplatesResult (+19 more)

### Community 45 - "_load_env_file"
Cohesion: 0.11
Nodes (27): _handle_agent_jira_inquiry(), _load_env_file(), Load key-value pairs from credentials.json and .env file if present.…, add_jira_comment(), adf_to_text(), extract_issue_templates(), fetch_jira_issue(), get_jira_auth_headers() (+19 more)

### Community 46 - "send_sms"
Cohesion: 0.10
Nodes (16): Session, Convenience helper to send a single message to one or more mobile numbers., Send a batch of SMS messages to the Karix SMS JSON API., send_quick_sms(), send_sms(), Outcome of sending an SMS request to Karix., SmsSendResponse, patch (+8 more)

### Community 47 - "TestSmsCrypto"
Cohesion: 0.11
Nodes (21): decrypt_dlr_gcm(), decrypt_sms_pii(), _derive_aes_key(), encrypt_dlr_gcm(), encrypt_sms_pii(), _normalize_iv_bytes(), _normalize_key_bytes(), Cryptographic utilities for Karix SMS API integration. Implements: 1. AES-256… (+13 more)

### Community 48 - "test_sms.py"
Cohesion: 0.17
Nodes (23): get_sms_logs_endpoint(), Query logged SMS submissions, delivery reports (DLR), and click events., get_sms_stats(), load_sms_clicks(), load_sms_dlrs(), load_sms_submissions(), _lock(), log_sms_click() (+15 more)

### Community 49 - "test_work_manager.py"
Cohesion: 0.09
Nodes (25): Unit and integration tests for Jira Work Management & Autonomous Workload…, Verify cycle time calculations, operator turnaround velocity, and roadblock…, Verify GET /api/work-management/turnaround-analytics returns expected analytics…, Verify POST /api/work-management/bulk-transfer accepts batch reassignments., Verify POST /api/work-management/assign-unassigned reassigns unassigned tickets…, Verify transfers to Soham Das or Aadya execute virtual operational assignments…, Verify relative due dates are bucketed accurately relative to today., Verify only Dnyanesh, Neel, Mrunalini (and admin) are authorized to transfer… (+17 more)

### Community 50 - "TestRcsPipeline"
Cohesion: 0.20
Nodes (6): _normalize_row_keys(), _parse_sender_ids(), Normalize spreadsheet header keys: strip whitespace, map common aliases to…, Parse sender IDs from a pipe/comma-separated string, list, or None., patch, TestRcsPipeline

### Community 51 - "extract_templates_from_excel_file"
Cohesion: 0.10
Nodes (22): extract_templates_from_excel_file(), _is_dlt_sms_sheet(), _load_spreadsheet_sheets(), _parse_dlt_sms_sheet(), Detect if an Excel spreadsheet is an official DLT SMS template export., Parse official DLT SMS template spreadsheet rows into canonical SMS template…, Inspect and extract template items from any client spreadsheet (.xlsx, .csv,…, Universally load any spreadsheet file (.xlsx, .csv, .xls) into a dictionary of… (+14 more)

### Community 52 - "loader.py"
Cohesion: 0.15
Nodes (22): _bind_embedded_media_to_row(), _build_single_cell_card_submission(), _canonicalize_dynamic_row(), _dynamic_body_value(), _dynamic_key(), _dynamic_row_to_submission(), _dynamic_template_name(), _flat_row_to_components() (+14 more)

### Community 53 - "test_template_identifier.py"
Cohesion: 0.10
Nodes (21): compute_text_similarity(), normalize_template_text(), Normalize template text for comparison: - Collapses variable placeholders…, Compute normalized text similarity ratio (0.0 to 1.0)., Tests for Phase 1 WhatsApp & RCS Template Identification Engine. Verifies…, Verify templates existing on WABA but with modified body classify as…, Verify live PENDING and REJECTED statuses are classified correctly., Verify offline fallback produces reliable token similarity without API key. (+13 more)

### Community 54 - "api.py"
Cohesion: 0.04
Nodes (131): log_activity(), Log an event permanently into SQLite and append to JSONL. Automatically updates…, agent_chat_endpoint(), ai_rebalance_workload_endpoint(), assign_unassigned_to_neel_endpoint(), bulk_transfer_jira_tickets_endpoint(), create_account(), delete_account() (+123 more)

### Community 55 - "4. Historical Error Incident Catalog"
Cohesion: 0.10
Nodes (19): 1. How to View & Inspect Errors, 2. How the AI Agent Uses the Error Log, 3. How Errors Are Recorded Over Time, 4. Historical Error Incident Catalog, Central Error Log & Diagnostic Engine, Incident 10: `Text Template Overridden to Rich Card Stand Alone with Image`, Incident 11: `PostbackData Lowercasing and Underscore Mismatch`, Incident 12: `Hashtag Variables (#var#) Not Extracted as Placeholders` (+11 more)

### Community 56 - "template_identifier.py"
Cohesion: 0.16
Nodes (16): load_from_json(), evaluate_semantic_equivalence_typesafe(), _extract_body_text(), IdentificationReport, identify_from_file(), identify_master_templates(), Any, Path (+8 more)

### Community 57 - "get_work_management_dashboard"
Cohesion: 0.11
Nodes (18): Verify TATA Service and wealth Campaign Manager (SWCM) project queries and…, Verify combined querying across all Tata projects (ALL)., Verify unassigned tickets automatically route to Neel Shah in work management., Verify arbitrary Jira statuses classify into PENDING, BLOCKED, or DONE., Verify that if any ticket mentions Soham in comments, attachments, or…, Verify live work management dashboard ingests tickets and populates metrics., test_all_projects_combined_dashboard(), test_soham_mention_routing_in_comments_and_attachments() (+10 more)

### Community 58 - "work_manager.py"
Cohesion: 0.18
Nodes (15): ai_rebalance_workload(), get_turnaround_and_bottleneck_analytics(), _init_operational_assignments_db(), OperatorVelocity, Any, Jira Work Management & Autonomous Workload Dispatcher Engine. Connects to…, AI Workload Rebalancing transfer recommendation., Operator turnaround speed and cycle time metrics. (+7 more)

### Community 59 - "submit/page.tsx"
Cohesion: 0.17
Nodes (16): ACCEPTED_EXTENSIONS, formatBytes(), isAcceptedFile(), State, SubmitPage(), fetchJob(), getSampleCsvUrl(), IdentificationReport (+8 more)

### Community 60 - "test_excel_parser_gaps.py"
Cohesion: 0.15
Nodes (16): detect_sheet_month(), _match_sheet_channel(), _parse_excel_channel_sheets(), _parse_excel_grid_messages(), _parse_excel_key_value_blocks(), Parse Excel sheets where copy spans multiple contiguous rows and Column 0…, Parse Excel sheets with Title: and Body: message blocks. e.g. RCS App…, should_skip_sheet() (+8 more)

### Community 61 - "chat-widget.tsx"
Cohesion: 0.16
Nodes (13): inter, metadata, AppShell(), ChatMessage, ChatWidget(), DEFAULT_SUGGESTED_PROMPTS, formatMessageContent(), renderInlineStyles() (+5 more)

### Community 62 - "context.tsx"
Cohesion: 0.16
Nodes (15): links, Account, AccountItem, AuthUser, Channel, clearAuthToken(), fetchAccounts(), fetchMe() (+7 more)

### Community 63 - "normalize_placeholders"
Cohesion: 0.20
Nodes (13): normalize_placeholders(), Convert informal Jira placeholders (<xxx>, <name>, [Loan Amount], [ROI],…, Unit tests for placeholder normalization in briefing_parser.py. Verifies: 1.…, Verify various square bracket parameters are converted to sequential {{1}},…, Verify that existing {{1}} placeholders mixed with <name> do not produce…, Verify duplicate and out-of-order placeholders are re-indexed strictly 1..N., Verify markdown links and CTA keywords in brackets are not replaced with {{1}}., Verify {#alphanumeric#} and DLT hash placeholders are converted to {{1}}. (+5 more)

### Community 64 - "extract_and_strip_cta"
Cohesion: 0.21
Nodes (11): extract_and_strip_cta(), Identify and extract the Call-to-Action (CTA) line from a message body,…, Unit tests for CTA extraction, removal from body, and default URL fallback…, Verify exact body from TCN-524 screenshot removes CTA line and sets button URL…, Verify specific campaign tracking URLs are preserved in the button., Verify CTA line without URL defaults to https://u3.mnge.co/., Verify parse_jira_brief integrates CTA extraction and places it only in the…, test_cta_line_removed_from_body_and_moved_to_button() (+3 more)

### Community 65 - "work-management/page.tsx"
Cohesion: 0.17
Nodes (11): JiraUserItem, OperatorVelocityItem, RoadblockTicketItem, TransferProposal, TurnaroundAnalyticsData, WorkItem, WorkManagementData, AlertEmailDraft (+3 more)

### Community 66 - "sms_models.py"
Cohesion: 0.20
Nodes (8): StrEnum, Data models for the Karix SMS JSON API integration. Includes dataclasses and…, Karix SMS content types., Normalized SMS Delivery Status., SmsDeliveryStatus, SmsMessageType, Test process-safe JSONL log tracker and stats aggregation., TestSmsTracker

### Community 67 - "transfer_jira_ticket"
Cohesion: 0.18
Nodes (11): Verify transfer_jira_ticket calls Atlassian API for licensed Jira users., Verify bulk_transfer_jira_tickets iterates across issues, reassigns, and audits., test_bulk_transfer_jira_tickets(), test_transfer_jira_ticket_mock(), assign_unassigned_tickets_to_neel(), bulk_transfer_jira_tickets(), Reassign a ticket: - If target is Soham Das or Aadya (or any user without a…, Reassign multiple Jira tickets in batch and post audit handover notes. (+3 more)

### Community 68 - "moengage-ops/page.tsx"
Cohesion: 0.29
Nodes (9): ChannelCounts, DashboardData, MoEngageOpsPage(), VerticalData, WorkspaceItem, fetchMoEngageOpsDashboard(), fetchMoEngageWorkspaces(), syncMoEngageOps() (+1 more)

### Community 69 - "rcs_runner.py"
Cohesion: 0.24
Nodes (9): load_rcs_from_csv(), load_rcs_from_list(), Load RCS templates from a CSV file., Load from a list of dicts already in memory., RCS Runner: wires rcs_loader -> rcs_client -> rcs_tracker together. Entry point…, Submit each RCS DLT template, log the attempt., Load RCS templates from CSV or Excel file, submit each, and log attempt., run_rcs() (+1 more)

### Community 70 - "WabaTokenBucket"
Cohesion: 0.22
Nodes (6): Token bucket rate limiter isolated per WABA ID. Enforces requests/sec quota and…, Throttle this WABA bucket upon carrier 429 rate limit notification., Asynchronously wait until tokens are available under the WABA quota., WabaTokenBucket, Verify per-WABA token bucket consumption and dynamic 429 throttling., test_rate_limiter_token_bucket_and_429_backoff()

### Community 71 - "patch"
Cohesion: 0.22
Nodes (9): patch, Verify /api/jira/projects returns full Tata Capital project catalog., Verify that when fetch_template_list raises an exception, the brief endpoint…, Verify that when fetch_template_list succeeds, matching templates are marked…, Verify that submit endpoint preserves TEXT headers, footers, and…, test_jira_brief_endpoint_cross_references_live_waba(), test_jira_brief_endpoint_resilient_to_waba_fetch_error(), test_jira_projects_catalog_endpoint() (+1 more)

### Community 72 - "fetch_whatsapp_templates"
Cohesion: 0.31
Nodes (9): _clean_error_message(), fetch_whatsapp_templates(), _filter_and_sort_templates(), get_templates(), _merge_rcs_templates(), _merge_sms_templates(), _merge_wa_templates(), Flatten error strings or nested error dictionaries into a clean message. (+1 more)

### Community 73 - "_parse_raw_sheet_rows"
Cohesion: 0.25
Nodes (8): is_cta_cell(), is_pure_cta_cell(), _normalize_channel_tag(), _parse_raw_sheet_rows(), Check if a cell contains a CTA link, button text, or redirect instruction., Check if a cell is purely a CTA button or link without body copy., Normalize any string (e.g. 'WhatsApp', 'WA', 'RCS', 'SMS Promotional') to…, Universally parse template content from 2D raw string rows of any sheet.…

### Community 74 - "useApp"
Cohesion: 0.43
Nodes (6): LoginPage(), SignupPage(), loginUser(), setAuthToken(), signupUser(), useApp()

### Community 75 - "load_from_csv"
Cohesion: 0.48
Nodes (6): load_from_csv(), Load standard or dynamically structured WhatsApp rows from CSV., _component(), test_csv_without_standard_template_columns_is_loaded_dynamically(), test_dynamic_loader_ignores_customer_data_without_message_content(), test_excel_without_standard_template_columns_is_loaded_dynamically()

### Community 76 - "fetch_assignable_jira_users"
Cohesion: 0.29
Nodes (6): Verify team members and interns are parsed with appropriate roles., test_assignable_users_and_capacity_tracking(), fetch_assignable_jira_users(), JiraUser, Team member profile and active capacity metrics., Fetch assignable users strictly scoped to the active team members.

### Community 77 - "download_jira_attachment"
Cohesion: 0.33
Nodes (6): get_public_media(), Serve cached template header images/videos/documents directly to Karix, Meta,…, api_route, download_jira_attachment(), Path, Download an attachment file from Jira and cache it in media_cache/.

### Community 78 - "test_integration.py"
Cohesion: 0.08
Nodes (40): Submit extracted WhatsApp and/or RCS templates from a Jira brief directly to…, submit_jira_brief_endpoint(), Shared data models for the Phase-2 (submission-only) pipeline. Kept…, classify_template_category_sla(), get_pending_templates_sla_insights(), poll_pending(), Runner: wires loader -> client -> tracker together for WhatsApp templates.…, Phase 2, step 1: submit each template, log the attempt. (+32 more)

### Community 79 - "_extract_media_from_xlsx"
Cohesion: 0.33
Nodes (6): _detect_media_kind(), _extract_images_from_xlsx(), _extract_media_from_xlsx(), Detect whether raw media bytes are IMAGE, VIDEO, or DOCUMENT, and return (kind,…, Extract all embedded media (images, videos, documents) from an Excel (.xlsx)…, Legacy image extractor helper.

### Community 93 - "_is_retryable"
Cohesion: 0.50
Nodes (4): Exception, Response, _is_retryable(), Return True only for transport-level failures we should retry.

### Community 98 - "TemplateSubmission"
Cohesion: 0.10
Nodes (17): load_from_list(), _row_to_submission(), One template to be submitted for whitelisting., TemplateSubmission, Any, Run single template submission in threadpool to avoid blocking event loop., Return whether the template needs an unverified official media handle., _requires_portal_media() (+9 more)

## Knowledge Gaps
- **146 isolated node(s):** `dynamic`, `maxDuration`, `GET`, `POST`, `PUT` (+141 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `parse_jira_brief()` connect `briefing_parser.py` to `extract_and_strip_cta`, `agent.py`, `test_jira_extractor.py`, `decompose_content`, `_load_env_file`, `test_integration.py`, `download_jira_attachment`, `extract_templates_from_excel_file`, `api.py`, `SmsMessage`, `normalize_placeholders`?**
  _High betweenness centrality (0.092) - this node is a cross-community bridge._
- **Why does `TemplateSubmission` connect `TemplateSubmission` to `submission_client.py`, `WabaTokenBucket`, `db_queue.py`, `test_typesafe_validator.py`, `load_from_csv`, `test_integration.py`, `KarixHealthGovernor`, `loader.py`, `test_template_identifier.py`, `api.py`, `template_identifier.py`, `SmsMessage`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Why does `_load_env_file()` connect `_load_env_file` to `moengage_sync.py`, `submission_client.py`, `db.py`, `moengage_ops_client.py`, `test_jira_extractor.py`, `test_typesafe_validator.py`, `decompose_content`, `api.py`, `email_notifier.py`, `work_manager.py`?**
  _High betweenness centrality (0.028) - this node is a cross-community bridge._
- **Are the 28 inferred relationships involving `TemplateSubmission` (e.g. with `AccountCreate` and `AgentChatRequest`) actually correct?**
  _`TemplateSubmission` has 28 INFERRED edges - model-reasoned connections that need verification._
- **What connects `dynamic`, `maxDuration`, `GET` to the rest of the system?**
  _146 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `get_db` be split into smaller, more focused modules?**
  _Cohesion score 0.0726950354609929 - nodes in this community are weakly interconnected._
- **Should `submission_client.py` be split into smaller, more focused modules?**
  _Cohesion score 0.058544303797468354 - nodes in this community are weakly interconnected._