"""
MoEngage Operations Dashboard Client & Aggregation Engine.
Directly connects to MoEngage REST APIs (V5) to automate the tracking,
scoping, and delivery reporting previously managed in MoEngage_Ops_Dashboard.xlsx.

Entities Tracked:
1. Standalone Campaigns (SMS, RCS, WhatsApp, Email, Push)
2. Flows (customer journeys / automations)
3. Flow Nodes (channel action steps inside flows)

Scoping Rules:
- Test Filter: Name contains "test", "copy", or "duplicate"
- Vendor/Ops Scope: Created by "@attributics.com" and not test
- Time Grouping: Work-week Monday start and YYYY-MM
"""

import base64
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from config import _load_env_file

logger = logging.getLogger(__name__)

_load_env_file()

CONFIG_PATH = Path("moengage_ops_config.json")
CACHE_DATA_PATH = Path("moengage_ops_cache.json")

# Default registered MoEngage workspaces
DEFAULT_WORKSPACES: list[dict[str, Any]] = [
    {
        "workspace_name": "Moneyfy",
        "vertical": "Moneyfy",
        "workspace_id": "PLBRDCVUS0YE8ME3E8XSHV5D",
        "api_key": "F9ED1AC8BB3449E8B6D94E5C",
        "data_center": "03",
        "is_active": True,
    },
    {
        "workspace_name": "Tata Capital (TCL)",
        "vertical": "TCL",
        "workspace_id": os.environ.get("MOENGAGE_TCL_WORKSPACE_ID") or "0KYUNUW5WODKX5ZFVAGPVL0U",
        "api_key": os.environ.get("MOENGAGE_TCL_API_KEY") or "D9FCC06FDE8947429FDB1928",
        "campaign_report_key": os.environ.get("TATA_MOENGAGE_CAMPAIGN_REPORT_KEY") or "DQCF55C6YIVC",
        "data_center": "03",
        "is_active": True,
    },
    {
        "workspace_name": "Services",
        "vertical": "Services",
        "workspace_id": os.environ.get("MOENGAGE_SERVICES_WORKSPACE_ID") or "YYPOH2RMX16ENTH66KE9LJ9O",
        "api_key": os.environ.get("MOENGAGE_SERVICES_API_KEY") or "D54B2350E267488FABAE4C87",
        "data_center": "03",
        "is_active": True,
    },
    {
        "workspace_name": "Wealth",
        "vertical": "Wealth",
        "workspace_id": os.environ.get("MOENGAGE_WEALTH_WORKSPACE_ID") or "9U9YTAXGRLCMVXK04EGTNLKP",
        "api_key": os.environ.get("MOENGAGE_WEALTH_API_KEY") or "1433F368EE9845F99F0A642E",
        "data_center": "03",
        "is_active": True,
    },
    {
        "workspace_name": "Collections",
        "vertical": "Collections",
        "workspace_id": os.environ.get("MOENGAGE_COLLECTIONS_WORKSPACE_ID", ""),
        "api_key": os.environ.get("MOENGAGE_COLLECTIONS_API_KEY", ""),
        "data_center": "03",
        "is_active": bool(os.environ.get("MOENGAGE_COLLECTIONS_WORKSPACE_ID")),
    },
]


@dataclass
class MoEngageWorkspaceConfig:
    workspace_name: str
    vertical: str
    workspace_id: str
    api_key: str
    campaign_report_key: str | None = None
    data_center: str = "03"
    is_active: bool = True

    def get_campaign_report_headers(self) -> dict[str, str]:
        key = self.campaign_report_key or self.api_key
        auth_str = f"{self.workspace_id}:{key}"
        b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
        return {
            "Authorization": f"Basic {b64_auth}",
            "MOE-APPKEY": self.workspace_id,
            "Content-Type": "application/json",
        }

    def get_base_url(self) -> str:
        return f"https://api-{self.data_center}.moengage.com"

    def get_headers(self) -> dict[str, str]:
        auth_str = f"{self.workspace_id}:{self.api_key}"
        b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
        return {
            "Authorization": f"Basic {b64_auth}",
            "MOE-APPKEY": self.workspace_id,
            "Content-Type": "application/json",
        }


@dataclass
class NormalizedOpsRecord:
    vertical: str  # TCL, Services, Wealth, TCHFL, Moneyfy, Collections
    type: str  # "Campaign", "Flow", "Node"
    channel: str  # "SMS", "RCS", "WhatsApp", "Email", "Push"
    date: str  # YYYY-MM-DD
    week_start: str  # YYYY-MM-DD
    month: str  # YYYY-MM
    in_scope: bool  # Built by Attributics and non-test
    is_test: bool
    name: str
    created_by: str
    source: str
    status: str = "Active"
    flow_name: str | None = None
    flow_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_workspace_configs() -> list[MoEngageWorkspaceConfig]:
    """Load configured MoEngage workspaces from disk or fall back to defaults."""
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return [MoEngageWorkspaceConfig(**w) for w in data]
        except Exception as err:
            logger.warning("Failed to parse %s: %s", CONFIG_PATH, err)
    return [MoEngageWorkspaceConfig(**w) for w in DEFAULT_WORKSPACES]


def save_workspace_configs(configs: list[MoEngageWorkspaceConfig]) -> None:
    """Save workspace configs to disk."""
    data = [asdict(c) for c in configs]
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _is_test_campaign(name: str) -> bool:
    """Check if campaign name indicates a test, copy, or duplicate."""
    if not name:
        return False
    lower = name.lower()
    return any(keyword in lower for keyword in ("test", "copy", "duplicate"))


def _compute_week_start(d: date) -> str:
    """Compute the Monday work-week start for a given date."""
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat()


def _normalize_channel_name(channel_raw: str | None, label: str | None = None) -> str:
    """Map MoEngage channel strings and node labels to standard dashboard channels."""
    text = f"{channel_raw or ''} {label or ''}".strip().upper()
    if not text:
        return "Push"
    if "WHATSAPP" in text or "WA" in text:
        return "WhatsApp"
    if "RCS" in text:
        return "RCS"
    if "SMS" in text:
        return "SMS"
    if "EMAIL" in text or "MAIL" in text:
        return "Email"
    if "PUSH" in text or "PN" in text:
        return "Push"
    return "Push"


def infer_channel_from_name_or_raw(
    channel_raw: str | None = None, name: str | None = None, label: str | None = None
) -> str:
    """
    Map channel using both MoEngage raw channel tag and standard campaign name suffixes
    (_WA -> WhatsApp, _RCS -> RCS, _SMS -> SMS, _PN -> Push, _Email -> Email).
    """
    n = (name or "").lower()
    lbl = (label or "").lower()
    c = (channel_raw or "").strip().lower()

    if "whatsapp" in c or "_wa" in n or "whatsapp" in n or "_wa" in lbl:
        return "WhatsApp"
    if "rcs" in c or "_rcs" in n or "rcs" in n or "_rcs" in lbl:
        return "RCS"
    if "sms" in c or "_sms" in n or "_sms" in lbl:
        return "SMS"
    if "email" in c or "mail" in c or "_email" in n:
        return "Email"
    if "push" in c or "_pn" in n or "pn" in n:
        return "Push"

    return _normalize_channel_name(channel_raw, label=label)


def _infer_vertical_from_name(name: str, default_vertical: str) -> str:
    """Infer vertical from campaign naming patterns matching Excel formulas."""
    n_lower = name.lower()
    if "tclmoe" in n_lower:
        return "TCL"
    if "tchfl" in n_lower:
        return "TCHFL"
    if "service" in n_lower:
        return "Services"
    if "wealth" in n_lower:
        return "Wealth"
    if "moneyfy" in n_lower:
        return "Moneyfy"
    return default_vertical


def fetch_workspace_campaigns(
    config: MoEngageWorkspaceConfig,
    max_pages: int = 15,
) -> list[NormalizedOpsRecord]:
    """
    Fetch campaigns and flow nodes from a MoEngage workspace using POST /v5/campaigns/search.
    Normalizes records matching the spreadsheet logic.
    """
    if not config.workspace_id or not config.api_key:
        return []

    headers = config.get_headers()
    url = f"{config.get_base_url()}/v5/campaigns/search"
    records: list[NormalizedOpsRecord] = []

    # Prefer Campaign Meta API if campaign_report_key is configured (returns WhatsApp, RCS, SMS, Push, Email)
    if config.campaign_report_key:
        headers = config.get_campaign_report_headers()
        url = f"{config.get_base_url()}/core-services/v1/campaigns/meta"
        for page in range(1, max_pages + 1):
            body = {
                "request_id": f"meta_{config.workspace_name.lower()}_{page}_{int(datetime.now(UTC).timestamp())}",
                "page": page,
                "limit": 15,
            }
            try:
                resp = requests.post(url, headers=headers, json=body, timeout=20)
                if not resp.ok:
                    break
                camps = resp.json()
                if not camps or not isinstance(camps, list):
                    break
                for c in camps:
                    name = str(c.get("campaign_name") or "Unnamed Campaign").strip()
                    c_by = str(c.get("created_by") or "").strip()
                    raw_chan = str(c.get("channel") or "")
                    chan = infer_channel_from_name_or_raw(raw_chan, name=name)
                    start_time = c.get("campaign_start_time") or c.get("created_at") or datetime.now(UTC).isoformat()
                    try:
                        dt = datetime.fromisoformat(start_time.split(".")[0].replace("Z", "+00:00")).date()
                    except Exception:
                        dt = datetime.now(UTC).date()
                    is_test = _is_test_campaign(name)
                    is_attributics = "@attributics.com" in c_by.lower() if c_by else True
                    vertical = _infer_vertical_from_name(name, config.vertical)
                    in_scope = is_attributics and not is_test

                    records.append(
                        NormalizedOpsRecord(
                            vertical=vertical,
                            type="Campaign",
                            channel=chan,
                            date=dt.isoformat(),
                            week_start=_compute_week_start(dt),
                            month=dt.strftime("%Y-%m"),
                            in_scope=in_scope,
                            is_test=is_test,
                            name=name,
                            created_by=c_by,
                            source=f"{config.vertical} / CampaignMeta",
                            status=str(c.get("campaign_status") or "Active"),
                        )
                    )
            except Exception as exc:
                logger.error("Error fetching campaign meta for %s: %s", config.workspace_name, exc)
                break
        return records

    for page in range(1, max_pages + 1):
        body = {
            "request_id": f"ops_{config.workspace_name.lower()}_{page}_{int(datetime.now(UTC).timestamp())}",
            "include_child_campaigns": False,  # Standalone campaigns
            "limit": 15,
            "page": page,
        }
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=20)
            if not resp.ok:
                logger.warning(
                    "Campaigns search for %s failed (%d): %s", config.workspace_name, resp.status_code, resp.text[:200]
                )
                break
            data = resp.json().get("data", {}).get("campaigns", [])
            if not data:
                break

            for c in data:
                name = c.get("basic_details", {}).get("name") or "Unnamed Campaign"
                c_by = str(c.get("created_by") or "").strip()
                chan = infer_channel_from_name_or_raw(c.get("channel"), name=name)
                created_at_raw = c.get("created_at") or datetime.now(UTC).isoformat()

                try:
                    dt = datetime.fromisoformat(created_at_raw.split(".")[0].replace("Z", "+00:00")).date()
                except Exception:
                    dt = datetime.now(UTC).date()

                is_test = _is_test_campaign(name)
                is_attributics = "@attributics.com" in c_by.lower()

                vertical = _infer_vertical_from_name(name, config.vertical)
                in_scope = is_attributics and not is_test

                records.append(
                    NormalizedOpsRecord(
                        vertical=vertical,
                        type="Campaign",
                        channel=chan,
                        date=dt.isoformat(),
                        week_start=_compute_week_start(dt),
                        month=dt.strftime("%Y-%m"),
                        in_scope=in_scope,
                        is_test=is_test,
                        name=name,
                        created_by=c_by,
                        source=f"{config.vertical} / Campaign",
                        status=str(c.get("status") or "Active"),
                    )
                )

        except Exception as exc:
            logger.error("Error fetching campaigns for %s: %s", config.workspace_name, exc)
            break

    return records


def fetch_workspace_flows(
    config: MoEngageWorkspaceConfig,
    max_pages: int = 5,
) -> list[NormalizedOpsRecord]:
    """
    Fetch automated customer journey flows from MoEngage using POST /v5/flows/search.
    """
    if not config.workspace_id or not config.api_key:
        return []

    headers = config.get_headers()
    url = f"{config.get_base_url()}/v5/flows/search"
    records: list[NormalizedOpsRecord] = []

    body = {
        "request_id": f"ops_flows_{config.workspace_name.lower()}_{int(datetime.now(UTC).timestamp())}",
        "limit": 25,
    }

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=20)
        if resp.ok:
            flows_data = resp.json().get("data", {}).get("flows", [])
            for f in flows_data:
                name = str(f.get("name") or "Unnamed Flow").strip()
                status = str(f.get("status") or "Active").title()
                c_by = str(f.get("created_by") or "")
                published_at_raw = f.get("published_at") or f.get("created_at") or datetime.now(UTC).isoformat()

                try:
                    dt = datetime.fromisoformat(published_at_raw.split(".")[0].replace("Z", "+00:00")).date()
                except Exception:
                    dt = datetime.now(UTC).date()

                is_test = _is_test_campaign(name)
                is_attributics = "@attributics.com" in c_by.lower()
                vertical = _infer_vertical_from_name(name, config.vertical)
                # In Collections sheet: Owned is true if status == "Active"
                in_scope = (
                    (status.lower() == "active")
                    if config.vertical == "Collections"
                    else (is_attributics and not is_test)
                )

                records.append(
                    NormalizedOpsRecord(
                        vertical=vertical,
                        type="Flow",
                        channel="",  # Flows can hold multiple channels
                        date=dt.isoformat(),
                        week_start=_compute_week_start(dt),
                        month=dt.strftime("%Y-%m"),
                        in_scope=in_scope,
                        is_test=is_test,
                        name=name,
                        created_by=c_by,
                        source=f"{config.vertical} / Flow",
                        status=status,
                        flow_id=f.get("flow_id"),
                    )
                )

                # Extract Action Nodes inside the flow (WhatsApp, RCS, SMS, Email, Push)
                flow_id = f.get("flow_id")
                if flow_id:
                    try:
                        detail_resp = requests.get(
                            f"{config.get_base_url()}/v5/flows/{flow_id}", headers=headers, timeout=12
                        )
                        if detail_resp.ok:
                            detail_data = detail_resp.json().get("data", {})
                            nodes = detail_data.get("structure", {}).get("nodes", [])
                            for node in nodes:
                                if node.get("type") == "ACTION":
                                    cfg = node.get("config", {})
                                    node_sub = str(node.get("sub_type") or cfg.get("channel") or "")
                                    node_label = str(node.get("label") or "")
                                    node_chan = _normalize_channel_name(node_sub, label=node_label)
                                    node_name = (
                                        cfg.get("campaign_name") or node.get("label") or f"{name}_{node_chan}_node"
                                    )
                                    node_test = _is_test_campaign(node_name) or is_test
                                    node_in_scope = (
                                        (is_attributics or not node_test)
                                        if config.vertical == "Collections"
                                        else (in_scope and not node_test)
                                    )

                                    records.append(
                                        NormalizedOpsRecord(
                                            vertical=vertical,
                                            type="Node",
                                            channel=node_chan,
                                            date=dt.isoformat(),
                                            week_start=_compute_week_start(dt),
                                            month=dt.strftime("%Y-%m"),
                                            in_scope=node_in_scope,
                                            is_test=node_test,
                                            name=node_name,
                                            created_by=c_by,
                                            source=f"{config.vertical} / Node",
                                            status=status,
                                            flow_name=name,
                                            flow_id=flow_id,
                                        )
                                    )
                    except Exception as err:
                        logger.debug("Could not fetch structure for flow %s: %s", flow_id, err)

    except Exception as exc:
        logger.error("Error fetching flows for %s: %s", config.workspace_name, exc)

    return records


def sync_all_moengage_ops() -> list[NormalizedOpsRecord]:
    """Fetch all campaigns and flows across all registered workspaces and cache to disk."""
    configs = load_workspace_configs()
    all_records: list[NormalizedOpsRecord] = []

    for cfg in configs:
        if not cfg.is_active:
            continue
        logger.info("Syncing MoEngage Ops for workspace: %s...", cfg.workspace_name)
        camps = fetch_workspace_campaigns(cfg)
        flows = fetch_workspace_flows(cfg)
        all_records.extend(camps)
        all_records.extend(flows)

    # Save to persistent cache
    try:
        CACHE_DATA_PATH.write_text(json.dumps([r.to_dict() for r in all_records], indent=2), encoding="utf-8")
    except Exception as err:
        logger.warning("Failed to write %s: %s", CACHE_DATA_PATH, err)

    return all_records


def load_cached_ops_records() -> list[NormalizedOpsRecord]:
    """Load cached operations records, or trigger sync if cache is empty."""
    if CACHE_DATA_PATH.exists():
        try:
            data = json.loads(CACHE_DATA_PATH.read_text(encoding="utf-8"))
            return [NormalizedOpsRecord(**r) for r in data]
        except Exception:
            pass
    return sync_all_moengage_ops()


def get_date_range_bounds(
    mode: str = "last_week", custom_start: str | None = None, custom_end: str | None = None
) -> tuple[date, date]:
    """Calculate effective start and end dates matching the Excel Dashboard formulas."""
    today = datetime.now(UTC).date()
    mode_clean = (mode or "last_week").lower().strip()

    if mode_clean == "custom" and custom_start and custom_end:
        try:
            s = date.fromisoformat(custom_start)
            e = date.fromisoformat(custom_end)
            return s, e
        except Exception:
            pass

    if mode_clean == "last_month":
        # First day of previous month to last day of previous month
        first_this_month = today.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return last_month_start, last_month_end

    # Default: last_week (Monday to Sunday of previous week)
    # Excel formula: TODAY()-WEEKDAY(TODAY(),2)+1-7 to TODAY()-WEEKDAY(TODAY(),2)+1-1
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(days=7)
    last_sunday = this_monday - timedelta(days=1)
    return last_monday, last_sunday


def compute_ops_dashboard_metrics(
    records: list[NormalizedOpsRecord],
    mode: str = "last_week",
    custom_start: str | None = None,
    custom_end: str | None = None,
    workspace_filter: str | None = None,
) -> dict[str, Any]:
    """
    Compute executive overview, channel breakdown, and vertical breakdowns
    replicating the exact COUNTIFS formulas in MoEngage_Ops_Dashboard.xlsx.
    """
    start_date, end_date = get_date_range_bounds(mode, custom_start, custom_end)
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    channels = ["SMS", "RCS", "WhatsApp", "Email", "Push"]
    all_verticals = ["TCL", "Services", "Wealth", "TCHFL", "Moneyfy", "Collections"]

    # Filter in-scope records by date
    # Note: In Collections, flows are reported as live active snapshot (not date filtered), exactly per spreadsheet row 44
    date_filtered_records = [
        r
        for r in records
        if r.in_scope and (start_str <= r.date <= end_str or (r.vertical == "Collections" and r.type == "Flow"))
    ]

    # Account Overview includes: TCL + Services + Wealth (and Moneyfy), or specific filtered vertical
    if workspace_filter and workspace_filter.strip().lower() not in ("all", "all accounts", "all workspaces", ""):
        wf_clean = workspace_filter.strip()
        account_overview_verticals = {wf_clean}
        title = f"{wf_clean} Workspace Isolated"
    else:
        account_overview_verticals = {"TCL", "Services", "Wealth", "Moneyfy"}
        title = "TCL + Services + Wealth + Moneyfy Combined"
    overview_camps = [
        r
        for r in date_filtered_records
        if r.type == "Campaign" and r.vertical in account_overview_verticals and (start_str <= r.date <= end_str)
    ]
    overview_flows = [
        r
        for r in date_filtered_records
        if r.type == "Flow" and r.vertical in account_overview_verticals and (start_str <= r.date <= end_str)
    ]
    overview_nodes = [
        r
        for r in date_filtered_records
        if r.type == "Node" and r.vertical in account_overview_verticals and (start_str <= r.date <= end_str)
    ]

    overview_channel_breakdown = {ch: 0 for ch in channels}
    campaigns_channel_breakdown = {ch: 0 for ch in channels}
    nodes_channel_breakdown = {ch: 0 for ch in channels}

    for r in overview_camps:
        if r.channel in campaigns_channel_breakdown:
            campaigns_channel_breakdown[r.channel] += 1
        if r.channel in overview_channel_breakdown:
            overview_channel_breakdown[r.channel] += 1

    for r in overview_nodes:
        if r.channel in nodes_channel_breakdown:
            nodes_channel_breakdown[r.channel] += 1
        if r.channel in overview_channel_breakdown:
            overview_channel_breakdown[r.channel] += 1

    vertical_breakdown: dict[str, dict[str, Any]] = {}
    for v in all_verticals:
        v_camps = [
            r
            for r in date_filtered_records
            if r.vertical == v and r.type == "Campaign" and (start_str <= r.date <= end_str)
        ]
        v_flows = [
            r
            for r in date_filtered_records
            if r.vertical == v and r.type == "Flow" and (v == "Collections" or (start_str <= r.date <= end_str))
        ]
        v_nodes = [
            r
            for r in date_filtered_records
            if r.vertical == v and r.type == "Node" and (v == "Collections" or (start_str <= r.date <= end_str))
        ]

        ch_split = {ch: 0 for ch in channels}
        camps_ch = {ch: 0 for ch in channels}
        nodes_ch = {ch: 0 for ch in channels}

        for r in v_camps:
            if r.channel in camps_ch:
                camps_ch[r.channel] += 1
            if r.channel in ch_split:
                ch_split[r.channel] += 1

        for r in v_nodes:
            if r.channel in nodes_ch:
                nodes_ch[r.channel] += 1
            if r.channel in ch_split:
                ch_split[r.channel] += 1

        vertical_breakdown[v] = {
            "campaigns_total": len(v_camps),
            "flows_total": len(v_flows),
            "flow_nodes_total": len(v_nodes),
            "channels": ch_split,
            "campaigns_channels": camps_ch,
            "nodes_channels": nodes_ch,
            "in_account_total": v in account_overview_verticals,
        }
    return {
        "date_filter": {
            "mode": mode,
            "start_date": start_str,
            "end_date": end_str,
        },
        "account_overview": {
            "title": title,
            "total_campaigns": len(overview_camps),
            "total_flows": len(overview_flows),
            "total_flow_nodes": len(overview_nodes),
            "total_touchpoints": len(overview_camps) + len(overview_nodes),
            "campaigns_channel_breakdown": campaigns_channel_breakdown,
            "nodes_channel_breakdown": nodes_channel_breakdown,
            "channel_breakdown": overview_channel_breakdown,
        },
        "vertical_breakdown": vertical_breakdown,
        "total_records_ingested": len(records),
        "in_scope_active_count": len(date_filtered_records),
    }


def export_ops_dashboard_excel(
    records: list[NormalizedOpsRecord] | None = None,
    template_path: str = "MoEngage_Ops_Dashboard.xlsx",
    output_path: str = "MoEngage_Ops_Dashboard_Live.xlsx",
) -> str:
    """
    Populate Master Data sheet in MoEngage_Ops_Dashboard.xlsx with live normalized records
    so all Dashboard formulas calculate dynamically.
    """
    import openpyxl

    t_path = Path(template_path)
    if not t_path.exists() and (Path("samples") / template_path).exists():
        t_path = Path("samples") / template_path

    if records is None:
        records = load_cached_ops_records()

    if t_path.exists():
        wb = openpyxl.load_workbook(str(t_path))
    else:
        logger.warning("Template workbook '%s' not found. Creating dynamic Master Data workbook.", template_path)
        wb = openpyxl.Workbook()
        if "Sheet" in wb.sheetnames:
            wb["Sheet"].title = "Master Data"

    if "Master Data" not in wb.sheetnames:
        ws = wb.create_sheet("Master Data")
    else:
        ws = wb["Master Data"]

    # Ensure header row (row 5) exists
    headers = ["Vertical", "Type", "Channel", "Date", "Week Start", "Month", "In Scope", "Is Test", "Source"]
    for c_idx, h in enumerate(headers, start=1):
        if not ws.cell(5, c_idx).value:
            ws.cell(5, c_idx).value = h
    # Clear existing rows starting from row 6
    for r in range(6, min(ws.max_row + 1, 10000)):
        for c in range(1, 10):
            ws.cell(r, c).value = None

    # Write live rows
    for idx, rec in enumerate(records, start=6):
        ws.cell(idx, 1).value = rec.vertical
        ws.cell(idx, 2).value = rec.type
        ws.cell(idx, 3).value = rec.channel
        ws.cell(idx, 4).value = rec.date
        ws.cell(idx, 5).value = rec.week_start
        ws.cell(idx, 6).value = rec.month
        ws.cell(idx, 7).value = 1 if rec.in_scope else 0
        ws.cell(idx, 8).value = 1 if rec.is_test else 0
        ws.cell(idx, 9).value = rec.source

    wb.save(output_path)
    logger.info("Exported %d live records to %s", len(records), output_path)
    return output_path


def _parse_flex_date(date_val: Any) -> date:
    """Parse various date formats from MoEngage exports into a datetime.date."""
    if isinstance(date_val, datetime):
        return date_val.date()
    if isinstance(date_val, date):
        return date_val

    if isinstance(date_val, (int, float)):
        # Unix timestamp (> 1e9) vs Excel serial number (30000 - 60000)
        if date_val > 1_000_000_000:
            try:
                return datetime.fromtimestamp(date_val, UTC).date()
            except Exception:
                pass
        elif 30_000 < date_val < 70_000:
            try:
                return (datetime(1899, 12, 30, tzinfo=UTC) + timedelta(days=date_val)).date()
            except Exception:
                pass

    if isinstance(date_val, str) and date_val.strip():
        clean = date_val.strip()
        # Strip trailing timezone indicators like 'Z' or '+05:30' or '.000'
        clean_no_tz = clean.replace("Z", "").split("+")[0].split(".")[0].strip()
        try:
            return datetime.fromisoformat(clean_no_tz).date()
        except Exception:
            pass

        # Standard date format patterns
        formats = (
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%m/%d/%Y",
            "%Y/%m/%d",
            "%d %b %Y",
            "%d %B %Y",
            "%b %d, %Y",
            "%B %d, %Y",
            "%d-%b-%Y",
            "%d-%b-%y",
            "%d %b %y",
            "%Y-%m-%d %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %I:%M:%S %p",
            "%d/%m/%Y %I:%M %p",
            "%d-%m-%Y %I:%M %p",
            "%Y-%m-%d %I:%M %p",
            "%d %b %Y %H:%M",
            "%d %b %Y, %I:%M %p",
        )
        for fmt in formats:
            try:
                return datetime.strptime(clean_no_tz, fmt).date()
            except Exception:
                pass

        # Regex fallback for embedded dates: e.g. YYYY-MM-DD
        m_iso = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", clean)
        if m_iso:
            try:
                return date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
            except Exception:
                pass

        # Regex fallback for DD/MM/YYYY or DD-MM-YYYY
        m_dmy = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", clean)
        if m_dmy:
            try:
                return date(int(m_dmy.group(3)), int(m_dmy.group(2)), int(m_dmy.group(1)))
            except Exception:
                pass

    return datetime.now(UTC).date()


def _is_attributics_author(c_by: str) -> bool:
    """Check if author is Attributics operator or unspecified default."""
    if not c_by:
        return True
    cb = c_by.lower().strip()
    if "@attributics.com" in cb:
        return True
    team_names = [
        "mrunalini", "gawande",
        "soham", "das",
        "neel", "shah",
        "aalya", "mulla",
        "naman", "dugad",
        "attributics",
    ]
    return any(name in cb for name in team_names)


def _infer_vertical_from_context(name: str, source_name: str, default_vertical: str) -> str:
    """Infer vertical from item name or source filename (e.g. Wealth_Campaigns.csv)."""
    # 1. From item name
    n_lower = name.lower()
    if "tclmoe" in n_lower:
        return "TCL"
    if "tchfl" in n_lower:
        return "TCHFL"
    if "service" in n_lower:
        return "Services"
    if "wealth" in n_lower:
        return "Wealth"
    if "moneyfy" in n_lower:
        return "Moneyfy"
    if "collection" in n_lower:
        return "Collections"

    # 2. From filename / folder
    s_lower = source_name.lower()
    if "tchfl" in s_lower:
        return "TCHFL"
    if "tcl" in s_lower:
        return "TCL"
    if "service" in s_lower:
        return "Services"
    if "wealth" in s_lower:
        return "Wealth"
    if "moneyfy" in s_lower:
        return "Moneyfy"
    if "collection" in s_lower:
        return "Collections"

    return default_vertical


def _parse_single_moengage_data_rows(
    rows_data: list[dict[str, Any]],
    source_name: str = "export.csv",
    default_vertical: str = "TCL",
) -> list[NormalizedOpsRecord]:
    """Convert raw dictionary rows from one CSV or Excel file into NormalizedOpsRecord objects."""
    records: list[NormalizedOpsRecord] = []
    s_lower = Path(source_name).name.lower()

    for row in rows_data:
        # 1. Determine Record Type (Node, Flow, or Campaign)
        t_val = str(
            row.get("Type")
            or row.get("type")
            or row.get("Record Type")
            or row.get("record_type")
            or ""
        ).lower()

        if "node" in t_val or "action" in t_val:
            rec_type = "Node"
        elif "flow" in t_val:
            rec_type = "Flow"
        elif "campaign" in t_val:
            rec_type = "Campaign"
        elif "node" in s_lower or "action" in s_lower:
            rec_type = "Node"
        elif "flow" in s_lower and "campaign" not in s_lower:
            if any(
                k in row
                for k in (
                    "Node Name",
                    "node_name",
                    "Action Name",
                    "action_name",
                    "Step Name",
                    "step_name",
                    "Node Label",
                    "node_label",
                    "Message Name",
                    "message_name",
                )
            ):
                rec_type = "Node"
            else:
                rec_type = "Flow"
        else:
            if any(
                k in row
                for k in (
                    "Node Name",
                    "node_name",
                    "Action Name",
                    "action_name",
                    "Step Name",
                    "step_name",
                    "Node Label",
                )
            ):
                rec_type = "Node"
            elif any(k in row for k in ("Flow Name", "flow_name", "Flow ID", "flow_id")) and not any(
                k in row for k in ("Campaign Name", "campaign_name", "Campaign")
            ):
                rec_type = "Flow"
            else:
                rec_type = "Campaign"

        # 2. Extract Name, Flow ID, and Flow Name
        flow_id = str(row.get("Flow ID") or row.get("flow_id") or row.get("Flow Id") or "").strip() or None
        flow_name = str(row.get("Flow Name") or row.get("flow_name") or row.get("Flow") or "").strip() or None

        if rec_type == "Node":
            name = str(
                row.get("Node Name")
                or row.get("node_name")
                or row.get("Action Name")
                or row.get("action_name")
                or row.get("Step Name")
                or row.get("step_name")
                or row.get("Node Label")
                or row.get("Label")
                or row.get("label")
                or row.get("Message Name")
                or row.get("message_name")
                or row.get("Campaign Name")
                or row.get("Campaign name")
                or row.get("campaign_name")
                or row.get("Name")
                or row.get("name")
                or ""
            ).strip()
        elif rec_type == "Flow":
            name = str(
                row.get("Flow Name")
                or row.get("flow_name")
                or row.get("Flow")
                or row.get("Name")
                or row.get("name")
                or row.get("Title")
                or ""
            ).strip()
            flow_name = None
        else:
            name = str(
                row.get("Campaign Name")
                or row.get("Campaign name")
                or row.get("campaign_name")
                or row.get("Campaign")
                or row.get("Name")
                or row.get("name")
                or row.get("Campaign Title")
                or ""
            ).strip()
            flow_name = None
            flow_id = None

        if not name:
            continue

        # 3. Channel resolution
        if rec_type == "Flow":
            chan = ""
        else:
            raw_chan = str(
                row.get("Channel")
                or row.get("channel")
                or row.get("Delivery Channel")
                or row.get("delivery_channel")
                or row.get("Channel Name")
                or row.get("channel_name")
                or row.get("Action Type")
                or row.get("action_type")
                or row.get("Sub Type")
                or row.get("sub_type")
                or row.get("Message Type")
                or row.get("message_type")
                or ""
            ).strip()
            chan = infer_channel_from_name_or_raw(raw_chan, name=name, label=row.get("Label") or s_lower)
            if not raw_chan:
                if "sms" in s_lower:
                    chan = "SMS"
                elif "whatsapp" in s_lower or "wa" in s_lower.split("_"):
                    chan = "WhatsApp"
                elif "rcs" in s_lower:
                    chan = "RCS"
                elif "email" in s_lower or "mail" in s_lower:
                    chan = "Email"
                elif "push" in s_lower or "pn" in s_lower.split("_"):
                    chan = "Push"

        # 4. Author & Status
        c_by = str(
            row.get("Created By")
            or row.get("Created by")
            or row.get("created_by")
            or row.get("Author")
            or row.get("author")
            or row.get("Owner")
            or row.get("owner")
            or ""
        ).strip()

        status = str(
            row.get("Status")
            or row.get("status")
            or row.get("Campaign Status")
            or row.get("campaign_status")
            or row.get("Flow Status")
            or "Sent"
        ).strip().title()

        # 5. Date resolution
        date_val = None
        for date_key in (
            "Date", "date", "Created", "created", "Created At", "Created at", "created_at",
            "Sent Time", "sent_time", "Send Date", "send_date", "Send Time", "send_time",
            "Start Time", "start_time", "Campaign Start Time", "Published At", "published_at",
            "Execution Time", "execution_time", "Schedule Time", "schedule_time",
            "Date Created", "date_created", "Trigger Time", "trigger_time",
            "Modified At", "modified_at", "Updated At", "updated_at",
        ):
            if row.get(date_key):
                date_val = row[date_key]
                break

        dt = _parse_flex_date(date_val)

        # 6. Vertical and Scope resolution
        vertical = _infer_vertical_from_context(name, source_name, default_vertical)
        is_test = _is_test_campaign(name)
        is_attributics = _is_attributics_author(c_by)
        in_scope = (status.lower() == "active") if vertical == "Collections" else (is_attributics and not is_test)

        records.append(
            NormalizedOpsRecord(
                vertical=vertical,
                type=rec_type,
                channel=chan,
                date=dt.isoformat(),
                week_start=_compute_week_start(dt),
                month=dt.strftime("%Y-%m"),
                in_scope=in_scope,
                is_test=is_test,
                name=name,
                created_by=c_by,
                source=f"{vertical} / {Path(source_name).name}",
                status=status,
                flow_name=flow_name,
                flow_id=flow_id,
            )
        )

    return records


def _extract_rows_from_file_bytes(content_bytes: bytes, filename: str) -> list[dict[str, Any]]:
    """Extract row dictionaries from CSV or Excel file bytes."""
    import csv
    import io

    import openpyxl

    ext = Path(filename).suffix.lower()
    rows: list[dict[str, Any]] = []

    if ext in (".xlsx", ".xls"):
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content_bytes), data_only=True)
            ws = wb.active
            header_row_idx = 1
            for r in range(1, min(ws.max_row + 1, 15)):
                row_vals = " ".join([str(ws.cell(r, c).value or "").strip().lower() for c in range(1, ws.max_column + 1)])
                if any(kw in row_vals for kw in ("campaign", "flow", "channel", "created by", "status", "name")):
                    header_row_idx = r
                    break
            headers = [str(ws.cell(header_row_idx, c).value or "").strip() for c in range(1, ws.max_column + 1)]
            for r in range(header_row_idx + 1, ws.max_row + 1):
                row_dict = {headers[c - 1]: ws.cell(r, c).value for c in range(1, len(headers) + 1) if headers[c - 1]}
                clean_row = {str(k).strip(): v for k, v in row_dict.items() if k}
                if any(clean_row.values()):
                    rows.append(clean_row)
        except Exception as exc:
            logger.warning("Could not parse excel file %s: %s", filename, exc)
    else:
        # CSV / TSV
        try:
            text = content_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = content_bytes.decode("latin-1", errors="replace")
            except Exception:
                text = content_bytes.decode("utf-8", errors="replace")

        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return []

        header_line_idx = 0
        for idx, line in enumerate(lines[:15]):
            line_lower = line.lower()
            if ("," in line or "\t" in line) and any(
                kw in line_lower
                for kw in ("campaign name", "flow name", "channel", "created by", "sent time", "status", "campaign", "flow", "name")
            ):
                header_line_idx = idx
                break

        csv_text = "\n".join(lines[header_line_idx:])
        first_line = lines[header_line_idx] if lines else ""
        delimiter = "\t" if ext == ".tsv" or ("\t" in first_line and "," not in first_line) else ","
        reader = csv.DictReader(io.StringIO(csv_text), delimiter=delimiter)
        for row in reader:
            clean_row = {str(k).strip(): v for k, v in row.items() if k is not None and str(k).strip()}
            if any(clean_row.values()):
                rows.append(clean_row)
    return rows


def parse_moengage_export_file(file_path: Path | str, default_vertical: str = "TCL") -> list[NormalizedOpsRecord]:
    """
    Parse a campaign export file downloaded directly from MoEngage.
    Supports:
    - ZIP archives containing multiple CSV / XLSX files across workspaces or date batches
    - Single CSV / TSV / XLSX / XLS files
    - Subdirectories inside zip archives (skips __MACOSX and hidden files)
    """
    import io
    import zipfile

    path = Path(file_path)
    if not path.exists():
        logger.warning("MoEngage export file not found: %s", path)
        return []

    records: list[NormalizedOpsRecord] = []

    # 1. Handle ZIP Archive (either extension or zip magic bytes)
    if path.suffix.lower() == ".zip" or zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path, "r") as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    fname = info.filename
                    base_name = Path(fname).name
                    # Skip macOS metadata and hidden files
                    if "__MACOSX" in fname or base_name.startswith("."):
                        continue

                    ext = Path(fname).suffix.lower()
                    if ext in (".csv", ".tsv", ".xlsx", ".xls"):
                        content = zf.read(fname)
                        rows = _extract_rows_from_file_bytes(content, fname)
                        file_recs = _parse_single_moengage_data_rows(
                            rows, source_name=fname, default_vertical=default_vertical
                        )
                        records.extend(file_recs)
                    elif ext == ".zip":
                        # Handle nested ZIP archive
                        try:
                            nested_bytes = zf.read(fname)
                            with zipfile.ZipFile(io.BytesIO(nested_bytes), "r") as nzf:
                                for ninfo in nzf.infolist():
                                    if ninfo.is_dir():
                                        continue
                                    nfname = ninfo.filename
                                    nbase = Path(nfname).name
                                    if "__MACOSX" in nfname or nbase.startswith("."):
                                        continue
                                    next_ext = Path(nfname).suffix.lower()
                                    if next_ext in (".csv", ".tsv", ".xlsx", ".xls"):
                                        nrows = _extract_rows_from_file_bytes(nzf.read(nfname), nfname)
                                        records.extend(
                                            _parse_single_moengage_data_rows(
                                                nrows, source_name=nfname, default_vertical=default_vertical
                                            )
                                        )
                        except Exception as n_err:
                            logger.warning("Could not unpack nested zip %s: %s", fname, n_err)
            return records
        except Exception as exc:
            logger.warning("Error unpacking MoEngage export zip %s: %s", path, exc)
            return []

    # 2. Handle Single CSV / XLSX file
    content = path.read_bytes()
    rows = _extract_rows_from_file_bytes(content, path.name)
    return _parse_single_moengage_data_rows(rows, source_name=path.name, default_vertical=default_vertical)


def ingest_moengage_export_file(file_path: Path | str, default_vertical: str = "TCL") -> dict[str, Any]:
    """
    Ingest a MoEngage export file (ZIP or CSV), merge with cached records,
    update live Excel, and return accurate metrics.
    """
    import zipfile

    path = Path(file_path)
    files_count = 1
    if path.suffix.lower() == ".zip" or (path.exists() and zipfile.is_zipfile(path)):
        try:
            with zipfile.ZipFile(path, "r") as zf:
                valid_files = [
                    info.filename
                    for info in zf.infolist()
                    if not info.is_dir()
                    and "__MACOSX" not in info.filename
                    and not Path(info.filename).name.startswith(".")
                    and Path(info.filename).suffix.lower() in (".csv", ".tsv", ".xlsx", ".xls", ".zip")
                ]
                files_count = max(len(valid_files), 1)
        except Exception:
            files_count = 1

    new_records = parse_moengage_export_file(file_path, default_vertical=default_vertical)
    cached = load_cached_ops_records()

    # Deduplicate by (name, date, vertical, type)
    seen_keys = {(r.name.lower(), r.date, r.vertical, r.type) for r in cached}
    merged = list(cached)
    added_count = 0
    for nr in new_records:
        k = (nr.name.lower(), nr.date, nr.vertical, nr.type)
        if k not in seen_keys:
            merged.append(nr)
            seen_keys.add(k)
            added_count += 1

    # Save to cache
    CACHE_DATA_PATH.write_text(json.dumps([r.to_dict() for r in merged], indent=2), encoding="utf-8")
    export_ops_dashboard_excel(merged)

    return {
        "ok": True,
        "files_parsed": files_count,
        "new_records_parsed": len(new_records),
        "new_records_added": added_count,
        "campaigns_count": sum(1 for r in new_records if r.type == "Campaign"),
        "flows_count": sum(1 for r in new_records if r.type == "Flow"),
        "nodes_count": sum(1 for r in new_records if r.type == "Node"),
        "total_records_now": len(merged),
    }
