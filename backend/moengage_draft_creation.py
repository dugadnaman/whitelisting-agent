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

    @classmethod
    def from_environment(cls, account: str, user: dict[str, Any]) -> DraftCreation:
        """Production construction is denied until the owner explicitly approves every gate."""
        authorize_draft_account(account, user)
        prefix = f"MOENGAGE_DRAFT_{account.upper()}_"
        if (os.environ.get(prefix + "ZERO_CHARGE_CONFIRMED") != "true"
                or os.environ.get(prefix + "NO_PUBLISH_SCOPE_CONFIRMED") != "true"):
            raise PermissionError("Workspace billing and no-publish scope approval required")
        if not get_database_url():
            raise PermissionError("A shared PostgreSQL database is required for live draft coordination")
        writer = DraftWriter(account, user)
        path = os.environ.get(prefix + "CATALOG_FILE", "")
        if not path:
            raise PermissionError("Server-owned workspace catalog required")
        catalog_file = Path(path)
        if not catalog_file.is_file() or catalog_file.stat().st_size > 1024 * 1024:
            raise ValueError("Account catalog must be a local JSON file of at most 1 MiB")
        catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
        if (not isinstance(catalog, dict) or catalog.get("account") != account
                or catalog.get("workspace_id") != os.environ.get(prefix + "WORKSPACE_ID")):
            raise ValueError("Catalog does not match the server-owned account/workspace")
        return cls(account, user, catalog, writer)

    def _db(self):
        conn = get_db()
        if not conn.is_postgres and (get_database_url() or not self.allow_sqlite_for_tests):
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

    def create(self, row: dict[str, Any]) -> dict[str, Any]:
        """Never reissue an attempted POST, including after timeout or process crash."""
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
            try:
                created = self.writer.create(payload, idempotency_key=stored["idempotency_key"])
            except Exception:
                self._record(source_ref, row_id, "UNCERTAIN", issue="create_result_unconfirmed")
                return self._result(source_ref, row_id, "UNCERTAIN", None, "create_result_unconfirmed")
            campaign_id = created.get("id")
            if (created.get("status") != "DRAFT" or not isinstance(campaign_id, str)
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
            if (readback.get("status") != "DRAFT" or readback.get("id") != campaign_id
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
