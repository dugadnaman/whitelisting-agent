"""Durable, account-owned staging and single-row handoff for V5 draft creation.

A new row is claimed as UNCERTAIN in shared storage *before* calling DraftCreation.
Only explicit pre-POST rejections release that claim. Interrupted creates cannot
cause another provider POST; known CREATED drafts may resume readback only.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from typing import Any
from uuid import uuid4

from db import get_database_url, get_db, init_database
from moengage_draft_creation import DraftCreation, DraftPreflightError, RateLimitError
from moengage_drafts import authorize_draft_account
from moengage_preview import prepare_batch
from moengage_workspaces import catalog_for_row


def prepare_routed_batch(
    rows: list[Any], account: str, user: dict[str, Any], catalog: dict[str, Any], *, source_type: str,
) -> dict[str, Any]:
    """Resolve each WhatsApp destination before preview; never create a campaign."""
    authorize_draft_account(account, user)
    if not rows:
        raise ValueError("At least one campaign row is required")
    duplicates = Counter(
        tuple(row.get(field, "").strip() if isinstance(row.get(field), str) else ""
              for field in ("source_ref", "row_id"))
        for row in rows if isinstance(row, dict)
    )
    catalogs: dict[tuple[str, ...], dict[str, Any]] = {}
    items = []
    for index, row in enumerate(rows, 1):
        selected = catalog
        issue = None
        normalized = row
        if isinstance(row, dict) and str(row.get("channel", "")).strip().upper() == "WHATSAPP":
            try:
                key = (str(row.get("workspace_id") or ""), str(row.get("workspace") or ""),
                       str(row.get("brand") or ""), str(row.get("goal_reference_id") or ""),
                       str(row.get("whatsapp_template_id") or "") if account == "apparel" else "")
                if key not in catalogs:
                    catalogs[key] = catalog_for_row(account, user, row, catalog)
                selected = catalogs[key]
                normalized = {**row, "workspace_id": selected["workspace_id"]}
            except (ValueError, PermissionError, RuntimeError) as exc:
                issue = str(exc)
        item = prepare_batch([normalized], account, selected, user["email"], source_type=source_type)["items"][0]
        if not isinstance(row, dict):
            item.update(row_id=f"row:{index}", channel="", source_fields={})
        if isinstance(row, dict) and duplicates[(item["source_ref"], item["row_id"])] > 1:
            issue = "Duplicate source_ref/row_id in batch"
        if issue:
            item.update(status="blocked", candidate_v5_payload=None, issues=[issue])
        item["workspace_id"] = selected["workspace_id"] if not issue else str(row.get("workspace_id") or "") if isinstance(row, dict) else ""
        if item["channel"] == "WHATSAPP":
            item["source_fields"].pop("workspace_name", None)
        if selected.get("workspace_name"):
            item["workspace_name"] = selected["workspace_name"]
            item["source_fields"]["workspace_name"] = selected["workspace_name"]
        items.append(item)
    return {
        "account": account, "workspace_id": catalog["workspace_id"], "source_type": source_type,
        "catalog_verified": True, "write_eligible": False, "items": items,
        "ready": sum(item["status"] == "preview_ready" for item in items),
        "blocked": sum(item["status"] == "blocked" for item in items),
    }


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

    def _batch_row(self, conn: Any, batch_id: str, *, include_archived: bool = False) -> dict[str, Any]:
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
        if row["archived_at"] is not None and not include_archived:
            raise LookupError("Draft batch not found")
        return dict(row)

    def _lock_batch(self, conn: Any, batch_id: str) -> None:
        # Archive and create must serialize before checking visibility or claims.
        if conn.is_postgres:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"moengage-draft-batch:{batch_id}",))
        else:
            conn.raw_connection.execute("BEGIN IMMEDIATE")

    def archive(self, batch_id: str) -> dict[str, Any]:
        """Hide an owned batch without changing audit rows, claims or provider drafts."""
        with self._db() as conn:
            self._lock_batch(conn, batch_id)
            batch = self._batch_row(conn, batch_id, include_archived=True)
            if batch["archived_at"] is None:
                identities = conn.execute(
                    "SELECT DISTINCT account,workspace_id,source_ref,row_id FROM moengage_draft_batch_rows "
                    "WHERE batch_id=? ORDER BY account,workspace_id,source_ref,row_id", (batch_id,),
                ).fetchall()
                if conn.is_postgres:
                    for row in identities:
                        conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (
                            f"{row['account']}:{row['workspace_id']}:{row['source_ref']}:{row['row_id']}",))
                # Include duplicate uploads and the lower-level reservation ledger:
                # an apparently ready row must not conceal an ongoing source attempt.
                unconfirmed = conn.execute(
                    "SELECT 1 FROM moengage_draft_batch_rows AS active "
                    "WHERE active.status NOT IN ('preview_ready','blocked','VERIFIED','VALIDATED','NEEDS_FIX') "
                    "AND EXISTS (SELECT 1 FROM moengage_draft_batch_rows AS selected "
                    "WHERE selected.batch_id=? AND selected.account=active.account "
                    "AND selected.workspace_id=active.workspace_id AND selected.source_ref=active.source_ref "
                    "AND selected.row_id=active.row_id)", (batch_id,),
                ).fetchone()
                attempt = conn.execute(
                    "SELECT 1 FROM moengage_draft_attempts AS attempt "
                    "WHERE (attempt.state NOT IN ('VERIFIED','VALIDATED','NEEDS_FIX') OR attempt.campaign_id IS NULL) "
                    "AND EXISTS (SELECT 1 FROM moengage_draft_batch_rows AS selected "
                    "WHERE selected.batch_id=? AND selected.account=attempt.account "
                    "AND selected.workspace_id=attempt.workspace_id AND selected.source_ref=attempt.source_ref "
                    "AND selected.row_id=attempt.row_id)", (batch_id,),
                ).fetchone()
                if unconfirmed is not None or attempt is not None:
                    raise ValueError("Draft batch has an ongoing or unconfirmed attempt; inspect it before removal")
                conn.execute(
                    "UPDATE moengage_draft_batches SET archived_at=? WHERE batch_id=?",
                    (time.time(), batch_id),
                )
        return {"ok": True, "batch_id": batch_id, "archived": True}

    def stage(self, rows: list[Any], source_ref: str) -> dict[str, Any]:
        """Persist every preview row, including blocked/duplicated rows, with raw inputs private."""
        if not isinstance(source_ref, str) or not source_ref.strip():
            raise ValueError("A non-empty batch source_ref is required")
        preview = prepare_routed_batch(rows, self.account, self.user, self.catalog, source_type="spreadsheet")
        if any(isinstance(row, dict) and row.get("source_ref") != source_ref for row in rows):
            raise ValueError("Each row source_ref must match the batch source_ref")
        # Refuse unsupported values before a transaction; original source rows are
        # stored unmodified and only vetted preview content is returned to clients.
        encoded_rows = [
            json.dumps({**row, "workspace_id": item["workspace_id"]}, ensure_ascii=False, allow_nan=False)
            if isinstance(row, dict) and item["channel"] == "WHATSAPP" and item["status"] == "preview_ready"
            else json.dumps(row, ensure_ascii=False, allow_nan=False)
            for row, item in zip(rows, preview["items"], strict=True)
        ]
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
                    (batch_id, index, self.account, item["workspace_id"], item["source_ref"], item["row_id"],
                     item.get("channel", ""), encoded_rows[index],
                     json.dumps(item["candidate_v5_payload"]) if item["candidate_v5_payload"] is not None else None,
                     json.dumps({**item.get("source_fields", {}), **(
                         {"_draft_warnings": json.dumps(item.get("warnings", []))} if self.account == "apparel" else {}
                     )}), item["status"], json.dumps(item["issues"]), now)
                    for index, item in enumerate(preview["items"])
                ],
            )
        return self.get(batch_id)

    def get(self, batch_id: str) -> dict[str, Any]:
        """Read only this account/workspace/creator's rows; never return raw input or catalog."""
        with self._db() as conn:
            batch = self._batch_row(conn, batch_id)
            rows = conn.execute(
                "SELECT workspace_id,source_ref,row_id,channel,candidate_json,source_fields_json,status,issues_json,campaign_id,issue,validation_json,updated_at "
                "FROM moengage_draft_batch_rows WHERE batch_id=? ORDER BY position",
                (batch_id,),
            ).fetchall()
        items = [{"source_ref": row["source_ref"], "row_id": row["row_id"], "channel": row["channel"], "workspace_id": row["workspace_id"],
                  "candidate_v5_payload": json.loads(row["candidate_json"]) if row["candidate_json"] else None,
                  "source_fields": json.loads(row["source_fields_json"]),
                  "status": row["status"], "issues": json.loads(row["issues_json"]),
                  "campaign_id": row["campaign_id"], "issue": row["issue"],
                  "validation_errors": json.loads(row["validation_json"]), "updated_at": row["updated_at"]} for row in rows]
        for item in items:
            if self.account == "apparel":
                item["warnings"] = json.loads(item["source_fields"].pop("_draft_warnings", "[]"))
            if item["channel"] == "WHATSAPP" and item["source_fields"].get("workspace_name"):
                item["workspace_name"] = item["source_fields"]["workspace_name"]
        return {"batch_id": batch_id, "account": batch["account"], "workspace_id": batch["workspace_id"],
                "source_ref": batch["source_ref"], "created_at": batch["created_at"], "items": items,
                "ready": sum(item["status"] == "preview_ready" for item in items),
                "blocked": sum(item["status"].lower() == "blocked" for item in items)}

    def _approved_retry_row(self, conn: Any, current: dict[str, Any]) -> dict[str, Any] | None:
        if self.account != "apparel":
            return None
        history = conn.execute(
            "SELECT h.retry_row_json FROM moengage_draft_retry_history h "
            "JOIN moengage_draft_attempts a ON a.account=h.account AND a.workspace_id=h.workspace_id "
            "AND a.source_ref=h.source_ref AND a.row_id=h.row_id AND a.idempotency_key=h.retry_idempotency_key "
            "WHERE h.account=? AND h.workspace_id=? AND h.source_ref=? AND h.row_id=? AND h.approved_by=?",
            (self.account, current["workspace_id"], current["source_ref"], current["row_id"], self.subject),
        ).fetchone()
        return json.loads(history["retry_row_json"]) if history else None

    def reconcile_row(self, batch_id: str, row_id: str) -> dict[str, Any]:
        """Associate only a verified existing draft; never repeat a provider create."""
        with self._db() as conn:
            batch = self._batch_row(conn, batch_id)
            rows = conn.execute(
                "SELECT * FROM moengage_draft_batch_rows WHERE batch_id=? AND row_id=? AND source_ref=?",
                (batch_id, row_id, batch["source_ref"].strip()),
            ).fetchall()
        if not rows:
            raise LookupError("Draft row not found")
        if len(rows) != 1:
            raise ValueError("Duplicate row_id in batch; no unique row can be reconciled")
        current = dict(rows[0])
        if current["channel"] != "WHATSAPP":
            raise ValueError("Only WhatsApp draft attempts support reconciliation")
        if current["status"] not in ("UNCERTAIN", "MAYBE_SENT", "UNKNOWN", "CREATED"):
            raise ValueError("This row has no unresolved draft attempt")
        row = json.loads(current["row_json"])
        with self._db() as conn:
            retry_row = self._approved_retry_row(conn, current)
        if retry_row is not None:
            row = retry_row
        target = current["workspace_id"]
        if isinstance(self.creator, dict):
            creator = self.creator[target]
        elif self.creator is not None:
            creator = self.creator
        else:
            options = {key: str(row.get(field) or "") or None for key, field in
                       (("reference_id", "goal_reference_id"), ("template_ref", "whatsapp_template_id"))} if self.account == "apparel" else {}
            creator = DraftCreation.from_environment(self.account, self.user, workspace_id=target, **options)
        if creator.catalog.get("workspace_id") != target:
            raise PermissionError("Staged workspace differs from the authorized workspace")
        result = creator.reconcile(row)
        if result["state"] == "verified":
            context = (current["row_json"], current["candidate_json"], current["source_fields_json"])
            if retry_row is not None:
                item = prepare_batch([row], self.account, creator.catalog, self.email, source_type="server_catalog")["items"][0]
                fields = {**item["source_fields"], "_draft_warnings": json.dumps(item.get("warnings", []))}
                context = (json.dumps(row), json.dumps(item["candidate_v5_payload"]), json.dumps(fields))
            with self._db() as conn:
                self._lock_batch(conn, batch_id)
                self._batch_row(conn, batch_id)
                changed = conn.execute(
                    "UPDATE moengage_draft_batch_rows SET status='VERIFIED',campaign_id=?,issue=NULL,"
                    "row_json=?,candidate_json=?,source_fields_json=?,updated_at=? "
                    "WHERE batch_id=? AND position=? AND status=? AND updated_at=?",
                    (result["campaign_id"], *context, time.time(), batch_id, current["position"], current["status"], current["updated_at"]),
                ).rowcount
            if changed != 1:
                result = {"state": "mismatch", "message": "The row changed while checking. No create was retried."}
        response = self.get(batch_id)
        response["reconciliation"] = {"state": result["state"], "message": result["message"]}
        return response

    def retry_row_once(self, batch_id: str, row_id: str, row: dict[str, Any],
                       expected_payload_hash: str) -> dict[str, Any]:
        """Apply one explicit owner approval; preserve the original uncertain attempt."""
        with self._db() as conn:
            batch = self._batch_row(conn, batch_id)
            rows = conn.execute(
                "SELECT * FROM moengage_draft_batch_rows WHERE batch_id=? AND row_id=? AND source_ref=?",
                (batch_id, row_id, batch["source_ref"].strip()),
            ).fetchall()
        if not rows:
            raise LookupError("Draft row not found")
        if len(rows) != 1:
            raise ValueError("Duplicate row_id in batch; no unique row can be retried")
        current = dict(rows[0])
        if self.account != "apparel" or current["channel"] != "WHATSAPP":
            raise DraftPreflightError("Only Apparel WhatsApp supports an explicitly approved retry")
        if current["campaign_id"]:
            return self.get(batch_id)
        if current["status"] not in ("UNCERTAIN", "UNKNOWN", "MAYBE_SENT"):
            raise DraftPreflightError("This row has no uncertain attempt to retry")
        previous = json.loads(current["row_json"])
        for field in ("account", "workspace_id", "source_ref", "row_id"):
            if row.get(field) != previous.get(field):
                raise DraftPreflightError("Approved retry source or workspace differs from this batch")
        target = current["workspace_id"]
        if isinstance(self.creator, dict):
            creator = self.creator[target]
        elif self.creator is not None:
            creator = self.creator
        else:
            options = {key: str(previous.get(field) or "") or None for key, field in
                       (("reference_id", "goal_reference_id"), ("template_ref", "whatsapp_template_id"))}
            creator = DraftCreation.from_environment(self.account, self.user, workspace_id=target, **options)
        if creator.catalog.get("workspace_id") != target:
            raise DraftPreflightError("Retry workspace differs from the authorized workspace")
        item = prepare_batch([row], self.account, creator.catalog, self.email, source_type="server_catalog")["items"][0]
        if item["status"] != "preview_ready":
            raise DraftPreflightError("; ".join(item["issues"]))
        reviewed = hashlib.sha256(json.dumps(item["candidate_v5_payload"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if reviewed != expected_payload_hash:
            raise DraftPreflightError("Reviewed retry content changed; no new draft request was made")
        result = creator.retry_once(previous, row, expected_payload_hash)
        if (not isinstance(result, dict) or result.get("account") != self.account
                or result.get("workspace_id") != target or result.get("source_ref") != current["source_ref"]
                or result.get("row_id") != row_id):
            raise ValueError("Approved retry result identity is unconfirmed")
        if result["state"] == "MAYBE_SENT":
            return self.get(batch_id)
        if result["state"] not in ("UNCERTAIN", "CREATED", "VERIFIED", "NEEDS_REVIEW"):
            raise ValueError("Approved retry result state is unconfirmed")
        if result["state"] in ("CREATED", "VERIFIED", "NEEDS_REVIEW") and not result.get("campaign_id"):
            raise ValueError("Approved retry campaign ID is unconfirmed")
        with self._db() as conn:
            approved = self._approved_retry_row(conn, current)
            if result.get("recovered_existing"):
                context = (current["row_json"], current["candidate_json"], current["source_fields_json"], current["issues_json"])
            elif approved == row:
                fields = {**item["source_fields"], "_draft_warnings": json.dumps(item.get("warnings", []))}
                context = (json.dumps(row), json.dumps(item["candidate_v5_payload"]), json.dumps(fields), json.dumps(item["issues"]))
            else:
                raise DraftPreflightError("No durable approved retry context was found")
            self._lock_batch(conn, batch_id)
            self._batch_row(conn, batch_id)
            conn.execute(
                "UPDATE moengage_draft_batch_rows SET status=?,campaign_id=?,issue=?,validation_json=?,"
                "row_json=?,candidate_json=?,source_fields_json=?,issues_json=?,updated_at=? "
                "WHERE batch_id=? AND position=? AND status=? AND updated_at=?",
                (result["state"], result.get("campaign_id"), result.get("issue"), json.dumps(result.get("validation_errors", [])),
                 *context, time.time(), batch_id, current["position"], current["status"], current["updated_at"]),
            )
        return self.get(batch_id)

    def create_row(self, batch_id: str, row_id: str) -> dict[str, Any]:
        """Claim one selected row once; replay only reads its persisted result."""
        with self._db() as conn:
            batch = self._batch_row(conn, batch_id)
            matches = conn.execute(
                "SELECT * FROM moengage_draft_batch_rows WHERE batch_id=? AND row_id=? ORDER BY position",
                (batch_id, row_id),
            ).fetchall()
        # Non-object rows have display-only synthetic IDs and no source_ref.
        # They must not shadow a real row in this batch's durable source.
        source_matches = [row for row in matches if row["source_ref"] == batch["source_ref"].strip()]
        if source_matches:
            matches = source_matches
        if not matches:
            raise LookupError("Draft row not found")
        if len(matches) != 1:
            raise ValueError("Duplicate row_id in batch; no unique row can be selected")
        current = dict(matches[0])
        resumable = current["channel"] == "WHATSAPP" and current["status"] == "CREATED" and current.get("campaign_id")
        if current["status"] != "preview_ready" and not resumable:
            return self.get(batch_id)
        # Production constructs the gated creator before claiming; a missing owner
        # approval leaves the row ready and cannot silently consume its one attempt.
        target = current["workspace_id"]
        if isinstance(self.creator, dict):
            creator = self.creator[target]
        elif self.creator is not None:
            creator = self.creator
        else:
            staged_row = json.loads(current["row_json"])
            options = {key: str(staged_row.get(field) or "") or None for key, field in
                       (("reference_id", "goal_reference_id"), ("template_ref", "whatsapp_template_id"))} if self.account == "apparel" else {}
            creator = DraftCreation.from_environment(
                self.account, self.user, workspace_id=target if current["channel"] == "WHATSAPP" else None,
                **options,
            )
        if creator.catalog.get("workspace_id") != target:
            raise PermissionError("Staged workspace differs from the approved live workspace")
        if self.account == "apparel" and not resumable:
            refreshed = prepare_batch([json.loads(current["row_json"])], self.account, creator.catalog,
                                      self.user["email"], source_type="server_catalog")["items"][0]
            if refreshed["candidate_v5_payload"] != json.loads(current["candidate_json"] or "null"):
                raise DraftPreflightError("Live draft configuration changed after staging; preview and stage again")
        with self._db() as conn:
            self._lock_batch(conn, batch_id)
            if conn.is_postgres:
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (
                    f"{self.account}:{target}:{current['source_ref']}:{row_id}",))
            self._batch_row(conn, batch_id)
            claimed_elsewhere = conn.execute(
                "SELECT other.batch_id FROM moengage_draft_batch_rows AS other "
                "JOIN moengage_draft_batches AS batch ON batch.batch_id=other.batch_id "
                "WHERE other.account=? AND other.workspace_id=? AND other.source_ref=? AND other.row_id=? "
                "AND other.batch_id<>? AND (other.status NOT IN ('preview_ready','blocked') "
                "OR batch.archived_at IS NOT NULL)",
                (self.account, target, current["source_ref"], row_id, batch_id),
            ).fetchone()
            if claimed_elsewhere is not None:
                raise ValueError("Source row already attempted or archived in another batch")
            if resumable:
                # A known remote draft must never become a fresh provider POST if
                # its lower-level durable reservation is missing or inconsistent.
                attempt = conn.execute(
                    "SELECT campaign_id FROM moengage_draft_attempts WHERE account=? AND workspace_id=? "
                    "AND source_ref=? AND row_id=?",
                    (self.account, target, current["source_ref"], row_id),
                ).fetchone()
                if attempt is None or attempt["campaign_id"] != current["campaign_id"]:
                    return self.get(batch_id)
            claimed = conn.execute(
                "UPDATE moengage_draft_batch_rows SET status='UNCERTAIN',issue='create_result_unconfirmed',updated_at=? "
                "WHERE batch_id=? AND position=? AND status=? AND updated_at=?",
                (time.time(), batch_id, current["position"], current["status"], current["updated_at"]),
            ).rowcount
            if claimed != 1:
                return self.get(batch_id)
        try:
            result = creator.create(json.loads(current["row_json"]))
            if not isinstance(result, dict) or result.get("state") not in (
                    "BLOCKED", "MAYBE_SENT", "UNCERTAIN", "CREATED", "VERIFIED", "VALIDATED", "NEEDS_FIX", "NEEDS_REVIEW"):
                raise ValueError("Draft create result unconfirmed")
            if result.get("account", self.account) != self.account or result.get("workspace_id", target) != target:
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
            if state == "BLOCKED":
                if resumable:
                    state, campaign_id, issue = "CREATED", current["campaign_id"], "readback_preflight_blocked"
                else:
                    # BLOCKED is an explicit pre-POST result, not an attempted
                    # identity. Keep it consistent with blocked staging rows.
                    state = "blocked"
        except (RateLimitError, DraftPreflightError):
            # These types explicitly guarantee no provider POST occurred.
            # Restore the prior state, including a known CREATED readback target.
            with self._db() as conn:
                conn.execute(
                    "UPDATE moengage_draft_batch_rows SET status=?,issue=?,updated_at=? "
                    "WHERE batch_id=? AND position=? AND status='UNCERTAIN'",
                    (current["status"], current["issue"], time.time(), batch_id, current["position"]),
                )
            raise
        except Exception:
            # A creator may have POSTed just before crashing or before a persistence
            # failure. No subsequent request may invoke it again for this source row.
            if resumable:
                with self._db() as conn:
                    conn.execute(
                        "UPDATE moengage_draft_batch_rows SET status='CREATED',issue=?,updated_at=? "
                        "WHERE batch_id=? AND position=? AND status='UNCERTAIN'",
                        (current["issue"], time.time(), batch_id, current["position"]),
                    )
            return self.get(batch_id)
        with self._db() as conn:
            conn.execute(
                "UPDATE moengage_draft_batch_rows SET status=?,issues_json=?,campaign_id=?,issue=?,validation_json=?,"
                "candidate_json=CASE WHEN ?='blocked' THEN NULL ELSE candidate_json END,updated_at=? "
                "WHERE batch_id=? AND position=? AND status='UNCERTAIN'",
                (state, json.dumps(issues), campaign_id, issue, json.dumps(validation), state, time.time(),
                 batch_id, current["position"]),
            )
        return self.get(batch_id)
