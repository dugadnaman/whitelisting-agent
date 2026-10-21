"""Offline Google login regressions: real RSA signatures, real users, no provider traffic."""

import base64
import json
import time
from unittest.mock import Mock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.exceptions import PyJWKClientConnectionError

import api
import auth
import db
import google_signin as google

CLIENT_ID = "offline-test.apps.googleusercontent.com"
ORIGIN = "http://localhost:3000"
EMAIL = "member@attributics.com"


@pytest.fixture(scope="module")
def google_keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update(kid="offline-rsa", alg="RS256", use="sig")
    return private, jwk


@pytest.fixture
def client(provision_user, monkeypatch, google_keys):
    monkeypatch.setenv("KARIX_GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("KARIX_GOOGLE_ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.delenv("KARIX_GOOGLE_ALLOWED_DOMAINS", raising=False)
    monkeypatch.setattr(google, "_load_env_file", lambda: None)
    jwks = jwt.PyJWKClient(google.GOOGLE_JWKS_URL)
    monkeypatch.setattr(jwks, "fetch_data", lambda: {"keys": [google_keys[1]]})
    monkeypatch.setattr(google, "GOOGLE_JWKS_CLIENT", jwks)
    return TestClient(api.app)


@pytest.fixture
def google_token(google_keys):
    def signed(nonce, *, claims=None, remove=(), headers=None):
        now = int(time.time())
        payload = {
            "iss": "https://accounts.google.com", "aud": CLIENT_ID,
            "iat": now - 1, "exp": now + 300, "sub": "google-offline-subject",
            "email": EMAIL, "email_verified": True, "hd": "attributics.com", "nonce": nonce,
        }
        payload.update(claims or {})
        for name in remove:
            payload.pop(name, None)
        return jwt.encode(payload, google_keys[0], algorithm="RS256", headers={"kid": "offline-rsa", **(headers or {})})
    return signed


def start(client, origin=ORIGIN):
    response = client.post("/api/auth/google/start", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return response.json()["nonce"]


def login(client, credential, origin=ORIGIN):
    response = client.post("/api/auth/google", headers={"Origin": origin}, json={"credential": credential})
    assert response.headers["cache-control"] == "no-store"
    if response.status_code != 200:
        assert credential not in response.text
    return response


def stored(user_id):
    with db.get_db() as conn:
        return dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def test_existing_user_preserves_password_permissions_and_updates_last_login(client, provision_user, google_token):
    user, _ = provision_user(tenant="tata", role="admin", email=EMAIL)
    with db.get_db() as conn:
        conn.execute("UPDATE users SET last_login = NULL WHERE id = ?", (user["id"],))
    before = stored(user["id"])
    nonce = start(client)
    cookie = client.cookies.get(google.CHALLENGE_COOKIE)
    assert auth.decode_access_token(cookie) is None
    with patch.object(api, "log_activity") as activity:
        response = login(client, google_token(nonce, claims={"tenant_id": "all", "role": "superadmin", "name": "Untrusted provider metadata"}))
    assert response.status_code == 200
    result = response.json()
    assert set(result) == {"user", "token"}
    assert result["user"]["id"] == user["id"]
    assert "password_hash" not in result["user"]
    payload = auth.decode_access_token(result["token"])
    assert (payload["sub"], payload["tenant_id"], payload["role"]) == (user["id"], "tata", "admin")
    after = stored(user["id"])
    assert after["last_login"] and result["user"]["last_login"] == after["last_login"]
    assert {key: value for key, value in before.items() if key != "last_login"} == {
        key: value for key, value in after.items() if key != "last_login"
    }
    assert client.cookies.get(google.CHALLENGE_COOKIE) is None
    assert activity.call_args.kwargs["details"]["auth_provider"] == "google"
    assert activity.call_args.kwargs["action"] == "USER_LOGIN"
    headers = {"Authorization": f"Bearer {result['token']}"}
    assert client.get("/api/auth/me", headers=headers).json()["tenant_id"] == "tata"
    password = client.post("/api/auth/login", json={"email": EMAIL, "password": "Test-only-password-456!"})
    assert password.status_code == 200 and password.json()["user"]["id"] == user["id"]
    assert login(client, google_token(nonce)).status_code == 401


def test_pending_identity_is_not_admitted_by_domain(client, provision_user, google_token):
    user, _ = provision_user("unassigned", email=EMAIL)
    with db.get_db() as conn:
        conn.execute("UPDATE users SET requested_tenant_id = 'apparel' WHERE id = ?", (user["id"],))
    response = login(client, google_token(start(client)))
    assert response.status_code == 200
    result = response.json()
    assert (result["user"]["tenant_id"], result["user"]["role"], result["user"]["requested_tenant_id"]) == ("unassigned", "operator", "apparel")
    headers = {"Authorization": f"Bearer {result['token']}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    for path in ("/api/accounts", "/api/auth/team", "/api/stats?account=apparel", "/api/work-management/projects"):
        assert client.get(path, headers=headers).status_code == 403


@pytest.mark.parametrize("changes,remove", [
    ({"iss": "https://attacker.invalid"}, ()),
    ({"aud": "another-client.apps.googleusercontent.com"}, ()),
    ({"aud": [CLIENT_ID, "other"]}, ()),
    ({"azp": "other"}, ()),
    ({"exp": 1}, ()),
    ({"iat": 4102444800}, ()),
    ({"iat": "1"}, ()),
    ({"iat": True}, ()),
    ({"exp": "4102444800"}, ()),
    ({"sub": ""}, ()),
    ({"sub": 123}, ()),
    ({"nonce": "another-browser"}, ()),
    ({"nonce": ["invalid"]}, ()),
    ({"email_verified": False}, ()),
    ({"email_verified": "true"}, ()),
    ({"email_verified": 1}, ()),
    ({"email": "member@external.invalid", "hd": "external.invalid"}, ()),
    ({"email": "member@attributics.com.evil.invalid", "hd": "attributics.com.evil.invalid"}, ()),
    ({"email": " member@attributics.com"}, ()),
    ({"hd": "different.invalid"}, ()),
    ({"hd": ["attributics.com"]}, ()),
    ({}, ("hd",)),
    ({}, ("iss",)),
    ({}, ("aud",)),
    ({}, ("exp",)),
    ({}, ("iat",)),
    ({}, ("sub",)),
    ({}, ("nonce",)),
    ({}, ("email_verified",)),
    ({}, ("email",)),
])
def test_invalid_identity_claims_fail_closed(client, provision_user, google_token, changes, remove):
    user, _ = provision_user(email=EMAIL)
    before = stored(user["id"])
    credential = google_token(start(client), claims=changes, remove=remove)
    assert login(client, credential).status_code == 401
    assert stored(user["id"]) == before


def test_bad_signature_algorithm_and_unknown_key_fail_closed(client, google_token):
    credential = google_token(start(client))
    parts = credential.split(".")
    signature = bytearray(base64.urlsafe_b64decode(parts[2] + "=="))
    signature[0] ^= 1
    parts[2] = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    assert login(client, ".".join(parts)).status_code == 401
    assert login(client, jwt.encode({"sub": "fake"}, "offline-unsigned-key-not-accepted", algorithm="HS256", headers={"kid": "offline-rsa"})).status_code == 401
    assert login(client, google_token(start(client), headers={"kid": "unknown"})).status_code == 401
    assert login(client, "malformed.jwt.credential").status_code == 401


def test_valid_audience_azp_issuer_and_ignored_key_urls(client, provision_user, google_token):
    provision_user(email=EMAIL)
    credential = google_token(start(client), claims={"iss": "accounts.google.com", "aud": [CLIENT_ID, "other"], "azp": CLIENT_ID}, headers={"jku": "https://attacker.invalid/keys", "x5u": "file:///not-a-key"})
    assert google.GOOGLE_JWKS_CLIENT.uri == "https://www.googleapis.com/oauth2/v3/certs"
    assert login(client, credential).status_code == 200


def test_verified_gmail_requires_explicit_domain_allowance(client, provision_user, google_token, monkeypatch):
    provision_user(email="member@gmail.com")
    credential = google_token(start(client), claims={"email": "member@gmail.com"}, remove=("hd",))
    assert login(client, credential).status_code == 401
    monkeypatch.setenv("KARIX_GOOGLE_ALLOWED_DOMAINS", "gmail.com,attributics.com")
    assert login(client, credential).status_code == 200


@pytest.mark.parametrize("state", ["missing", "tampered", "expired", "wrong-origin", "wrong-client", "wrong-audience"])
def test_missing_invalid_and_expired_browser_challenges(client, google_token, state):
    nonce = start(client)
    cookie = client.cookies.get(google.CHALLENGE_COOKIE)
    client.cookies.clear()
    if state != "missing":
        claims = jwt.decode(cookie, auth.configured_jwt_secret(), algorithms=["HS256"], audience=google.CHALLENGE_AUDIENCE)
        if state == "expired":
            claims.update(iat=int(time.time()) - 700, exp=int(time.time()) - 100)
        elif state == "wrong-origin":
            claims["origin"] = "http://localhost:4000"
        elif state == "wrong-client":
            claims["client_id"] = "other"
        elif state == "wrong-audience":
            claims["aud"] = "access-token"
        cookie = jwt.encode(claims, auth.configured_jwt_secret() if state != "tampered" else "different-test-only-key-1234567890", algorithm="HS256")
        client.cookies.set(google.CHALLENGE_COOKIE, cookie, path=google.COOKIE_PATH)
    assert login(client, google_token(nonce)).status_code == 401


def test_challenge_cannot_be_used_as_access_token_even_with_existing_subject(client, provision_user):
    user, _ = provision_user(email=EMAIL)
    start(client)
    cookie = client.cookies.get(google.CHALLENGE_COOKIE)
    claims = jwt.decode(cookie, auth.configured_jwt_secret(), algorithms=["HS256"], audience=google.CHALLENGE_AUDIENCE)
    claims["sub"] = user["id"]
    challenge = jwt.encode(claims, auth.configured_jwt_secret(), algorithm="HS256")
    assert auth.decode_access_token(challenge) is None
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {challenge}"}).status_code == 401


@pytest.mark.parametrize("origin", [None, "null", "https://attacker.invalid", "http://localhost:3000.evil.invalid", "http://localhost:3000/", "http://127.0.0.1:3000"])
def test_exact_origin_required_on_both_endpoints(client, google_token, origin):
    credential = google_token(start(client))
    headers = {"Origin": origin} if origin is not None else {}
    for path, body in (("/api/auth/google/start", {}), ("/api/auth/google", {"credential": credential})):
        response = client.post(path, headers=headers, json=body)
        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"
        assert credential not in response.text


def test_duplicate_origin_headers_are_rejected(client):
    response = client.post("/api/auth/google/start", headers=[("Origin", ORIGIN), ("Origin", ORIGIN)])
    assert response.status_code == 403


def test_unconfigured_google_does_not_affect_password_login(client, provision_user, monkeypatch):
    user, _ = provision_user(email=EMAIL)
    monkeypatch.delenv("KARIX_GOOGLE_CLIENT_ID")
    monkeypatch.delenv("KARIX_GOOGLE_ALLOWED_ORIGINS")
    response = client.post("/api/auth/google/start")
    assert response.status_code == 200 and response.json() == {"enabled": False}
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    assert login(client, "not-a-provider-credential").status_code == 503
    assert client.post("/api/auth/login", json={"email": user["email"], "password": "Test-only-password-456!"}).status_code == 200


@pytest.mark.parametrize("name,value", [
    ("KARIX_GOOGLE_CLIENT_ID", ""),
    ("KARIX_GOOGLE_CLIENT_ID", "not-a-google-client"),
    ("KARIX_GOOGLE_ALLOWED_ORIGINS", ""),
    ("KARIX_GOOGLE_ALLOWED_ORIGINS", "*"),
    ("KARIX_GOOGLE_ALLOWED_ORIGINS", "http://production.invalid"),
    ("KARIX_GOOGLE_ALLOWED_ORIGINS", "https://portal.invalid/path"),
    ("KARIX_GOOGLE_ALLOWED_ORIGINS", "https://user@portal.invalid"),
    ("KARIX_GOOGLE_ALLOWED_ORIGINS", "https://portal.invalid#fragment"),
    ("KARIX_GOOGLE_ALLOWED_ORIGINS", "https://portal.invalid,"),
    ("KARIX_GOOGLE_ALLOWED_ORIGINS", "https://portal.invalid:99999"),
    ("KARIX_GOOGLE_ALLOWED_ORIGINS", "https://portal.invalid:"),
    ("KARIX_GOOGLE_ALLOWED_DOMAINS", ""),
    ("KARIX_GOOGLE_ALLOWED_DOMAINS", "*.attributics.com"),
    ("KARIX_GOOGLE_ALLOWED_DOMAINS", "attributics.com,"),
])
def test_partial_and_malformed_configuration_fails_closed(client, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    response = client.post("/api/auth/google/start", headers={"Origin": ORIGIN})
    assert response.status_code == 503
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("origin", ["https://portal.example.com", "http://localhost:3000", "http://127.0.0.1:3000"])
def test_cookie_security_and_allowed_origin_configuration(client, monkeypatch, origin):
    monkeypatch.setenv("KARIX_GOOGLE_ALLOWED_ORIGINS", origin)
    response = client.post("/api/auth/google/start", headers={"Origin": origin})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=600" in cookie
    assert "Path=/api/auth/google" in cookie
    assert ("Secure" in cookie) == origin.startswith("https://")
    assert response.json()["client_id"] == CLIENT_ID


@pytest.mark.parametrize("account_state", ["unregistered", "inactive", "passwordless", "duplicate", "bad-scope"])
def test_only_unique_active_password_backed_existing_accounts(client, provision_user, google_token, account_state):
    user = None
    if account_state != "unregistered":
        user, _ = provision_user(email=EMAIL)
        with db.get_db() as conn:
            if account_state == "inactive":
                conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user["id"],))
            elif account_state == "passwordless":
                conn.execute("UPDATE users SET password_hash = NULL WHERE id = ?", (user["id"],))
            elif account_state == "duplicate":
                conn.execute(
                    "INSERT INTO users (id, email, password_hash, name, tenant_id, role, created_at, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                    ("duplicate-offline-user", " MEMBER@ATTRIBUTICS.COM ", "not-used", "Duplicate", "bajaj", "operator", "2026-01-01T00:00:00+00:00"),
                )
            elif account_state == "bad-scope":
                conn.execute("UPDATE users SET tenant_id = 'all', role = 'operator' WHERE id = ?", (user["id"],))
    before = stored(user["id"]) if user else None
    response = login(client, google_token(start(client)))
    assert response.status_code == (403 if account_state == "bad-scope" else 401)
    if user:
        assert stored(user["id"]) == before
    with db.get_db() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    assert count == (0 if user is None else 2 if account_state == "duplicate" else 1)


@pytest.mark.parametrize("body", [None, [], {}, {"credential": 1}, {"credential": ""}, {"credential": "sensitive-test-value", "role": "superadmin"}, {"credential": "sensitive-test-value", "tenant_id": "all"}, {"credential": "sensitive-test-value", "nonce": "injected"}])
def test_login_body_is_strict_and_errors_do_not_echo_input(client, body):
    response = client.post("/api/auth/google", headers={"Origin": ORIGIN}, json=body)
    assert response.status_code == 400
    assert "sensitive-test-value" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_malformed_json_does_not_echo_credential(client):
    response = client.post("/api/auth/google", headers={"Origin": ORIGIN, "Content-Type": "application/json"}, content='{"credential":"sensitive-test-value"')
    assert response.status_code == 400
    assert "sensitive-test-value" not in response.text


def test_provider_outage_is_recoverable_and_never_leaks_provider_error(client, google_token, monkeypatch, caplog):
    credential = google_token(start(client))
    lookup = Mock(side_effect=PyJWKClientConnectionError("sensitive-provider-error"))
    monkeypatch.setattr(google.GOOGLE_JWKS_CLIENT, "get_signing_key", lookup)
    response = login(client, credential)
    assert response.status_code == 503
    assert "sensitive-provider-error" not in response.text + caplog.text
    assert credential not in caplog.text


@pytest.mark.parametrize("method,path", [("GET", "/api/auth/google"), ("GET", "/api/auth/google/start"), ("POST", "/api/auth/google/extra"), ("POST", "/api/auth/google/start/extra")])
def test_public_google_allowlist_does_not_cover_methods_or_descendants(client, method, path):
    assert client.request(method, path).status_code == 401
