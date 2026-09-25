"""
Unified Database Adapter for Karix Whitelisting.
Provides seamless dual-driver support:
- PostgreSQL (when DATABASE_URL or POSTGRES_URL is set, e.g. on Render / Cloud)
- SQLite (default for local development, automated testing, and zero-config execution)
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
import logging
import os
from pathlib import Path
import re
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_SQLITE_PATH = Path(os.environ.get("KARIX_DB_PATH", "karix_store.db"))
DB_PATH = DEFAULT_SQLITE_PATH


def get_database_url() -> str:
    """Retrieve normalized PostgreSQL database URL or empty string if using SQLite."""
    raw = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
        or os.environ.get("POSTGRESQL_URL")
        or ""
    ).strip()
    if not raw:
        return ""
    # Render and Heroku use postgres://, but SQLAlchemy and psycopg require postgresql://
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    return raw


def is_postgres() -> bool:
    """Check if PostgreSQL driver is actively configured."""
    return bool(get_database_url())


def translate_query_for_postgres(sql: str) -> str:
    """Translate SQLite-dialect SQL statements into PostgreSQL-compliant syntax."""
    trimmed = sql.strip()
    if trimmed.upper().startswith("PRAGMA "):
        return "SELECT 1"

    # Translate INSERT OR REPLACE INTO ... for PostgreSQL
    m_replace = re.match(
        r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    if m_replace:
        tbl = m_replace.group(1)
        cols = [c.strip() for c in m_replace.group(2).split(",")]
        pk = cols[0]
        update_clauses = [f"{c} = EXCLUDED.{c}" for c in cols if c != pk]
        cols_str = ", ".join(cols)
        up_str = ", ".join(update_clauses)
        sql = f"INSERT INTO {tbl} ({cols_str}) VALUES ({m_replace.group(3)}) ON CONFLICT ({pk}) DO UPDATE SET {up_str}"

    # Quote reserved column name "user" if present as bare unquoted word in column lists
    sql = re.sub(r"\buser\b(?=\s*,|\s*\))", '"user"', sql, flags=re.IGNORECASE)

    # Translate ? parameter markers to %s outside single-quoted string literals
    parts: list[str] = []
    in_string = False
    for char in sql:
        if char == "'":
            in_string = not in_string
            parts.append(char)
        elif char == "?" and not in_string:
            parts.append("%s")
        else:
            parts.append(char)
    return "".join(parts)


class DBCursor:
    """Unified cursor wrapper supporting dict and tuple indexing."""

    def __init__(self, raw_cursor: Any, is_pg: bool = False):
        self._cur = raw_cursor
        self._is_pg = is_pg

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def lastrowid(self) -> Any:
        return getattr(self._cur, "lastrowid", None)

    def fetchone(self) -> Any:
        return self._cur.fetchone()

    def fetchall(self) -> list[Any]:
        return self._cur.fetchall()

    def fetchmany(self, size: int = 1) -> list[Any]:
        return self._cur.fetchmany(size)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._cur)


class DBConnection:
    """Unified database connection wrapper across SQLite and PostgreSQL."""

    def __init__(self, raw_conn: Any, is_pg: bool = False):
        self._conn = raw_conn
        self._is_pg = is_pg

    @property
    def raw_connection(self) -> Any:
        return self._conn

    @property
    def is_postgres(self) -> bool:
        return self._is_pg

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> DBCursor:
        if self._is_pg:
            pg_sql = translate_query_for_postgres(sql)
            cur = self._conn.cursor()
            cur.execute(pg_sql, params or ())
            return DBCursor(cur, is_pg=True)
        else:
            cur = self._conn.execute(sql, params or ())
            return DBCursor(cur, is_pg=False)

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> DBCursor:
        if self._is_pg:
            pg_sql = translate_query_for_postgres(sql)
            cur = self._conn.cursor()
            cur.executemany(pg_sql, seq_of_params)
            return DBCursor(cur, is_pg=True)
        else:
            cur = self._conn.executemany(sql, seq_of_params)
            return DBCursor(cur, is_pg=False)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> DBConnection:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self.close()


def get_db(timeout_sec: float = 15.0) -> DBConnection:
    """
    Return an active database connection.
    Connects to PostgreSQL if DATABASE_URL is configured, otherwise SQLite.
    """
    pg_url = get_database_url()
    if pg_url:
        try:
            import psycopg2
            import psycopg2.extras

            conn = psycopg2.connect(
                pg_url,
                connect_timeout=int(timeout_sec),
                cursor_factory=psycopg2.extras.DictCursor,
            )
            return DBConnection(conn, is_pg=True)
        except Exception as exc:
            logger.error("Failed to connect to PostgreSQL at %s: %s. Falling back to SQLite.", pg_url.split("@")[-1], exc)

    # SQLite fallback
    DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DEFAULT_SQLITE_PATH), timeout=timeout_sec)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return DBConnection(conn, is_pg=False)


# ---------------------------------------------------------------------------
# Schema Initialization
# ---------------------------------------------------------------------------

SQLITE_SCHEMA_DDL = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE,
        password_hash TEXT,
        name TEXT NOT NULL,
        tenant_id TEXT NOT NULL DEFAULT 'all',
        role TEXT DEFAULT 'operator',
        created_at TEXT NOT NULL,
        last_login TEXT,
        is_active INTEGER DEFAULT 1
    );
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);",
    "CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);",
    """
    CREATE TABLE IF NOT EXISTS activities (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        user TEXT NOT NULL,
        action TEXT NOT NULL,
        account TEXT NOT NULL,
        channel TEXT NOT NULL,
        details TEXT NOT NULL,
        status TEXT NOT NULL,
        ip_address TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_act_ts ON activities(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_act_user ON activities(user);",
    "CREATE INDEX IF NOT EXISTS idx_act_account ON activities(account);",
    "CREATE INDEX IF NOT EXISTS idx_act_action ON activities(action);",
    """
    CREATE TABLE IF NOT EXISTS ingestion_jobs (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        channel TEXT NOT NULL DEFAULT 'whatsapp',
        filename TEXT NOT NULL,
        total_count INTEGER NOT NULL,
        submitted_count INTEGER NOT NULL DEFAULT 0,
        duplicate_count INTEGER NOT NULL DEFAULT 0,
        failed_count INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL CHECK(status IN ('QUEUED', 'RUNNING', 'PAUSED_FOR_AUTH', 'COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED')),
        submitted_by TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_jobs_tenant ON ingestion_jobs(tenant_id, status);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_created ON ingestion_jobs(created_at DESC);",
    """
    CREATE TABLE IF NOT EXISTS job_tasks (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        channel TEXT NOT NULL DEFAULT 'whatsapp',
        source_ref TEXT,
        template_name TEXT NOT NULL,
        category TEXT,
        language TEXT,
        payload_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('PENDING', 'SUBMITTED', 'DUPLICATE', 'FAILED')),
        approval_status TEXT NOT NULL CHECK(approval_status IN ('pending', 'approved', 'rejected', 'unknown')),
        provider_ref_id TEXT,
        error TEXT,
        approval_reason TEXT,
        retry_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(job_id) REFERENCES ingestion_jobs(id) ON DELETE CASCADE
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_tasks_job ON job_tasks(job_id, status);",
    "CREATE INDEX IF NOT EXISTS idx_tasks_tenant_tpl ON job_tasks(tenant_id, template_name);",
    "CREATE INDEX IF NOT EXISTS idx_tasks_approval ON job_tasks(tenant_id, approval_status);",
    """
    CREATE TABLE IF NOT EXISTS operational_assignments (
        issue_key TEXT PRIMARY KEY,
        operational_assignee TEXT NOT NULL,
        operational_account_id TEXT,
        operational_role TEXT,
        original_jira_assignee TEXT,
        transferred_by TEXT,
        handover_note TEXT,
        transferred_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS sms_submissions (
        id TEXT PRIMARY KEY,
        client TEXT NOT NULL DEFAULT 'bajaj',
        ackid TEXT,
        status TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_sms_sub_client ON sms_submissions(client, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_sms_sub_ackid ON sms_submissions(ackid);",
    """
    CREATE TABLE IF NOT EXISTS sms_dlrs (
        id TEXT PRIMARY KEY,
        client TEXT NOT NULL DEFAULT 'bajaj',
        ackid TEXT,
        status TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_sms_dlr_client ON sms_dlrs(client, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_sms_dlr_ackid ON sms_dlrs(ackid);",
    """
    CREATE TABLE IF NOT EXISTS sms_clicks (
        id TEXT PRIMARY KEY,
        client TEXT NOT NULL DEFAULT 'bajaj',
        ackid TEXT,
        click_time TEXT,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_sms_click_client ON sms_clicks(client, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_sms_click_ackid ON sms_clicks(ackid);",
    """
    CREATE TABLE IF NOT EXISTS system_errors (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        severity TEXT NOT NULL,
        category TEXT NOT NULL,
        channel TEXT NOT NULL,
        account TEXT NOT NULL,
        error_type TEXT,
        error_message TEXT NOT NULL,
        module TEXT,
        function TEXT,
        stack_trace TEXT,
        context_json TEXT,
        remediation_hint TEXT,
        resolved INTEGER DEFAULT 0,
        resolved_by TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_sys_err_ts ON system_errors(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_sys_err_cat ON system_errors(category, severity);",
]

POSTGRES_SCHEMA_DDL = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id VARCHAR(255) PRIMARY KEY,
        email VARCHAR(255) UNIQUE,
        password_hash TEXT,
        name VARCHAR(255) NOT NULL,
        tenant_id VARCHAR(100) NOT NULL DEFAULT 'all',
        role VARCHAR(50) DEFAULT 'operator',
        created_at VARCHAR(100) NOT NULL,
        last_login VARCHAR(100),
        is_active INTEGER DEFAULT 1
    );
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);",
    "CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);",
    """
    CREATE TABLE IF NOT EXISTS activities (
        id VARCHAR(255) PRIMARY KEY,
        timestamp VARCHAR(100) NOT NULL,
        "user" VARCHAR(255) NOT NULL,
        action VARCHAR(100) NOT NULL,
        account VARCHAR(100) NOT NULL,
        channel VARCHAR(50) NOT NULL,
        details TEXT NOT NULL,
        status VARCHAR(50) NOT NULL,
        ip_address VARCHAR(100)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_act_ts ON activities(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_act_user ON activities(\"user\");",
    "CREATE INDEX IF NOT EXISTS idx_act_account ON activities(account);",
    "CREATE INDEX IF NOT EXISTS idx_act_action ON activities(action);",
    """
    CREATE TABLE IF NOT EXISTS ingestion_jobs (
        id VARCHAR(255) PRIMARY KEY,
        tenant_id VARCHAR(100) NOT NULL,
        channel VARCHAR(50) NOT NULL DEFAULT 'whatsapp',
        filename VARCHAR(255) NOT NULL,
        total_count INTEGER NOT NULL,
        submitted_count INTEGER NOT NULL DEFAULT 0,
        duplicate_count INTEGER NOT NULL DEFAULT 0,
        failed_count INTEGER NOT NULL DEFAULT 0,
        status VARCHAR(50) NOT NULL,
        submitted_by VARCHAR(255),
        error_message TEXT,
        created_at VARCHAR(100) NOT NULL,
        updated_at VARCHAR(100) NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_jobs_tenant ON ingestion_jobs(tenant_id, status);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_created ON ingestion_jobs(created_at DESC);",
    """
    CREATE TABLE IF NOT EXISTS job_tasks (
        id VARCHAR(255) PRIMARY KEY,
        job_id VARCHAR(255) NOT NULL REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
        tenant_id VARCHAR(100) NOT NULL,
        channel VARCHAR(50) NOT NULL DEFAULT 'whatsapp',
        source_ref VARCHAR(255),
        template_name VARCHAR(255) NOT NULL,
        category VARCHAR(50),
        language VARCHAR(50),
        payload_json TEXT NOT NULL,
        status VARCHAR(50) NOT NULL,
        approval_status VARCHAR(50) NOT NULL,
        provider_ref_id VARCHAR(255),
        error TEXT,
        approval_reason TEXT,
        retry_count INTEGER NOT NULL DEFAULT 0,
        created_at VARCHAR(100) NOT NULL,
        updated_at VARCHAR(100) NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_tasks_job ON job_tasks(job_id, status);",
    "CREATE INDEX IF NOT EXISTS idx_tasks_tenant_tpl ON job_tasks(tenant_id, template_name);",
    "CREATE INDEX IF NOT EXISTS idx_tasks_approval ON job_tasks(tenant_id, approval_status);",
    """
    CREATE TABLE IF NOT EXISTS operational_assignments (
        issue_key VARCHAR(100) PRIMARY KEY,
        operational_assignee VARCHAR(255) NOT NULL,
        operational_account_id VARCHAR(255),
        operational_role VARCHAR(100),
        original_jira_assignee VARCHAR(255),
        transferred_by VARCHAR(255),
        handover_note TEXT,
        transferred_at VARCHAR(100)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS sms_submissions (
        id VARCHAR(255) PRIMARY KEY,
        client VARCHAR(50) NOT NULL DEFAULT 'bajaj',
        ackid VARCHAR(255),
        status VARCHAR(50) NOT NULL,
        payload_json TEXT NOT NULL,
        created_at VARCHAR(100) NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_sms_sub_client ON sms_submissions(client, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_sms_sub_ackid ON sms_submissions(ackid);",
    """
    CREATE TABLE IF NOT EXISTS sms_dlrs (
        id VARCHAR(255) PRIMARY KEY,
        client VARCHAR(50) NOT NULL DEFAULT 'bajaj',
        ackid VARCHAR(255),
        status VARCHAR(50) NOT NULL,
        payload_json TEXT NOT NULL,
        created_at VARCHAR(100) NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_sms_dlr_client ON sms_dlrs(client, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_sms_dlr_ackid ON sms_dlrs(ackid);",
    """
    CREATE TABLE IF NOT EXISTS sms_clicks (
        id VARCHAR(255) PRIMARY KEY,
        client VARCHAR(50) NOT NULL DEFAULT 'bajaj',
        ackid VARCHAR(255),
        click_time VARCHAR(100),
        payload_json TEXT NOT NULL,
        created_at VARCHAR(100) NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_sms_click_client ON sms_clicks(client, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_sms_click_ackid ON sms_clicks(ackid);",
    """
    CREATE TABLE IF NOT EXISTS system_errors (
        id VARCHAR(255) PRIMARY KEY,
        timestamp VARCHAR(100) NOT NULL,
        severity VARCHAR(50) NOT NULL,
        category VARCHAR(50) NOT NULL,
        channel VARCHAR(50) NOT NULL,
        account VARCHAR(100) NOT NULL,
        error_type VARCHAR(255),
        error_message TEXT NOT NULL,
        module VARCHAR(255),
        function VARCHAR(255),
        stack_trace TEXT,
        context_json TEXT,
        remediation_hint TEXT,
        resolved INTEGER DEFAULT 0,
        resolved_by VARCHAR(255)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_sys_err_ts ON system_errors(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_sys_err_cat ON system_errors(category, severity);",
]


def init_database() -> None:
    """Initialize database tables and indexes for active driver (PostgreSQL or SQLite)."""
    with get_db() as conn:
        ddl_list = POSTGRES_SCHEMA_DDL if conn.is_postgres else SQLITE_SCHEMA_DDL
        for stmt in ddl_list:
            clean_stmt = stmt.strip()
            if clean_stmt:
                conn.execute(clean_stmt)
        conn.commit()


# ---------------------------------------------------------------------------
# Migration Utility (SQLite -> PostgreSQL)
# ---------------------------------------------------------------------------

def migrate_sqlite_to_postgres(sqlite_path: Path | str = DEFAULT_SQLITE_PATH, pg_url: str | None = None) -> dict[str, Any]:
    """
    Copy all table data from a local SQLite database file into PostgreSQL.
    Safely skips duplicate primary keys using ON CONFLICT DO NOTHING.
    """
    target_url = pg_url or get_database_url()
    if not target_url:
        raise ValueError("DATABASE_URL or target postgres_url must be provided for migration.")

    src_path = Path(sqlite_path)
    if not src_path.exists():
        raise FileNotFoundError(f"Source SQLite database not found at {src_path}")

    import psycopg2
    import psycopg2.extras

    src_conn = sqlite3.connect(str(src_path))
    src_conn.row_factory = sqlite3.Row

    dest_conn = psycopg2.connect(target_url, cursor_factory=psycopg2.extras.DictCursor)

    # 1. Initialize Postgres schema
    with dest_conn.cursor() as cur:
        for stmt in POSTGRES_SCHEMA_DDL:
            cur.execute(stmt)
    dest_conn.commit()

    migration_report: dict[str, int] = {}
    tables_to_migrate = ["users", "activities", "ingestion_jobs", "job_tasks", "operational_assignments"]

    for table in tables_to_migrate:
        src_cur = src_conn.cursor()
        src_cur.execute(f"SELECT * FROM {table}")
        rows = src_cur.fetchall()
        if not rows:
            migration_report[table] = 0
            continue

        col_names = [col[0] for col in src_cur.description]
        quoted_cols = [f'"{c}"' if c.lower() == "user" else c for c in col_names]
        cols_str = ", ".join(quoted_cols)
        placeholders = ", ".join(["%s"] * len(col_names))
        pk = col_names[0]

        insert_sql = (
            f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) "
            f"ON CONFLICT ({pk}) DO NOTHING"
        )

        with dest_conn.cursor() as dest_cur:
            psycopg2.extras.execute_batch(
                dest_cur,
                insert_sql,
                [tuple(r) for r in rows],
                page_size=100,
            )
        dest_conn.commit()
        migration_report[table] = len(rows)

    src_conn.close()
    dest_conn.close()
    logger.info("Successfully completed SQLite to PostgreSQL migration: %s", migration_report)
    return migration_report
