"""Durable, account-owned staging and single-row handoff for V5 draft creation.

A row is claimed as UNCERTAIN in shared storage *before* calling DraftCreation.
An interrupted process can therefore leave a row uncertain, but cannot cause a
second provider POST. UNCERTAIN rows require manual investigation, not retry.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from uuid import uuid4

from db import get_database_url, get_db, init_database
from moengage_draft_creation import DraftCreation, RateLimitError
from moengage_drafts import authorize_draft_account
from moengage_preview import prepare_batch


class BatchAccessDenied(PermissionError):
    """A batch exists, but belongs to another account, workspace or creator."""


class DraftBatchQueue:
    """Staged campaign rows scoped to one authenticated creator and workspace."""

    def __init__(
        self,
        account: str,
        user: dict[str, Any],
        catalog: dict[str, Any],
        *,
        allow_sqlite_for_tests: bool = False,
        creator: Any = None,
    ) -> None:
        authorize_draft_account(account, user)
        email = user.get("email")
        subject = user.get("sub")
        if not isinstance(email, str) or "@" not in email or not isinstance(subject, str) or not subject.strip():
            raise PermissionError("Authenticated creator identity required")
        if (not isinstance(catalog, dict) or catalog.get("account") != account
                or not isinstance(catalog.get("workspace_id"), str) or not catalog["workspace_id"].strip()):
            raise ValueError("Account-bound workspace catalog required")
        if creator is not None and not allow_sqlite_for_tests:
            raise PermissionError("Draft creator injection is only available in explicit offline tests")
        self.account = account
        self.user = user
        self.catalog = catalog
        self.email = email
        self.subject = subject
        self.workspace_id = catalog["workspace_id"]
        self.allow_sqlite_for_tests = allow_sqlite_for_tests
        self.creator = creator
        self._init_db()

    def _db(self):
        conn = get_db()
        allow_sqlite = (
            self.allow_sqlite_for_tests
            or os.environ.get("MOENGAGE_DRAFT_ALLOW_SQLITE") == "true"
            or os.environ.get(f"MOENGAGE_DRAFT_{self.account.upper()}_ALLOW_SQLITE") == "true"
        )
        if not conn.is_postgres and (get_database_url() or not allow_sqlite):
            conn.close()
            raise PermissionError("Shared PostgreSQL unavailable; draft batches disabled")
        return conn

    def _init_db(self) -> None:
        # The adapter may silently fall back to SQLite when PostgreSQL fails.
        # Initialize schema on the same checked connection, never that fallback.
        with self._db() as conn:
            init_database(conn)

    def _batch_row(self, conn: Any, batch_id: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM moengage_draft_batches WHERE batch_id=? AND account=? "
            "AND workspace_id=? AND creator_sub=? AND creator_email=?",
            (batch_id, self.account, self.workspace_id, self.subject, self.email),
        ).fetchone()
        if row is None:
            exists = conn.execute(
                "SELECT 1 FROM moengage_draft_batches WHERE batch_id=?", (batch_id,),
            ).fetchone()
            if exists is not None:
                raise BatchAccessDenied("Draft batch access denied")
            raise LookupError("Draft batch not found")
        return dict(row)

    def stage(self, rows: list[Any], source_ref: str) -> dict[str, Any]:
        """Persist every preview row, including blocked/duplicated rows, with raw inputs private."""
        if not isinstance(source_ref, str) or not source_ref.strip():
            raise ValueError("A non-empty batch source_ref is required")
        preview = prepare_batch(rows, self.account, self.catalog, self.email, source_type="spreadsheet")
        if any(isinstance(row, dict) and row.get("source_ref") != source_ref for row in rows):
            raise ValueError("Each row source_ref must match the batch source_ref")
        # Refuse unsupported values before a transaction; original source rows are
        # stored unmodified and only vetted preview content is returned to clients.
        encoded_rows = [json.dumps(row, ensure_ascii=False, allow_nan=False) for row in rows]
        batch_id, now = str(uuid4()), time.time()
        with self._db() as conn:
            conn.execute(
                "INSERT INTO moengage_draft_batches "
                "(batch_id,account,workspace_id,creator_sub,creator_email,source_ref,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (batch_id, self.account, self.workspace_id, self.subject, self.email, source_ref, now),
            )
            conn.executemany(
                "INSERT INTO moengage_draft_batch_rows "
                "(batch_id,position,account,workspace_id,source_ref,row_id,channel,row_json,candidate_json,"
                "source_fields_json,status,issues_json,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (batch_id, index, self.account, self.workspace_id, item["source_ref"], item["row_id"],
                     item.get("channel", ""), encoded_rows[index],
                     json.dumps(item["candidate_v5_payload"]) if item["candidate_v5_payload"] is not None else None,
                     json.dumps(item.get("source_fields", {})), item["status"], json.dumps(item["issues"]), now)
                    for index, item in enumerate(preview["items"])
                ],
            )
        return self.get(batch_id)

    def get(self, batch_id: str) -> dict[str, Any]:
        """Read only this account/workspace/creator's rows; never return raw input or catalog."""
        with self._db() as conn:
            batch = self._batch_row(conn, batch_id)
            rows = conn.execute(
                "SELECT source_ref,row_id,channel,candidate_json,source_fields_json,status,issues_json,campaign_id,issue,validation_json,updated_at "
                "FROM moengage_draft_batch_rows WHERE batch_id=? ORDER BY position",
                (batch_id,),
            ).fetchall()
        items = [{"source_ref": row["source_ref"], "row_id": row["row_id"], "channel": row["channel"],
                  "candidate_v5_payload": json.loads(row["candidate_json"]) if row["candidate_json"] else None,
                  "source_fields": json.loads(row["source_fields_json"]),
                  "status": row["status"], "issues": json.loads(row["issues_json"]),
                  "campaign_id": row["campaign_id"], "issue": row["issue"],
                  "validation_errors": json.loads(row["validation_json"]), "updated_at": row["updated_at"]} for row in rows]
        return {"batch_id": batch_id, "account": batch["account"], "workspace_id": batch["workspace_id"],
                "source_ref": batch["source_ref"], "created_at": batch["created_at"], "items": items,
                "ready": sum(item["status"] == "preview_ready" for item in items),
                "blocked": sum(item["status"].lower() == "blocked" for item in items)}

    def create_row(self, batch_id: str, row_id: str) -> dict[str, Any]:
        """Claim one selected row once; replay only reads its persisted result."""
        with self._db() as conn:
            self._batch_row(conn, batch_id)
            matches = conn.execute(
                "SELECT * FROM moengage_draft_batch_rows WHERE batch_id=? AND row_id=? ORDER BY position",
                (batch_id, row_id),
            ).fetchall()
        if not matches:
            raise LookupError("Draft row not found")
        if len(matches) != 1:
            raise ValueError("Duplicate row_id in batch; no unique row can be selected")
        current = dict(matches[0])
        if current["status"] != "preview_ready":
            if not (current.get("channel") == "WHATSAPP" and current["status"] == "UNCERTAIN"):
                return self.get(batch_id)
        # Production constructs the gated creator before claiming; a missing owner
        # approval leaves the row ready and cannot silently consume its one attempt.
        creator = self.creator if self.creator is not None else DraftCreation.from_environment(self.account, self.user)
        if self.creator is None and creator.catalog.get("workspace_id") != self.workspace_id:
            raise PermissionError("Staged workspace differs from the approved live workspace")
        with self._db() as conn:
            if conn.is_postgres:
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (
                    f"{self.account}:{self.workspace_id}:{current['source_ref']}:{row_id}",))
            else:
                conn.raw_connection.execute("BEGIN IMMEDIATE")
            self._batch_row(conn, batch_id)
            claimed_elsewhere = conn.execute(
                "SELECT batch_id FROM moengage_draft_batch_rows WHERE account=? AND workspace_id=? "
                "AND source_ref=? AND row_id=? AND batch_id<>? AND status NOT IN ('preview_ready','blocked')",
                (self.account, self.workspace_id, current["source_ref"], row_id, batch_id),
            ).fetchone()
            if claimed_elsewhere is not None:
                raise ValueError("Source row already attempted in another batch")
            claimed = conn.execute(
                "UPDATE moengage_draft_batch_rows SET status='UNCERTAIN',issue='create_result_unconfirmed',updated_at=? "
                "WHERE batch_id=? AND position=? AND (status='preview_ready' OR (channel='WHATSAPP' AND status='UNCERTAIN'))",
                (time.time(), batch_id, current["position"]),
            ).rowcount
            if claimed != 1:
                return self.get(batch_id)
        try:
            result = creator.create(json.loads(current["row_json"]))
            if not isinstance(result, dict) or result.get("state") not in (
                    "BLOCKED", "MAYBE_SENT", "UNCERTAIN", "CREATED", "VERIFIED", "VALIDATED", "NEEDS_FIX", "NEEDS_REVIEW"):
                raise ValueError("Draft create result unconfirmed")
            if result.get("account", self.account) != self.account or result.get("workspace_id", self.workspace_id) != self.workspace_id:
                raise ValueError("Draft create result workspace unconfirmed")
            if (result.get("source_ref") != current["source_ref"] or result.get("row_id") != row_id):
                raise ValueError("Draft create result row identity unconfirmed")
            state = "UNCERTAIN" if result["state"] == "MAYBE_SENT" else result["state"]
            issues = result.get("issues") if state == "BLOCKED" else json.loads(current["issues_json"])
            if not isinstance(issues, list):
                raise ValueError("Draft create issues unconfirmed")
            validation = result.get("validation_errors", [])
            if not isinstance(validation, list):
                raise ValueError("Draft validation result unconfirmed")
            campaign_id = result.get("campaign_id")
            if campaign_id is not None and not isinstance(campaign_id, str):
                raise ValueError("Draft campaign ID unconfirmed")
            if state in ("CREATED", "VERIFIED", "VALIDATED", "NEEDS_FIX", "NEEDS_REVIEW") and not campaign_id:
                raise ValueError("Created draft campaign ID unconfirmed")
            issue = result.get("issue")
            if issue is not None and not isinstance(issue, str):
                raise ValueError("Draft create issue unconfirmed")
        except RateLimitError:
            # DraftCreation raises this only from its local pre-POST reservation.
            # No external attempt occurred; preserve the preview row for a later
            # deliberate operator action and let the API report the rate cap.
            with self._db() as conn:
                conn.execute(
                    "UPDATE moengage_draft_batch_rows SET status='preview_ready',issue=NULL,updated_at=? "
                    "WHERE batch_id=? AND position=? AND status='UNCERTAIN'",
                    (time.time(), batch_id, current["position"]),
                )
            raise
        except Exception:
            # A creator may have POSTed just before crashing or before a persistence
            # failure. No subsequent request may invoke it again for this source row.
            return self.get(batch_id)
        with self._db() as conn:
            conn.execute(
                "UPDATE moengage_draft_batch_rows SET status=?,issues_json=?,campaign_id=?,issue=?,validation_json=?,updated_at=? "
                "WHERE batch_id=? AND position=? AND status='UNCERTAIN'",
                (state, json.dumps(issues), campaign_id, issue, json.dumps(validation), time.time(),
                 batch_id, current["position"]),
            )
        return self.get(batch_id)
