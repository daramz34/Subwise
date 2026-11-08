from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Notification, User
from app.services import notification_service

N = "/api/v1/notifications"
S = "/api/v1/subscriptions"


def _today():
    return datetime.now(timezone.utc).date()


def _sub(client, headers, name="Netflix", amount=10, **extra):
    r = client.post(S, headers=headers, json={
        "name": name, "amount": amount, "currency": "USD", "billing_interval": "month", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _list(client, headers):
    r = client.get(N, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _due_in(days):
    return (_today() + timedelta(days=days)).isoformat()


def test_renewal_alert_is_created_for_a_close_renewal(client, alice):
    _sub(client, alice, "Netflix", next_renewal_date=_due_in(2))
    data = _list(client, alice)
    assert data["unread_count"] == 1
    item = data["items"][0]
    assert item["notification_type"] == "renewal" and item["channel"] == "in_app"
    assert "Netflix renews in 2 days" in item["title"]
    assert "10.00 USD" in item["message"]


def test_running_twice_creates_one_alert(client, alice):
    _sub(client, alice, "Netflix", next_renewal_date=_due_in(2))
    assert len(_list(client, alice)["items"]) == 1
    assert len(_list(client, alice)["items"]) == 1
    assert len(_list(client, alice)["items"]) == 1


def test_closer_thresholds_create_new_alerts_but_never_duplicates(client, alice, db):
    _sub(client, alice, "Netflix", next_renewal_date="2027-06-15")
    user = db.scalar(select(User).where(User.email == "alice@example.com"))

    def total(today):
        notification_service.generate_for_user(db, user, today=today)
        notification_service.generate_for_user(db, user, today=today)   # same day again
        return len(db.scalars(select(Notification).where(Notification.user_id == user.id)).all())

    assert total(date(2027, 6, 1)) == 0    # 14 days away: outside every threshold
    assert total(date(2027, 6, 10)) == 1   # 5 days: the "7 days" alert
    assert total(date(2027, 6, 11)) == 1   # 4 days: same alert, no duplicate
    assert total(date(2027, 6, 12)) == 2   # 3 days: the "3 days" alert
    assert total(date(2027, 6, 14)) == 3   # 1 day: the "1 day" alert
    assert total(date(2027, 6, 14)) == 3


def test_far_paused_and_archived_get_no_alerts(client, alice):
    _sub(client, alice, "Far", next_renewal_date=_due_in(30))
    paused = _sub(client, alice, "Paused", next_renewal_date=_due_in(1))
    gone = _sub(client, alice, "Gone", next_renewal_date=_due_in(1))
    assert client.put(f"{S}/{paused['id']}", json={"status": "paused"}, headers=alice).status_code == 200
    assert client.delete(f"{S}/{gone['id']}", headers=alice).status_code == 200
    assert _list(client, alice)["items"] == []


def test_trial_ending_alert(client, alice):
    _sub(client, alice, "Trialware", status="trial", trial_end_date=_due_in(2))
    items = _list(client, alice)["items"]
    assert [i["notification_type"] for i in items] == ["trial_ending"]
    assert "Trialware trial ends in 2 days" in items[0]["title"]


def test_price_increase_alerts_but_a_decrease_does_not(client, alice):
    s = _sub(client, alice, "Netflix", 10)
    assert client.put(f"{S}/{s['id']}", json={"amount": 12}, headers=alice).status_code == 200
    items = _list(client, alice)["items"]
    assert [i["notification_type"] for i in items] == ["price_increase"]
    assert "12.00" in items[0]["message"] and "24.00" in items[0]["message"]
    assert client.put(f"{S}/{s['id']}", json={"amount": 8}, headers=alice).status_code == 200
    types = [i["notification_type"] for i in _list(client, alice)["items"]]
    assert types.count("price_increase") == 1


def test_preferences_default_and_update(client, alice):
    r = client.get(f"{N}/preferences", headers=alice)
    assert r.status_code == 200
    assert r.json()["in_app_enabled"] is True and r.json()["renewal_days_before"] == [1, 3, 7]
    r = client.patch(f"{N}/preferences", json={"renewal_days_before": [5, 2, 5]}, headers=alice)
    assert r.status_code == 200 and r.json()["renewal_days_before"] == [2, 5]
    r = client.patch(f"{N}/preferences", json={"trial_alerts_enabled": False}, headers=alice)
    assert r.status_code == 200 and r.json()["trial_alerts_enabled"] is False
    assert client.get(f"{N}/preferences", headers=alice).json()["renewal_days_before"] == [2, 5]


def test_disabled_preferences_stop_alerts(client, alice):
    _sub(client, alice, "Soon", next_renewal_date=_due_in(1))
    _sub(client, alice, "Later", next_renewal_date=_due_in(3))
    assert client.patch(f"{N}/preferences", json={"in_app_enabled": False}, headers=alice).status_code == 200
    assert _list(client, alice)["items"] == []
    client.patch(f"{N}/preferences", json={"in_app_enabled": True, "renewal_days_before": [1]}, headers=alice)
    items = _list(client, alice)["items"]
    assert len(items) == 1 and "Soon" in items[0]["title"]


def test_mark_read_is_idempotent(client, alice):
    _sub(client, alice, "Netflix", next_renewal_date=_due_in(1))
    note = _list(client, alice)["items"][0]
    assert note["read_at"] is None
    r = client.patch(f"{N}/{note['id']}/read", headers=alice)
    assert r.status_code == 200 and r.json()["read_at"] is not None
    assert client.patch(f"{N}/{note['id']}/read", headers=alice).status_code == 200
    data = _list(client, alice)
    assert data["unread_count"] == 0
    assert client.get(f"{N}?unread_only=true", headers=alice).json()["items"] == []


def test_notifications_are_private(client, alice, bob):
    _sub(client, alice, "Netflix", next_renewal_date=_due_in(1))
    note = _list(client, alice)["items"][0]
    assert client.patch(f"{N}/{note['id']}/read", headers=bob).status_code == 404
    assert _list(client, bob)["items"] == []


@pytest.mark.parametrize("days", [[-1], [200], [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]])
def test_invalid_preferences_are_rejected(client, alice, days):
    r = client.patch(f"{N}/preferences", json={"renewal_days_before": days}, headers=alice)
    assert r.status_code == 422


def test_requires_login(client):
    assert client.get(N).status_code == 401
    assert client.get(f"{N}/preferences").status_code == 401
    assert client.patch(f"{N}/preferences", json={"in_app_enabled": False}).status_code == 401