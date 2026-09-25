"""
Unit tests for unified PostgreSQL and SQLite database engine (db.py).
"""

import os
from pathlib import Path
import pytest

import db


def test_translate_query_for_postgres_placeholders():
    sql = "SELECT id, email FROM users WHERE email = ? AND is_active = ?"
    translated = db.translate_query_for_postgres(sql)
    assert translated == "SELECT id, email FROM users WHERE email = %s AND is_active = %s"


def test_translate_query_for_postgres_preserves_question_marks_inside_strings():
    sql = "SELECT * FROM activities WHERE details = 'Did you submit?' AND user = ?"
    translated = db.translate_query_for_postgres(sql)
    assert "details = 'Did you submit?'" in translated
    assert translated.endswith("user = %s")


def test_translate_query_for_postgres_pragmas():
    assert db.translate_query_for_postgres("PRAGMA journal_mode=WAL") == "SELECT 1"
    assert db.translate_query_for_postgres("PRAGMA table_info(users)") == "SELECT 1"


def test_translate_query_for_postgres_insert_or_replace():
    sql = (
        "INSERT OR REPLACE INTO operational_assignments "
        "(issue_key, operational_assignee, operational_account_id, operational_role) "
        "VALUES (?, ?, ?, ?)"
    )
    translated = db.translate_query_for_postgres(sql)
    assert "INSERT INTO operational_assignments" in translated
    assert "ON CONFLICT (issue_key) DO UPDATE SET" in translated
    assert "operational_assignee = EXCLUDED.operational_assignee" in translated
    assert "operational_account_id = EXCLUDED.operational_account_id" in translated
    assert "%s, %s, %s, %s" in translated


def test_get_database_url_normalization(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@ep-test.neon.tech/neondb?sslmode=require")
    url = db.get_database_url()
    assert url.startswith("postgresql://")
    assert db.is_postgres() is True

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.delenv("POSTGRESQL_URL", raising=False)
    assert db.get_database_url() == ""
    assert db.is_postgres() is False


def test_db_connection_sqlite_execution():
    with db.get_db() as conn:
        assert conn.is_postgres is False
        cur = conn.execute("SELECT COUNT(*) as c FROM users")
        row = cur.fetchone()
        assert row["c"] >= 0
        assert row[0] >= 0


def test_init_database_executes_cleanly():
    db.init_database()
    with db.get_db() as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        for t in ["users", "activities", "ingestion_jobs", "job_tasks", "operational_assignments"]:
            assert t in tables


def test_migration_utility_dry_run():
    from scripts.migrate_sqlite_to_postgres import main
    import sys

    orig_argv = sys.argv
    try:
        sys.argv = ["migrate_sqlite_to_postgres.py", "--dry-run"]
        exit_code = main()
        assert exit_code == 0
    finally:
        sys.argv = orig_argv
