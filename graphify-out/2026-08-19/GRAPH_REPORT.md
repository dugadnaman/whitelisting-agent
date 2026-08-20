# Graph Report - karix  (2026-08-17)

## Corpus Check
- 32 files · ~13,546 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 282 nodes · 449 edges · 17 communities (11 shown, 6 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 3 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- api.py
- test_rcs.py
- submission_client.py
- devDependencies
- compilerOptions
- api.ts
- _is_retryable
- Karix WhatsApp Template Whitelisting — Project Rules
- layout.tsx
- Frontend Design
- AGENTS.md
- rules/graphify.md
- workflows/graphify.md
- next.config.mjs
- next-env.d.ts
- postcss.config.mjs
- tailwind.config.ts

## God Nodes (most connected - your core abstractions)
1. `compilerOptions` - 16 edges
2. `RcsTemplateSubmission` - 16 edges
3. `get_auth_headers()` - 11 edges
4. `TemplateSubmission` - 11 edges
5. `submit_rcs_template()` - 11 edges
6. `_row_to_rcs_submission()` - 11 edges
7. `submit_template()` - 11 edges
8. `Karix WhatsApp Template Whitelisting — Project Rules` - 10 edges
9. `load_from_csv()` - 9 edges
10. `load_from_excel()` - 9 edges

## Surprising Connections (you probably didn't know these)
- `test_credentials()` --calls--> `get_auth_headers()`  [EXTRACTED]
  api.py → config.py
- `_build_create_body()` --references--> `TemplateSubmission`  [EXTRACTED]
  submission_client.py → models.py
- `submit_template()` --references--> `TemplateSubmission`  [EXTRACTED]
  submission_client.py → models.py
- `log_result()` --references--> `SubmissionResult`  [EXTRACTED]
  tracker.py → models.py
- `TestRcsPipeline` --uses--> `RcsSubmissionStatus`  [INFERRED]
  test_rcs.py → rcs_models.py

## Import Cycles
- None detected.

## Communities (17 total, 6 thin omitted)

### Community 0 - "api.py"
Cohesion: 0.08
Nodes (46): CredentialUpdate, get_stats(), get_templates(), poll(), preview_file(), FastAPI backend for the Karix WhatsApp template whitelisting tool. Wraps the…, submit_file(), test_credentials() (+38 more)

### Community 1 - "test_rcs.py"
Cohesion: 0.06
Nodes (53): patch, _build_dlt_payload(), Client for Karix Lounge RCS / DLT template registration. Sends…, Build the payload for Karix Lounge DLT registration., Submit one RCS DLT template for configuration/whitelisting on Karix Lounge.…, submit_rcs_template(), get_rcs_auth_headers(), _load_env_file() (+45 more)

### Community 2 - "submission_client.py"
Cohesion: 0.09
Nodes (34): get_auth_headers(), _load_env_file(), Configuration for the Karix WhatsApp template submission pipeline. All secrets…, Load key-value pairs from a local .env file if present., Build the full set of HTTP headers required by the Karix API. Raises…, # NOTE: Content-Type is NOT included here because it differs per endpoint:, ApprovalStatus, Enum (+26 more)

### Community 3 - "devDependencies"
Cohesion: 0.07
Nodes (29): autoprefixer, dependencies, next, react, react-dom, devDependencies, autoprefixer, postcss (+21 more)

### Community 4 - "compilerOptions"
Cohesion: 0.07
Nodes (26): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+18 more)

### Community 5 - "api.ts"
Cohesion: 0.15
Nodes (18): DashboardPage(), formatDate(), Banner, ACCEPTED_EXTENSIONS, formatBytes(), isAcceptedFile(), State, SubmitPage() (+10 more)

### Community 6 - "_is_retryable"
Cohesion: 0.50
Nodes (4): Exception, Response, _is_retryable(), Return True only for transport-level failures we should retry.

### Community 7 - "Karix WhatsApp Template Whitelisting — Project Rules"
Cohesion: 0.18
Nodes (10): Auth model — known limitation, Bajaj account constants, Bajaj vs Tata Capital — strict separation, File responsibilities, Karix API quirks — do NOT "clean up", Karix WhatsApp Template Whitelisting — Project Rules, Likely next steps (for planning context), Scope boundaries (+2 more)

### Community 8 - "layout.tsx"
Cohesion: 0.33
Nodes (4): inter, metadata, links, Nav()

### Community 9 - "Frontend Design"
Cohesion: 0.29
Nodes (6): Design principles, Frontend Design, Ground it in the subject, More on writing in design, Process: brainstorm, explore, plan, critique, build, critique again, Restraint and self-critique

### Community 10 - "AGENTS.md"
Cohesion: 0.40
Nodes (4): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution

## Knowledge Gaps
- **66 isolated node(s):** `inter`, `metadata`, `Banner`, `State`, `links` (+61 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_auth_headers()` connect `submission_client.py` to `api.py`?**
  _High betweenness centrality (0.014) - this node is a cross-community bridge._
- **Why does `submit_template()` connect `submission_client.py` to `api.py`?**
  _High betweenness centrality (0.009) - this node is a cross-community bridge._
- **What connects `inter`, `metadata`, `Banner` to the rest of the system?**
  _66 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `api.py` be split into smaller, more focused modules?**
  _Cohesion score 0.08 - nodes in this community are weakly interconnected._
- **Should `test_rcs.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06340326340326341 - nodes in this community are weakly interconnected._
- **Should `submission_client.py` be split into smaller, more focused modules?**
  _Cohesion score 0.08677098150782361 - nodes in this community are weakly interconnected._
- **Should `devDependencies` be split into smaller, more focused modules?**
  _Cohesion score 0.06666666666666667 - nodes in this community are weakly interconnected._