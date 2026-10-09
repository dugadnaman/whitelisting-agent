"""JWT authentication, pending access requests and strict tenant isolation."""

import argparse
import getpass
import logging
import os
import re
import uuid
import string
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db import DBConnection, get_db as _get_db

logger = logging.getLogger(__name__)
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30
security = HTTPBearer(auto_error=False)
TATA_SUB_ACCOUNTS = {"tata", "tcl_promo", "tcl_trans", "tchfl", "wealth", "moneyfy"}
REQUESTABLE_TENANTS = {"bajaj", "tata", "apparel"}
_PROFILE_COLUMNS = "id, email, name, tenant_id, role, requested_tenant_id, created_at, last_login"


def _auth_db():
    try:
        return _get_db(strict_backend=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Authentication database is unavailable.") from exc

def configured_jwt_secret() -> str:
    """Use one configured signing key; never replace it during authentication."""
    from config import _load_env_file

    _load_env_file()
    secret = os.environ.get("JWT_SECRET", "").strip()
    if not secret or len(secret.encode("utf-8")) < 32 or len(set(secret)) < 16 or secret == "karix_whitelisting_secure_jwt_secret_key_2026_prod":
        raise HTTPException(
            status_code=503,
            detail="Authentication signing key is unavailable. Configure a strong, persistent JWT_SECRET.",
        )
    return secret


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (ValueError, TypeError, AttributeError):
        return False


def init_auth_db() -> None:
    """Initialize and safely normalize legacy identity scopes; never seed or reset users."""
    from db import init_database
    from config import _load_env_file

    _load_env_file()

    with _auth_db() as conn:
        init_database(conn)
        rows = conn.execute("SELECT id, tenant_id, role FROM users").fetchall()
        for row in rows:
            tenant = str(row["tenant_id"] or "").strip().lower()
            role = str(row["role"] or "").strip().lower()
            if (tenant == "all" and role != "superadmin") or tenant == "unassigned":
                tenant, role = "unassigned", "operator"
            elif role not in ("operator", "admin", "superadmin") or not re.fullmatch(r"[a-z0-9][a-z0-9_]{0,99}", tenant):
                continue
            if (tenant, role) != (row["tenant_id"], row["role"]):
                conn.execute(
                    "UPDATE users SET tenant_id = ?, role = ? WHERE id = ? AND tenant_id = ? "
                    "AND (role = ? OR (role IS NULL AND ? IS NULL))",
                    (tenant, role, row["id"], row["tenant_id"], row["role"], row["role"]),
                )


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
    except (jwt.InvalidTokenError, TypeError, ValueError, OverflowError, RecursionError):
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
    if tenant_id == "unassigned" and role != "operator":
        raise ValueError("Unassigned accounts must be operators.")


def _email_matches(conn: DBConnection, email: str) -> list[Any]:
    # Preserve stored legacy emails while comparing their normalized identity.
    trim = "BTRIM" if conn.is_postgres else "TRIM"
    return conn.execute(
        f"SELECT * FROM users WHERE LOWER({trim}(email, ?)) = ? LIMIT 2",
        (string.whitespace, email.lower().strip()),
    ).fetchall()


def _user_profile(conn: DBConnection, user_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_PROFILE_COLUMNS} FROM users WHERE id = ? AND is_active = 1 AND password_hash IS NOT NULL",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def register_user(
    email: str, password: str, name: str, tenant_id: str, role: str = "operator",
    *, requested_tenant_id: str | None = None,
) -> dict[str, Any]:
    """Create a user. Callers must authorize provisioning; existing users are never overwritten."""
    configured_jwt_secret()
    clean_email, clean_name = email.lower().strip(), name.strip()
    clean_tenant, clean_role = tenant_id.lower().strip(), role.lower().strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", clean_email):
        raise ValueError("A valid email address is required.")
    validate_new_password(password)
    if not clean_name:
        raise ValueError("Name is required.")
    validate_identity_scope(clean_tenant, clean_role)
    if requested_tenant_id is not None and (requested_tenant_id not in REQUESTABLE_TENANTS or clean_tenant != "unassigned"):
        raise ValueError("Request a supported organization only from an unassigned account.")
    now = datetime.now(UTC).isoformat()
    user_id = f"usr_{uuid.uuid4().hex}"
    with _auth_db() as conn:
        if _email_matches(conn, clean_email):
            raise ValueError("An account with this email already exists; provisioning cannot reset it.")
        inserted = conn.execute(
            "INSERT INTO users (id, email, password_hash, name, tenant_id, role, requested_tenant_id, created_at, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1) ON CONFLICT(email) DO NOTHING",
            (user_id, clean_email, hash_password(password), clean_name, clean_tenant, clean_role, requested_tenant_id, now),
        )
        if inserted.rowcount != 1:
            raise ValueError("An account with this email already exists; provisioning cannot reset it.")
    return {
        "id": user_id, "email": clean_email, "name": clean_name, "tenant_id": clean_tenant,
        "role": clean_role, "requested_tenant_id": requested_tenant_id, "created_at": now,
    }


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    configured_jwt_secret()
    with _auth_db() as conn:
        matches = _email_matches(conn, email)
        if len(matches) != 1:
            return None
        row = matches[0]
        if row["is_active"] != 1 or not verify_password(password, row["password_hash"]):
            return None
        try:
            validate_identity_scope(row["tenant_id"], row["role"])
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=403,
                detail="Your account permissions need administrator configuration.",
            ) from exc
        user_data = dict(row)
        user_data.pop("password_hash", None)
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (datetime.now(UTC).isoformat(), row["id"]))
    return {"user": user_data, "token": create_access_token(row["id"], row["email"], row["tenant_id"], row["role"], row["name"])}


def get_user_profile(user_id: str) -> dict[str, Any] | None:
    with _auth_db() as conn:
        return _user_profile(conn, user_id)


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
    if user.get("tenant_id") == "unassigned" or user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Organization administrator access required.")


def require_tenant_access(account: str, user: dict[str, Any]) -> None:
    target = account.lower().strip()
    tenant = str(user.get("tenant_id", "")).lower().strip()
    if tenant == "unassigned" or target == "unassigned":
        raise HTTPException(status_code=403, detail="Organization access has not been approved.")
    if user.get("role") == "superadmin":
        return
    if target and target != "all" and tenant != "all" and (target == tenant or tenant == "tata" and target in TATA_SUB_ACCOUNTS):
        return
    raise HTTPException(status_code=403, detail=f"Access denied to organization '{target}'.")



def request_organization_access(user: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    if user.get("tenant_id") != "unassigned" or user.get("role") != "operator":
        raise HTTPException(status_code=403, detail="Only unassigned accounts may request organization access.")
    if tenant_id not in REQUESTABLE_TENANTS:
        raise ValueError("Choose bajaj, tata or apparel.")
    previous = user.get("requested_tenant_id")
    with _auth_db() as conn:
        updated = conn.execute(
            "UPDATE users SET requested_tenant_id = ? WHERE id = ? AND tenant_id = 'unassigned' "
            "AND role = 'operator' AND is_active = 1 "
            "AND (requested_tenant_id = ? OR (requested_tenant_id IS NULL AND ? IS NULL))",
            (tenant_id, user["id"], previous, previous),
        )
        if updated.rowcount != 1:
            raise HTTPException(status_code=409, detail="Account or access request changed; refresh your status.")
        return _user_profile(conn, user["id"])


def list_access_requests(user: dict[str, Any], tenant_id: str | None = None) -> list[dict[str, Any]]:
    require_admin(user)
    tenant = tenant_id.strip().lower() if tenant_id is not None else None
    if user["role"] != "superadmin":
        tenant = tenant or user["tenant_id"]
        require_tenant_access(tenant, user)
    if tenant is not None and tenant not in REQUESTABLE_TENANTS:
        raise ValueError("Choose bajaj, tata or apparel.")
    query = (
        f"SELECT {_PROFILE_COLUMNS} FROM users WHERE tenant_id = 'unassigned' AND role = 'operator' "
        "AND is_active = 1 AND password_hash IS NOT NULL AND requested_tenant_id IN ('bajaj', 'tata', 'apparel')"
    )
    params = ()
    if tenant is not None:
        query += " AND requested_tenant_id = ?"
        params = (tenant,)
    with _auth_db() as conn:
        return [dict(row) for row in conn.execute(query + " ORDER BY created_at, id", params).fetchall()]


def approve_access_request(user_id: str, administrator: dict[str, Any]) -> dict[str, Any]:
    require_admin(administrator)
    with _auth_db() as conn:
        applicant = _user_profile(conn, user_id)
        if not applicant:
            raise HTTPException(status_code=404, detail="Active applicant not found.")
        tenant = applicant["requested_tenant_id"]
        if applicant["tenant_id"] != "unassigned" or applicant["role"] != "operator" or tenant not in REQUESTABLE_TENANTS:
            raise HTTPException(status_code=409, detail="No pending organization access request.")
        require_tenant_access(tenant, administrator)
        updated = conn.execute(
            "UPDATE users SET tenant_id = ?, role = 'operator', requested_tenant_id = NULL "
            "WHERE id = ? AND tenant_id = 'unassigned' AND role = 'operator' "
            "AND is_active = 1 AND requested_tenant_id = ?",
            (tenant, user_id, tenant),
        )
        if updated.rowcount != 1:
            raise HTTPException(status_code=409, detail="Account or access request changed; refresh the applicant list.")
        return _user_profile(conn, user_id)

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
