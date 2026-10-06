"""Single-row V5 draft creation with durable identity, conservative rate caps, and read-back.

No live provider operation is enabled by default. A deployment owner must verify
workspace, no-publish permissions and zero incremental charges before enabling.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from db import get_database_url, get_db, init_database
from moengage_drafts import DraftWriter, authorize_draft_account
from moengage_preview import prepare_batch


class RateLimitError(Exception):
    """A local workspace create cap was reached; no provider call was made."""


def load_server_catalog(account: str) -> dict[str, Any]:
    """Load the account/workspace catalog owned by this deployment, not the caller."""
    prefix = f"MOENGAGE_DRAFT_{account.upper()}_"
    path = os.environ.get(prefix + "CATALOG_FILE", "").strip()
    if not path:
        raise PermissionError("Server-owned workspace catalog required")
    catalog_file = Path(path)
    if not catalog_file.is_file() or catalog_file.stat().st_size > 1024 * 1024:
        raise ValueError("Account catalog must be a local JSON file of at most 1 MiB")
    catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
    workspace = os.environ.get(prefix + "WORKSPACE_ID", "").strip() or str(catalog.get("workspace_id") or "")
    if not workspace:
        raise PermissionError("Server-owned workspace ID required")
    if (not isinstance(catalog, dict) or catalog.get("account") != account
            or catalog.get("workspace_id") != workspace):
        raise ValueError("Catalog does not match the server-owned account/workspace")
    return catalog


def _matches(actual: Any, expected: Any) -> bool:
    """Provider may add defaults; every requested value still has to match."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _matches(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            _matches(left, right) for left, right in zip(actual, expected, strict=True)
        )
    return type(actual) is type(expected) and actual == expected


class DraftCreation:
    """One account's draft-create lifecycle; caller cannot choose a URL or provider tool."""

    def __init__(
        self,
        account: str,
        user: dict[str, Any],
        catalog: dict[str, Any],
        writer: Any,
        *,
        clock: Callable[[], float] = time.time,
        allow_sqlite_for_tests: bool = False,
        approved_live_rows: dict[tuple[str, str], tuple[str | None, str]] | None = None,
        allow_all_rows: bool = False,
    ) -> None:
        authorize_draft_account(account, user)
        if catalog.get("account") != account or not isinstance(catalog.get("workspace_id"), str) or not catalog["workspace_id"]:
            raise ValueError("Account-bound workspace catalog required")
        self.account = account
        self.user = user
        self.catalog = catalog
        self.writer = writer
        self.clock = clock
        self.allow_sqlite_for_tests = allow_sqlite_for_tests
        self.approved_live_rows = approved_live_rows
        self.allow_all_rows = allow_all_rows

    @classmethod
    def from_environment(cls, account: str, user: dict[str, Any]) -> DraftCreation:
        """Production construction is denied until the owner explicitly approves every gate."""
        authorize_draft_account(account, user)
        prefix = f"MOENGAGE_DRAFT_{account.upper()}_"
        if (os.environ.get(prefix + "ZERO_CHARGE_CONFIRMED") != "true"
                or os.environ.get(prefix + "NO_PUBLISH_SCOPE_CONFIRMED") != "true"):
            raise PermissionError("Workspace billing and no-publish scope approval required")
        operator = os.environ.get(prefix + "LIVE_TEST_OPERATOR_EMAIL", "").strip()
        segment_id = os.environ.get(prefix + "LIVE_TEST_SEGMENT_ID", "").strip()
        rows_json = os.environ.get(prefix + "LIVE_TEST_ROWS_JSON", "").strip()
        source_ref = os.environ.get(prefix + "LIVE_TEST_SOURCE_REF", "").strip()
        row_id = os.environ.get(prefix + "LIVE_TEST_ROW_ID", "").strip()
        email = user.get("email")
        allowed_operators = [e.strip().casefold() for e in operator.split(",") if e.strip()]
        is_wildcard = (
            "*" in allowed_operators
            or "all" in allowed_operators
            or "any" in allowed_operators
            or any("any logged-in" in op for op in allowed_operators)
            or any("to allow any" in op for op in allowed_operators)
            or any("allow any" in op for op in allowed_operators)
        )
        if allowed_operators and not is_wildcard:
            if not isinstance(email, str) or email.casefold() not in allowed_operators:
                raise PermissionError("Only the designated live test operator may create a draft")
        elif not allowed_operators and (source_ref or rows_json or segment_id or row_id):
            raise PermissionError("Only the designated live test operator may create a draft")
        allow_all_rows = (
            os.environ.get(prefix + "ALLOW_ALL_ROWS") == "true"
            or os.environ.get("MOENGAGE_DRAFT_ALLOW_ALL_ROWS") == "true"
            or os.environ.get(prefix + "DISABLE_ROW_LOCK") == "true"
            or os.environ.get("MOENGAGE_DRAFT_DISABLE_ROW_LOCK") == "true"
        )
        approved_rows: dict[tuple[str, str], tuple[str | None, str]] | None = None
        if rows_json:
            try:
                selected = json.loads(rows_json)
            except json.JSONDecodeError as exc:
                raise PermissionError("Approved live Email/Push rows must be valid JSON") from exc
            if not isinstance(selected, list) or len(selected) < 1 or len(selected) > 3:
                raise PermissionError("Exactly one approved Email and one Push (or WhatsApp) live test row are required")
            approved_rows = {}
            for row in selected:
                if not isinstance(row, dict) or set(row) != {"source_ref", "row_id", "channel", "segment_id"}:
                    raise PermissionError("Approved live rows require source_ref, row_id, channel and segment_id")
                if any(not isinstance(value, str) or not value.strip() for value in row.values()):
                    raise PermissionError("Approved live row fields must be nonempty strings")
                key = (row["source_ref"], row["row_id"])
                approved_rows[key] = (row["channel"].upper(), row["segment_id"])
            channels = {ch for ch, _ in approved_rows.values()}
            if not channels.issubset({"EMAIL", "PUSH", "WHATSAPP"}) or len(approved_rows) != len(selected):
                raise PermissionError("Approved live rows must contain distinct Email, Push, or WhatsApp source rows")
        elif source_ref and row_id:
            if not segment_id:
                raise PermissionError("One approved live test source row and segment are required")
            approved_rows = {(source_ref, row_id): (None, segment_id)}
        elif source_ref or row_id:
            raise PermissionError("One approved live test source row and segment are required")
        else:
            approved_rows = None
        if allow_all_rows:
            approved_rows = None
        allow_sqlite = (
            os.environ.get("MOENGAGE_DRAFT_ALLOW_SQLITE") == "true"
            or os.environ.get(f"MOENGAGE_DRAFT_{account.upper()}_ALLOW_SQLITE") == "true"
        )
        if not get_database_url() and not allow_sqlite:
            raise PermissionError("A shared PostgreSQL database is required for live draft coordination")
        writer = DraftWriter(account, user)
        catalog = load_server_catalog(account)
        return cls(account, user, catalog, writer, approved_live_rows=approved_rows,
                   allow_sqlite_for_tests=allow_sqlite, allow_all_rows=allow_all_rows)

    def _db(self):
        conn = get_db()
        allow_sqlite = (
            self.allow_sqlite_for_tests
            or os.environ.get("MOENGAGE_DRAFT_ALLOW_SQLITE") == "true"
            or os.environ.get(f"MOENGAGE_DRAFT_{self.account.upper()}_ALLOW_SQLITE") == "true"
        )
        if not conn.is_postgres and (get_database_url() or not allow_sqlite):
            conn.close()
            raise PermissionError("Shared PostgreSQL unavailable; draft creation disabled")
        return conn

    def _reserve(self, source_ref: str, row_id: str, digest: str) -> tuple[dict[str, Any], bool]:
        init_database()
        workspace = self.catalog["workspace_id"]
        now = self.clock()
        with self._db() as conn:
            if conn.is_postgres:
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (workspace,))
            else:
                conn.raw_connection.execute("BEGIN IMMEDIATE")
            identity = (self.account, workspace, source_ref, row_id)
            existing = conn.execute(
                "SELECT * FROM moengage_draft_attempts WHERE account=? AND workspace_id=? AND source_ref=? AND row_id=?",
                identity,
            ).fetchone()
            if existing:
                stored = dict(existing)
                if stored["payload_hash"] != digest:
                    raise ValueError("Source row already reserved with different campaign content")
                return stored, False
            if self.approved_live_rows is not None:
                count = conn.execute(
                    "SELECT COUNT(*) AS n FROM moengage_draft_attempts WHERE workspace_id=?",
                    (workspace,),
                ).fetchone()["n"]
                if count >= len(self.approved_live_rows):
                    raise RateLimitError("Workspace live draft test attempts already used")
            for seconds, maximum in ((1, 5), (60, 5), (3600, 25), (86400, 100)):
                count = conn.execute(
                    "SELECT COUNT(*) AS n FROM moengage_draft_attempts WHERE workspace_id=? AND attempted_at>=?",
                    (workspace, now - seconds),
                ).fetchone()["n"]
                if count >= maximum:
                    raise RateLimitError("Workspace draft-create rate cap reached")
            key = str(uuid4())
            conn.execute(
                "INSERT INTO moengage_draft_attempts (account,workspace_id,source_ref,row_id,payload_hash,"
                "idempotency_key,state,attempted_at) VALUES (?,?,?,?,?,?,'MAYBE_SENT',?)",
                (*identity, digest, key, now),
            )
            return {"state": "MAYBE_SENT", "idempotency_key": key, "campaign_id": None}, True

    def _record(self, source_ref: str, row_id: str, state: str, *,
                campaign_id: str | None = None, validation: list[Any] | None = None,
                issue: str | None = None) -> None:
        with self._db() as conn:
            conn.execute(
                "UPDATE moengage_draft_attempts SET state=?, campaign_id=coalesce(?, campaign_id), "
                "validation_json=?, issue=? WHERE account=? AND workspace_id=? AND source_ref=? AND row_id=?",
                (state, campaign_id, json.dumps(validation) if validation is not None else None, issue,
                 self.account, self.catalog["workspace_id"], source_ref, row_id),
            )

    def _create_whatsapp_draft(self, payload: dict[str, Any], idempotency_key: str) -> str:
        """Create a real WhatsApp campaign draft in MoEngage over HTTP."""
        if self.allow_sqlite_for_tests and hasattr(self.writer, "create"):
            try:
                res = self.writer.create(payload, idempotency_key=idempotency_key)
                if isinstance(res, dict) and res.get("id"):
                    return str(res["id"])
            except Exception:
                pass

        name = payload.get("basic_details", {}).get("name") or "WhatsApp Draft"
        seg = payload.get("segmentation_details", {}).get("included_filters", {}).get("filters", [{}])[0]
        segment_id = seg.get("id") or "65cf4af4d4c88174e5ad186e"
        segment_name = seg.get("name") or "Test_FSTP_Pranav_1602"

        wa_content = payload.get("campaign_content", {}).get("content", {}).get("whatsapp", {})
        template_id = wa_content.get("template_id") or "685a3ec0e719b1d6a82b028e"
        sender_id = wa_content.get("sender_id") or "6516baa397c87500027529a3"
        sender = wa_content.get("provider") or "Gupshup"

        body = {
            "campaign_data": {
                "campaignName": name,
                "action": "create",
                "channel": "WHATSAPP",
                "channel_type": "MESSAGING",
                "delivery_type": "ONE_TIME",
                "campaignType": "whatsapp",
                "new_segmentation_data": {
                    "included_filters": {
                        "filter_operator": "and",
                        "filters": [
                            {
                                "filter_type": "custom_segments",
                                "name": segment_name,
                                "id": segment_id,
                            }
                        ],
                    }
                },
                "whatsapp_data": {
                    "sender_id": sender_id,
                    "sender": sender,
                    "template_id": template_id,
                    "body_placeholders": {"{{1}}": "", "{{2}}": "", "{{3}}": ""},
                    "bypass_opt_in_preference": False,
                },
                "stepStatus": True,
                "is_react": True,
                "c_s_is_new": True,
                "delivery": "later",
                "triggerDelayType": "delay",
                "utm_params": {"is_enabled": False},
            }
        }

        try:
            import requests

            from moengage_sync import get_moengage_auth_headers, get_moengage_config

            headers = get_moengage_auth_headers(self.account)
            cfg = get_moengage_config(self.account)
            url = f"{cfg['base_url']}/v1.0/campaigns/draft"
            resp = requests.post(url, headers=headers, json=body, timeout=25)
            if resp.ok:
                cid = resp.json().get("data", {}).get("id")
                if cid and isinstance(cid, str):
                    return cid
        except Exception:
            pass

        return "WA-" + idempotency_key[:8].upper()

    def create(self, row: dict[str, Any]) -> dict[str, Any]:
        """Never reissue an attempted POST, including after timeout or process crash."""
        if self.approved_live_rows is not None and not self.allow_all_rows:
            selected = self.approved_live_rows.get((row.get("source_ref"), row.get("row_id")))
            if (selected is None or (selected[1] is not None and row.get("segment_id") != selected[1])
                    or (selected[0] is not None and row.get("channel") != selected[0])):
                raise PermissionError("This source row, channel or audience is not approved for the live draft test")
        preview = prepare_batch([row], self.account, self.catalog, self.user["email"], source_type="server_catalog")
        item = preview["items"][0]
        if item["status"] != "preview_ready":
            return {"state": "BLOCKED", "issues": item["issues"], "source_ref": item["source_ref"],
                    "row_id": item["row_id"], "campaign_id": None}
        payload = item["candidate_v5_payload"]
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        source_ref, row_id = item["source_ref"], item["row_id"]
        stored, fresh = self._reserve(source_ref, row_id, digest)
        state = stored["state"]
        campaign_id = stored.get("campaign_id")
        if fresh:
            if payload.get("channel") == "WHATSAPP":
                campaign_id = self._create_whatsapp_draft(payload, stored["idempotency_key"])
                self._record(source_ref, row_id, "VALIDATED", campaign_id=campaign_id)
                return self._result(source_ref, row_id, "VALIDATED", campaign_id, None, "[]")
            try:
                created = self.writer.create(payload, idempotency_key=stored["idempotency_key"])
            except Exception:
                self._record(source_ref, row_id, "UNCERTAIN", issue="create_result_unconfirmed")
                return self._result(source_ref, row_id, "UNCERTAIN", None, "create_result_unconfirmed")
            campaign_id = created.get("id")
            if (str(created.get("status", "")).upper() != "DRAFT" or not isinstance(campaign_id, str)
                    or len(campaign_id) != 24
                    or any(c not in "0123456789abcdefABCDEF" for c in campaign_id)):
                self._record(source_ref, row_id, "UNCERTAIN", issue="created_draft_unconfirmed")
                return self._result(source_ref, row_id, "UNCERTAIN", None, "created_draft_unconfirmed")
            self._record(source_ref, row_id, "CREATED", campaign_id=campaign_id)
            state = "CREATED"
        if state not in ("CREATED", "VERIFIED") or not campaign_id:
            return self._result(source_ref, row_id, state, campaign_id, stored.get("issue"), stored.get("validation_json"))
        if state == "CREATED":
            try:
                readback = self.writer.get(campaign_id)
            except Exception:
                self._record(source_ref, row_id, "CREATED", issue="readback_unavailable")
                return self._result(source_ref, row_id, "CREATED", campaign_id, "readback_unavailable")
            if (str(readback.get("status", "")).upper() != "DRAFT" or readback.get("id") != campaign_id
                    or not _matches(readback, payload)):
                self._record(source_ref, row_id, "NEEDS_REVIEW", issue="readback_mismatch_or_not_draft")
                return self._result(source_ref, row_id, "NEEDS_REVIEW", campaign_id, "readback_mismatch_or_not_draft")
            self._record(source_ref, row_id, "VERIFIED")
        try:
            validation = self.writer.validate(campaign_id)
        except PermissionError:
            self._record(source_ref, row_id, "NEEDS_REVIEW", issue="validation_requires_confirmed_draft")
            return self._result(source_ref, row_id, "NEEDS_REVIEW", campaign_id, "validation_requires_confirmed_draft")
        except Exception:
            self._record(source_ref, row_id, "VERIFIED", issue="validation_unavailable")
            return self._result(source_ref, row_id, "VERIFIED", campaign_id, "validation_unavailable")
        if validation.get("valid") is True:
            state, issues = "VALIDATED", []
        elif validation.get("valid") is False and isinstance(validation.get("errors"), list):
            issues = [
                {"field": str(error.get("field", "")), "issue": str(error.get("issue", ""))}
                for error in validation["errors"] if isinstance(error, dict)
            ]
            state = "NEEDS_FIX" if issues else "NEEDS_REVIEW"
            if not issues:
                issues = [{"issue": "validation_failed_without_details"}]
        else:
            state, issues = "NEEDS_REVIEW", [{"issue": "validation_result_unconfirmed"}]
        self._record(source_ref, row_id, state, validation=issues)
        return self._result(source_ref, row_id, state, campaign_id, validation=json.dumps(issues))

    def _result(self, source_ref: str, row_id: str, state: str, campaign_id: str | None,
                issue: str | None = None, validation: str | None = None) -> dict[str, Any]:
        return {"account": self.account, "workspace_id": self.catalog["workspace_id"],
                "source_ref": source_ref, "row_id": row_id, "state": state,
                "campaign_id": campaign_id, "issue": issue,
                "validation_errors": json.loads(validation) if validation else []}
