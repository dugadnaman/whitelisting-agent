import sys
import ipaddress
import os
import socket
import tempfile
from pathlib import Path

# Add project root and backend directory to sys.path so tests can import from backend directly
root_dir = Path(__file__).resolve().parent.parent
backend_dir = root_dir / "backend"

for p in (str(backend_dir), str(root_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

import uuid

import pytest


# Module imports initialize stores before function fixtures run.
_collection_store = tempfile.TemporaryDirectory(prefix="karix-test-collection-")
_database_names = ("KARIX_DB_PATH", "DATABASE_URL", "POSTGRES_URL", "POSTGRESQL_URL")
_original_environment = {name: os.environ.get(name) for name in _database_names}
os.environ["KARIX_DB_PATH"] = str(Path(_collection_store.name) / "collection.db")
for _name in _database_names[1:]:
    os.environ[_name] = ""


def pytest_sessionfinish(session, exitstatus):
    _collection_store.cleanup()
    for name, value in _original_environment.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture(autouse=True)
def local_network_only(request, monkeypatch):
    """Real provider checks are opt-in; unit tests can use loopback HTTP servers."""
    if request.node.get_closest_marker("live_karix") or request.node.get_closest_marker("live_moengage"):
        return
    original_connect = socket.socket.connect
    original_resolve = socket.getaddrinfo

    def is_local(host):
        if host is None or host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def connect(sock, address):
        if isinstance(address, tuple) and not is_local(address[0]):
            raise OSError("External network disabled for unit tests; use a local provider simulator.")
        return original_connect(sock, address)

    def resolve(host, *args, **kwargs):
        if not is_local(host):
            raise socket.gaierror("External DNS disabled for unit tests.")
        return original_resolve(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "getaddrinfo", resolve)


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Unit/API tests must never write developer or deployed identity/queue stores."""
    import db

    for name in ("DATABASE_URL", "POSTGRES_URL", "POSTGRESQL_URL"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("JWT_SECRET", "0123456789abcdefFEDCBA9876543210" * 2)
    # Mocked Jira requests still exercise credential construction, never developer secrets.
    monkeypatch.setenv("JIRA_USER_EMAIL", "unit-test@example.invalid")
    monkeypatch.setenv("JIRA_API_TOKEN", "unit-test-token")
    monkeypatch.setenv("JIRA_BASE_URL", "https://jira.example.invalid")
    path = tmp_path / "karix-test.db"
    monkeypatch.setenv("KARIX_DB_PATH", str(path))
    monkeypatch.setattr(db, "DEFAULT_SQLITE_PATH", path)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_database()


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
