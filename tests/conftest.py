import sys
from pathlib import Path

# Add project root and backend directory to sys.path so tests can import from backend directly
root_dir = Path(__file__).resolve().parent.parent
backend_dir = root_dir / "backend"

for p in (str(backend_dir), str(root_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

import uuid

import pytest


@pytest.fixture
def provision_user(tmp_path, monkeypatch):
    """Explicit opt-in identities with real JWTs in a disposable database, never auth overrides."""
    import auth
    import db

    monkeypatch.setattr(db, "get_database_url", lambda: "")
    monkeypatch.setattr(db, "DEFAULT_SQLITE_PATH", tmp_path / "auth-test.db")
    monkeypatch.setenv("JWT_SECRET", "0123456789abcdefFEDCBA9876543210" * 2)
    auth.init_auth_db()

    def provision(tenant="apparel", role="operator", email=None, password="Test-only-password-456!"):
        user = auth.register_user(email or f"test-{uuid.uuid4().hex}@example.com", password, "Test User", tenant, role)
        token = auth.authenticate_user(user["email"], password)["token"]
        return user, {"Authorization": f"Bearer {token}"}

    return provision
