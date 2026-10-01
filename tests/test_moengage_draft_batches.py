"""Account-owned batch lifecycle, independent rows, and no duplicate remote create."""

import pytest

import db
from moengage_draft_batches import BatchAccessDenied, DraftBatchQueue
from moengage_draft_creation import DraftCreation
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
