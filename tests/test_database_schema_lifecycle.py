"""Database identities and upgrades must preserve queued submissions."""
import sqlite3

import pytest

import db


def connect(path):
    raw = sqlite3.connect(path)
    raw.row_factory = sqlite3.Row
    return db.DBConnection(raw)


def test_independent_memory_databases_have_independent_users():
    with connect(":memory:") as first, connect(":memory:") as second:
        db.init_database(first)
        first.execute("INSERT INTO users(id,name,created_at) VALUES('first','First','now')")
        first.commit()
        db.init_database(second)
        assert second.execute("SELECT id FROM users").fetchall() == []
        assert first.execute("SELECT id FROM users").fetchone()[0] == "first"


def test_recreated_database_is_initialized(tmp_path):
    path = tmp_path / "store.db"
    with connect(path) as conn:
        db.init_database(conn)
        conn.execute("INSERT INTO users(id,name,created_at) VALUES('old','Old','now')")
    path.unlink()
    with connect(path) as conn:
        db.init_database(conn)
        conn.execute("INSERT INTO users(id,name,created_at) VALUES('new','New','now')")
        assert conn.execute("SELECT id FROM users").fetchone()[0] == "new"


def test_legacy_task_checks_upgrade_without_losing_rows_or_custom_schema(tmp_path):
    with connect(tmp_path / "legacy.db") as conn:
        for statement in db.SQLITE_SCHEMA_DDL:
            legacy = statement.replace("'PENDING', 'PROCESSING',", "'PENDING',")
            legacy = legacy.replace(", 'BLOCKED_ASPECT_RATIO'", "").replace(", 'blocked_aspect_ratio'", "")
            conn.execute(legacy)
        conn.execute("ALTER TABLE job_tasks ADD COLUMN operator_note TEXT")
        conn.execute("CREATE INDEX operator_note_index ON job_tasks(operator_note)")
        conn.execute("CREATE TABLE task_audit(task_id TEXT, status TEXT)")
        conn.execute("CREATE TRIGGER task_update_audit AFTER UPDATE ON job_tasks BEGIN INSERT INTO task_audit VALUES(new.id,new.status); END")
        conn.execute("INSERT INTO ingestion_jobs(id,tenant_id,channel,filename,total_count,status,created_at,updated_at) VALUES('job','tata','rcs','sheet',1,'QUEUED','now','now')")
        conn.execute("INSERT INTO job_tasks(id,job_id,tenant_id,channel,template_name,payload_json,status,approval_status,created_at,updated_at,operator_note) VALUES('task','job','tata','rcs','offer','{}','PENDING','unknown','now','now','keep')")
        conn.commit()
        db.init_database(conn)
        conn.execute("UPDATE job_tasks SET status='PROCESSING' WHERE id='task'")
        conn.execute("UPDATE job_tasks SET status='BLOCKED_ASPECT_RATIO', approval_status='blocked_aspect_ratio' WHERE id='task'")
        assert conn.execute("SELECT operator_note FROM job_tasks WHERE id='task'").fetchone()[0] == "keep"
        assert [tuple(row) for row in conn.execute("SELECT * FROM task_audit").fetchall()] == [("task", "PROCESSING"), ("task", "BLOCKED_ASPECT_RATIO")]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='operator_note_index'").fetchone()[0] == "operator_note_index"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE job_tasks SET status='MADE_UP' WHERE id='task'")


@pytest.mark.parametrize("failure", ["commit", "rollback"])
def test_transaction_failure_still_closes_connection(failure):
    class BrokenConnection:
        closed = False

        def commit(self):
            raise RuntimeError("commit failed")

        def rollback(self):
            raise RuntimeError("rollback failed")

        def close(self):
            self.closed = True

    raw = BrokenConnection()
    with pytest.raises(RuntimeError):
        with db.DBConnection(raw):
            if failure == "rollback":
                raise ValueError("operation failed")
    assert raw.closed


def test_configured_database_outage_does_not_create_shadow_queue(tmp_path, monkeypatch):
    driver = pytest.importorskip("psycopg2")
    fallback = tmp_path / "shadow.db"
    monkeypatch.setattr(db, "DEFAULT_SQLITE_PATH", fallback)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test.invalid/queue")

    def offline(*args, **kwargs):
        raise ConnectionError("configured database offline")

    monkeypatch.setattr(driver, "connect", offline)
    with pytest.raises(RuntimeError, match="PostgreSQL database is unavailable"):
        db.get_db()
    assert not fallback.exists()
