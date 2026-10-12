"""A failed catalog lookup is not proof a template is absent or safe to send."""
import json

import agent
import db
import rcs_client
from template_identifier import find_template_by_content


def unavailable(**kwargs):
    raise rcs_client.RcsInventoryUnavailable("Provider inventory unavailable")


def test_content_search_reports_outage_instead_of_safe_to_submit(monkeypatch):
    monkeypatch.setattr(rcs_client, "fetch_rcs_templates", unavailable)
    result = find_template_by_content("Customer offer", client="tata", channel="rcs")
    assert result.found is False
    assert result.error == "Provider inventory unavailable"


def test_agent_inspection_does_not_leak_another_accounts_local_template(monkeypatch):
    with db.get_db() as conn:
        conn.execute("INSERT INTO ingestion_jobs(id,tenant_id,channel,filename,total_count,status,created_at,updated_at) VALUES('private-job','bajaj','rcs','sheet',1,'COMPLETED','now','now')")
        payload = json.dumps({"client": "bajaj", "template_name": "private_offer", "template_message": "Private content"})
        conn.execute("INSERT INTO job_tasks(id,job_id,tenant_id,channel,template_name,payload_json,status,approval_status,created_at,updated_at) VALUES('private-task','private-job','bajaj','rcs','private_offer',?,'SUBMITTED','approved','now','now')", (payload,))
    monkeypatch.setattr(agent, "fetch_rcs_templates", unavailable)
    result = agent.tool_inspect_template("private_offer", account="tata", channel="rcs")
    assert result["found"] is False
    assert result["template"] is None
    assert result["error"] == "Provider inventory unavailable"


def test_agent_inspects_json_encoded_provider_content(monkeypatch):
    monkeypatch.setattr(agent, "fetch_rcs_templates", lambda **kwargs: [{
        "templateId": "provider-reference", "status": "approved",
        "viTemplate": json.dumps({"name": "offer", "textMessage": "Real provider content"}),
    }])
    result = agent.tool_inspect_template("offer", account="tata", channel="rcs")
    assert result["template"]["template_message"] == "Real provider content"
    assert result["template"]["approval_status"] == "approved"
    assert result["template"]["live"] is True
