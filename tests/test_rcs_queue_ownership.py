"""Private SQLite + local HTTP provider regressions for durable queue ownership."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest
import requests

import api
import db
import db_queue
import rcs_client
import rcs_config
from queue_manager import QueueManager
from rcs_models import RcsSubmissionResult, RcsTemplateSubmission
from rcs_runner import rcs_submission_payload, run_rcs
from rcs_tracker import log_rcs_result, update_rcs_results


@pytest.fixture(autouse=True)
def private_queue_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_SQLITE_PATH", tmp_path / "queue.sqlite")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "queue.sqlite")
    monkeypatch.setattr(db, "get_database_url", lambda: "")
    for key in ("DATABASE_URL", "POSTGRES_URL", "POSTGRESQL_URL"):
        monkeypatch.setenv(key, "")
    monkeypatch.setattr(rcs_config, "_load_env_file", lambda: None)
    for tenant in ("TATA", "BAJAJ"):
        monkeypatch.setenv(f"{tenant}_RCS_AUTH_TOKEN", "local-provider-test-token")
        monkeypatch.setenv(f"{tenant}_RCS_ESMEADDR", "72434700000000")
        monkeypatch.setenv(f"{tenant}_RCS_BOT_ID", f"local-{tenant.lower()}-bot")
    original_request = requests.sessions.Session.request

    def local_only(session, method, url, *args, **kwargs):
        assert urlparse(url).hostname in ("127.0.0.1", "localhost"), f"Remote network forbidden: {url}"
        return original_request(session, method, url, *args, **kwargs)

    monkeypatch.setattr(requests.sessions.Session, "request", local_only)
    db.init_database()


@pytest.fixture
def provider(monkeypatch):
    state = {"saves": [], "inventory": [], "entered": threading.Event(), "release": threading.Event(),
             "hold": False, "auth_once": False, "fail": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/inventory":
                code, body = 200, {"templateInfo": state["inventory"]}
            else:
                state["saves"].append(payload)
                state["entered"].set()
                if state["hold"]:
                    assert state["release"].wait(5), "Test did not release the local provider"
                if state["auth_once"]:
                    state["auth_once"] = False
                    code, body = 401, {"error": "Local credentials expired"}
                elif state["fail"]:
                    code, body = 500, {"error": "Local provider outcome unavailable"}
                else:
                    code, body = 200, {"status": "success", "templateId": f"local-provider-{len(state['saves'])}"}
            encoded = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(rcs_client, "KARIX_RCS_SAVE_URL", f"{base}/save")
    monkeypatch.setattr(rcs_client, "KARIX_RCS_FETCH_TEMPLATES_URL", f"{base}/inventory")
    try:
        yield state
    finally:
        state["release"].set()
        server.shutdown()
        server.server_close()
        thread.join()


def submission(name="owned_row", **changes):
    return RcsTemplateSubmission(template_name=name, source_ref=f"source-{name}", client="tata",
                                 bot_id="local-tata-bot", esme_addr="72434700000000",
                                 template_type="text", text_message="Original row content", **changes)


def stage(*rows):
    job = db_queue.create_job_with_tasks("tata", "rcs", "private.csv", "Tester",
                                         [rcs_submission_payload(row) for row in rows])
    return job, [row["id"] for row in db_queue.get_job_tasks(job["id"])]


@pytest.mark.parametrize("owner", ["queue", "inline"])
def test_overlapping_consumers_save_once_and_preserve_pending_approval(provider, owner):
    row = submission()
    job, ids = stage(row)
    provider["hold"] = True

    async def run():
        manager = QueueManager()
        if owner == "queue":
            first = manager.start_job_execution(job["id"], "tata", "rcs")
        else:
            first = asyncio.create_task(asyncio.to_thread(run_rcs, [row], client="tata", task_ids=ids))
        assert await asyncio.to_thread(provider["entered"].wait, 3)
        second = QueueManager().start_job_execution(job["id"], "tata", "rcs")
        await asyncio.wait_for(second, 3)
        other_inline = await asyncio.to_thread(run_rcs, [row], client="tata", task_ids=ids)
        assert other_inline[0]["status"] == "processing"
        provider["release"].set()
        await asyncio.wait_for(first, 3)

    asyncio.run(run())
    assert len(provider["saves"]) == 1
    assert provider["saves"][0]["viTemplate"]["textMessage"] == row.text_message
    task = db_queue.get_job_task(ids[0])
    assert (task["status"], task["approval_status"], task["provider_ref_id"]) == (
        "SUBMITTED", "pending", "local-provider-1")
    settled = db_queue.get_job(job["id"])
    assert (settled["status"], settled["submitted_count"], settled["duplicate_count"], settled["failed_count"]) == (
        "COMPLETED", 1, 0, 0)


def test_job_and_payload_mismatches_never_dispatch(provider):
    job, ids = stage(submission())
    with pytest.raises(ValueError, match="tenant/channel"):
        asyncio.run(QueueManager()._process_job_tasks(job["id"], "bajaj", "rcs"))
    with pytest.raises(ValueError, match="tenant/channel"):
        asyncio.run(QueueManager()._process_job_tasks(job["id"], "tata", "whatsapp"))
    with db.get_db() as conn:
        payload = json.loads(db_queue.get_job_task(ids[0])["payload_json"])
        payload["client"] = "bajaj"
        conn.execute("UPDATE job_tasks SET payload_json = ? WHERE id = ?", (json.dumps(payload), ids[0]))
    asyncio.run(QueueManager()._process_job_tasks(job["id"], "tata", "rcs"))
    assert provider["saves"] == []
    assert db_queue.get_job_task(ids[0])["status"] == "FAILED"
    assert db_queue.get_job(job["id"])["failed_count"] == 1


def test_auth_resume_retries_exact_refused_row_then_next_row(provider):
    job, ids = stage(submission("first"), submission("second"))
    provider["auth_once"] = True

    async def run():
        manager = QueueManager()
        events = manager.subscribe_job(job["id"])
        worker = manager.start_job_execution(job["id"], "tata", "rcs")
        while "event: auth_paused" not in await asyncio.wait_for(events.get(), 3):
            pass
        assert db_queue.get_job(job["id"])["status"] == "PAUSED_FOR_AUTH"
        assert [db_queue.get_job_task(task_id)["status"] for task_id in ids] == ["PENDING", "PENDING"]
        assert manager.notify_credentials_updated("tata") == 1
        await asyncio.wait_for(worker, 3)
        await asyncio.sleep(0)
        if manager._active_worker_tasks:
            await asyncio.wait_for(asyncio.gather(*manager._active_worker_tasks), 3)
        manager.unsubscribe_job(job["id"], events)

    asyncio.run(run())
    names = [payload["viTemplate"]["name"] for payload in provider["saves"]]
    assert names[0] == "first"
    assert sorted(names[1:]) == ["first", "second"]
    assert db_queue.get_job(job["id"])["submitted_count"] == 2
    assert db_queue.get_job(job["id"])["failed_count"] == 0


def test_unexpected_exceptions_settle_rows_and_counters(monkeypatch):
    job, ids = stage(submission("first"), submission("second"))
    manager = QueueManager()

    async def broken(*args):
        raise RuntimeError("Local operation raised unexpectedly")

    monkeypatch.setattr(manager, "_execute_task_submission", broken)
    asyncio.run(manager._process_job_tasks(job["id"], "tata", "rcs"))
    assert [(db_queue.get_job_task(task_id)["status"], db_queue.get_job_task(task_id)["approval_status"])
            for task_id in ids] == [("FAILED", "unknown"), ("FAILED", "unknown")]
    assert db_queue.get_job(job["id"])["status"] == "FAILED"
    assert db_queue.get_job(job["id"])["failed_count"] == 2


def test_ambiguous_provider_failure_is_not_replayed(provider):
    job, ids = stage(submission())
    provider["fail"] = True
    asyncio.run(QueueManager()._process_job_tasks(job["id"], "tata", "rcs"))
    asyncio.run(QueueManager()._process_job_tasks(job["id"], "tata", "rcs"))
    assert len(provider["saves"]) == 1
    assert json.loads(db_queue.get_job_task(ids[0])["payload_json"])["outcome_uncertain"] is True
    assert db_queue.get_job(job["id"])["failed_count"] == 1


def test_cancellation_waits_for_provider_and_never_fails_another_claim(provider):
    job, ids = stage(submission())
    provider["hold"] = True

    async def run():
        owner = QueueManager().start_job_execution(job["id"], "tata", "rcs")
        assert await asyncio.to_thread(provider["entered"].wait, 3)
        duplicate = QueueManager().start_job_execution(job["id"], "tata", "rcs")
        duplicate.cancel()
        with pytest.raises(asyncio.CancelledError):
            await duplicate
        assert db_queue.get_job_task(ids[0])["status"] == "PROCESSING"
        owner.cancel()
        await asyncio.sleep(0)
        assert not owner.done()
        owner.cancel()
        await asyncio.sleep(0)
        assert db_queue.get_job_task(ids[0])["status"] == "PROCESSING"
        provider["release"].set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(owner, 3)

    asyncio.run(run())
    assert len(provider["saves"]) == 1
    assert db_queue.get_job_task(ids[0])["status"] == "SUBMITTED"
    assert db_queue.get_job(job["id"])["submitted_count"] == 1
    assert db_queue.get_job(job["id"])["failed_count"] == 0


def test_terminal_streams_close_and_slow_consumers_are_bounded():
    completed = db_queue.create_job_with_tasks("tata", "rcs", "duplicates.csv", "Tester",
        [{"template_name": "same", "status": "DUPLICATE", "approval_status": "pending"}])
    active, _ = stage(submission())

    async def run():
        manager = QueueManager()
        stream = manager.sse_event_stream(completed["id"])
        assert "COMPLETED" in await anext(stream)
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), 1)
        assert completed["id"] not in manager._sse_listeners
        queue = manager.subscribe_job(active["id"])
        for index in range(300):
            manager.broadcast_event(active["id"], "task_update", {"index": index})
        assert queue.qsize() == queue.maxsize == 128
        stream = manager.sse_event_stream(active["id"])
        await anext(stream)
        manager.broadcast_event(active["id"], "job_status", {"status": "FAILED"})
        assert "FAILED" in await asyncio.wait_for(anext(stream), 1)
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), 1)
        manager.unsubscribe_job(active["id"], queue)
        assert not manager._sse_listeners

    asyncio.run(run())
    assert completed["status"] == "COMPLETED"
    assert completed["duplicate_count"] == completed["total_count"] == 1


def test_tracker_refuses_wrong_owner_and_whatsapp_updater_never_touches_rcs():
    job, ids = stage(submission())
    wrong = RcsSubmissionResult("wrong-source", "owned_row", client="tata", bot_id="local-tata-bot")
    with pytest.raises(ValueError, match="owning task row"):
        log_rcs_result(wrong, task_id=ids[0])
    with pytest.raises(ValueError, match="tenant/channel"):
        log_rcs_result(RcsSubmissionResult("source-owned_row", "owned_row", client="bajaj"), task_id=ids[0])
    db_queue.record_task_result(ids[0], "submitted", "pending", "local-owned-id")
    wa = db_queue.create_job_with_tasks("tata", "whatsapp", "wa.csv", "Tester",
        [{"template_name": "owned_row", "status": "SUBMITTED", "approval_status": "pending"}])
    assert db_queue.update_template_approval_monotonic("tata", "owned_row", "approved") == 1
    assert db_queue.get_job_task(ids[0])["approval_status"] == "pending"
    assert db_queue.get_job_tasks(wa["id"])[0]["approval_status"] == "approved"
    assert update_rcs_results({ids[0]: {"approval_status": "approved"}}, client="bajaj") == 0
    assert update_rcs_results({ids[0]: {"approval_status": "approved"}}, client="tata") == 1
    assert update_rcs_results({ids[0]: {"approval_status": "pending"}}, client="tata") == 0
    with pytest.raises(ValueError, match="approval metadata"):
        update_rcs_results({ids[0]: {"client": "bajaj"}}, client="tata")


def test_polling_reads_only_selected_tenant_and_channel(provider):
    import api

    jobs = {}
    for tenant, channel in (("tata", "rcs"), ("bajaj", "rcs"), ("tata", "whatsapp")):
        jobs[(tenant, channel)] = db_queue.create_job_with_tasks(tenant, channel, "poll.csv", "Tester", [{
            "template_name": "shared_name", "source_ref": "shared_source", "status": "SUBMITTED",
            "approval_status": "pending", "provider_ref_id": "shared-provider-id",
            "client": tenant, "channel": channel, "bot_id": f"local-{tenant}-bot"}])
    provider["inventory"] = [{"templateId": "shared-provider-id", "status": "APPROVED",
                               "botId": "local-tata-bot", "viTemplate": {"name": "shared_name", "type": "text"}}]
    result = api.poll(account="tata", channel="rcs", user="Tester",
                      current_user={"tenant_id": "tata", "role": "operator"})
    assert result == {"checked": 1, "updated": 1}
    assert db_queue.get_job_tasks(jobs[("tata", "rcs")]["id"])[0]["approval_status"] == "approved"
    assert db_queue.get_job_tasks(jobs[("bajaj", "rcs")]["id"])[0]["approval_status"] == "pending"
    assert db_queue.get_job_tasks(jobs[("tata", "whatsapp")]["id"])[0]["approval_status"] == "pending"


def test_failed_inventory_blocks_batch_without_creating_or_dispatching(monkeypatch, tmp_path):
    import api
    from fastapi import HTTPException

    source = tmp_path / "input.csv"
    source.write_text("template_name,template_type,text_message\nrow,text,Original content\n")

    def unavailable(*args, **kwargs):
        raise rcs_client.RcsInventoryUnavailable("local catalog fetch failed")

    monkeypatch.setattr(api, "fetch_rcs_templates", unavailable)
    with pytest.raises(HTTPException) as error:
        asyncio.run(api._submit_rcs_batch(str(source), ".csv", "tata", "Tester", True,
                    source.name, {"tenant_id": "tata", "role": "operator"}))
    assert error.value.status_code == 503
    with db.get_db() as conn:
        assert conn.execute("SELECT count(*) AS c FROM ingestion_jobs").fetchone()["c"] == 0


def test_inventory_singleflight_is_scoped_and_never_retains_success_or_failure(monkeypatch):
    import api
    from concurrent.futures import Future, ThreadPoolExecutor
    from fastapi import HTTPException

    follower = threading.Event()
    calls = []
    fail = False

    class ObservedFuture(Future):
        def result(self, *args, **kwargs):
            follower.set()
            return super().result(*args, **kwargs)

    def fetch(*, client):
        calls.append(client)
        assert follower.wait(3), "Concurrent request did not join its exact account/bot flight"
        if fail:
            raise rcs_client.RcsInventoryUnavailable("Local provider outage")
        return []

    monkeypatch.setattr(api, "Future", ObservedFuture)
    monkeypatch.setattr(api, "fetch_rcs_templates", fetch)
    with ThreadPoolExecutor(max_workers=2) as workers:
        pair = [workers.submit(api._fetch_rcs_inventory, "tata") for _ in range(2)]
        assert [work.result() for work in pair] == [[], []]
    assert calls == ["tata"]
    assert not api._rcs_inventory_inflight
    fail = True
    # There is deliberately no success cache, so a subsequent outage is visible.
    with pytest.raises(HTTPException) as outage:
        api._fetch_rcs_inventory("tata")
    assert outage.value.status_code == 503
    assert calls == ["tata", "tata"]
    assert not api._rcs_inventory_inflight
    fail = False
    assert api._fetch_rcs_inventory("tata") == []
    assert calls == ["tata", "tata", "tata"]

    independent = threading.Barrier(2)
    calls.clear()

    def independent_fetch(*, client):
        calls.append(client)
        independent.wait(timeout=3)
        return []

    monkeypatch.setattr(api, "fetch_rcs_templates", independent_fetch)
    with ThreadPoolExecutor(max_workers=2) as workers:
        pair = [workers.submit(api._fetch_rcs_inventory, tenant) for tenant in ("tata", "bajaj")]
        assert [work.result() for work in pair] == [[], []]
    assert sorted(calls) == ["bajaj", "tata"]


@pytest.mark.parametrize("runner", ["queue", "inline"])
@pytest.mark.parametrize("payload_json", ["not-json", "[]"])
def test_malformed_claimed_payload_settles_without_dispatch(monkeypatch, runner, payload_json):
    import rcs_runner

    row = submission()
    job, ids = stage(row)
    with db.get_db() as conn:
        conn.execute("UPDATE job_tasks SET payload_json = ? WHERE id = ?", (payload_json, ids[0]))
    calls = []

    def should_not_dispatch(*args, **kwargs):
        calls.append(args)
        raise AssertionError("Malformed persisted input must not reach a provider")

    monkeypatch.setattr(rcs_client, "submit_rcs_template", should_not_dispatch)
    monkeypatch.setattr(rcs_runner, "submit_rcs_template", should_not_dispatch)
    if runner == "queue":
        asyncio.run(QueueManager()._process_job_tasks(job["id"], "tata", "rcs"))
    else:
        assert run_rcs([row], client="tata", task_ids=ids)[0]["status"] == "failed"
    assert calls == []
    assert db_queue.get_job_task(ids[0])["status"] == "FAILED"
    assert db_queue.get_job(job["id"])["failed_count"] == 1


def test_inline_auth_pause_is_resumed_from_the_same_durable_tasks(provider):
    rows = [submission("first"), submission("second")]
    job, ids = stage(*rows)
    provider["auth_once"] = True

    async def run():
        manager = QueueManager()
        manager.bind_event_loop()
        entries = await asyncio.to_thread(run_rcs, rows, client="tata", task_ids=ids)
        assert [entry["task_id"] for entry in entries] == ids
        assert [entry["status"] for entry in entries] == ["pending", "pending"]
        assert db_queue.get_job(job["id"])["status"] == "PAUSED_FOR_AUTH"
        assert manager.notify_credentials_updated("tata") == 1
        await asyncio.sleep(0)
        await asyncio.wait_for(asyncio.gather(*manager._active_worker_tasks), 3)

    asyncio.run(run())
    assert [payload["viTemplate"]["name"] for payload in provider["saves"]] == ["first", "first", "second"]
    assert db_queue.get_job(job["id"])["submitted_count"] == 2
    assert db_queue.get_job(job["id"])["failed_count"] == 0


def test_persisted_embedded_media_round_trips_without_invented_provider_names(provision_user):
    from fastapi.testclient import TestClient
    from rcs_runner import rcs_submission_from_payload
    from rcs_tracker import _row_to_entry_dict

    row = submission(image_bytes=b"local-source-bytes", image_filename="source.png",
                     carousel_cards=[{"card_title": "Card", "image_bytes": b"other-source-bytes",
                                      "image_filename": "card.png"}])
    _, headers = provision_user("tata")
    job, ids = stage(row)
    stored = db_queue.get_job_task(ids[0])
    restored = rcs_submission_from_payload(json.loads(stored["payload_json"]))
    assert restored.image_bytes == row.image_bytes
    assert restored.image_filename == "source.png"
    assert restored.file_name is None
    assert restored.carousel_cards[0]["image_bytes"] == b"other-source-bytes"
    assert restored.carousel_cards[0]["image_filename"] == "card.png"
    assert "fileName" not in restored.carousel_cards[0]
    public_result = _row_to_entry_dict(stored)
    assert "image_bytes_base64" not in public_result
    assert "image_bytes_base64" not in public_result["carousel_cards"][0]
    response = TestClient(api.app, headers=headers).get(f"/api/jobs/{job['id']}")
    assert response.status_code == 200
    assert response.json()["tasks"][0]["id"] == ids[0]
    assert "payload_json" not in response.json()["tasks"][0]
    assert json.loads(db_queue.get_job_task(ids[0])["payload_json"])["image_bytes_base64"]


def test_interrupting_duplicate_consumer_preserves_another_workers_remaining_rows():
    job, ids = stage(submission("first"), submission("second"))
    assert db_queue.claim_task(ids[0], "tata", "rcs")
    db_queue.fail_unfinished_job(job["id"], "Duplicate consumer cancelled")
    assert [db_queue.get_job_task(task_id)["status"] for task_id in ids] == ["PROCESSING", "PENDING"]
    assert db_queue.get_job(job["id"])["failed_count"] == 0
    assert db_queue.get_job(job["id"])["error_message"] is None
    db_queue.record_task_result(ids[0], "submitted", "pending", "local-first")
    db_queue.fail_unfinished_job(job["id"], "Owning worker stopped before the next dispatch")
    assert db_queue.get_job_task(ids[1])["status"] == "FAILED"
    assert db_queue.get_job(job["id"])["status"] == "PARTIALLY_COMPLETED"
    assert db_queue.get_job(job["id"])["failed_count"] == 1


def test_concurrent_legacy_import_is_account_owned_and_never_replays_unknown_rows(tmp_path, monkeypatch, caplog):
    from concurrent.futures import ThreadPoolExecutor

    source = tmp_path / "legacy.jsonl"
    entries = [
        {"client": "tata", "template_name": "tata_one", "status": "submitted", "provider_ref_id": "original-tata"},
        {"client": "bajaj", "template_name": "bajaj_one", "status": "duplicate", "provider_ref_id": "original-bajaj"},
        {"template_name": "no_account", "status": "submitted"},
        {"client": "tata", "channel": "whatsapp", "template_name": "wrong_channel", "status": "submitted"},
        {"client": "tata", "template_name": "unknown_attempt", "status": "pending"},
    ]
    source.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
    monkeypatch.setattr(db_queue, "SUBMISSION_LOG_PATH", tmp_path / "no-wa-history.jsonl")
    monkeypatch.setattr(db_queue, "RCS_SUBMISSION_LOG_PATH", source)
    unrelated, _ = stage(submission("new_queue_row"))
    before = db_queue.get_job_tasks(unrelated["id"])
    barrier = threading.Barrier(2)

    def import_history():
        barrier.wait(timeout=3)
        db_queue.migrate_legacy_jsonl_if_needed()

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(import_history) for _ in range(2)]
        for future in futures:
            future.result()
    db_queue.migrate_legacy_jsonl_if_needed()
    assert db_queue.get_job_tasks(unrelated["id"]) == before
    tata = db_queue.get_job_tasks("job_legacy_rcs_tata")
    bajaj = db_queue.get_job_tasks("job_legacy_rcs_bajaj")
    assert len(tata) == 2 and len(bajaj) == 1
    assert {task["tenant_id"] for task in tata} == {"tata"}
    assert {task["tenant_id"] for task in bajaj} == {"bajaj"}
    assert {task["channel"] for task in tata + bajaj} == {"rcs"}
    assert {task["approval_status"] for task in tata + bajaj} == {"unknown"}
    assert {task["status"] for task in tata} == {"SUBMITTED", "FAILED"}
    assert bajaj[0]["status"] == "DUPLICATE"
    assert db_queue.get_job("job_legacy_rcs_tata")["status"] == "PARTIALLY_COMPLETED"
    assert db_queue.get_job("job_legacy_rcs_bajaj")["status"] == "COMPLETED"
    assert "Skipping RCS legacy JSONL row" in caplog.text
    with db.get_db() as conn:
        assert conn.execute("SELECT count(*) AS c FROM job_tasks").fetchone()["c"] == 4


def test_old_mixed_legacy_container_rehomes_proven_owners_without_losing_results(tmp_path, monkeypatch, caplog):
    source = tmp_path / "legacy.jsonl"
    originals = [
        {"client": "tata", "template_name": "tata_row", "source_ref": "tata-source",
         "status": "submitted", "approval_status": "pending", "provider_ref_id": "old-tata-provider",
         "bot_id": "local-tata-bot"},
        {"client": "bajaj", "template_name": "bajaj_row", "source_ref": "bajaj-source",
         "status": "duplicate", "approval_status": "pending", "provider_ref_id": "old-bajaj-provider"},
        {"template_name": "unattributed_row", "source_ref": "unknown-source",
         "status": "submitted", "provider_ref_id": "old-unknown-provider"},
    ]
    source.write_text("".join(json.dumps(entry) + "\n" for entry in originals))
    monkeypatch.setattr(db_queue, "SUBMISSION_LOG_PATH", tmp_path / "no-wa-history.jsonl")
    monkeypatch.setattr(db_queue, "RCS_SUBMISSION_LOG_PATH", source)
    old_tasks = [{**entry, "client": entry.get("client") or "bajaj", "channel": "rcs"} for entry in originals]
    db_queue.create_job_with_tasks("legacy_import", "rcs", source.name, "Legacy Importer",
                                   old_tasks, job_id="job_legacy_rcs")
    before = {task["id"]: task for task in db_queue.get_job_tasks("job_legacy_rcs")}
    db_queue.migrate_legacy_jsonl_if_needed()
    db_queue.migrate_legacy_jsonl_if_needed()
    for index, tenant in enumerate(("tata", "bajaj")):
        task_id = f"task_job_legacy_rcs_{index:04d}"
        restored = db_queue.get_job_task(task_id)
        assert restored["tenant_id"] == tenant
        assert restored["job_id"] == f"job_legacy_rcs_{tenant}"
        assert restored["status"] == before[task_id]["status"]
        assert restored["provider_ref_id"] == before[task_id]["provider_ref_id"]
        assert restored["approval_status"] == before[task_id]["approval_status"]
    quarantined = db_queue.get_job_task("task_job_legacy_rcs_0002")
    assert quarantined["tenant_id"] == "legacy_import"
    assert quarantined["job_id"] == "job_legacy_rcs"
    assert db_queue.get_job("job_legacy_rcs")["total_count"] == 1
    assert "Quarantining legacy RCS task" in caplog.text
    with db.get_db() as conn:
        assert conn.execute("SELECT count(*) AS c FROM job_tasks").fetchone()["c"] == 3


def test_rehome_corrects_only_source_proven_legacy_default_approval(tmp_path, monkeypatch):
    source = tmp_path / "legacy.jsonl"
    entry = {"client": "tata", "template_name": "unreviewed", "status": "submitted",
             "provider_ref_id": "original-provider-reference"}
    source.write_text(json.dumps(entry) + "\n")
    monkeypatch.setattr(db_queue, "SUBMISSION_LOG_PATH", tmp_path / "no-wa-history.jsonl")
    monkeypatch.setattr(db_queue, "RCS_SUBMISSION_LOG_PATH", source)
    db_queue.create_job_with_tasks("legacy_import", "rcs", source.name, "Legacy Importer",
        [{**entry, "channel": "rcs", "approval_status": "approved"}], job_id="job_legacy_rcs")
    normal = db_queue.create_job_with_tasks("tata", "rcs", "normal.csv", "Tester",
        [{**entry, "approval_status": "approved"}])
    db_queue.migrate_legacy_jsonl_if_needed()
    repaired = db_queue.get_job_task("task_job_legacy_rcs_0000")
    assert repaired["tenant_id"] == "tata"
    assert repaired["approval_status"] == "unknown"
    assert repaired["status"] == "SUBMITTED"
    assert repaired["provider_ref_id"] == entry["provider_ref_id"]
    assert db_queue.get_job_tasks(normal["id"])[0]["approval_status"] == "approved"


@pytest.mark.parametrize("approval", ["approved", "rejected"])
def test_rehome_preserves_previously_verified_legacy_review(tmp_path, monkeypatch, approval):
    source = tmp_path / "legacy.jsonl"
    original = {"client": "tata", "template_name": "verified", "status": "submitted",
                "provider_ref_id": "original-provider-reference"}
    source.write_text(json.dumps(original) + "\n")
    monkeypatch.setattr(db_queue, "SUBMISSION_LOG_PATH", tmp_path / "no-wa-history.jsonl")
    monkeypatch.setattr(db_queue, "RCS_SUBMISSION_LOG_PATH", source)
    db_queue.create_job_with_tasks("legacy_import", "rcs", source.name, "Legacy Importer",
        [{**original, "channel": "rcs", "approval_status": "approved"}], job_id="job_legacy_rcs")
    task_id = "task_job_legacy_rcs_0000"
    with db.get_db() as conn:
        payload = json.loads(db_queue.get_job_task(task_id)["payload_json"])
        payload.update(approval_status=approval, provider_response={"status": approval.upper()})
        conn.execute("UPDATE job_tasks SET approval_status = ?, payload_json = ?, updated_at = ? WHERE id = ?",
                     (approval, json.dumps(payload), "2099-01-01T00:00:00+00:00", task_id))
    db_queue.migrate_legacy_jsonl_if_needed()
    restored = db_queue.get_job_task(task_id)
    assert restored["tenant_id"] == "tata"
    assert restored["approval_status"] == approval
    assert json.loads(restored["payload_json"])["provider_response"] == {"status": approval.upper()}
    assert restored["provider_ref_id"] == original["provider_ref_id"]
