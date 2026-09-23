"""
Atlassian Jira REST API Integration Client for Karix Whitelisting & Briefing Engine.
Connects to tatacapital-team.atlassian.net to inspect campaign briefs,
download creative attachments, and post automated status reports back to tickets.
"""

import base64
import logging
import os
import re
from pathlib import Path
from typing import Any

import requests
from config import _load_env_file

logger = logging.getLogger(__name__)

MEDIA_CACHE_DIR = Path("media_cache")
MEDIA_CACHE_DIR.mkdir(exist_ok=True)


def get_jira_credentials() -> tuple[str, str, str]:
    """Load Jira base URL, email, and API token from environment / credentials.json."""
    _load_env_file()
    base_url = (
        os.environ.get("JIRA_BASE_URL")
        or "https://tatacapital-team.atlassian.net"
    ).rstrip("/")
    email = (
        os.environ.get("JIRA_USER_EMAIL")
        or os.environ.get("JIRA_EMAIL")
        or ""
    ).strip()
    token = (
        os.environ.get("JIRA_API_TOKEN")
        or os.environ.get("ATLASSIAN_API_TOKEN")
        or ""
    ).strip()
    return base_url, email, token


def get_jira_auth_headers() -> dict[str, str]:
    """Build Basic Auth headers for Atlassian Jira Cloud REST API v3."""
    _, email, token = get_jira_credentials()
    if not email or not token:
        raise OSError(
            "Missing Jira credentials. Configure JIRA_USER_EMAIL and JIRA_API_TOKEN in Settings / credentials.json."
        )
    auth_str = f"{email}:{token}"
    b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
    return {
        "Authorization": f"Basic {b64_auth}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Karix-Briefing-Agent/1.0",
    }


def adf_to_text(node: dict[str, Any] | None) -> str:
    """Recursively convert Atlassian Document Format (ADF) into readable text with tables."""
    if not node or not isinstance(node, dict):
        return ""

    node_type = node.get("type")
    if node_type == "text":
        return str(node.get("text", ""))
    if node_type == "hardBreak":
        return "\n"
    if node_type == "paragraph":
        content = [adf_to_text(c) for c in node.get("content", [])]
        return "".join(content) + "\n"
    if node_type == "bulletList" or node_type == "orderedList":
        items = []
        for idx, item in enumerate(node.get("content", []), start=1):
            prefix = f"{idx}. " if node_type == "orderedList" else "• "
            items.append(prefix + adf_to_text(item).strip())
        return "\n".join(items) + "\n\n"
    if node_type == "listItem":
        return "".join(adf_to_text(c) for c in node.get("content", []))
    if node_type == "table":
        rows = []
        for row in node.get("content", []):
            cells = [
                "".join(adf_to_text(c) for c in cell.get("content", [])).strip()
                for cell in row.get("content", [])
            ]
            rows.append(" | ".join(cells))
        return "\n".join(rows) + "\n\n"
    if "content" in node and isinstance(node["content"], list):
        return "".join(adf_to_text(c) for c in node["content"])
    return ""


def list_jira_issues(
    project: str = "TCN",
    status: str | None = None,
    search: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """List issues in project (e.g. TCN) using Atlassian's /rest/api/3/search/jql API."""
    base_url, _, _ = get_jira_credentials()
    url = f"{base_url}/rest/api/3/search/jql"
    headers = get_jira_auth_headers()

    p_clean = (project or "TCN").strip()
    if p_clean.upper() == "ALL":
        jql_parts = ['project in ("TCN", "SWCM", "TM", "TAT", "MON", "COL")']
    elif "," in p_clean:
        keys_str = ", ".join([f'"{k.strip().upper()}"' for k in p_clean.split(",") if k.strip()])
        jql_parts = [f"project in ({keys_str})"]
    else:
        jql_parts = [f'project = "{p_clean.upper()}"']
    if status and status.lower() != "all":
        jql_parts.append(f'status = "{status}"')
    if search:
        clean_q = search.replace('"', '\\"')
        jql_parts.append(f'(summary ~ "{clean_q}" OR text ~ "{clean_q}")')

    jql = " AND ".join(jql_parts) + " ORDER BY created DESC"

    payload = {
        "jql": jql,
        "maxResults": min(max(1, limit), 100),
        "fields": [
            "summary",
            "status",
            "assignee",
            "reporter",
            "duedate",
            "attachment",
            "created",
            "updated",
            "labels",
            "components",
        ],
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    if not resp.ok:
        raise RuntimeError(f"Jira API error ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    issues_raw = data.get("issues", [])
    results = []

    for item in issues_raw:
        fields = item.get("fields", {})
        results.append(
            {
                "key": item.get("key"),
                "id": item.get("id"),
                "summary": fields.get("summary", ""),
                "status": fields.get("status", {}).get("name", "Unknown"),
                "assignee": fields.get("assignee", {}).get("displayName")
                if fields.get("assignee")
                else "Unassigned",
                "reporter": fields.get("reporter", {}).get("displayName")
                if fields.get("reporter")
                else "Anonymous",
                "duedate": fields.get("duedate"),
                "created": fields.get("created"),
                "updated": fields.get("updated"),
                "attachment_count": len(fields.get("attachment", [])),
                "attachments": [
                    {
                        "id": a.get("id"),
                        "filename": a.get("filename"),
                        "size": a.get("size"),
                        "mimeType": a.get("mimeType"),
                        "created": a.get("created"),
                    }
                    for a in fields.get("attachment", [])
                ],
                "labels": fields.get("labels", []),
            }
        )

    return results


def fetch_jira_issue(issue_key: str) -> dict[str, Any]:
    """Fetch complete issue details, parsing description ADF to text."""
    base_url, _, _ = get_jira_credentials()
    clean_key = issue_key.strip().upper()
    url = f"{base_url}/rest/api/3/issue/{clean_key}"
    headers = get_jira_auth_headers()

    resp = requests.get(url, headers=headers, timeout=20)
    if not resp.ok:
        raise RuntimeError(f"Failed to fetch Jira issue {clean_key} ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    fields = data.get("fields", {})

    description_adf = fields.get("description")
    description_text = adf_to_text(description_adf)

    attachments = []
    for a in fields.get("attachment", []):
        attachments.append(
            {
                "id": a.get("id"),
                "filename": a.get("filename"),
                "size": a.get("size"),
                "mimeType": a.get("mimeType"),
                "content_url": a.get("content"),
                "created": a.get("created"),
            }
        )

    return {
        "key": data.get("key"),
        "id": data.get("id"),
        "summary": fields.get("summary", ""),
        "status": fields.get("status", {}).get("name", "Unknown"),
        "assignee": fields.get("assignee", {}).get("displayName") if fields.get("assignee") else "Unassigned",
        "reporter": fields.get("reporter", {}).get("displayName") if fields.get("reporter") else "Anonymous",
        "duedate": fields.get("duedate"),
        "created": fields.get("created"),
        "updated": fields.get("updated"),
        "description_raw": description_adf,
        "description_text": description_text.strip(),
        "attachments": attachments,
        "labels": fields.get("labels", []),
    }


def download_jira_attachment(attachment_id: str | int, filename: str) -> Path:
    """Download an attachment file from Jira and cache it in media_cache/."""
    base_url, _, _ = get_jira_credentials()
    url = f"{base_url}/rest/api/3/attachment/content/{attachment_id}"
    headers = get_jira_auth_headers()
    # Remove application/json accept header so binary content streams raw
    headers.pop("Content-Type", None)
    headers["Accept"] = "*/*"

    clean_fn = re.sub(r"[^\w\-.]", "_", Path(filename).name)
    target_path = MEDIA_CACHE_DIR / f"jira_{attachment_id}_{clean_fn}"

    if target_path.exists() and target_path.stat().st_size > 0:
        return target_path

    logger.info("Downloading Jira attachment %s (%s)...", attachment_id, clean_fn)
    resp = requests.get(url, headers=headers, stream=True, timeout=45)
    if not resp.ok:
        raise RuntimeError(f"Failed to download Jira attachment {attachment_id}: HTTP {resp.status_code}")

    with open(target_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)

    return target_path


def add_jira_comment(issue_key: str, comment_text: str) -> dict[str, Any]:
    """Add a comment back to a Jira issue in Atlassian Document Format."""
    base_url, _, _ = get_jira_credentials()
    clean_key = issue_key.strip().upper()
    url = f"{base_url}/rest/api/3/issue/{clean_key}/comment"
    headers = get_jira_auth_headers()

    lines = comment_text.strip().split("\n")
    paragraphs = []
    for line in lines:
        if not line.strip():
            continue
        paragraphs.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": line}],
            }
        )

    body = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": paragraphs or [{"type": "paragraph", "content": [{"type": "text", "text": comment_text}]}],
        }
    }

    resp = requests.post(url, headers=headers, json=body, timeout=20)
    if not resp.ok:
        logger.warning("Could not post comment to Jira %s: HTTP %s: %s", clean_key, resp.status_code, resp.text[:200])
        return {"ok": False, "error": resp.text[:200]}

    return {"ok": True, "comment_id": resp.json().get("id")}



def add_jira_sla_mention_comment(
    issue_key: str,
    account_id: str,
    operator_name: str,
    stage: str,
    stage_message: str,
) -> dict[str, Any]:
    """
    Post an SLA alert comment with an active Atlassian user mention.
    This triggers Atlassian's official email delivery to the user's inbox
    and posts an auditable comment on the Jira issue.
    """
    base_url, _, _ = get_jira_credentials()
    clean_key = issue_key.strip().upper()
    url = f"{base_url}/rest/api/3/issue/{clean_key}/comment"
    headers = get_jira_auth_headers()

    stage_prefix = {
        "MORNING": "🌞 [10:00 AM SLA Kickoff]",
        "MIDDAY": "🥪 [1:00 PM SLA Checkpoint]",
        "EOD": "🚨 [4:00 PM Urgent SLA Escalation]",
    }.get(stage, f"🚨 [{stage} SLA Alert]")

    # Build Atlassian Document Format (ADF) with mention node
    mention_node: dict[str, Any] = (
        {
            "type": "mention",
            "attrs": {
                "id": account_id,
                "text": f"@{operator_name}",
                "userType": "DEFAULT",
            },
        }
        if account_id
        else {"type": "text", "text": f"@{operator_name}"}
    )

    body = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": f"{stage_prefix} ", "marks": [{"type": "strong"}]},
                        mention_node,
                        {"type": "text", "text": f" {stage_message}"},
                    ],
                }
            ],
        }
    }

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=20)
        if resp.ok:
            logger.info("Posted Jira SLA mention comment to %s for %s", clean_key, operator_name)
            return {"ok": True, "comment_id": resp.json().get("id")}
        logger.warning("Could not post SLA comment to Jira %s: HTTP %s", clean_key, resp.status_code)
        return {"ok": False, "status": resp.status_code, "error": resp.text[:200]}
    except Exception as exc:
        logger.error("Failed to post SLA comment to %s: %s", clean_key, exc)
        return {"ok": False, "error": str(exc)}

def extract_issue_templates(
    issue_key: str,
    download_creatives: bool = False,
) -> dict[str, Any]:
    """
    Fetch a Jira ticket and semantically extract template drafts, channel routing,
    and Meta-compliant sample values.
    """
    from dataclasses import asdict
    from briefing_parser import parse_jira_brief

    issue_data = fetch_jira_issue(issue_key)
    brief = parse_jira_brief(issue_data, download_creatives=download_creatives)
    return {
        "issue_key": brief.issue_key,
        "summary": brief.summary,
        "whatsapp_drafts": brief.whatsapp_templates,
        "rcs_drafts": brief.rcs_templates,
        "sms_drafts": brief.sms_templates,
        "total_templates": len(brief.whatsapp_templates) + len(brief.rcs_templates) + len(brief.sms_templates),
        "attachments": brief.attachments_mapped,
    }
