# MoEngage Campaign Creation Agent — Architectural Specification & Research Dossier

> **Audience:** Autonomous AI Agents (e.g. GPT-6 / Specialized Solvers) and Systems Engineers.  
> **Status:** Specification & Architectural Reference  
> **Primary Systems:** MoEngage V5 REST API, MoEngage Hosted MCP Server (`https://mcp.moengage.com`), OAuth 2.0 Auth Server (`https://moeauth.moengage.com`).

---

## 1. Executive Summary & Scope Boundaries

### 1.1 What This System Is
The **MoEngage Campaign Creation Agent** is an automated engine that accepts structured campaign briefs (from Jira tickets, batch Excel/CSV spreadsheets, or JSON requests) and converts them into fully populated, compliant, and validated **Campaign Drafts** directly inside MoEngage workspaces.

### 1.2 Strict Separation from WhatsApp Whitelisting
This agent is **independent from the Karix WhatsApp Whitelisting Engine**:
- **Karix Whitelisting Engine:** Automates template submission from master catalogs/Jira to Karix BSP → Meta WABA approval for WhatsApp templates.
- **MoEngage Campaign Creation Agent:** Takes approved templates, creatives, copy, and audience filters, and assembles actual marketing/utility campaign drafts inside the customer engagement platform (MoEngage).

### 1.3 Inviolable Safety Constraint: STRICTLY DRAFT-ONLY
> **CRITICAL INVARIANT:** Under no circumstances may this agent publish, launch, broadcast, or trigger live outbound messages to end-users.

All campaigns created by this agent must:
1. Be created in `status: "DRAFT"`.
2. Pass pre-flight publish validation (`validate_campaign_draft`) in dry-run mode.
3. Be left in MoEngage's **Drafts** queue for a human marketer to review, verify audience sizing, and manually click **Publish**.

---

## 2. MoEngage Primary API & MCP Research Findings

Research conducted directly against MoEngage's primary documentation, OpenAPI specifications, and the live MoEngage MCP Server (`v1.30.0` at `https://mcp.moengage.com`):

### 2.1 Channel Capability Matrix

| Channel | Programmatic Draft Creation | Public API / MCP Endpoint | Notes & Constraints |
| :--- | :---: | :--- | :--- |
| **Email** | **YES (100%)** | `POST /campaigns` (V5)<br>or `create_campaign_draft` (MCP) | Full support: HTML copy, Jinja variables (`{{UserAttribute['First Name']}}`), attachments, A/B variants, scheduling. |
| **Mobile Push** (Android, iOS, Web) | **YES (100%)** | `POST /campaigns` (V5)<br>or `create_campaign_draft` (MCP) | Full support: notification channels, deep links, custom key-value pairs, rich media banners, iOS live activity. |
| **SMS / MMS** | **YES (MCP / V1)** | `create_campaign_draft` (MCP)<br>or Legacy V1 API | Supported via MCP (`channel='SMS'` or `channel='MMS'`). V5 REST API does not support SMS creation directly. Max 1,600 chars. |
| **WhatsApp Outbound Broadcast** | **NO (Dashboard Only)** | ❌ None (Read-only via API) | Public APIs and MCP only support `search_campaigns` and `get_campaign` for WhatsApp. WhatsApp *templates* can be created via MCP `create_template`, but *campaign broadcasts* require dashboard creation. |
| **RCS Outbound Broadcast** | **NO (Dashboard Only)** | ❌ None (Read-only via API) | RCS templates can be registered via Settings API, but campaign broadcasts require dashboard creation. |
| **Multi-Channel Flows (Journeys)** | **NO (Dashboard Only)** | ❌ Read & Status control only | `search_flows`, `get_flow`, and `update_flow_status` (pause/resume/stop). MoEngage does not support programmatic flow creation. |

### 2.2 API Rate Limits (Enforced by MoEngage Gateway)
- **Per Minute:** 5 successful campaign creations per client.
- **Per Hour:** 25 successful campaign creations per client.
- **Per Day:** 100 successful campaign creations per client (strictest ceiling).
- *Implication for Agent:* Batch creation pipelines must throttle requests and serialize submissions with rate-limiting queues.

---

## 3. Authentication & Workspace Discovery

MoEngage supports two distinct authentication surfaces:

### 3.1 OAuth 2.0 (MCP Server — 30-Day Session)
- **Hosted MCP Endpoint:** `https://mcp.moengage.com`
- **Auth Server:** `https://moeauth.moengage.com`
- **Protocol:** Dynamic Client Registration (RFC 7591) + Authorization Code Grant with PKCE (`S256`).
- **Scopes:** `openid email profile offline_access campaigns:read`
- **Session Duration:** 30 days via `refresh_token` rotation (7-day idle timeout).
- **Embedded Dashboard Token:** The issued JWT contains a `moe_bearer` claim containing the valid dashboard JWT for `dashboard-0X.moengage.com`, allowing background synchronization with private endpoints without manual DevTools intervention.

### 3.2 Basic Authentication (REST API V1 / V5)
- **Endpoint Pattern:** `https://api-{dc}.moengage.com/core-services/v1` (where `{dc}` is `01`, `02`, `03`, etc. — e.g. Tata Capital is `03`).
- **Headers:**
  ```http
  Authorization: Basic base64(WORKSPACE_ID:API_KEY)
  MOE-APPKEY: WORKSPACE_ID
  Content-Type: application/json
  ```
- **Permission Requirements:** The API Key must have the **Campaigns** scope set to **Create & Manage** (or **Create, Manage & Publish**).

---

## 4. Universal Campaign Input Specifications

Every MoEngage campaign draft requires five distinct schema blocks:

```
┌────────────────────────────────────────────────────────┐
│               Campaign Input Structure                 │
├────────────────────────────────────────────────────────┤
│ 1. Basic Details     (Name, Tags, Channel Settings)    │
│ 2. Campaign Content  (Copy, HTML, Subject, CTA URL)    │
│ 3. Connector         (Sender Profile, ESP Connector)   │
│ 4. Segmentation      (Target Audience Filter / Custom) │
│ 5. Scheduling        (ASAP / Fixed Time / Throttling)  │
└────────────────────────────────────────────────────────┘
```

### 4.1 Block 1: Basic Details (`basic_details`)
- `name` (String, 5–256 chars, required): Canonical campaign identifier.
  - *Standard Naming Pattern:* `{VERTICAL}MOE_{PRODUCT}_{CAMPAIGN}_{CHANNEL}_{DATE}` (e.g., `TCLMOE_PAPL_Diwali_Email_01Oct26`).
- `created_by` (String, email, required): Corporate email address of the creator.
- `tags` (Array of Strings, max 30): Tagging taxonomy for reporting (e.g., `["PAPL", "Diwali", "Q3"]`).
- `content_type` (Email-only enum): `"PROMOTIONAL"` or `"TRANSACTIONAL"`.
- `subscription_category` (Email-only string): Category matching workspace settings (e.g., `"marketing"`).
- `user_attribute_identifier` (Email-only string): User profile attribute holding the email (usually `"Email (Standard)"` or `"MOE_EMAIL_ID"`).
- `platforms` (Push-only array): `["ANDROID", "IOS"]` or `["WEB"]`.

### 4.2 Block 2: Campaign Content (`campaign_content`)

#### For Email:
```json
{
  "content": {
    "email": {
      "subject": "Diwali Pre-Approved Loan Offer for {{UserAttribute['First Name']}}",
      "preview_text": "Exclusive interest rates starting from 8.99% p.a.",
      "sender_name": "Tata Capital",
      "from_address": "offers@tatacapital.com",
      "reply_to_address": "contact@tatacapital.com",
      "html_content": "<!DOCTYPE html><html><body>...</body></html>"
    }
  }
}
```
*Note:* `html_content` and `custom_template_id` are mutually exclusive.

#### For Mobile Push:
```json
{
  "content": {
    "push": {
      "android": {
        "template_type": "BASIC",
        "basic_details": {
          "notification_channel": "general",
          "title": "⚡ Funds in 24 Hours!",
          "message": "Hi {{UserAttribute['First Name']}}, your special loan offer is ready.",
          "default_click_action": "DEEPLINKING",
          "default_click_action_value": "tatacapital://loans/apply?campaign=diwali"
        }
      },
      "ios": {
        "template_type": "BASIC",
        "basic_details": {
          "title": "⚡ Funds in 24 Hours!",
          "message": "Hi {{UserAttribute['First Name']}}, your special loan offer is ready.",
          "default_click_action": "DEEPLINKING",
          "default_click_action_value": "tatacapital://loans/apply?campaign=diwali"
        }
      }
    }
  }
}
```

#### For SMS:
```json
{
  "content": {
    "sms": {
      "message": "Dear {#var#}, your Tata Capital loan of Rs. {#var#} is ready. Apply now: https://u3.mnge.co/d T&Cs apply."
    }
  }
}
```

### 4.3 Block 3: Connector Configuration (`connector`)
- **Email:**
  ```json
  "connector": {
    "connector_type": "SENDGRID",
    "connector_name": "default"
  }
  ```
- **SMS:**
  ```json
  "connector": {
    "connector_name": "SmsGupshup",
    "sender_name": "TCFSL_TATATC"
  }
  ```

### 4.4 Block 4: Segmentation Details (`segmentation_details`)
Campaigns must target either a pre-built segment or an attribute filter.

- **Option A: Referencing a Pre-Built Custom Segment (Recommended):**
  ```json
  "segmentation_details": {
    "included_filters": {
      "filter_operator": "and",
      "filters": [
        {
          "filter_type": "custom_segments",
          "name": "Tata_Capital_PreApproved_Audience",
          "id": "673f4e2b06ff33a780c822a1"
        }
      ]
    }
  }
  ```
- **Option B: Attribute Filter (e.g. All Reachable Users):**
  ```json
  "segmentation_details": {
    "is_all_user_campaign": false,
    "included_filters": {
      "filter_operator": "and",
      "filters": [
        {
          "filter_type": "user_attributes",
          "data_type": "string",
          "name": "Email (Standard)",
          "operator": "exists"
        }
      ]
    }
  }
  ```

### 4.5 Block 5: Scheduling Details (`scheduling_details`)
- **ASAP (Launches immediately upon human marketer review/publish):**
  ```json
  "scheduling_details": {
    "delivery_type": "ASAP"
  }
  ```
- **Fixed Future Time:**
  ```json
  "scheduling_details": {
    "delivery_type": "AT_FIXED_TIME",
    "start_time": "2026-10-15T10:00:00",
    "timezone": "Asia/Kolkata"
  }
  ```
  *Constraint:* `start_time` must use format `YYYY-MM-DDTHH:mm:ss` (no trailing `Z`).

---

## 5. Input Ingestion Interfaces for Batch Creation

To support "bunches of campaigns" without manual UI data entry, the agent must accept three input interfaces:

### Interface 1: Multi-Row Spreadsheet Ingestion (CSV / Excel)
Used by business marketing teams submitting multiple campaign variants:

| Column Header | Data Type | Required | Description | Example |
| :--- | :---: | :---: | :--- | :--- |
| `campaign_name` | String | Yes | Name for the MoEngage campaign | `TCL_Diwali_Email_Tier1` |
| `channel` | Enum | Yes | `EMAIL`, `PUSH`, or `SMS` | `EMAIL` |
| `subject_or_title` | String | Yes | Email Subject or Push Title | `Exclusive Diwali Offer` |
| `body_or_html` | Text / Path | Yes | Copy text, HTML string, or file path | `<html>...</html>` |
| `target_segment` | String / ID | Yes | Segment ID or exact Segment Name | `PreApproved_LTV_50` |
| `scheduled_time` | ISO String | No | Scheduled delivery time (or ASAP) | `2026-10-10T10:00:00` |
| `cta_url` | URL | No | Destination / Deep link | `https://u3.mnge.co/oct26` |
| `tags` | Comma-list | No | Tags for MoEngage grouping | `Diwali, Loans, Tier1` |

### Interface 2: Jira Brief Ingestion (e.g. TCN / SWCM Tickets)
The agent integrates with Jira Cloud via ADF and attachment parsing:
1. **Summary & Labels:** Yields `campaign_name` prefix, product tags, and target account.
2. **Attached Assets:**
   - `.zip` mailer package → extracted into HTML body + image assets.
   - `.docx` / `.xlsx` copy grid → parsed into multiple variant copies (Segment 1, Segment 2, Segment 3).
3. **Execution:** The agent maps each variant in the Jira brief into an individual MoEngage draft.

### Interface 3: Batch JSON API Schema
For programmatic system-to-system integration:

```json
{
  "account": "tata",
  "batch_reference": "JIRA-TCN-543-BATCH",
  "campaigns": [
    {
      "channel": "EMAIL",
      "name": "tcn_543_tcl_email_tier1",
      "subject": "Diwali Offer - Tier 1",
      "html_content": "<!DOCTYPE html>...",
      "segment_name": "Tier_1_Approved",
      "delivery_type": "ASAP"
    },
    {
      "channel": "PUSH",
      "name": "tcn_543_tcl_push_tier1",
      "title": "⚡ Special Offer",
      "message": "Your loan is ready.",
      "deeplink": "tatacapital://loans",
      "segment_name": "Tier_1_Approved",
      "delivery_type": "ASAP"
    }
  ]
}
```

---

## 6. Execution Lifecycle for the Agent

When executing a campaign creation task, the agent must adhere to this exact sequence:

```
[Input Brief]
      │
      ▼
1. Discovery (MCP discover_schema, list_segments, get_sms_settings)
      │
      ▼
2. Resolution (Match segment_name -> segment_id, resolve sender connectors)
      │
      ▼
3. Draft Assembly (Construct strict V5 / MCP JSON payload)
      │
      ▼
4. Draft Creation (create_campaign_draft -> returns draft_id in status: DRAFT)
      │
      ▼
5. Validation (validate_campaign_draft -> verify { valid: true })
      │
      ▼
6. Staging Report (Post draft IDs and preview links to Jira / Audit Log)
      │
      ▼
[Human Review in MoEngage UI -> Manual Publish]
```

### Step-by-Step Rulebook

1. **Discovery First:** The agent must never guess internal identifiers (segment IDs, connector names, notification channel names). Use `list_segments` and `get_sms_settings` to retrieve canonical identifiers.
2. **Enforce Rate Limits:** Sleep or yield between requests if batch size exceeds 5 campaigns per minute.
3. **Draft Verification:** Immediately following `create_campaign_draft`, the agent must invoke `validate_campaign_draft(campaign_id=...)`. If `valid` is false, inspect the `errors` array, patch the invalid component, and re-validate.
4. **Handoff:** Conclude by logging the newly generated MoEngage `campaign_id`s in the activity log and Jira ticket comments with direct deep-links to the MoEngage Drafts console:
   `https://dashboard-03.moengage.com/v4/campaigns/drafts?id={campaign_id}`.

---

## 7. Reference Implementations in Codebase

- **MCP Client & OAuth Engine:** `backend/moengage_mcp.py`
  - `start_mcp_oauth` / `complete_mcp_oauth`
  - `mcp_search_campaigns` / `mcp_search_flows`
  - `mcp_create_campaign_draft` / `call_mcp_tool`
- **Dashboard Sync & Template Engine:** `backend/moengage_sync.py`
  - `get_or_refresh_moe_bearer` (automatically extracts 30-day token)
- **Briefing Parser & Jira Intake:** `backend/briefing_parser.py`
  - `parse_jira_brief` (extracts email mailer packages and staged payloads)
- **Operational Reporting Engine:** `backend/moengage_ops_client.py`
  - `sync_all_moengage_ops` (aggregates live campaigns and flows)
