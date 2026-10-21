"""Tests for activity log date-range filtering, memory saving and audit trails."""
from datetime import UTC, datetime, timedelta
import pytest
from fastapi.testclient import TestClient

import activity_tracker
import api
import db
@pytest.fixture
def client(provision_user):
    return TestClient(api.app)


def test_activity_date_range_filtering(tmp_path, monkeypatch):
    path = tmp_path / "activity_test.db"
    monkeypatch.setenv("KARIX_DB_PATH", str(path))
    monkeypatch.setattr(db, "DEFAULT_SQLITE_PATH", path)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_database()

    now = datetime.now(UTC)
    now_iso = now.isoformat()
    yesterday_iso = (now - timedelta(days=1)).isoformat()
    last_week_iso = (now - timedelta(days=5)).isoformat()
    last_month_iso = (now - timedelta(days=20)).isoformat()
    old_iso = (now - timedelta(days=60)).isoformat()

    # Log activities at different timestamps
    with db.get_db() as conn:
        for i, ts in enumerate([now_iso, yesterday_iso, last_week_iso, last_month_iso, old_iso]):
            conn.execute(
                """
                INSERT INTO activities (id, timestamp, user, action, account, channel, details, status)
                VALUES (?, ?, 'Test User', 'TEMPLATE_SUBMISSION', 'bajaj', 'whatsapp', '{}', 'success')
                """,
                (f"act_{i}", ts),
            )

    # 1. Default / today filter
    today_records = activity_tracker.load_activities(date_range="today")
    assert len(today_records) == 1
    assert today_records[0]["id"] == "act_0"

    # 2. Yesterday filter
    yesterday_records = activity_tracker.load_activities(date_range="yesterday")
    assert len(yesterday_records) == 1
    assert yesterday_records[0]["id"] == "act_1"

    # 3. 7d filter
    week_records = activity_tracker.load_activities(date_range="7d")
    assert len(week_records) == 3
    assert [r["id"] for r in week_records] == ["act_0", "act_1", "act_2"]

    # 4. 30d filter
    month_records = activity_tracker.load_activities(date_range="30d")
    assert len(month_records) == 4
    assert [r["id"] for r in month_records] == ["act_0", "act_1", "act_2", "act_3"]

    # 5. All time filter
    all_records = activity_tracker.load_activities(date_range="all")
    assert len(all_records) == 5

    # 6. None (unfiltered / recent for dashboard widgets)
    unfiltered = activity_tracker.load_activities(limit=2)
    assert len(unfiltered) == 2
    assert unfiltered[0]["id"] == "act_0"


def test_api_activity_date_filter_endpoint(client, provision_user):
    user, headers = provision_user(role="admin")

    # Log an activity today
    activity_tracker.log_activity(
        user=user["name"],
        action="TEMPLATE_SUBMISSION",
        account="apparel",
        channel="rcs",
        details={"count": 1},
    )

    # Query with date_range=today
    res_today = client.get("/api/activity?date_range=today", headers=headers)
    assert res_today.status_code == 200
    data_today = res_today.json()
    assert len(data_today) >= 1
    assert data_today[0]["action"] == "TEMPLATE_SUBMISSION"

    # Query with date_range=all
    res_all = client.get("/api/activity?date_range=all", headers=headers)
    assert res_all.status_code == 200
    assert len(res_all.json()) >= len(data_today)
