# Graph Report - karix  (2026-10-01)

## Corpus Check
- 123 files · ~294,376 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2248 nodes · 5532 edges · 106 communities (94 shown, 12 thin omitted)
- Extraction: 85% EXTRACTED · 15% INFERRED · 0% AMBIGUOUS · INFERRED: 816 edges (avg confidence: 0.61)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `836723a7`
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
- RcsTemplateSubmission
- rcs_loader.py
- KarixHealthGovernor
- Quick Start
- _json_safe
- Frontend Design
- CLAUDE.md
- post
- test_moengage_draft_creation.py
- TestMultiTenantAuth
- MoEngage Campaign Creation Agent — Architectural Specification & Research Dossier
- init_database
- _load_env_file
- route.ts
- sms_loader.py
- moengage_sync.py
- _submit_wa_batch
- send_sms
- download_jira_attachment
- get
- test_production_smoke.py
- api.py
- extract_template_from_jira_text
- fetchWithRetry
- get_db
- is_valid_template_copy
- api.ts
- test_moengage_ops.py
- TestSmsApiEndpoints
- sms_crypto.py
- sms_tracker.py
- submit_rcs_template
- rcs_client.py
- test_moengage_mcp.py
- agent.py
- DraftWriter
- require_tenant_access
- 4. Historical Error Incident Catalog
- db.py
- test_work_manager.py
- rcs_runner.py
- submit/page.tsx
- test_excel_parser_gaps.py
- useApp
- context.tsx
- normalize_placeholders
- extract_and_strip_cta
- work-management/page.tsx
- TestRcsPipeline
- work_manager.py
- bulk_transfer_jira_tickets_endpoint
- moengage_ops_client.py
- log_error
- test_jira_brief_endpoint.py
- TemplateSubmission
- dispatch_due_today_alerts
- queue_manager.py
- loader.py
- _compute_week_start
- _resolve_body_variables
- runner.py
- datetime
- RcsSuggestion
- karix_webhook_endpoint
- validate_template_semantic_quality
- update_moengage_ops_workspace
- AlertEmailDraft
- TestSmsModels
- derive_clean_card_title
- test_email_campaign_separation.py
- extract_templates_from_excel_file
- OperatorTicketSummary
- test_agent_remediation.py
- TestCredentialContract
- AlertSchedulerState
- sms_client.py
- Karix Multi-Channel Template Whitelisting & Automation Platform
- test_integration.py
- Web Application Testing
- Karpathy Guidelines
- test_dashboard_data.py
- run_scheduler_loop
- email_notifier.py
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

## Communities (106 total, 12 thin omitted)

### Community 0 - "briefing_parser.py"
Cohesion: 0.09
Nodes (40): clean_safelink(), _clean_template_name(), detect_sheet_month(), detect_ticket_month(), _extract_images_from_zip(), _extract_links_from_adf_node(), extract_templates_from_docx_file(), _extract_text_from_adf_node() (+32 more)

### Community 1 - "auth.py"
Cohesion: 0.13
Nodes (21): authenticate_user(), create_access_token(), decode_access_token(), get_current_user(), get_user_profile(), hash_password(), Any, Multi-Tenant Authentication & Strict Tenant Isolation Engine. Provides secure… (+13 more)

### Community 2 - "submission_client.py"
Cohesion: 0.10
Nodes (36): _init_media_cache(), _build_official_create_body(), _download_remote_media(), _ensure_default_sample_image(), _ensure_default_sample_pdf(), _ensure_default_sample_video(), _evaluate_portal_create_response(), _handle_portal_media_auto_recovery() (+28 more)

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
Cohesion: 0.11
Nodes (24): get_moengage_ops_dashboard(), Get aggregated MoEngage Operations KPI metrics, channel breakdowns, and…, Trigger live sync of campaigns and flows across all registered MoEngage…, Upload and ingest a raw campaign export file (ZIP/CSV/XLSX) downloaded directly…, sync_moengage_ops_endpoint(), upload_moengage_export_endpoint(), compute_ops_dashboard_metrics(), export_ops_dashboard_excel() (+16 more)

### Community 7 - "Karix WhatsApp Template Whitelisting — Project Rules"
Cohesion: 0.18
Nodes (10): Auth model — known limitation, Bajaj account constants, Bajaj vs Tata Capital — strict separation, File responsibilities, Karix API quirks — do NOT "clean up", Karix WhatsApp Template Whitelisting — Project Rules, Likely next steps (for planning context), Scope boundaries (+2 more)

### Community 8 - "moengage_mcp.py"
Cohesion: 0.09
Nodes (44): call_mcp_tool(), complete_mcp_oauth(), ensure_mcp_initialized(), extract_moe_bearer_from_mcp_token(), get_mcp_config(), get_mcp_status(), get_or_refresh_moe_bearer(), list_mcp_tools() (+36 more)

### Community 9 - "moengage_preview.py"
Cohesion: 0.16
Nodes (29): _parse_excel_key_value_blocks(), Parse Excel sheets with Title: and Body: message blocks. e.g. RCS App…, _asset(), _audience(), _email(), _https_url(), _items(), prepare_batch() (+21 more)

### Community 10 - "AGENTS.md"
Cohesion: 0.40
Nodes (4): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution

### Community 17 - "RcsTemplateSubmission"
Cohesion: 0.23
Nodes (62): AccountCreate, AgentChatRequest, AiRebalanceRequest, BulkTicketTransferRequest, CredentialUpdate, DeleteTemplatesRequest, DispatchAlertsRequest, GeminiTestRequest (+54 more)

### Community 18 - "rcs_loader.py"
Cohesion: 0.10
Nodes (27): Upload a binary image or video to Karix RCS media storage (gRBM). Returns the…, upload_rcs_media(), _build_carousel_cards_from_row(), _build_suggestions_from_row(), check_rcs_image_aspect_ratio(), _extract_images_from_xlsx(), _extract_images_spatially(), infer_cta_link_and_button() (+19 more)

### Community 19 - "KarixHealthGovernor"
Cohesion: 0.22
Nodes (7): KarixHealthGovernor, Working Memory: Tracks real-time Karix API response latency and error rates to…, Dynamically calculate optimal worker pool size: - Healthy (< 1.8s avg latency,…, Return an optional inter-request delay in seconds based on server load., Return real-time working memory metrics., Verify KarixHealthGovernor tracks latency and throttles concurrency during high…, test_adaptive_rate_limiting_and_governor()

### Community 20 - "Quick Start"
Cohesion: 0.20
Nodes (9): Design & Style Guidelines, Quick Start, Reference, Step 1: Initialize Project, Step 2: Develop Your Artifact, Step 3: Bundle to Single HTML File, Step 4: Share Artifact with User, Step 5: Testing/Visualizing the Artifact (Optional) (+1 more)

### Community 21 - "_json_safe"
Cohesion: 0.05
Nodes (42): ai_rebalance_workload_endpoint(), dispatch_alerts_endpoint(), get_activity_logs(), get_activity_stats(), get_delivery_logs_endpoint(), get_jira_issues_endpoint(), get_me_endpoint(), get_moengage_mcp_status_endpoint() (+34 more)

### Community 22 - "Frontend Design"
Cohesion: 0.29
Nodes (6): Design principles, Frontend Design, Ground it in the subject, More on writing in design, Process: brainstorm, explore, plan, critique, build, critique again, Restraint and self-critique

### Community 23 - "CLAUDE.md"
Cohesion: 0.33
Nodes (4): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution

### Community 24 - "post"
Cohesion: 0.07
Nodes (41): log_activity(), Log an event permanently into SQLite and append to JSONL. Automatically updates…, assign_unassigned_to_neel_endpoint(), _authorize_moengage_preview(), create_moengage_draft_endpoint(), delete_templates_endpoint(), delete_templates_from_file(), identify_templates_endpoint() (+33 more)

### Community 25 - "test_moengage_draft_creation.py"
Cohesion: 0.22
Nodes (16): FakeWriter, offline_db(), fixture, Offline V5 draft-create lifecycle: durability, read-back, validation and no-…, service(), test_create_route_requires_owner_approval_and_uses_server_catalog(), test_live_test_only_approved_row_and_segment_once_across_time(), test_rate_limit_is_shared_by_workspace_not_account() (+8 more)

### Community 26 - "TestMultiTenantAuth"
Cohesion: 0.13
Nodes (7): Comprehensive Multi-Tenant Authentication & Strict Tenant Isolation Tests.…, AI Copilot blocks cross-tenant query attempts for locked operators., Verify user signup binds to selected tenant and login returns signed JWT., Invalid credentials return 401 Unauthorized., Attempting to signup with existing email returns 400 Bad Request., Critical Multi-Tenant Isolation Check: Bajaj operator CANNOT access Tata…, TestMultiTenantAuth

### Community 27 - "MoEngage Campaign Creation Agent — Architectural Specification & Research Dossier"
Cohesion: 0.04
Nodes (44): 1.1 What This System Is, 1.2 Strict Separation from WhatsApp Whitelisting, 1.3 Inviolable Safety Constraint: STRICTLY DRAFT-ONLY, 1. Executive Summary & Scope Boundaries, 2.1 Channel Capability Matrix, 2.2 API Rate Limits (Enforced by MoEngage Gateway), 2. MoEngage Primary API & MCP Research Findings, 3.1 OAuth 2.0 (MCP Server — 30-Day Session) (+36 more)

### Community 28 - "init_database"
Cohesion: 0.13
Nodes (21): get_activity_summary(), get_all_users(), init_store(), load_activities(), Activity tracker & User Identity Manager: Stores all user operations (template…, Query activities from SQLite with filtering, search, and unlimited pagination., Calculate instant live metrics across all team members and activities., Initialize database tables, indexes, and migrate existing JSONL logs. (+13 more)

### Community 29 - "_load_env_file"
Cohesion: 0.08
Nodes (44): _account_prefix(), _esmeaddr_from_session_token(), get_esmeaddr(), get_official_auth_headers(), get_portal_auth_headers(), get_template_namespace_id(), get_waba_id(), _load_env_file() (+36 more)

### Community 30 - "route.ts"
Cohesion: 0.25
Nodes (6): DELETE, dynamic, GET, maxDuration, POST, PUT

### Community 31 - "sms_loader.py"
Cohesion: 0.10
Nodes (31): preview_sms_file_endpoint(), Send single or batch SMS messages directly via JSON. Supports plain or AES-256…, Preview SMS messages from uploaded CSV or Excel file., send_sms_api_endpoint(), _clean_phone_number(), load_sms_from_csv(), load_sms_from_excel(), load_sms_from_list() (+23 more)

### Community 32 - "moengage_sync.py"
Cohesion: 0.06
Nodes (51): AttributeMappingResult, check_semantic_duplicate_pair(), DuplicateCheckResult, find_semantic_duplicate(), MoEngageTemplateTranslation, Any, TypeSafe AI MoEngage Semantic Resolver. Enhances the Karix-to-MoEngage sync and…, Evaluate whether a candidate template semantically duplicates an existing… (+43 more)

### Community 33 - "_submit_wa_batch"
Cohesion: 0.13
Nodes (18): _clean_error_message(), _fetch_whatsapp_inventory(), fetch_whatsapp_templates(), get_stats(), _inspect_template_quality_and_warnings(), Inspect image dimensions, text grammar/spelling, and cross-reference with live…, Flatten error strings or nested error dictionaries into a clean message., Keep Karix's empty-inventory response distinct from a failed fetch. (+10 more)

### Community 34 - "send_sms"
Cohesion: 0.19
Nodes (10): Session, Convenience helper to send a single message to one or more mobile numbers., Send a batch of SMS messages to the Karix SMS JSON API., send_quick_sms(), send_sms(), Outcome of sending an SMS request to Karix., SmsSendResponse, patch (+2 more)

### Community 35 - "download_jira_attachment"
Cohesion: 0.33
Nodes (6): api_route, get_public_media(), Serve cached template header images/videos/documents directly to Karix, Meta,…, download_jira_attachment(), Path, Download an attachment file from Jira and cache it in media_cache/.

### Community 36 - "get"
Cohesion: 0.07
Nodes (35): download_jira_creative_endpoint(), export_moengage_ops_excel_endpoint(), _filter_and_sort_templates(), get_jira_brief_projects_endpoint(), get_moengage_credentials_endpoint(), get_moengage_ops_workspaces(), get_sample_csv(), get_templates() (+27 more)

### Community 38 - "test_production_smoke.py"
Cohesion: 0.15
Nodes (12): Production Deployment & Docker Configuration Smoke Tests. Validates: - Health…, Verify production webhook connectivity: - Rejects unauthorized calls without…, Verify production uptime monitor endpoints respond with 200 OK., - Multi-stage build (frontend-builder + Python runner) - Supervisord running…, Verify signup creates a user and login returns a usable JWT., Verify SQLite store runs in WAL mode with normal sync and 5000ms busy timeout,…, setup_module(), test_auth_signup_and_login_contract() (+4 more)

### Community 39 - "api.py"
Cohesion: 0.11
Nodes (29): _build_rcs_credentials_mapping(), _build_sms_credentials_mapping(), _build_wa_credentials_mapping(), _commit_credentials_to_github(), create_account(), delete_account(), get_account_name(), get_accounts() (+21 more)

### Community 40 - "extract_template_from_jira_text"
Cohesion: 0.07
Nodes (30): extract_template_from_jira_text(), ExtractedTemplateComponent, generate_compliant_variable_samples(), JiraExtractionResult, JiraRoutingDecision, Any, Parse free-form text into Header, Body, Footer, and Button components using…, Determine target channel (WHATSAPP, RCS, SMS, MULTI_CHANNEL) and campaign… (+22 more)

### Community 41 - "fetchWithRetry"
Cohesion: 0.13
Nodes (42): ChannelCounts, DashboardData, MoEngageOpsPage(), VerticalData, WorkspaceItem, callMoEngageMcpTool(), createAccount(), deleteAccount() (+34 more)

### Community 42 - "get_db"
Cohesion: 0.06
Nodes (50): get_db(), _clean_sql_str(), create_job_with_tasks(), get_job(), get_job_task(), get_job_tasks(), list_paused_jobs(), migrate_legacy_jsonl_if_needed() (+42 more)

### Community 43 - "is_valid_template_copy"
Cohesion: 0.07
Nodes (36): Test connectivity to Google Gemini 3.1 Flash-Lite AI Studio API., test_gemini_endpoint(), decompose_content(), detect_category(), detect_language(), is_cta_cell(), is_pure_cta_cell(), _is_targeting_or_planner_row() (+28 more)

### Community 44 - "api.ts"
Cohesion: 0.10
Nodes (26): JiraBriefsPage(), AccountDetection, AlertsDispatchOptions, AspectRatioWarning, AuthResponse, ComplianceWarning, delay(), DeleteTemplatesResult (+18 more)

### Community 45 - "test_moengage_ops.py"
Cohesion: 0.11
Nodes (17): Unit and integration tests for MoEngage Operations Dashboard & Scoping Engine.…, Verify live export into Master Data sheet of MoEngage_Ops_Dashboard.xlsx., Verify live API connection and data extraction from Moneyfy workspace., Verify test, copy, and duplicate keywords are flagged as test campaigns., Verify zip parsing skips __MACOSX, .DS_Store, and non-CSV files., Verify ingest_moengage_export_file processes zip archive and updates…, Verify POST /api/moengage/ops/upload-export accepts ZIP file and returns…, Verify campaign naming conventions accurately resolve to target business… (+9 more)

### Community 46 - "TestSmsApiEndpoints"
Cohesion: 0.09
Nodes (15): StrEnum, Karix SMS content types., Normalized SMS Delivery Status., SmsDeliveryStatus, SmsMessageType, Unit and integration tests for the Karix SMS pipeline. Covers: 1. PII…, Test input normalization and loading from list/CSV., Test process-safe JSONL log tracker and stats aggregation. (+7 more)

### Community 47 - "sms_crypto.py"
Cohesion: 0.10
Nodes (19): decrypt_dlr_gcm(), decrypt_sms_pii(), _derive_aes_key(), encrypt_dlr_gcm(), encrypt_sms_pii(), _normalize_iv_bytes(), _normalize_key_bytes(), Cryptographic utilities for Karix SMS API integration. Implements: 1. AES-256… (+11 more)

### Community 48 - "sms_tracker.py"
Cohesion: 0.17
Nodes (20): get_sms_logs_endpoint(), Query logged SMS submissions, delivery reports (DLR), and click events., get_sms_stats(), load_sms_clicks(), load_sms_dlrs(), load_sms_submissions(), _lock(), log_sms_click() (+12 more)

### Community 49 - "submit_rcs_template"
Cohesion: 0.20
Nodes (18): fetch_rcs_templates(), Submit one RCS template to the official Karix RCS Bot Builder Template API., Fetch all live RCS templates for the bot ID from official Karix RCS endpoint:…, submit_rcs_template(), _account_prefix(), get_rcs_auth_headers(), get_rcs_bot_id(), get_rcs_bot_name() (+10 more)

### Community 50 - "rcs_client.py"
Cohesion: 0.29
Nodes (13): _build_rcs_carousel_vi_template(), _build_rcs_clean_suggestions(), _build_rcs_richcard_vi_template(), _build_rcs_save_payload(), _build_rcs_text_vi_template(), _build_single_suggestion(), _ensure_url_variable(), _extract_and_number_rcs_variables() (+5 more)

### Community 51 - "test_moengage_mcp.py"
Cohesion: 0.20
Nodes (9): Unit and endpoint tests for MoEngage MCP Client & OAuth 2.0 Connector…, Verify FastAPI /api/moengage/mcp/* endpoints., Verify get_mcp_status returns standard mcpServers.moengage JSON configuration., Verify start_mcp_oauth registers a client and complete_mcp_oauth exchanges the…, Verify MCP JSON-RPC client handles initialize, tools/list, and tools/call over…, test_mcp_api_endpoints(), test_mcp_oauth_dynamic_registration_and_pkce_flow(), test_mcp_rpc_initialize_list_tools_and_call_tool_sse() (+1 more)

### Community 52 - "agent.py"
Cohesion: 0.09
Nodes (36): _check_agent_tenant_isolation(), _handle_agent_content_search(), _handle_agent_copy_lint(), _handle_agent_fallback_guidance(), _handle_agent_help_inquiry(), _handle_agent_jira_inquiry(), _handle_agent_list_templates(), _handle_agent_rejection_diagnosis() (+28 more)

### Community 53 - "DraftWriter"
Cohesion: 0.10
Nodes (20): _matches(), Any, Never reissue an attempted POST, including after timeout or process crash., Provider may add defaults; every requested value still has to match., Production construction is denied until the owner explicitly approves every…, authorize_draft_account(), DraftWriter, Any (+12 more)

### Community 54 - "require_tenant_access"
Cohesion: 0.09
Nodes (22): agent_chat_endpoint(), call_moengage_mcp_tool_endpoint(), get_job_endpoint(), get_moengage_rcs_templates_endpoint(), get_sms_stats_endpoint(), get_system_errors(), identify_templates_json_endpoint(), Search Karix / Meta live template inventory by message body copy. Returns… (+14 more)

### Community 55 - "4. Historical Error Incident Catalog"
Cohesion: 0.10
Nodes (19): 1. How to View & Inspect Errors, 2. How the AI Agent Uses the Error Log, 3. How Errors Are Recorded Over Time, 4. Historical Error Incident Catalog, Central Error Log & Diagnostic Engine, Incident 10: `Text Template Overridden to Rich Card Stand Alone with Image`, Incident 11: `PostbackData Lowercasing and Underscore Mismatch`, Incident 12: `Hashtag Variables (#var#) Not Extracted as Placeholders` (+11 more)

### Community 56 - "db.py"
Cohesion: 0.07
Nodes (20): DBConnection, DBCursor, get_database_url(), is_postgres(), migrate_sqlite_to_postgres(), Any, Path, Unified Database Adapter for Karix Whitelisting. Provides seamless dual-driver… (+12 more)

### Community 57 - "test_work_manager.py"
Cohesion: 0.06
Nodes (33): Unit and integration tests for Jira Work Management & Autonomous Workload…, Verify transfer_jira_ticket calls Atlassian API for licensed Jira users., Verify combined querying across all Tata projects (ALL)., Verify cycle time calculations, operator turnaround velocity, and roadblock…, Verify GET /api/work-management/turnaround-analytics returns expected analytics…, Verify bulk_transfer_jira_tickets iterates across issues, reassigns, and audits., Verify POST /api/work-management/bulk-transfer accepts batch reassignments., Verify unassigned tickets automatically route to Neel Shah in work management. (+25 more)

### Community 58 - "rcs_runner.py"
Cohesion: 0.11
Nodes (22): load_rcs_from_csv(), load_rcs_from_list(), Load RCS templates from a CSV file., Load from a list of dicts already in memory., Data models for Karix RCS Bot Builder & DLT template submissions. Storage-…, RCS Runner: wires rcs_loader -> rcs_client -> rcs_tracker together. Entry point…, Submit each RCS DLT template, log the attempt., Load RCS templates from CSV or Excel file, submit each, and log attempt. (+14 more)

### Community 59 - "submit/page.tsx"
Cohesion: 0.17
Nodes (16): ACCEPTED_EXTENSIONS, formatBytes(), isAcceptedFile(), State, SubmitPage(), fetchJob(), getSampleCsvUrl(), IdentificationReport (+8 more)

### Community 60 - "test_excel_parser_gaps.py"
Cohesion: 0.18
Nodes (10): _match_sheet_channel(), _parse_excel_grid_messages(), Parse Excel sheets where copy spans multiple contiguous rows and Column 0…, Unit tests for Excel spreadsheet parser enhancements in briefing_parser.py.…, Verify sheet channel matcher recognizes common client naming variations., Verify _parse_excel_channel_sheets extracts templates from varied sheet names., Verify _parse_excel_grid_messages preserves multi-paragraph copy with blank…, test_match_sheet_channel_variations() (+2 more)

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

### Community 66 - "TestRcsPipeline"
Cohesion: 0.22
Nodes (5): _parse_sender_ids(), Parse sender IDs from a pipe/comma-separated string, list, or None., patch, Unit tests for the RCS Bot Builder template pipeline (current architecture).…, TestRcsPipeline

### Community 67 - "work_manager.py"
Cohesion: 0.06
Nodes (65): add_jira_comment(), adf_to_text(), extract_issue_templates(), fetch_jira_issue(), get_jira_auth_headers(), get_jira_credentials(), list_jira_issues(), Any (+57 more)

### Community 68 - "bulk_transfer_jira_tickets_endpoint"
Cohesion: 0.29
Nodes (7): bulk_transfer_jira_tickets_endpoint(), Any, Authorization policy: Only three people have the power to transfer tickets that…, Transfer/reassign a Jira ticket to another team member or intern. Strictly…, Bulk transfer/reassign multiple Jira tickets to another team member or intern.…, require_transfer_authorization(), transfer_jira_ticket_endpoint()

### Community 69 - "moengage_ops_client.py"
Cohesion: 0.11
Nodes (28): fetch_mcp_ops_records(), fetch_workspace_campaigns(), fetch_workspace_flows(), infer_channel_from_name_or_raw(), _infer_vertical_from_context(), _infer_vertical_from_name(), _is_attributics_author(), _is_test_campaign() (+20 more)

### Community 70 - "log_error"
Cohesion: 0.09
Nodes (40): _handle_agent_error_inquiry(), _handle_agent_learning_inquiry(), diagnose_error_with_learning(), learn_from_error(), LearnedPattern, load_learned_patterns(), _lock(), Any (+32 more)

### Community 71 - "test_jira_brief_endpoint.py"
Cohesion: 0.09
Nodes (25): patch, Tests for Jira brief inspection endpoint (/api/jira/brief/{issue_key}).…, Verify that submit endpoint preserves TEXT headers, footers, and…, Verify /api/jira/projects returns full Tata Capital project catalog., Verify SWCM-59 parses .docx into 3 UTILITY WhatsApp templates with headers and…, Verify SWCM-61 key-value metadata table emits 0 WhatsApp templates and…, Verify channel_counts breakdown is computed on Jira briefs., Verify SWCM-85 single-header execution table extracts WhatsApp template even… (+17 more)

### Community 72 - "TemplateSubmission"
Cohesion: 0.06
Nodes (54): load_from_json(), Shared data models for the Phase-2 (submission-only) pipeline. Kept…, One template to be submitted for whitelisting., TemplateSubmission, compute_text_similarity(), ContentSearchResult, evaluate_semantic_equivalence_typesafe(), _extract_body_text() (+46 more)

### Community 73 - "dispatch_due_today_alerts"
Cohesion: 0.29
Nodes (7): dispatch_due_today_alerts(), Dispatch SLA alerts strictly via Google Chat Space and/or Direct Email.…, Verify dispatch_due_today_alerts in dry-run mode returns draft summaries…, Client-owned blockers must not count against an operator at any SLA checkpoint., test_client_pending_tickets_are_not_attributed_in_sla_webhook(), test_dispatch_due_today_alerts_dry_run(), test_only_client_pending_tickets_do_not_trigger_webhook()

### Community 74 - "queue_manager.py"
Cohesion: 0.13
Nodes (11): QueueManager, Queue Manager, Per-WABA Rate Limiter, Circuit Breaker, and SSE Event Hub.…, Get or initialize the isolated token bucket for a tenant's WABA., Subscribe an SSE connection to live job events., Remove an SSE connection subscriber., Yield Server-Sent Events for a job until it settles or client disconnects., Run single template submission in threadpool to avoid blocking event loop., Token bucket rate limiter isolated per WABA ID. Enforces requests/sec quota and… (+3 more)

### Community 75 - "loader.py"
Cohesion: 0.10
Nodes (35): _bind_embedded_media_to_row(), _build_single_cell_card_submission(), _canonicalize_dynamic_row(), _detect_media_kind(), _dynamic_body_value(), _dynamic_key(), _dynamic_row_to_submission(), _dynamic_template_name() (+27 more)

### Community 76 - "_compute_week_start"
Cohesion: 0.27
Nodes (10): _compute_week_start(), get_date_range_bounds(), _parse_flex_date(), Compute the Monday work-week start for a given date., Calculate effective start and end dates matching the Excel Dashboard formulas., Parse various date formats from MoEngage exports into a datetime.date., date, Verify work-week start always computes the preceding Monday. (+2 more)

### Community 77 - "_resolve_body_variables"
Cohesion: 0.33
Nodes (6): normalize_whatsapp_text_variables(), Normalize non-standard variable tags into official WhatsApp sequential…, Ensure any BODY or BUTTON component containing variables ({{1}}, {{2}}, <name>,…, _resolve_body_variables(), _resolve_button_cta_variables(), Verify that variable normalization and CTA examples generate Tata Capital…

### Community 78 - "runner.py"
Cohesion: 0.11
Nodes (29): classify_template_category_sla(), get_pending_templates_sla_insights(), poll_pending(), Runner: wires loader -> client -> tracker together for WhatsApp templates.…, Phase 2, step 1: submit each template, log the attempt., Phase 2, step 2: check approval status for everything still pending. ONE remote…, Phase 2, step 1 (from CSV or XLSX): load templates from file, submit in…, Classify a pending template into its SLA tier based on category and media… (+21 more)

### Community 79 - "datetime"
Cohesion: 0.14
Nodes (20): Get current state of the automated 10am/1pm/4pm IST alert scheduler., Enable or disable the automated daily alert scheduler., scheduler_status_endpoint(), scheduler_toggle_endpoint(), determine_current_stage(), get_current_ist_time(), is_stage_within_window(), Return the current time in Indian Standard Time (IST, UTC+5:30). (+12 more)

### Community 81 - "karix_webhook_endpoint"
Cohesion: 0.29
Nodes (7): karix_webhook_endpoint(), Real-time webhook receiver for Karix WhatsApp template status updates. Enforces…, Karix SMS Click Report Webhook Callback. Logs URL link clicks from shortened…, Initiate OAuth 2.0 + PKCE flow against https://moeauth.moengage.com for…, receive_sms_click_webhook(), start_moengage_mcp_oauth_endpoint(), Request

### Community 82 - "validate_template_semantic_quality"
Cohesion: 0.07
Nodes (40): lint_and_fix_body(), _lint_meta_variable_rules(), _lint_punctuation_and_caps(), _lint_repeated_and_typos(), Grammar, Spelling & Meta Template Quality Linter. Detects repeated words,…, Analyze text for grammatical mistakes, repeated words, spelling typos,…, Validate technical Meta WhatsApp and RCS compliance rules (Semantic Memory).…, Complete pre-submission audit combining: 1. Grammar & spelling linter with… (+32 more)

### Community 83 - "update_moengage_ops_workspace"
Cohesion: 0.50
Nodes (4): Add or update a MoEngage workspace configuration., update_moengage_ops_workspace(), Save workspace configs to disk., save_workspace_configs()

### Community 84 - "AlertEmailDraft"
Cohesion: 0.28
Nodes (8): AlertEmailDraft, Prepared email ready for dispatch., Send one draft email via SMTP. Falls back gracefully to simulation if SMTP is…, Unified outbound email delivery: 1. Resend API (HTTPS Port 443) if…, send_email_dispatcher(), send_email_smtp(), Verify safe fallback to simulation mode when SMTP credentials are not…, test_send_email_smtp_simulation_fallback()

### Community 89 - "derive_clean_card_title"
Cohesion: 0.40
Nodes (5): derive_clean_card_title(), Derive card title / header title directly from the first line of the content…, Verify first line headline (e.g. '⚡ Funds in 24 Hours!') is used directly as…, test_rcs_card_title_derived_cleanly_from_body_topic(), test_rcs_card_title_uses_first_line_headline_without_fallback()

### Community 90 - "test_email_campaign_separation.py"
Cohesion: 0.33
Nodes (5): Unit tests for Email campaign separation from WhatsApp, RCS, and SMS. Verifies:…, Verify list_jira_issues tags email vs messaging campaigns., Verify parse_jira_brief isolates email templates from WhatsApp/RCS/SMS., test_list_jira_issues_separates_email_and_messaging(), test_parse_jira_brief_separates_email_templates()

### Community 91 - "extract_templates_from_excel_file"
Cohesion: 0.09
Nodes (26): extract_templates_from_excel_file(), _is_dlt_sms_sheet(), _load_spreadsheet_sheets(), _parse_dlt_sms_sheet(), Universally load any spreadsheet file (.xlsx, .csv, .xls) into a dictionary of…, Detect if an Excel spreadsheet is an official DLT SMS template export., Parse official DLT SMS template spreadsheet rows into canonical SMS template…, Inspect and extract template items from any client spreadsheet (.xlsx, .csv,… (+18 more)

### Community 92 - "OperatorTicketSummary"
Cohesion: 0.21
Nodes (12): build_stage_email(), OperatorTicketSummary, Group of due-today incomplete tickets assigned to an operator., Generate HTML and plain text email content tailored to the stage., Send an interactive rich card to Google Chat Space via Incoming Webhook. Uses…, send_google_chat_sla_alert(), Verify Google Chat fallback simulation when no webhook URL is configured., Verify Google Chat webhook POST request structure. (+4 more)

### Community 93 - "test_agent_remediation.py"
Cohesion: 0.10
Nodes (19): Tests for Autonomous AI Copilot Auto-Remediation Engine and Meta Policy…, Verify conversational chat interaction for rejection diagnosis and 1-click…, Verify AI Copilot can search existing Karix templates by body copy in natural…, Verify word-to-variable ratio remediation (Meta Error 2388293)., Pasting template copy alone should search the live Karix catalog., Plain sentence copy should also be treated as pasted template content., A catalog/API failure must not be presented as a missing template., Verify header text exceeding 60 characters is trimmed to compliant length. (+11 more)

### Community 94 - "TestCredentialContract"
Cohesion: 0.33
Nodes (3): Tests for credential handling after Playwright removal. The Karix portal…, A 401 from the portal API fails the template with a clear message — no browser,…, TestCredentialContract

### Community 95 - "AlertSchedulerState"
Cohesion: 0.22
Nodes (6): AlertSchedulerState, Persistent state of the automated daily alert scheduler backed by…, Verify AlertSchedulerState prevents duplicate sends for the same slot on the…, Verify AlertSchedulerState persists to DB and prevents duplicate dispatch on…, test_scheduler_db_persistence_deduplication(), test_scheduler_state_deduplication()

### Community 96 - "sms_client.py"
Cohesion: 0.11
Nodes (35): Karix SMS Delivery Report (DLR) Forwarding via HTTPs Callback API. Supports…, receive_sms_dlr_webhook(), _prepare_payload_messages(), Any, Client for Karix SMS JSON API. Sends SMS messages (One-to-One, One-to-Many,…, Check configuration and reachability for the given account's SMS integration.…, Validate and sanitize a single message, returning cleaned destinations and…, Prepare all messages for the API request payload. (+27 more)

### Community 97 - "Karix Multi-Channel Template Whitelisting & Automation Platform"
Cohesion: 0.22
Nodes (8): 1. Environment Configuration, 2. Local Development, 3. Docker Deployment, 🚀 Getting Started, Karix Multi-Channel Template Whitelisting & Automation Platform, 🏛 Multi-Channel Architecture, 📁 Repository Directory Structure, 🧪 Testing & Security Verification

### Community 100 - "test_integration.py"
Cohesion: 0.12
Nodes (16): check_status(), _match_template(), Match a provider ref against fb_template_id, sno, or template name (case-…, Read the latest approval status from the official Karix template list.…, Verify validate_meta_technical_compliance detects word ratio limits (Meta Error…, Verify check_status can reach the API and find a known template. Picks the…, Verify that when Karix or Meta returns 'Template Already Exist.' or 'There is…, Verify that duplicate template names within the same uploaded batch/spreadsheet… (+8 more)

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
Cohesion: 0.20
Nodes (14): get_brevo_event_logs(), get_due_today_incomplete_tickets(), get_smtp_sender_info(), group_tickets_by_operator(), preview_due_today_alerts(), Any, Automated 3-Stage Daily SLA Email Dispatcher & Scheduler. Schedules &…, Return due-today operator work, excluding client-owned base/content blockers. (+6 more)

## Knowledge Gaps
- **181 isolated node(s):** `moengage`, `moengage`, `dynamic`, `maxDuration`, `GET` (+176 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `parse_jira_brief()` connect `briefing_parser.py` to `extract_and_strip_cta`, `download_jira_attachment`, `work_manager.py`, `api.py`, `extract_template_from_jira_text`, `test_jira_brief_endpoint.py`, `is_valid_template_copy`, `agent.py`, `post`, `derive_clean_card_title`, `test_email_campaign_separation.py`, `extract_templates_from_excel_file`, `normalize_placeholders`?**
  _High betweenness centrality (0.080) - this node is a cross-community bridge._
- **Why does `_load_env_file()` connect `_load_env_file` to `moengage_sync.py`, `work_manager.py`, `moengage_ops_client.py`, `api.py`, `moengage_mcp.py`, `is_valid_template_copy`, `email_notifier.py`, `validate_template_semantic_quality`, `agent.py`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Why does `TemplateSubmission` connect `TemplateSubmission` to `submission_client.py`, `test_integration.py`, `api.py`, `queue_manager.py`, `loader.py`, `RcsTemplateSubmission`, `KarixHealthGovernor`, `post`, `_load_env_file`, `TestCredentialContract`?**
  _High betweenness centrality (0.019) - this node is a cross-community bridge._
- **Are the 44 inferred relationships involving `TemplateSubmission` (e.g. with `AccountCreate` and `AgentChatRequest`) actually correct?**
  _`TemplateSubmission` has 44 INFERRED edges - model-reasoned connections that need verification._
- **What connects `moengage`, `moengage`, `dynamic` to the rest of the system?**
  _181 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `briefing_parser.py` be split into smaller, more focused modules?**
  _Cohesion score 0.09024390243902439 - nodes in this community are weakly interconnected._
- **Should `auth.py` be split into smaller, more focused modules?**
  _Cohesion score 0.1341991341991342 - nodes in this community are weakly interconnected._