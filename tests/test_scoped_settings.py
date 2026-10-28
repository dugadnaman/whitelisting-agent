"""One-time credential setup survives reload without cross-account or plaintext writes."""

import base64
from pathlib import Path

from fastapi.testclient import TestClient

import api
import config
import db
from portal_sessions import load_settings
from sms_config import get_sms_auth_headers, get_sms_encryption_key


def test_sms_setup_is_encrypted_persistent_and_account_scoped(tmp_path, monkeypatch, provision_user):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "_load_env_file", lambda: None)
    monkeypatch.setattr(api.QUEUE_MANAGER, "notify_credentials_updated", lambda account: None)
    _, headers = provision_user("tata")
    client = TestClient(api.app)
    response = client.put("/api/credentials", headers=headers, json={
        "account": "tchfl", "channel": "sms", "sms_key": "test-private-sms-key",
        "sms_username": "test-tchfl-user", "sms_encryption_key": "test-encryption-key",
    })
    assert response.status_code == 200, response.text
    expected = base64.b64encode(b"test-tchfl-user:test-private-sms-key").decode()
    assert get_sms_auth_headers("tchfl")["Authorization"] == "Basic " + expected
    assert get_sms_encryption_key("tchfl") == "test-encryption-key"
    assert load_settings("bajaj", "sms") == {}
    assert "test-private-sms-key" not in str(load_settings("tcl_promo", "sms"))
    assert not Path("credentials.json").exists() and not Path(".env").exists()
    with db.get_db() as conn:
        # Plaintext never enters database rows, either; the accessor must decrypt it.
        dump = "\n".join(conn.raw_connection.iterdump())
    assert "test-private-sms-key" not in dump and "test-encryption-key" not in dump
    assert client.put("/api/credentials", headers=headers, json={"account": "tchfl", "channel": "sms", "sms_sender_id": "TCHFL"}).status_code == 200
    assert get_sms_auth_headers("tchfl")["Authorization"] == "Basic " + expected
    assert client.put("/api/credentials", headers=headers, json={"account": "bajaj", "channel": "sms", "sms_key": "wrong-account"}).status_code == 403


def test_moengage_metadata_setup_is_separate_per_account(tmp_path, monkeypatch, provision_user):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "_load_env_file", lambda: None)
    _, headers = provision_user("tata")
    client = TestClient(api.app)
    for account, workspace in (("tchfl", "ABCDEFGHIJKLMNOPQRSTUVWX"), ("tcl_promo", "bbbbbbbbbbbbbbbbbbbbbbbb")):
        response = client.put("/api/moengage/credentials", headers=headers, json={
            "account": account, "base_url": "https://dashboard-03.moengage.com", "workspace_id": workspace,
        })
        assert response.status_code == 200, response.text
    assert load_settings("tchfl", "moengage")["TCHFL_MOENGAGE_WORKSPACE_ID"] == "ABCDEFGHIJKLMNOPQRSTUVWX"
    assert load_settings("tcl_promo", "moengage")["TCL_PROMO_MOENGAGE_WORKSPACE_ID"] == "bbbbbbbbbbbbbbbbbbbbbbbb"
    partial = client.put("/api/moengage/credentials", headers=headers, json={"account": "tchfl", "bearer_token": "partial-session"})
    assert partial.status_code == 422
    assert load_settings("tchfl", "moengage")["TCHFL_MOENGAGE_WORKSPACE_ID"] == "ABCDEFGHIJKLMNOPQRSTUVWX"
    assert not Path("credentials.json").exists() and not Path(".env").exists()
