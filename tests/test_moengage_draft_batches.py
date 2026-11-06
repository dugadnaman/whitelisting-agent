"""Account-owned batch lifecycle, independent rows, and no duplicate remote create."""

import copy
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import db
from moengage_draft_batches import BatchAccessDenied, DraftBatchQueue, prepare_routed_batch
from moengage_draft_creation import DraftCreation, DraftPreflightError, RateLimitError
from tests.test_moengage_draft_creation import CATALOG, ROW, USER, FakeWriter


@pytest.fixture
def isolated_batch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_SQLITE_PATH", tmp_path / "batch.db")
    for name in ("DATABASE_URL", "POSTGRES_URL", "POSTGRESQL_URL"):
        monkeypatch.delenv(name, raising=False)


def _queue(writer, *, user=USER, catalog=CATALOG):
    creator = DraftCreation("tata", USER, CATALOG, writer, allow_sqlite_for_tests=True)
    return DraftBatchQueue("tata", user, catalog, allow_sqlite_for_tests=True, creator=creator)


def test_mixed_batch_persists_blocked_row_and_confirmed_draft_without_reposting(isolated_batch_db):
    writer = FakeWriter()
    queue = _queue(writer)
    batch = queue.stage([ROW, {**ROW, "row_id": "2", "campaign_name": "Missing audience",
                               "segment_id": "not-in-catalog"}], "rows.json")
    assert (batch["ready"], batch["blocked"]) == (1, 1)
    assert [item["row_id"] for item in batch["items"]] == ["1", "2"]
    assert batch["items"][1]["source_fields"]["campaign_name"] == "Missing audience"
    assert batch["items"][1]["candidate_v5_payload"] is None
    assert batch["items"][1]["updated_at"] == batch["created_at"]

    blocked = queue.create_row(batch["batch_id"], "2")
    assert blocked["items"][1]["status"] == "blocked"
    assert writer.calls == []

    created = queue.create_row(batch["batch_id"], "1")
    assert created["items"][0]["status"] == "VALIDATED"
    assert created["items"][0]["campaign_id"] == "000000000000000000000001"
    assert created["items"][0]["updated_at"] >= batch["created_at"]
    assert created["items"][1]["updated_at"] == batch["created_at"]
    assert queue.create_row(batch["batch_id"], "1")["items"] == created["items"]
    assert [name for name, _ in writer.calls] == ["create", "get", "validate"]
    other_user = {**USER, "sub": "other-operator", "email": "other@example.com"}
    with pytest.raises(BatchAccessDenied):
        _queue(FakeWriter(), user=other_user).get(batch["batch_id"])
    other_catalog = {**CATALOG, "workspace_id": "another-workspace"}
    with pytest.raises(BatchAccessDenied):
        _queue(FakeWriter(), catalog=other_catalog).get(batch["batch_id"])


def test_ambiguous_create_and_duplicate_upload_never_repost(isolated_batch_db):
    writer = FakeWriter(create_error=TimeoutError("provider response lost"))
    queue = _queue(writer)
    first = queue.stage([ROW], "rows.json")
    second = queue.stage([ROW], "rows.json")
    ambiguous = queue.create_row(first["batch_id"], "1")
    assert ambiguous["items"][0]["status"] == "UNCERTAIN"
    assert ambiguous["items"][0]["campaign_id"] is None
    assert queue.create_row(first["batch_id"], "1")["items"] == ambiguous["items"]
    with pytest.raises(ValueError, match="already attempted"):
        queue.create_row(second["batch_id"], "1")
    assert [name for name, _ in writer.calls] == ["create"]


@pytest.mark.parametrize("second_id", ["1", " 1 "])
def test_duplicate_normalized_row_ids_are_blocked_before_claim(isolated_batch_db, second_id):
    writer = FakeWriter()
    queue = _queue(writer)
    batch = queue.stage([ROW, {**ROW, "row_id": second_id}], ROW["source_ref"])
    assert (batch["ready"], batch["blocked"]) == (0, 2)
    assert [item["row_id"] for item in batch["items"]] == ["1", "1"]
    assert all("Duplicate source_ref/row_id in batch" in item["issues"] for item in batch["items"])
    with pytest.raises(ValueError, match="Duplicate row_id"):
        queue.create_row(batch["batch_id"], "1")
    assert writer.calls == []


def test_nonobject_rows_keep_distinct_positions_and_do_not_block_valid_sibling(isolated_batch_db):
    writer = FakeWriter()
    queue = _queue(writer)
    batch = queue.stage([None, ["not", "an", "object"], ROW], ROW["source_ref"])
    assert (batch["ready"], batch["blocked"]) == (1, 2)
    assert [item["row_id"] for item in batch["items"]] == ["row:1", "row:2", "1"]
    assert [item["channel"] for item in batch["items"]] == ["", "", "EMAIL"]
    assert all(item["issues"] == ["Row must be an object"] for item in batch["items"][:2])
    assert queue.create_row(batch["batch_id"], "row:2")["blocked"] == 2
    created = queue.create_row(batch["batch_id"], "1")
    assert created["items"][2]["status"] == "VALIDATED"
    assert [name for name, _ in writer.calls] == ["create", "get", "validate"]


@pytest.mark.parametrize("field,value", [("row_id", []), ("row_id", {}), ("source_ref", [])])
def test_unhashable_identity_fields_produce_blocked_preview(field, value):
    preview = prepare_routed_batch([{**ROW, field: value}], "tata", USER, CATALOG, source_type="spreadsheet")
    assert (preview["ready"], preview["blocked"]) == (0, 1)
    assert "source_ref and row_id are required" in preview["items"][0]["issues"]
    assert preview["items"][0]["candidate_v5_payload"] is None


@pytest.mark.parametrize("changes", [{"sub": "another-sub"}, {"email": "another@example.com"}])
def test_batch_owner_requires_both_subject_and_email(isolated_batch_db, changes):
    owner = _queue(FakeWriter())
    batch = owner.stage([ROW], ROW["source_ref"])
    intruder = _queue(FakeWriter(), user={**USER, **changes})
    for operation in (lambda: intruder.get(batch["batch_id"]),
                      lambda: intruder.create_row(batch["batch_id"], "1"),
                      lambda: intruder.archive(batch["batch_id"]),
                      lambda: intruder.reconcile_row(batch["batch_id"], "1")):
        with pytest.raises(BatchAccessDenied):
            operation()
    assert owner.get(batch["batch_id"])["items"][0]["status"] == "preview_ready"


def test_superadmin_cannot_cross_batch_account_ownership(isolated_batch_db):
    owner = _queue(FakeWriter())
    batch = owner.stage([ROW], ROW["source_ref"])
    superadmin = {**USER, "tenant_id": "all", "role": "superadmin"}
    catalog = {**CATALOG, "account": "bajaj"}
    intruder = DraftBatchQueue("bajaj", superadmin, catalog, allow_sqlite_for_tests=True)
    with pytest.raises(BatchAccessDenied):
        intruder.get(batch["batch_id"])
    with pytest.raises(BatchAccessDenied):
        intruder.create_row(batch["batch_id"], "1")
    with pytest.raises(BatchAccessDenied):
        intruder.archive(batch["batch_id"])


@pytest.mark.parametrize("invalid", [{**ROW, "source_ref": "another.csv"},
                                   {**ROW, "row_id": "invalid", "value": float("nan")}])
def test_invalid_batch_input_is_rejected_before_any_persistence(isolated_batch_db, invalid):
    queue = _queue(FakeWriter())
    with pytest.raises(ValueError):
        queue.stage([ROW, invalid], ROW["source_ref"])
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM moengage_draft_batches").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM moengage_draft_batch_rows").fetchone()["n"] == 0


class _PausedWriter(FakeWriter):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def create(self, payload, *, idempotency_key):
        self.entered.set()
        if not self.release.wait(5):
            raise TimeoutError("Test did not release the provider create")
        return super().create(payload, idempotency_key=idempotency_key)


def test_concurrent_clicks_make_one_provider_post(isolated_batch_db):
    writer = _PausedWriter()
    queue = _queue(writer)
    batch = queue.stage([ROW], ROW["source_ref"])
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(queue.create_row, batch["batch_id"], "1")
        try:
            assert writer.entered.wait(5)
            repeated = queue.create_row(batch["batch_id"], "1")
            assert repeated["items"][0]["status"] == "UNCERTAIN"
        finally:
            writer.release.set()
        assert first.result(timeout=5)["items"][0]["status"] == "VALIDATED"
    assert [name for name, _ in writer.calls].count("create") == 1


def test_concurrent_batches_cannot_claim_same_source_identity(isolated_batch_db):
    writer = _PausedWriter()
    queue = _queue(writer)
    first = queue.stage([ROW], ROW["source_ref"])
    second = queue.stage([ROW], ROW["source_ref"])
    with ThreadPoolExecutor(max_workers=1) as pool:
        active = pool.submit(queue.create_row, first["batch_id"], "1")
        try:
            assert writer.entered.wait(5)
            with pytest.raises(ValueError, match="already attempted"):
                queue.create_row(second["batch_id"], "1")
            assert queue.get(second["batch_id"])["items"][0]["status"] == "preview_ready"
        finally:
            writer.release.set()
        assert active.result(timeout=5)["items"][0]["status"] == "VALIDATED"
    assert [name for name, _ in writer.calls].count("create") == 1


@pytest.mark.parametrize("error", [RateLimitError("local cap"), DraftPreflightError("row not approved")])
def test_known_prepost_errors_release_claim_without_losing_preview(isolated_batch_db, monkeypatch, error):
    writer = FakeWriter()
    queue = _queue(writer)
    batch = queue.stage([ROW], ROW["source_ref"])
    real_create = queue.creator.create
    monkeypatch.setattr(queue.creator, "create", lambda row: (_ for _ in ()).throw(error))
    with pytest.raises(type(error)):
        queue.create_row(batch["batch_id"], "1")
    restored = queue.get(batch["batch_id"])["items"][0]
    assert restored["status"] == "preview_ready"
    assert restored["issue"] is None
    assert restored["candidate_v5_payload"] == batch["items"][0]["candidate_v5_payload"]
    assert writer.calls == []
    monkeypatch.setattr(queue.creator, "create", real_create)
    assert queue.create_row(batch["batch_id"], "1")["items"][0]["status"] == "VALIDATED"


def test_preflight_blocked_result_does_not_consume_source_claim(isolated_batch_db):
    writer = FakeWriter()
    queue = _queue(writer)
    first = queue.stage([ROW], ROW["source_ref"])
    queue.creator.catalog = {**CATALOG, "segments": []}
    rejected = queue.create_row(first["batch_id"], "1")
    assert rejected["items"][0]["status"] == "blocked"
    assert rejected["items"][0]["candidate_v5_payload"] is None
    assert rejected["items"][0]["issues"]
    assert writer.calls == []
    queue.creator.catalog = CATALOG
    second = queue.stage([ROW], ROW["source_ref"])
    assert queue.create_row(second["batch_id"], "1")["items"][0]["status"] == "VALIDATED"


@pytest.mark.parametrize("error", [PermissionError("not necessarily preflight"), RuntimeError("unknown failure")])
def test_arbitrary_creator_exception_keeps_irrecoverable_claim(isolated_batch_db, monkeypatch, error):
    queue = _queue(FakeWriter())
    first = queue.stage([ROW], ROW["source_ref"])
    second = queue.stage([ROW], ROW["source_ref"])
    calls = []

    def fail(row):
        calls.append(copy.deepcopy(row))
        raise error

    monkeypatch.setattr(queue.creator, "create", fail)
    assert queue.create_row(first["batch_id"], "1")["items"][0]["status"] == "UNCERTAIN"
    assert queue.create_row(first["batch_id"], "1")["items"][0]["status"] == "UNCERTAIN"
    with pytest.raises(ValueError, match="already attempted"):
        queue.create_row(second["batch_id"], "1")
    assert len(calls) == 1


def test_lazy_writer_credential_failure_does_not_consume_claim(isolated_batch_db, monkeypatch):
    queue = _queue(FakeWriter())
    queue.creator.writer = None
    monkeypatch.delenv("MOENGAGE_DRAFT_TATA_LIVE_ENABLED", raising=False)
    batch = queue.stage([ROW], ROW["source_ref"])
    with pytest.raises(DraftPreflightError, match="owner approval"):
        queue.create_row(batch["batch_id"], "1")
    assert queue.get(batch["batch_id"])["items"][0]["status"] == "preview_ready"
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM moengage_draft_attempts").fetchone()["n"] == 0


def test_approved_source_policy_rejection_does_not_consume_claim(isolated_batch_db):
    writer = FakeWriter()
    queue = _queue(writer)
    queue.creator.approved_live_rows = {("approved.csv", "approved"): ("EMAIL", "seg-vip")}
    batch = queue.stage([ROW], ROW["source_ref"])
    with pytest.raises(DraftPreflightError, match="not approved"):
        queue.create_row(batch["batch_id"], "1")
    assert queue.get(batch["batch_id"])["items"][0]["status"] == "preview_ready"
    assert writer.calls == []
    queue.creator.approved_live_rows = None
    assert queue.create_row(batch["batch_id"], "1")["items"][0]["status"] == "VALIDATED"


def test_invalid_synthetic_row_identity_cannot_shadow_real_source_row(isolated_batch_db):
    writer = FakeWriter()
    queue = _queue(writer)
    brief = {**ROW, "row_id": "row:1"}
    batch = queue.stage([None, brief], brief["source_ref"])
    assert [(item["source_ref"], item["row_id"]) for item in batch["items"]] == [
        ("", "row:1"), (brief["source_ref"], "row:1")]
    result = queue.create_row(batch["batch_id"], brief["row_id"])
    assert result["items"][0]["status"] == "blocked"
    assert result["items"][1]["status"] == "VALIDATED"
    assert [name for name, _ in writer.calls].count("create") == 1


@pytest.mark.parametrize("attempted", [False, True])
def test_legacy_preflight_rejection_migration_never_unlocks_a_provider_attempt(isolated_batch_db, attempted):
    writer = FakeWriter(create_error=TimeoutError("lost acknowledgement")) if attempted else FakeWriter()
    queue = _queue(writer)
    legacy = queue.stage([ROW], ROW["source_ref"])
    if attempted:
        assert queue.create_row(legacy["batch_id"], ROW["row_id"])["items"][0]["status"] == "UNCERTAIN"
    with db.get_db() as conn:
        conn.execute("UPDATE moengage_draft_batch_rows SET status='BLOCKED' WHERE batch_id=?",
                     (legacy["batch_id"],))
    db.init_database(force=True)
    stored = queue.get(legacy["batch_id"])["items"][0]
    replacement = queue.stage([ROW], ROW["source_ref"])
    if attempted:
        assert stored["status"] == "BLOCKED"
        with pytest.raises(ValueError, match="already attempted"):
            queue.create_row(replacement["batch_id"], ROW["row_id"])
    else:
        assert stored["status"] == "blocked"
        assert stored["candidate_v5_payload"] is None
        assert queue.create_row(replacement["batch_id"], ROW["row_id"])["items"][0]["status"] == "VALIDATED"
    assert [name for name, _ in writer.calls].count("create") == 1


def test_archive_is_durable_idempotent_and_preserves_audit_and_source_claims(isolated_batch_db):
    writer = FakeWriter()
    queue = _queue(writer)
    batch_id = queue.stage([ROW], ROW["source_ref"])["batch_id"]
    assert queue.create_row(batch_id, ROW["row_id"])["items"][0]["status"] == "VALIDATED"
    with db.get_db() as conn:
        original_batch = dict(conn.execute("SELECT * FROM moengage_draft_batches").fetchone())
        audit = [dict(row) for row in conn.execute("SELECT * FROM moengage_draft_batch_rows").fetchall()]
        attempts = [dict(row) for row in conn.execute("SELECT * FROM moengage_draft_attempts").fetchall()]
    calls = list(writer.calls)
    expected = {"ok": True, "batch_id": batch_id, "archived": True}
    assert queue.archive(batch_id) == expected
    with db.get_db() as conn:
        archived = dict(conn.execute("SELECT * FROM moengage_draft_batches").fetchone())
        assert archived["archived_at"] >= original_batch["created_at"]
        assert archived == {**original_batch, "archived_at": archived["archived_at"]}
        assert [dict(row) for row in conn.execute("SELECT * FROM moengage_draft_batch_rows").fetchall()] == audit
        assert [dict(row) for row in conn.execute("SELECT * FROM moengage_draft_attempts").fetchall()] == attempts
    restarted = _queue(writer)
    assert restarted.archive(batch_id) == expected
    with db.get_db() as conn:
        assert conn.execute("SELECT archived_at FROM moengage_draft_batches").fetchone()["archived_at"] == archived["archived_at"]
    for operation in (lambda: restarted.get(batch_id),
                      lambda: restarted.create_row(batch_id, ROW["row_id"])):
        with pytest.raises(LookupError, match="not found"):
            operation()
    duplicate = restarted.stage([ROW], ROW["source_ref"])
    with pytest.raises(ValueError, match="already attempted"):
        restarted.create_row(duplicate["batch_id"], ROW["row_id"])
    assert queue.creator.create(ROW)["state"] == "VALIDATED"
    assert writer.calls == calls


def test_archiving_unattempted_rows_does_not_allow_source_recreation(isolated_batch_db):
    writer = FakeWriter()
    queue = _queue(writer)
    batch_id = queue.stage([ROW], ROW["source_ref"])["batch_id"]
    wrong_workspace = _queue(writer, catalog={**CATALOG, "workspace_id": "another-workspace"})
    with pytest.raises(BatchAccessDenied):
        wrong_workspace.archive(batch_id)
    assert queue.archive(batch_id)["archived"] is True
    duplicate = queue.stage([ROW], ROW["source_ref"])
    with pytest.raises(ValueError, match="archived"):
        queue.create_row(duplicate["batch_id"], ROW["row_id"])
    with pytest.raises(LookupError, match="not found"):
        queue.archive("missing-batch")
    assert writer.calls == []
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM moengage_draft_attempts").fetchone()["n"] == 0


@pytest.mark.parametrize("status", ["UNCERTAIN", "MAYBE_SENT", "CREATED", "NEEDS_REVIEW", "BLOCKED", "unknown"])
def test_archive_rejects_unconfirmed_row_states_without_changing_them(isolated_batch_db, status):
    queue = _queue(FakeWriter())
    batch_id = queue.stage([ROW], ROW["source_ref"])["batch_id"]
    with db.get_db() as conn:
        conn.execute("UPDATE moengage_draft_batch_rows SET status=? WHERE batch_id=?", (status, batch_id))
    with pytest.raises(ValueError, match="ongoing or unconfirmed"):
        queue.archive(batch_id)
    assert queue.get(batch_id)["items"][0]["status"] == status
    with db.get_db() as conn:
        assert conn.execute("SELECT archived_at FROM moengage_draft_batches").fetchone()["archived_at"] is None


def test_archive_checks_ledger_even_when_batch_row_looks_ready(isolated_batch_db):
    writer = FakeWriter(create_error=TimeoutError("provider acknowledgement lost"))
    queue = _queue(writer)
    batch_id = queue.stage([ROW], ROW["source_ref"])["batch_id"]
    assert queue.creator.create(ROW)["state"] == "UNCERTAIN"
    with pytest.raises(ValueError, match="ongoing or unconfirmed"):
        queue.archive(batch_id)
    assert queue.get(batch_id)["items"][0]["status"] == "preview_ready"
    assert [name for name, _ in writer.calls] == ["create"]


def test_archive_rejects_active_create_and_its_duplicate_upload(isolated_batch_db):
    writer = _PausedWriter()
    queue = _queue(writer)
    batch_id = queue.stage([ROW], ROW["source_ref"])["batch_id"]
    duplicate_id = queue.stage([ROW], ROW["source_ref"])["batch_id"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        active = pool.submit(queue.create_row, batch_id, ROW["row_id"])
        try:
            assert writer.entered.wait(5)
            for target in (batch_id, duplicate_id):
                with pytest.raises(ValueError, match="ongoing or unconfirmed"):
                    queue.archive(target)
                queue.get(target)
        finally:
            writer.release.set()
        assert active.result(timeout=5)["items"][0]["status"] == "VALIDATED"
    assert queue.archive(batch_id)["archived"] is True
    assert [name for name, _ in writer.calls].count("create") == 1


def test_create_rechecks_archive_under_the_shared_lock(isolated_batch_db, monkeypatch):
    writer = FakeWriter()
    queue = _queue(writer)
    batch_id = queue.stage([ROW], ROW["source_ref"])["batch_id"]
    entered, release = threading.Event(), threading.Event()
    lock_batch = queue._lock_batch

    def pause_create_lock(conn, selected_batch):
        if threading.current_thread() is not threading.main_thread():
            entered.set()
            assert release.wait(5)
        lock_batch(conn, selected_batch)

    monkeypatch.setattr(queue, "_lock_batch", pause_create_lock)
    with ThreadPoolExecutor(max_workers=1) as pool:
        active = pool.submit(queue.create_row, batch_id, ROW["row_id"])
        try:
            assert entered.wait(5)
            assert queue.archive(batch_id)["archived"] is True
        finally:
            release.set()
        with pytest.raises(LookupError, match="not found"):
            active.result(timeout=5)
    assert writer.calls == []
