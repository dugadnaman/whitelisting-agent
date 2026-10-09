"""Strict, offline authentication and provisioning regressions using real DB users/JWTs."""

import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api
import auth
import db
import sys
from types import ModuleType


def test_auth_database_outage_never_falls_back_to_sqlite(client, provision_user, monkeypatch):
    user, headers = provision_user()
    driver, extras = ModuleType("psycopg2"), ModuleType("psycopg2.extras")
    driver.__path__ = []
    extras.DictCursor = object
    driver.extras = extras
    with patch.dict(sys.modules, {"psycopg2": driver, "psycopg2.extras": extras}), patch.object(
        driver, "connect", create=True, side_effect=ConnectionError("offline configured database")
    ) as connect:
        monkeypatch.setattr(db, "get_database_url", lambda: "postgresql://test.invalid/test")
        assert client.get("/api/auth/me", headers=headers).status_code == 503
        assert client.post("/api/auth/login", json={"email": user["email"], "password": "Test-only-password-456!"}).status_code == 503
        with pytest.raises(HTTPException) as denied:
            auth.register_user("outage@example.com", "Outage-password-123", "Outage", "apparel")
        assert denied.value.status_code == 503
        with pytest.raises(HTTPException):
            auth.reset_password(user["email"], "Outage-password-123")
        assert connect.call_count == 4


@pytest.mark.parametrize("path", ["/api/activity/stats", "/api/sample-csv", "/api/users", "/api/work-management/projects", "/api/nonexistent"])
def test_global_api_guard_covers_legacy_handlers(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer invalid", "X-User": "admin@example.com"}).status_code == 401


def test_verified_identity_is_loaded_once_per_request(client, provision_user):
    _, headers = provision_user()
    with patch("auth.get_user_profile", wraps=auth.get_user_profile) as profile:
        assert client.get("/api/auth/me", headers=headers).status_code == 200
        assert profile.call_count == 1


def test_public_media_never_serves_config_source_or_arbitrary_root_files(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cache = tmp_path / "media_cache"
    cache.mkdir()
    monkeypatch.setattr(api, "MEDIA_CACHE_DIR", cache)
    fake_secret = b"synthetic-regression-secret"
    for filename in (".env", "credentials.json", "api.py", "unapproved.jpg"):
        (tmp_path / filename).write_bytes(fake_secret)
    (cache / "credentials.json").write_bytes(fake_secret)
    (cache / "misleading.png").write_bytes(fake_secret)
    (cache / "escape.png").symlink_to(tmp_path / ".env")
    with patch("jira_client.download_jira_attachment") as download:
        for filename in (".env", "credentials.json", "api.py", "unapproved.jpg", "misleading.png", "escape.png", "jira_123_unseen.png"):
            response = client.get(f"/api/media/{filename}")
            assert response.status_code == 404
            assert fake_secret not in response.content
        download.assert_not_called()
    image = b"\x89PNG\r\n\x1a\n" + b"\0" * 16
    (cache / "approved.png").write_bytes(image)
    response = client.get("/api/media/approved.png")
    assert response.status_code == 200 and response.content == image
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.head("/api/media/approved.png").status_code == 200
    (tmp_path / "default_sample_header.png").write_bytes(image)
    assert client.get("/api/media/default_sample_header.png").status_code == 200


def test_webhook_without_explicit_secret_has_no_known_default(client, monkeypatch):
    monkeypatch.delenv("BAJAJ_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("KARIX_WEBHOOK_SECRET", raising=False)
    with patch("submission_client.check_status") as probe:
        assert client.post("/api/webhooks/karix/bajaj", json={}).status_code == 401
        assert client.post("/api/webhooks/karix/bajaj", headers={"X-Webhook-Token": "karix_webhook_secret_2026"}, json={}).status_code == 503
        probe.assert_not_called()


@pytest.fixture
def client(provision_user):
    assert api.get_current_user not in api.app.dependency_overrides
    return TestClient(api.app)


def test_provision_login_and_verified_identity(client, provision_user):
    user, headers = provision_user(role="admin")
    login = client.post("/api/auth/login", json={"email": user["email"], "password": "Test-only-password-456!"})
    assert login.status_code == 200
    assert login.json()["user"]["id"] == user["id"]
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["sub"] == me.json()["id"] == user["id"]
    assert me.json()["tenant_id"] == "apparel"
    assert "password_hash" not in me.json()


@pytest.mark.parametrize("authorization", [None, "Bearer malformed", "Basic fake", "Bearer", "Bearer unsigned.jwt.value"])
def test_missing_malformed_and_invalid_tokens_rejected(client, authorization):
    headers = {"X-User": "admin@example.com"}
    if authorization is not None:
        headers["Authorization"] = authorization
    for path in ("/api/auth/me", "/api/accounts", "/api/credentials?account=apparel"):
        response = client.get(path, headers=headers)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


def test_expired_and_missing_required_claims_rejected(client, provision_user):
    user, _ = provision_user()
    expired = auth.create_access_token(user["id"], user["email"], "apparel", "operator", user["name"], timedelta(seconds=-1))
    without_exp = jwt.encode({"sub": user["id"], "iat": datetime.now(UTC)}, auth.configured_jwt_secret(), algorithm="HS256")
    wrong_key = jwt.encode({"sub": user["id"], "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1)}, "other-unrelated-strong-signing-key-123456789", algorithm="HS256")
    for token in (expired, without_exp, wrong_key):
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_revocation_and_current_database_permissions(client, provision_user):
    user, headers = provision_user(role="admin")
    with db.get_db() as conn:
        conn.execute("UPDATE users SET role = 'operator', tenant_id = 'bajaj' WHERE id = ?", (user["id"],))
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["role"] == "operator" and me["tenant_id"] == "bajaj"
    assert client.get("/api/auth/team?tenant_id=apparel", headers=headers).status_code == 403
    assert client.post("/api/auth/team/invite", headers=headers, json={"email": "colleague@example.com", "name": "Colleague", "password": "Colleague-password-123"}).status_code == 403
    with db.get_db() as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user["id"],))
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.post("/api/auth/login", json={"email": user["email"], "password": "Test-only-password-456!"}).status_code == 401
    with db.get_db() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    assert client.get("/api/auth/me", headers=headers).status_code == 401


@pytest.mark.parametrize("role", ["operator", "admin", "superadmin"])
def test_public_signup_cannot_assign_privileges(client, role):
    response = client.post("/api/auth/signup", json={"email": "attacker@example.com", "password": "Attacker-password-123", "name": "Attacker", "tenant_id": "apparel", "role": role})
    assert response.status_code == 422
    with db.get_db() as conn:
        assert conn.execute("SELECT id FROM users WHERE email = 'attacker@example.com'").fetchone() is None


def test_legacy_password_login_stays_pending_until_company_approval(client, provision_user):
    legacy, _ = provision_user(email="legacy@example.com")
    with db.get_db() as conn:
        conn.execute("UPDATE users SET tenant_id = ' ALL ', role = 'Operator', email = ? WHERE id = ?", (" \tLegacy@Example.com\n ", legacy["id"]))
        before = dict(conn.execute("SELECT * FROM users WHERE id = ?", (legacy["id"],)).fetchone())
    auth.init_auth_db()
    auth.init_auth_db()
    with db.get_db() as conn:
        migrated = dict(conn.execute("SELECT * FROM users WHERE id = ?", (legacy["id"],)).fetchone())
    assert migrated["tenant_id"] == "unassigned" and migrated["role"] == "operator"
    assert {key: value for key, value in migrated.items() if key not in ("tenant_id", "role")} == {
        key: value for key, value in before.items() if key not in ("tenant_id", "role")
    }
    credentials = {"email": " LEGACY@example.com ", "password": "Test-only-password-456!"}
    assert client.post("/api/auth/login", json={**credentials, "password": "Wrong-password-123!"}).status_code == 401
    login = client.post("/api/auth/login", json=credentials)
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    assert client.get("/api/auth/me", headers=headers).json()["requested_tenant_id"] is None
    for path in (
        "/api/users", "/api/activity/stats", "/api/accounts", "/api/auth/team",
        "/api/stats?account=apparel", "/api/stats?account=unassigned", "/api/stats?account=all",
        "/api/work-management/projects", "/api/auth/access-requests", "/api/nonexistent",
    ):
        assert client.get(path, headers=headers).status_code == 403, path
    assert client.post("/api/accounts", headers=headers, json={"name": "Unapproved"}).status_code == 403
    with pytest.raises(ValueError, match="already exists"):
        auth.register_user("legacy@example.com", "Replacement-password-123!", "Replacement", "apparel")
    requested = client.post("/api/auth/access-requests", headers=headers, json={"tenant_id": "tata"})
    assert requested.status_code == 200 and set(requested.json()) == {"user"}
    assert requested.json()["user"]["tenant_id"] == "unassigned"
    administrator, admin_headers = provision_user("tata", "admin", email="tata-admin@example.com")
    applications = client.get("/api/auth/access-requests", headers=admin_headers)
    assert applications.status_code == 200
    assert [user["id"] for user in applications.json()] == [legacy["id"]]
    approved = client.post(f"/api/auth/access-requests/{legacy['id']}/approve", headers=admin_headers)
    assert approved.status_code == 200 and set(approved.json()) == {"user"}
    assert approved.json()["user"]["tenant_id"] == "tata"
    assert approved.json()["user"]["role"] == "operator"
    assert approved.json()["user"]["requested_tenant_id"] is None
    assert "password_hash" not in approved.json()["user"]
    assert client.get("/api/auth/me", headers=admin_headers).json()["id"] == administrator["id"]
    assert client.get("/api/auth/me", headers=headers).json()["tenant_id"] == "tata"
    assert client.post("/api/auth/login", json=credentials).json()["user"]["tenant_id"] == "tata"
    assert client.post("/api/auth/access-requests", headers=headers, json={"tenant_id": "bajaj"}).status_code == 403
    with patch("api.load_accounts", return_value=[{"id": "tata", "name": "Tata"}, {"id": "apparel", "name": "Apparel"}]), patch("api.get_rcs_bot_id", return_value=""):
        assert [account["id"] for account in client.get("/api/accounts", headers=headers).json()] == ["tata"]
    with db.get_db() as conn:
        final = dict(conn.execute("SELECT * FROM users WHERE id = ?", (legacy["id"],)).fetchone())
    for key in ("id", "password_hash", "email", "name", "created_at", "is_active"):
        assert final[key] == before[key]


def test_signup_duplicate_preservation_and_company_approval_boundary(client, provision_user):
    body = {"email": " Applicant@Example.com ", "password": "Applicant-password-123!", "name": "Applicant", "tenant_id": "apparel"}
    signup = client.post("/api/auth/signup", json=body)
    assert signup.status_code == 201
    applicant = signup.json()["user"]
    headers = {"Authorization": f"Bearer {signup.json()['token']}"}
    assert applicant["email"] == "applicant@example.com"
    assert applicant["tenant_id"] == "unassigned" and applicant["role"] == "operator"
    assert applicant["requested_tenant_id"] == "apparel"
    with db.get_db() as conn:
        before = dict(conn.execute("SELECT * FROM users WHERE id = ?", (applicant["id"],)).fetchone())
    assert before["is_active"] == 1 and auth.verify_password(body["password"], before["password_hash"])
    duplicate = client.post("/api/auth/signup", json={**body, "email": "APPLICANT@example.com", "password": "Replacement-password-123!", "name": "Replacement", "tenant_id": "bajaj"})
    assert duplicate.status_code == 400 and "already exists" in duplicate.json()["detail"]
    with db.get_db() as conn:
        assert dict(conn.execute("SELECT * FROM users WHERE id = ?", (applicant["id"],)).fetchone()) == before
        assert conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 1
    assert client.post("/api/auth/login", json={"email": applicant["email"], "password": "Replacement-password-123!"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": applicant["email"], "password": body["password"]}).status_code == 200
    assert client.get("/api/users", headers=headers).status_code == 403
    _, other_headers = provision_user("bajaj", "admin", email="other-admin@example.com")
    _, own_headers = provision_user("apparel", "admin", email="own-admin@example.com")
    _, operator_headers = provision_user("apparel", "operator", email="operator@example.com")
    assert client.get("/api/auth/access-requests", headers=other_headers).json() == []
    assert client.get("/api/auth/access-requests?tenant_id=apparel", headers=other_headers).status_code == 403
    assert client.post(f"/api/auth/access-requests/{applicant['id']}/approve", headers=other_headers).status_code == 403
    assert client.post(f"/api/auth/access-requests/{applicant['id']}/approve", headers=operator_headers).status_code == 403
    assert client.get("/api/auth/me", headers=headers).json()["tenant_id"] == "unassigned"
    approved = client.post(f"/api/auth/access-requests/{applicant['id']}/approve", headers=own_headers)
    assert approved.status_code == 200 and set(approved.json()) == {"user"}
    assert approved.json()["user"]["tenant_id"] == "apparel"
    assert client.get("/api/auth/me", headers=headers).json()["tenant_id"] == "apparel"
    assert client.post("/api/auth/login", json={"email": applicant["email"], "password": body["password"]}).json()["user"]["tenant_id"] == "apparel"
    assert client.post(f"/api/auth/access-requests/{applicant['id']}/approve", headers=own_headers).status_code == 409


@pytest.mark.parametrize("tenant_id", ["all", "unassigned", "tchfl", "unknown", ""])
def test_signup_rejects_unsupported_requested_company(client, tenant_id):
    response = client.post("/api/auth/signup", json={
        "email": "invalid-request@example.com", "password": "Applicant-password-123!", "name": "Applicant", "tenant_id": tenant_id,
    })
    assert response.status_code == 422
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0


def test_access_request_competing_updates_do_not_approve_stale_company(client, provision_user):
    pending = auth.register_user("race@example.com", "Race-password-123!", "Race", "unassigned", requested_tenant_id="apparel")
    _, admin_headers = provision_user("apparel", "admin")
    original_profile = auth._user_profile

    def changed_request(conn, user_id):
        profile = original_profile(conn, user_id)
        if user_id == pending["id"]:
            with db.get_db() as competing:
                competing.execute("UPDATE users SET requested_tenant_id = 'bajaj' WHERE id = ?", (user_id,))
        return profile

    with patch("auth._user_profile", side_effect=changed_request):
        approval = client.post(f"/api/auth/access-requests/{pending['id']}/approve", headers=admin_headers)
    assert approval.status_code == 409
    current = auth.get_user_profile(pending["id"])
    assert current["tenant_id"] == "unassigned" and current["requested_tenant_id"] == "bajaj"
    with pytest.raises(HTTPException) as conflict:
        auth.request_organization_access({**current, "requested_tenant_id": "apparel"}, "tata")
    assert conflict.value.status_code == 409
    assert auth.get_user_profile(pending["id"]) == current


def test_superadmin_can_list_and_filter_active_pending_requests(client, provision_user):
    _, headers = provision_user("all", "superadmin")
    applicants = [
        auth.register_user(f"pending-{tenant}@example.com", "Applicant-password-123!", tenant, "unassigned", requested_tenant_id=tenant)
        for tenant in ("bajaj", "tata", "apparel")
    ]
    with db.get_db() as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (applicants[0]["id"],))
    listing = client.get("/api/auth/access-requests", headers=headers)
    assert listing.status_code == 200
    assert {user["requested_tenant_id"] for user in listing.json()} == {"tata", "apparel"}
    filtered = client.get("/api/auth/access-requests?tenant_id=tata", headers=headers)
    assert [user["id"] for user in filtered.json()] == [applicants[1]["id"]]
    assert client.get("/api/auth/access-requests?tenant_id=all", headers=headers).status_code == 400
    assert client.post(f"/api/auth/access-requests/{applicants[0]['id']}/approve", headers=headers).status_code == 404
    assert client.post(f"/api/auth/access-requests/{applicants[1]['id']}/approve", headers=headers).json()["user"]["tenant_id"] == "tata"


@pytest.mark.parametrize("tenant,role,active,expected_tenant,expected_role", [
    (" ALL ", "Admin", 0, "unassigned", "operator"),
    (" TATA ", "Admin", 1, "tata", "admin"),
    (" ALL ", "SuperAdmin", 1, "all", "superadmin"),
    ("Custom_Company", "Operator", 1, "custom_company", "operator"),
])
def test_legacy_scope_normalization_preserves_password_and_active_state(provision_user, tenant, role, active, expected_tenant, expected_role):
    user, _ = provision_user()
    with db.get_db() as conn:
        conn.execute("UPDATE users SET tenant_id = ?, role = ?, is_active = ? WHERE id = ?", (tenant, role, active, user["id"]))
        before = dict(conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone())
    auth.init_auth_db()
    auth.init_auth_db()
    with db.get_db() as conn:
        after = dict(conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone())
    assert after == {**before, "tenant_id": expected_tenant, "role": expected_role}
    login = auth.authenticate_user(user["email"], "Test-only-password-456!")
    assert bool(login) == bool(active)
    with pytest.raises(ValueError, match="already exists"):
        auth.register_user(user["email"].upper(), "Replacement-password-123!", "Replacement", "apparel")


def test_old_sqlite_user_schema_adds_nullable_request_without_reset(provision_user, tmp_path, monkeypatch):
    path = tmp_path / "old-schema.db"
    password_hash = auth.hash_password("Legacy-password-123!")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT UNIQUE, password_hash TEXT, name TEXT NOT NULL, "
            "tenant_id TEXT NOT NULL, role TEXT, created_at TEXT NOT NULL, last_login TEXT, is_active INTEGER)"
        )
        conn.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            "legacy-id", "legacy-schema@example.com", password_hash, "Legacy", "all", "Operator", "2020-01-01", "2020-02-01", 1,
        ))
    monkeypatch.setattr(db, "DEFAULT_SQLITE_PATH", path)
    auth.init_auth_db()
    auth.init_auth_db()
    with db.get_db() as conn:
        row = dict(conn.execute("SELECT * FROM users WHERE id = 'legacy-id'").fetchone())
    assert row["requested_tenant_id"] is None
    assert row["tenant_id"] == "unassigned" and row["role"] == "operator"
    assert row["password_hash"] == password_hash and row["is_active"] == 1
    assert row["created_at"] == "2020-01-01" and row["last_login"] == "2020-02-01"
    assert auth.authenticate_user(row["email"], "Legacy-password-123!")["user"]["id"] == "legacy-id"




def test_retained_account_authentication_is_cwd_independent(provision_user, tmp_path, monkeypatch):
    root = tmp_path / "repository"
    (root / "backend").mkdir(parents=True)
    (root / "data").mkdir()
    retained = root / "data" / "karix_store.db"
    conflicting = root / "backend" / "karix_store.db"
    conflicting.write_bytes(b"untouched-conflicting-store")
    monkeypatch.delenv("KARIX_DB_PATH", raising=False)
    monkeypatch.chdir(root)
    monkeypatch.setattr(db, "__file__", str(root / "backend" / "db.py"))
    monkeypatch.setattr(db, "DEFAULT_SQLITE_PATH", retained)
    auth.init_auth_db()
    user, _ = provision_user(email="retained@example.com")
    for directory in (root, root / "backend", tmp_path):
        monkeypatch.chdir(directory)
        assert db._resolve_default_db_path() == retained
        monkeypatch.setattr(db, "DEFAULT_SQLITE_PATH", db._resolve_default_db_path())
        login = auth.authenticate_user(user["email"], "Test-only-password-456!")
        assert login["user"]["id"] == user["id"] and login["user"]["tenant_id"] == "apparel"
    assert conflicting.read_bytes() == b"untouched-conflicting-store"


def test_empty_placeholders_do_not_hide_existing_backend_accounts(provision_user, tmp_path, monkeypatch):
    root = tmp_path / "repository"
    (root / "backend").mkdir(parents=True)
    (root / "data").mkdir()
    retained = root / "backend" / "karix_store.db"
    monkeypatch.setattr(db, "__file__", str(root / "backend" / "db.py"))
    monkeypatch.setattr(db, "DEFAULT_SQLITE_PATH", retained)
    auth.init_auth_db()
    user, _ = provision_user(email="retained-backend@example.com")
    (root / "data" / "karix_store.db").touch()
    (root / "karix_store.db").touch()
    monkeypatch.delenv("KARIX_DB_PATH", raising=False)
    monkeypatch.chdir(root)
    monkeypatch.setattr(db, "DEFAULT_SQLITE_PATH", db._resolve_default_db_path())
    auth.init_auth_db()
    login = auth.authenticate_user(user["email"], "Test-only-password-456!")
    assert login is not None
    assert login["user"]["id"] == user["id"]


@pytest.mark.parametrize("process_url", [None, "postgresql://process.invalid/accounts"])
def test_auth_schema_initialization_loads_file_config_before_strict_connection(provision_user, tmp_path, monkeypatch, process_url):
    (tmp_path / ".env").write_text("DATABASE_URL=postgresql://file.invalid/accounts\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if process_url is not None:
        monkeypatch.setenv("DATABASE_URL", process_url)

    def unavailable(*, strict_backend):
        assert strict_backend is True
        assert auth.os.environ["DATABASE_URL"] == (process_url or "postgresql://file.invalid/accounts")
        raise RuntimeError("Configured PostgreSQL database is unavailable.")

    with patch("auth._get_db", side_effect=unavailable):
        with pytest.raises(HTTPException) as failure:
            auth.init_auth_db()
    assert failure.value.status_code == 503


@pytest.mark.parametrize("account", ["apparel", "tata", "bajaj", "unassigned", "all"])
def test_pending_identity_never_has_company_or_admin_permissions(account):
    pending = {"tenant_id": "unassigned", "role": "operator"}
    with pytest.raises(HTTPException) as failure:
        auth.require_tenant_access(account, pending)
    assert failure.value.status_code == 403
    with pytest.raises(HTTPException):
        auth.require_admin(pending)


def test_authorized_staff_provisioning_does_not_replace_admin_session(client, provision_user):
    admin, headers = provision_user(role="admin")
    response = client.post("/api/auth/team/invite", headers=headers, json={"email": "staff@example.com", "password": "Staff-password-123", "name": "Staff", "role": "operator"})
    assert response.status_code == 200
    assert set(response.json()) == {"user"}
    assert response.json()["user"]["tenant_id"] == "apparel"
    assert client.get("/api/auth/me", headers=headers).json()["id"] == admin["id"]
    login = client.post("/api/auth/login", json={"email": "staff@example.com", "password": "Staff-password-123"})
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "operator"
    team = client.get("/api/auth/team", headers=headers)
    assert {user["email"] for user in team.json()} == {admin["email"], "staff@example.com"}


@pytest.mark.parametrize("tenant,role,status", [("bajaj", "operator", 403), ("apparel", "superadmin", 400), ("all", "admin", 403), ("apparel", "owner", 400)])
def test_admin_cannot_cross_tenants_or_grant_superadmin(client, provision_user, tenant, role, status):
    _, headers = provision_user(role="admin")
    response = client.post("/api/auth/team/invite", headers=headers, json={"email": "escalation@example.com", "password": "Escalation-password-123", "name": "Escalation", "tenant_id": tenant, "role": role})
    assert response.status_code == status


def test_superadmin_must_select_concrete_tenant_for_staff(client, provision_user):
    _, headers = provision_user("all", "superadmin")
    body = {"email": "new-admin@example.com", "password": "New-admin-password-123", "name": "Company Admin", "role": "admin"}
    assert client.post("/api/auth/team/invite", headers=headers, json=body).status_code == 400
    response = client.post("/api/auth/team/invite", headers=headers, json={**body, "tenant_id": "apparel"})
    assert response.status_code == 200
    assert response.json()["user"]["tenant_id"] == "apparel"
    assert client.get("/api/auth/team?tenant_id=apparel", headers=headers).json()[0]["email"] == body["email"]


@pytest.mark.parametrize("tenant,target,allowed", [("bajaj", "tata", False), ("apparel", "bajaj", False), ("tata", "tchfl", True), ("tata", "all", False), ("all", "bajaj", False), ("apparel", "apparel", True)])
def test_only_actual_superadmin_has_all_scope(tenant, target, allowed):
    user = {"tenant_id": tenant, "role": "operator"}
    if allowed:
        auth.require_tenant_access(target, user)
    else:
        with pytest.raises(HTTPException) as denied:
            auth.require_tenant_access(target, user)
        assert denied.value.status_code == 403
    auth.require_tenant_access(target, {"tenant_id": "all", "role": "superadmin"})


def test_cross_tenant_accounts_stats_and_copilot_rejected(client, provision_user):
    _, headers = provision_user("bajaj")
    for path in ("/api/auth/team?tenant_id=tata", "/api/stats?account=tata", "/api/templates?account=tata", "/api/credentials?account=tata"):
        assert client.get(path, headers=headers).status_code == 403
    assert client.post("/api/agent/chat", headers=headers, json={"message": "List Tata templates", "account": "tata"}).status_code == 403
    with patch("api.load_accounts", return_value=[{"id": "bajaj", "name": "Bajaj"}, {"id": "apparel", "name": "Apparel"}]), patch("api.get_rcs_bot_id", return_value=""):
        assert [account["id"] for account in client.get("/api/accounts", headers=headers).json()] == ["bajaj"]


def test_operators_cannot_read_change_or_test_credentials(client, provision_user):
    _, headers = provision_user()
    with patch("api._load_env_file") as env_loader, patch("api._commit_credentials_to_github") as persist, patch("moengage_sync.get_moengage_credentials") as credentials:
        assert client.get("/api/credentials?account=apparel", headers=headers).status_code == 403
        assert client.put("/api/credentials", headers=headers, json={"account": "apparel", "channel": "rcs", "rcs_auth_token": "do-not-write"}).status_code == 403
        assert client.post("/api/test-credentials?account=apparel", headers=headers).status_code == 403
        assert client.get("/api/moengage/credentials?account=apparel", headers=headers).status_code == 403
        assert client.put("/api/moengage/credentials", headers=headers, json={"account": "apparel", "bearer_token": "do-not-write"}).status_code == 403
        env_loader.assert_not_called()
        persist.assert_not_called()
        credentials.assert_not_called()
    assert client.post("/api/accounts", headers=headers, json={"name": "Escalated company"}).status_code == 403
    assert client.delete("/api/accounts/bajaj", headers=headers).status_code == 403
    assert client.post("/api/gemini/test", headers=headers, json={"api_key": "do-not-write"}).status_code == 403


@pytest.mark.parametrize("email,bypass", [("dugadnaman@gmail.com", "namandugad13"), ("namandugad46@gmail.com", "Naman@123"), ("neel.shah@attributics.com", "Neel@123"), ("aadya.trivedi@attributics.com", "Password@123")])
def test_known_password_bypasses_and_duplicate_resets_removed(client, provision_user, email, bypass):
    user, _ = provision_user(email=email)
    assert client.post("/api/auth/login", json={"email": email, "password": bypass}).status_code == 401
    with pytest.raises(ValueError, match="already exists"):
        auth.register_user(email, "Replacement-password-123", "Attacker", "all", "superadmin")
    assert auth.authenticate_user(email, "Test-only-password-456!")["user"]["id"] == user["id"]


def test_schema_initialization_preserves_users_and_never_seeds(provision_user):
    user, _ = provision_user()
    with db.get_db() as conn:
        before = dict(conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone())
    auth.init_auth_db()
    with db.get_db() as conn:
        assert dict(conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()) == before
        assert conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 1


def test_explicit_password_rotation_preserves_identity_and_permissions(provision_user):
    user, _ = provision_user(role="admin")
    with db.get_db() as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user["id"],))
        before = dict(conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone())
    auth.reset_password(user["email"], "Rotated-password-123!")
    with db.get_db() as conn:
        after = dict(conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone())
    assert {key: value for key, value in before.items() if key != "password_hash"} == {key: value for key, value in after.items() if key != "password_hash"}
    assert auth.verify_password("Rotated-password-123!", after["password_hash"])
    assert not auth.verify_password("Test-only-password-456!", after["password_hash"])


def test_getpass_bootstrap_cli_and_explicit_rotation(provision_user, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["auth.py", "--email", "bootstrap@example.com", "--name", "Company Admin", "--tenant", "apparel"])
    with patch("auth.getpass.getpass", return_value="Bootstrap-password-123!"):
        auth.bootstrap_cli()
    login = auth.authenticate_user("bootstrap@example.com", "Bootstrap-password-123!")
    assert login["user"]["role"] == "admin" and login["user"]["tenant_id"] == "apparel"
    monkeypatch.setattr("sys.argv", ["auth.py", "--reset-password", "--email", "bootstrap@example.com"])
    with patch("auth.getpass.getpass", return_value="Rotated-password-123!"):
        auth.bootstrap_cli()
    assert auth.authenticate_user("bootstrap@example.com", "Bootstrap-password-123!") is None
    assert auth.authenticate_user("bootstrap@example.com", "Rotated-password-123!")["user"]["id"] == login["user"]["id"]
    output = capsys.readouterr().out
    assert "Bootstrap-password" not in output and "Rotated-password" not in output


@pytest.mark.parametrize("secret", ["", "short", "x" * 64, "karix_whitelisting_secure_jwt_secret_key_2026_prod"])
def test_unconfigured_or_weak_secret_fails_closed(client, provision_user, monkeypatch, secret):
    user, headers = provision_user()
    monkeypatch.setenv("JWT_SECRET", secret)
    assert client.get("/api/auth/me", headers=headers).status_code == 503
    assert client.post("/api/auth/login", json={"email": user["email"], "password": "Test-only-password-456!"}).status_code == 503
    signup = client.post("/api/auth/signup", json={
        "email": "unavailable-signup@example.com", "password": "Signup-password-456!",
        "name": "New Colleague", "tenant_id": "apparel",
    })
    assert signup.status_code == 503
    with db.get_db() as conn:
        assert conn.execute("SELECT id FROM users WHERE email = ?", ("unavailable-signup@example.com",)).fetchone() is None
    assert client.get("/healthz").status_code == 200


def test_sample_content_variables_use_tata_capital():
    from loader import infer_whatsapp_cta
    from submission_client import _resolve_button_cta_variables, normalize_whatsapp_text_variables

    _, samples = normalize_whatsapp_text_variables("Offer from {{1}}. Terms & conditions apply.")
    assert "Tata Capital" in samples and "Bajaj Markets" not in samples
    _, samples_fallback = normalize_whatsapp_text_variables("Check {{1}} and {{2}}.")
    assert "Tata Capital" in samples_fallback and "Bajaj Markets" not in samples_fallback
    buttons = [{"type": "URL", "url": "https://1kx.in"}]
    _resolve_button_cta_variables(buttons, client="bajaj")
    assert any("tatacapital.com" in example for example in buttons[0].get("example", []))
    assert not any("bajajfinservmarkets" in example for example in buttons[0].get("example", []))
    _, _, example_url = infer_whatsapp_cta("Special offer")
    assert "tatacapital.com" in example_url and "bajajfinservmarkets" not in example_url
