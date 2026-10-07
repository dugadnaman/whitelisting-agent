# Tata Capital — imported-base unique click count

Investigated 2026-10-07. Design/research only; no Tata customer API query, segment creation, message sending, or credential changes performed. Apparel remains paused; see APPAREL_ATTRIBUTION_PAUSED.md.

## Required metric

Distinct MoEngage users who belong to the selected imported base AND performed at least one eligible click event on ANY selected channel within the reporting interval. This is a union, not a sum of per-channel unique counts. Start date comes from Data Imports creation metadata, not campaign sent date or user-profile creation date. Operator selects end date; interpret the dates in Tata's workspace timezone and explicitly include the whole end date. Confirm whether the manual workflow starts at the exact import timestamp or midnight on that date before building the payload.

Default interpretation of the user's stated query is clicks on any eligible campaign by base members. If their existing manual query narrows to campaigns for this base, retain those event attribute filters; do not silently change the scope.

## Documented API route

MoEngage's hosted MCP at https://mcp.moengage.com offers deterministic tools; an AI/model call is not needed to invoke them. Its official reference documents:

- `list_segments`: File/Filter segment metadata, IDs, names and timestamps; does not cover Warehouse, Analytics or Composite segments.
- `get_segment`: complete filter definition, or metadata only for file/cohort-import segments.
- `find_events`, `find_user_attributes`, `find_event_attributes`: resolve internal names rather than guessed UI labels.
- `discover_schema`: retrieve current payload schema; do not assume REST and MCP argument envelopes are interchangeable.
- `deep_validate_segment_filters`: HTTP 200 is not sufficient; require `is_valid` true.
- `create_recent_query`, `get_recent_query`, `get_recent_query_filters`: ad-hoc audience count without saving a segment; poll until `success` and then read `user_count`; failure has `failure_reason`. Reachability counts are contactability, not click counts, and are not the requested metric.
- `create_custom_segment`, `start_segment_count`, `poll_segment_count`: saved-segment alternative if the business also needs a reusable segment.

Source: https://www.moengage.com/docs/user-guide/ai-and-intelligence/merlin-ai/moengage-mcp-server . Tools depend on Tata's authenticated workspace/environment and role. Account access, entitlement and incremental charges have NOT been verified. OAuth authorization is distinct from browser sign-in.

REST provides GET/POST `/v3/custom-segments` and GET `/v3/custom-segments/{id}` on the workspace's `https://api-{dc}.moengage.com` origin, Basic Auth plus `MOE-APPKEY` (or documented database-name alternative). List/get metadata examples include `created_time`; these are not a documented standalone count result. The filter contract supports `custom_segments` membership by ID, `nested_filters` AND/OR groups, and `actions` with at-least-once execution and absolute `between` time ranges.

Sources:
- https://www.moengage.com/docs/api/filter-segments/list-segments
- https://www.moengage.com/docs/api/filter-segments/get-segment-by-id
- https://www.moengage.com/docs/api/filter-segments/create-filter-segment

## Imported-base metadata API

The official Import Details API documents `POST https://fileimports-data-api-{dc}.moengage.com/v1.0/data/fileimports/import/status`, with Basic Auth and `MOE-APPKEY`. It returns `import_id`, `import_name`, `created_at`, `time_zone`, processing status and `custom_segment_config` with linked segment ID/name when present. The documented no-filter request body is `{}`. Paginate in pages of at most 50 using `offset` and `more_files`. Use `created_at`, not segment `created_time` or `last_run_at`.

File-level discovery uses `POST https://fileimports-data-api-{dc}.moengage.com/v1.0/data/fileimports/import/run/history` with import ID or name. This exposes filenames, file IDs, scheduled/completed timestamps and statuses. A file ID is not a saved segment ID. Data Import creation, scheduled run, processing completion and segment creation are different timestamps; retain the user's actual chosen source.

The Data Imports UI explicitly distinguishes import Name, linked Custom Segment and Created at. Times display in the configured app timezone (UTC if unset). An import need not save a custom segment. If no membership segment exists, metadata alone cannot constrain the audience; require the actual approved base-membership source. Current mutable segment membership is not an original-file snapshot.

The official import docs have schema/example inconsistencies: timestamp type vs offset-less string examples, arrays vs strings for filters, and boolean vs string pagination flags. Verify one real Tata response before implementing parsing/date normalization. Endpoint existence does not establish Tata access or zero incremental charges.

Sources:
- https://www.moengage.com/docs/api/file-import/import-details
- https://www.moengage.com/docs/api/file-import/import-file-run-history
- https://www.moengage.com/docs/user-guide/data/imports/overview-imports

## Existing repository boundary

`backend/moengage_mcp.py` already has MCP initialization, tool discovery and a paginated `mcp_list_segments` helper. `backend/api.py` restricts generic MCP calls to search_campaigns, search_flows, list_segments and get_campaign_stats. Count queries are not implemented/allowed there today. Add a dedicated authenticated Tata count route in any later implementation, not arbitrary tool access and not reuse of the Apparel worker.

## Acceptance for later implementation

- Resolve base membership and correct import start date, using immutable IDs rather than ambiguous names.
- Resolve eligible click event internal names in Tata's workspace; opens/read/delivered events are not clicks.
- Keep Tata-only credentials and workspace/environment binding on the server; authorize each portal caller.
- Compare one known manual segment count with the API result using the exact same base, interval, filters and identity semantics.
- Display processing/failure separately from a genuine zero count.
- Do not create a saved segment when the requested result is just a number; do not publish/send any campaign.
- Record base, start/end, timezone, chosen channels, evaluated-at time and count. Counts may change with late-arriving events or changes to base membership.
- Segmentation time-range queries use server Received Time according to https://www.moengage.com/docs/user-guide/data/event-data/event-time-and-received-time ; this may differ from actual click occurrence time. Match the existing dashboard query semantics, do not promise occurrence-time reporting.
- Count MoEngage user identities, not sums of link-unique metrics. Exact channel event names need Tata catalog/payload confirmation, particularly RCS suggestion clicks vs URL clicks. Tracked-link coverage/expiry and bot filtering can affect historical counts.

## Verification performed

A synthetic in-memory set/date example returned two unique base users when one clicked SMS and WhatsApp, another clicked RCS on the end date, one clicker was outside the base, another clicked before start, and another clicked at next-day midnight. This proves the intended union/date semantics only, not MoEngage execution. No live Tata count was run.
