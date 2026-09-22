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
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
import json
import logging
import os
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
    data_center: str = "03"
    is_active: bool = True

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
                logger.warning("Campaigns search for %s failed (%d): %s", config.workspace_name, resp.status_code, resp.text[:200])
                break
            data = resp.json().get("data", {}).get("campaigns", [])
            if not data:
                break

            for c in data:
                name = c.get("basic_details", {}).get("name") or "Unnamed Campaign"
                c_by = str(c.get("created_by") or "").strip()
                chan = _normalize_channel_name(c.get("channel"))
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
                in_scope = (status.lower() == "active") if config.vertical == "Collections" else (is_attributics and not is_test)

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
                        detail_resp = requests.get(f"{config.get_base_url()}/v5/flows/{flow_id}", headers=headers, timeout=12)
                        if detail_resp.ok:
                            detail_data = detail_resp.json().get("data", {})
                            nodes = detail_data.get("structure", {}).get("nodes", [])
                            for node in nodes:
                                if node.get("type") == "ACTION":
                                    cfg = node.get("config", {})
                                    node_sub = str(node.get("sub_type") or cfg.get("channel") or "")
                                    node_label = str(node.get("label") or "")
                                    node_chan = _normalize_channel_name(node_sub, label=node_label)
                                    node_name = cfg.get("campaign_name") or node.get("label") or f"{name}_{node_chan}_node"
                                    node_test = _is_test_campaign(node_name) or is_test
                                    node_in_scope = (is_attributics or not node_test) if config.vertical == "Collections" else (in_scope and not node_test)

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


def get_date_range_bounds(mode: str = "last_week", custom_start: str | None = None, custom_end: str | None = None) -> tuple[date, date]:
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
        r for r in records
        if r.in_scope and (start_str <= r.date <= end_str or (r.vertical == "Collections" and r.type == "Flow"))
    ]

    # Account Overview includes: TCL + Services + Wealth (and Moneyfy). TCHFL and Collections reported separately.
    account_overview_verticals = {"TCL", "Services", "Wealth", "Moneyfy"}

    overview_camps = [
        r for r in date_filtered_records
        if r.type == "Campaign" and r.vertical in account_overview_verticals and (start_str <= r.date <= end_str)
    ]
    overview_flows = [
        r for r in date_filtered_records
        if r.type == "Flow" and r.vertical in account_overview_verticals and (start_str <= r.date <= end_str)
    ]
    overview_nodes = [
        r for r in date_filtered_records
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
            r for r in date_filtered_records
            if r.vertical == v and r.type == "Campaign" and (start_str <= r.date <= end_str)
        ]
        v_flows = [
            r for r in date_filtered_records
            if r.vertical == v and r.type == "Flow" and (v == "Collections" or (start_str <= r.date <= end_str))
        ]
        v_nodes = [
            r for r in date_filtered_records
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
            "title": "TCL + Services + Wealth + Moneyfy Combined",
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
    if not t_path.exists():
        raise FileNotFoundError(f"Template workbook '{template_path}' not found.")

    if records is None:
        records = load_cached_ops_records()

    wb = openpyxl.load_workbook(str(t_path))
    if "Master Data" not in wb.sheetnames:
        raise ValueError("Workbook missing 'Master Data' sheet.")

    ws = wb["Master Data"]

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
