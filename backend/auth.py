"""JWT authentication, explicit user provisioning and strict tenant isolation."""

import argparse
import getpass
import logging
import os
import re
import uuid
from pathlib import Path
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db import get_db as _get_db

logger = logging.getLogger(__name__)
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30
security = HTTPBearer(auto_error=False)
TATA_SUB_ACCOUNTS = {"tata", "tcl_promo", "tcl_trans", "tchfl", "wealth", "moneyfy"}


def _auth_db():
    try:
        return _get_db(strict_backend=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Authentication database is unavailable.") from exc

def configured_jwt_secret() -> str:
    """Retrieve cryptographically strong JWT secret, loading from .env or auto-generating for local dev."""
    try:
        from config import _load_env_file
        _load_env_file()
    except Exception:
        pass
    secret = os.environ.get("JWT_SECRET", "").strip()
    if not secret or len(secret.encode("utf-8")) < 32 or len(set(secret)) < 16 or secret == "karix_whitelisting_secure_jwt_secret_key_2026_prod":
        dev_secret_path = Path(".jwt_secret")
        if dev_secret_path.exists():
            try:
                secret = dev_secret_path.read_text(encoding="utf-8").strip()
            except OSError:
                secret = ""
        if not secret or len(secret) < 32:
            secret = secrets.token_urlsafe(48)
            try:
                dev_secret_path.write_text(secret, encoding="utf-8")
                dev_secret_path.chmod(0o600)
            except OSError:
                pass
        os.environ["JWT_SECRET"] = secret
    return secret


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (ValueError, TypeError, AttributeError):
        return False


def init_auth_db() -> None:
    """Initialize schema only; never seed, reset or delete stored users."""
    from db import init_database

    with _auth_db() as conn:
        init_database(conn)


try:
    init_auth_db()
except Exception as exc:
    logger.warning("Could not auto-initialize auth database: %s", exc)


def create_access_token(
    user_id: str,
    email: str,
    tenant_id: str,
    role: str,
    name: str,
    expires_delta: timedelta | None = None,
) -> str:
    now = datetime.now(UTC)
    expire = now + (expires_delta if expires_delta is not None else timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS))
    return jwt.encode(
        {"sub": user_id, "email": email, "tenant_id": tenant_id, "role": role, "name": name, "exp": expire, "iat": now},
        configured_jwt_secret(), algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict[str, Any] | None:
    secret = configured_jwt_secret()
    try:
        return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM], options={"require": ["sub", "exp", "iat"]})
    except jwt.InvalidTokenError:
        return None


def validate_new_password(password: str) -> None:
    if len(password) < 12 or len(password.encode("utf-8")) > 72:
        raise ValueError("Password must contain at least 12 characters and at most 72 UTF-8 bytes.")


def validate_identity_scope(tenant_id: str, role: str) -> None:
    if role not in ("operator", "admin", "superadmin"):
        raise ValueError("Role must be operator, admin or superadmin.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]{0,99}", tenant_id):
        raise ValueError("A valid organization ID is required.")
    if (tenant_id == "all") != (role == "superadmin"):
        raise ValueError("Only platform superadmins may have all-organization scope; company users require a concrete organization.")


def register_user(email: str, password: str, name: str, tenant_id: str, role: str = "operator") -> dict[str, Any]:
    """Create a user. Callers must authorize provisioning; existing users are never overwritten."""
    clean_email, clean_name = email.lower().strip(), name.strip()
    clean_tenant, clean_role = tenant_id.lower().strip(), role.lower().strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", clean_email):
        raise ValueError("A valid email address is required.")
    validate_new_password(password)
    if not clean_name:
        raise ValueError("Name is required.")
    validate_identity_scope(clean_tenant, clean_role)
    now = datetime.now(UTC).isoformat()
    user_id = f"usr_{uuid.uuid4().hex}"
    password_hash = hash_password(password)
    with _auth_db() as conn:
        if conn.execute("SELECT id FROM users WHERE email = ?", (clean_email,)).fetchone():
            raise ValueError("An account with this email already exists; provisioning cannot reset it.")
        conn.execute(
            "INSERT INTO users (id, email, password_hash, name, tenant_id, role, created_at, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (user_id, clean_email, password_hash, clean_name, clean_tenant, clean_role, now),
        )
    return {"id": user_id, "email": clean_email, "name": clean_name, "tenant_id": clean_tenant, "role": clean_role, "created_at": now}


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    configured_jwt_secret()
    with _auth_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ? AND is_active = 1", (email.lower().strip(),)).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            return None
        try:
            validate_identity_scope(row["tenant_id"], row["role"])
        except (ValueError, TypeError):
            return None
        user_data = dict(row)
        user_data.pop("password_hash", None)
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (datetime.now(UTC).isoformat(), row["id"]))
    return {"user": user_data, "token": create_access_token(row["id"], row["email"], row["tenant_id"], row["role"], row["name"])}


def get_user_profile(user_id: str) -> dict[str, Any] | None:
    with _auth_db() as conn:
        row = conn.execute(
            "SELECT id, email, name, tenant_id, role, created_at, last_login FROM users WHERE id = ? AND is_active = 1 AND password_hash IS NOT NULL",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def list_tenant_team(tenant_id: str) -> list[dict[str, Any]]:
    """Return one concrete organization's users; all-scope is handled by authorized API callers."""
    with _auth_db() as conn:
        rows = conn.execute(
            "SELECT id, email, name, tenant_id, role, created_at, last_login, is_active FROM users WHERE tenant_id = ? ORDER BY created_at DESC",
            (tenant_id,),
        ).fetchall()
        return [dict(row) for row in rows]


async def get_current_user(request: Request, auth: HTTPAuthorizationCredentials | None = Depends(security)) -> dict[str, Any]:
    cached_user = getattr(request.state, "current_user", None)
    if cached_user is not None:
        return cached_user
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid authentication required.", headers={"WWW-Authenticate": "Bearer"})
    if not auth or auth.scheme.lower() != "bearer" or not auth.credentials:
        raise unauthorized
    payload = decode_access_token(auth.credentials)
    if not payload or not isinstance(payload.get("sub"), str):
        raise unauthorized
    user = get_user_profile(payload["sub"])
    if not user:
        raise unauthorized
    try:
        validate_identity_scope(user["tenant_id"], user["role"])
    except (ValueError, TypeError):
        raise unauthorized
    # Always reload roles and tenant from the database, never trust stale JWT claims.
    return {**user, "sub": user["id"]}


def require_admin(user: dict[str, Any]) -> None:
    if user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Organization administrator access required.")


def require_tenant_access(account: str, user: dict[str, Any]) -> None:
    target = account.lower().strip()
    tenant = str(user.get("tenant_id", "")).lower().strip()
    if user.get("role") == "superadmin":
        return
    if target and target != "all" and tenant != "all" and (target == tenant or tenant == "tata" and target in TATA_SUB_ACCOUNTS):
        return
    raise HTTPException(status_code=403, detail=f"Access denied to organization '{target}'.")


def reset_password(email: str, password: str) -> dict[str, Any]:
    """Explicit local administrative rotation, preserving identity, role and active state."""
    validate_new_password(password)
    with _auth_db() as conn:
        row = conn.execute("SELECT id, email, name, tenant_id, role FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
        if not row:
            raise ValueError("Account not found; reset cannot create a user.")
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), row["id"]))
    return dict(row)


def bootstrap_cli() -> None:
    """Run on the backend host with the production DB configuration; password stays out of argv."""
    parser = argparse.ArgumentParser(description="Create an explicit company admin or platform superadmin without modifying existing users.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name")
    parser.add_argument("--tenant", help="Company ID such as apparel; use all only with --superadmin")
    parser.add_argument("--superadmin", action="store_true", help="Explicitly provision a platform administrator (tenant all)")
    parser.add_argument("--reset-password", action="store_true", help="Explicitly rotate an existing account password without changing its identity or permissions")
    args = parser.parse_args()
    if args.reset_password:
        if args.name or args.tenant or args.superadmin:
            parser.error("--reset-password accepts only --email; identity and permissions are preserved")
    elif not args.name or not args.tenant:
        parser.error("New account bootstrap requires --name and --tenant")
    try:
        configured_jwt_secret()
        init_auth_db()
        password = getpass.getpass("New account password (12+ characters): ")
        if password != getpass.getpass("Confirm password: "):
            raise ValueError("Passwords do not match.")
        user = reset_password(args.email, password) if args.reset_password else register_user(
            args.email, password, args.name, args.tenant, "superadmin" if args.superadmin else "admin"
        )
    except (ValueError, HTTPException) as exc:
        parser.exit(1, f"Bootstrap failed: {getattr(exc, 'detail', str(exc))}\n")
    action = "Rotated password for" if args.reset_password else "Created"
    print(f"{action} {user['role']} {user['email']} for {user['tenant_id']}; sign in through the portal to provision colleagues.")


if __name__ == "__main__":
    bootstrap_cli()
