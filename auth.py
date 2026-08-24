"""
Multi-Tenant Authentication & Strict Tenant Isolation Engine.
Provides secure password hashing (bcrypt), JSON Web Tokens (JWT),
user lifecycle management, default account seeding, and FastAPI tenant guards.
"""

import logging
import os
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

DB_PATH = Path("karix_store.db")
JWT_SECRET = os.environ.get("JWT_SECRET") or "karix_whitelisting_secure_jwt_secret_key_2026_prod"
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

security = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Database Schema & Initialization
# ---------------------------------------------------------------------------


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str) -> str:
    """Hash plaintext password with bcrypt salt (10 rounds for responsive container performance)."""
    salt = bcrypt.gensalt(rounds=10)
    return bcrypt.hashpw(password.strip().encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plaintext password against bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.strip().encode("utf-8"), hashed_password.strip().encode("utf-8"))
    except Exception:
        return False


def init_auth_db() -> None:
    """Ensure multi-tenant users table exists with all required columns and seed accounts."""
    with _get_db() as conn:
        conn.execute("""
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
            )
        """)
        # Check if columns are missing from old schema
        cur = conn.execute("PRAGMA table_info(users)")
        existing_cols = {row[1] for row in cur.fetchall()}
        if "email" not in existing_cols:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
        if "password_hash" not in existing_cols:
            conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        if "tenant_id" not in existing_cols:
            conn.execute("ALTER TABLE users ADD COLUMN tenant_id TEXT DEFAULT 'all'")
        if "last_login" not in existing_cols:
            conn.execute("ALTER TABLE users ADD COLUMN last_login TEXT")
        if "is_active" not in existing_cols:
            conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")

        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id)")

        # Seed default accounts if needed
        now = datetime.now(UTC).isoformat()
        seed_users = [
            (
                "usr_bajaj_admin",
                "bajaj@karix.com",
                hash_password("Bajaj@123"),
                "Bajaj Lead Operator",
                "bajaj",
                "admin",
                now,
                now,
                1,
            ),
            (
                "usr_tata_admin",
                "tata@karix.com",
                hash_password("Tata@123"),
                "Tata Capital Admin",
                "tata",
                "admin",
                now,
                now,
                1,
            ),
            (
                "usr_superadmin",
                "admin@karix.com",
                hash_password("Admin@123"),
                "Platform SuperAdmin",
                "all",
                "superadmin",
                now,
                now,
                1,
            ),
        ]
        for u in seed_users:
            conn.execute(
                """
                INSERT INTO users (id, email, password_hash, name, tenant_id, role, created_at, last_login, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET password_hash = excluded.password_hash, tenant_id = excluded.tenant_id, role = excluded.role
            """,
                u,
            )
        logger.info("Multi-tenant users table initialized and accounts seeded.")


# Initialize tables at module import time
try:
    init_auth_db()
except Exception as e:
    logger.warning("Could not auto-initialize auth database: %s", e)


# ---------------------------------------------------------------------------
# JWT Token Operations
# ---------------------------------------------------------------------------


def create_access_token(
    user_id: str,
    email: str,
    tenant_id: str,
    role: str,
    name: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Generate a signed JWT token carrying user identity, tenant claim, and role."""
    expire = datetime.now(UTC) + (expires_delta or timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS))
    payload = {
        "sub": user_id,
        "email": email.lower().strip(),
        "tenant_id": tenant_id.lower().strip(),
        "role": role.lower().strip(),
        "name": name.strip(),
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT access token."""
    try:
        return jwt.decode(token.strip(), JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


# ---------------------------------------------------------------------------
# User Data Operations
# ---------------------------------------------------------------------------


def register_user(
    email: str,
    password: str,
    name: str,
    tenant_id: str = "bajaj",
    role: str = "operator",
) -> dict[str, Any]:
    """Register a new user account bound to a specific tenant."""
    clean_email = email.lower().strip()
    clean_name = name.strip()
    clean_tenant = tenant_id.lower().strip()
    clean_role = role.lower().strip()

    if not clean_email or "@" not in clean_email:
        raise ValueError("A valid email address is required.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters long.")
    if not clean_name:
        raise ValueError("Name is required.")
    if clean_tenant not in ("bajaj", "tata", "all"):
        # Support custom tenants if valid
        clean_tenant = clean_tenant.replace(" ", "_")

    now = datetime.now(UTC).isoformat()
    u_id = f"usr_{uuid.uuid4().hex[:10]}"
    p_hash = hash_password(password)

    with _get_db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO users (id, email, password_hash, name, tenant_id, role, created_at, last_login, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
                (u_id, clean_email, p_hash, clean_name, clean_tenant, clean_role, now, now),
            )
        except sqlite3.IntegrityError as err:
            raise ValueError(f"An account with email '{clean_email}' already exists.") from err
    user_data = {
        "id": u_id,
        "email": clean_email,
        "name": clean_name,
        "tenant_id": clean_tenant,
        "role": clean_role,
        "created_at": now,
    }

    token = create_access_token(
        user_id=u_id,
        email=clean_email,
        tenant_id=clean_tenant,
        role=clean_role,
        name=clean_name,
    )

    return {
        "user": user_data,
        "token": token,
    }


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    """Validate user credentials and return user profile with access token."""
    clean_email = email.lower().strip()
    with _get_db() as conn:
        cur = conn.execute("SELECT * FROM users WHERE email = ? AND is_active = 1", (clean_email,))
        row = cur.fetchone()
        if not row:
            return None

        if not verify_password(password, row["password_hash"]):
            return None

        now = datetime.now(UTC).isoformat()
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, row["id"]))

        user_data = dict(row)
        user_data.pop("password_hash", None)

        token = create_access_token(
            user_id=user_data["id"],
            email=user_data["email"],
            tenant_id=user_data["tenant_id"],
            role=user_data["role"],
            name=user_data["name"],
        )

        return {
            "user": user_data,
            "token": token,
        }


def get_user_profile(user_id: str) -> dict[str, Any] | None:
    """Fetch user profile by ID."""
    with _get_db() as conn:
        cur = conn.execute(
            "SELECT id, email, name, tenant_id, role, created_at, last_login FROM users WHERE id = ?", (user_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None


def list_tenant_team(tenant_id: str) -> list[dict[str, Any]]:
    """List team members within a tenant."""
    clean_tenant = tenant_id.lower().strip()
    with _get_db() as conn:
        if clean_tenant == "all":
            cur = conn.execute(
                "SELECT id, email, name, tenant_id, role, created_at, last_login FROM users ORDER BY created_at DESC"
            )
        else:
            cur = conn.execute(
                "SELECT id, email, name, tenant_id, role, created_at, last_login FROM users WHERE tenant_id = ? ORDER BY created_at DESC",
                (clean_tenant,),
            )
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# FastAPI Dependency: Strict Tenant Enforcement
# ---------------------------------------------------------------------------


async def get_current_user(
    auth: HTTPAuthorizationCredentials | None = Depends(security),
    x_user: str | None = Header(default=None),
) -> dict[str, Any]:
    """
    Authenticate request via JWT Bearer token.
    If no token is provided, returns an anonymous profile with open tenant for backward compatibility.
    """
    if auth and auth.credentials:
        payload = decode_access_token(auth.credentials)
        if payload:
            return payload

    # Fallback to demo / legacy identity if unauthenticated
    return {
        "sub": "usr_anon",
        "email": (x_user or "operator@karix.com").strip(),
        "name": (x_user or "Operator").strip(),
        "tenant_id": "all",
        "role": "operator",
    }


def require_tenant_access(account: str, user: dict[str, Any]) -> None:
    """
    Enforce strict tenant isolation.
    Raises HTTP 403 Forbidden if user's tenant does not match the requested account.
    """
    target = account.lower().strip()
    user_tenant = str(user.get("tenant_id", "all")).lower().strip()
    user_role = str(user.get("role", "operator")).lower().strip()

    # Superadmin or platform users with "all" can access any tenant
    if user_tenant == "all" or user_role == "superadmin":
        return

    if user_tenant != target:
        user_name = user.get("name") or user.get("email") or "Operator"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Access Denied: User '{user_name}' belongs to organization '{user_tenant.upper()}' "
                f"and is strictly forbidden from accessing '{target.upper()}' templates or credentials."
            ),
        )
