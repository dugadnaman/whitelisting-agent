"""Jira media references resolve to exact attachment IDs without signed URL leakage."""
from unittest.mock import Mock

import pytest
import requests

import jira_client

BASE = "https://example.atlassian.net"
OLD = "11111111-1111-4111-8111-111111111111"
NEW = "22222222-2222-4222-8222-222222222222"
IMAGE = "33333333-3333-4333-8333-333333333333"


def body(text="Kindly whitelist the attached regional content.", media=NEW, kind="mediaInline"):
    content = [{"type": "text", "text": text}]
    if media is not None:
        content.append({"type": kind, "attrs": {"type": "file", "id": media}})
    return {"type": "doc", "content": [{"type": "paragraph", "content": content}]}


@pytest.fixture
def jira_http(monkeypatch):
    jira_client._attachment_media_id.cache_clear()
    monkeypatch.setattr(jira_client, "get_jira_credentials", lambda: (BASE, "user", "secret"))
    monkeypatch.setattr(jira_client, "get_jira_auth_headers", lambda: {"Authorization": "Basic private"})
    attachments = [
        {"id": "12", "filename": "old.xlsx"},
        {"id": "7", "filename": "image.png"},
        {"id": "93", "filename": "regional.xlsx"},
    ]
    issue = {"key": "TEST-1", "fields": {"attachment": attachments, "comment": {"comments": []}}}
    responses = []
    locations = {"12": OLD, "93": NEW, "7": IMAGE}

    def get(url, **kwargs):
        if url == f"{BASE}/rest/api/3/issue/TEST-1":
            return Mock(ok=True, json=lambda: issue)
        attachment_id = url.rsplit("/", 1)[-1]
        assert url == f"{BASE}/rest/api/3/attachment/content/{attachment_id}"
        assert kwargs == {
            "headers": {"Authorization": "Basic private"},
            "allow_redirects": False, "stream": True, "timeout": 20,
        }
        response = Mock(status_code=303, headers={
            "Location": f"https://api.media.atlassian.com/file/{locations[attachment_id]}/binary?token=private-query"
        })
        responses.append(response)
        return response

    http = Mock(side_effect=get)
    monkeypatch.setattr(jira_client.requests, "get", http)
    yield issue, http, responses
    jira_client._attachment_media_id.cache_clear()


def fetch(issue, *bodies):
    issue["fields"]["comment"]["comments"] = [
        {"id": str(index), "body": value} for index, value in enumerate(bodies)
    ]
    return jira_client.fetch_jira_issue("test-1")


@pytest.mark.parametrize("kind", ["media", "mediaInline"])
def test_exact_mapping_unordered_attachments_and_success_cache(jira_http, kind):
    issue, http, responses = jira_http
    result = fetch(issue, body(kind=kind), body("Also whitelist the attached additional content.", kind=kind))
    assert [c["attachment_ids"] for c in result["comments"]] == [["93"], ["93"]]
    assert http.call_count == 3  # one issue request, two copy-document identity requests
    assert "private-query" not in repr(result)
    assert "private-query" not in repr(jira_client._attachment_media_id.cache_info())
    for response in responses:
        response.close.assert_called_once()
        response.iter_content.assert_not_called()


@pytest.mark.parametrize("comment", [
    body("Please review this file."),
    body(media=None),
    body("Please whitelist the attached image."),
    body("Do not whitelist the attached content."),
])
def test_unrelated_or_reference_free_comments_do_not_request_media(jira_http, comment):
    issue, http, _ = jira_http
    assert fetch(issue, comment)["comments"][0]["attachment_ids"] == []
    assert http.call_count == 1


def test_no_copy_candidates_do_not_request_media(jira_http):
    issue, http, _ = jira_http
    issue["fields"]["attachment"] = [{"id": "7", "filename": "image.png"}]
    assert fetch(issue, body())["comments"][0]["attachment_ids"] == []
    assert http.call_count == 1


def test_image_reference_never_becomes_copy_scope(jira_http):
    issue, _, _ = jira_http
    assert fetch(issue, body(media=IMAGE))["comments"][0]["attachment_ids"] == []


@pytest.mark.parametrize("location", [
    "https://evil.example/file/22222222-2222-4222-8222-222222222222/binary?token=private-query",
    "https://api.media.atlassian.com/file/not-a-uuid/binary?token=private-query",
    "https://api.media.atlassian.com.evil.example/file/22222222-2222-4222-8222-222222222222/binary",
])
def test_untrusted_mapping_fails_without_leaking_query_or_caching(jira_http, location):
    issue, http, _ = jira_http
    original = http.side_effect

    def invalid(url, **kwargs):
        if "/attachment/content/" in url:
            return Mock(status_code=303, headers={"Location": location})
        return original(url, **kwargs)

    http.side_effect = invalid
    with pytest.raises(RuntimeError) as error:
        fetch(issue, body())
    assert "private-query" not in str(error.value)
    assert jira_client._attachment_media_id.cache_info().currsize == 0


def test_network_failure_is_not_cached_or_silently_additive(jira_http):
    issue, http, _ = jira_http
    original = http.side_effect

    def unavailable(url, **kwargs):
        if "/attachment/content/" in url:
            raise requests.ConnectionError("private-query")
        return original(url, **kwargs)

    http.side_effect = unavailable
    with pytest.raises(RuntimeError, match="Unable to resolve") as error:
        fetch(issue, body())
    assert "private-query" not in str(error.value)
    assert jira_client._attachment_media_id.cache_info().currsize == 0
    http.side_effect = original
    assert fetch(issue, body())["comments"][0]["attachment_ids"] == ["93"]


def test_unknown_media_reference_fails_instead_of_merging(jira_http):
    issue, _, _ = jira_http
    with pytest.raises(RuntimeError, match="Unable to resolve requested"):
        fetch(issue, body(media="44444444-4444-4444-8444-444444444444"))


def test_direct_jira_attachment_link_needs_no_media_request(jira_http):
    issue, http, _ = jira_http
    comment = body(media=None)
    comment["content"][0]["content"][0]["marks"] = [{
        "type": "link", "attrs": {"href": f"{BASE}/secure/attachment/93/regional.xlsx"}
    }]
    assert fetch(issue, comment)["comments"][0]["attachment_ids"] == ["93"]
    assert http.call_count == 1
