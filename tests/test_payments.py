import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
from app.core.config import settings
from app.models import PayPalWebhookEvent, User, UserEntitlement  # NAMES
from app.services import paypal_client

P = "/api/v1/payments"


@pytest.fixture
def paypal(monkeypatch):
    """Fake PayPal: no test ever reaches the real one."""
    s = SimpleNamespace(created=[], captured=[], capture_amount="5.00", capture_status="COMPLETED", verify=True)

    def fake_create(**kw):
        s.created.append(kw)
        return {"id": f"ORDER{len(s.created)}", "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "payer-action", "href": "https://sandbox.paypal.com/checkoutnow?token=X"}]}

    def fake_capture(order_id, request_id=None):
        s.captured.append(order_id)
        return {"id": order_id, "status": s.capture_status, "purchase_units": [{"payments": {"captures": [
            {"id": "CAP-" + order_id, "status": s.capture_status,
             "amount": {"currency_code": "USD", "value": s.capture_amount}}]}}]}

    monkeypatch.setattr(paypal_client, "create_order", fake_create)
    monkeypatch.setattr(paypal_client, "capture_order", fake_capture)
    monkeypatch.setattr(paypal_client, "verify_webhook", lambda headers, event: s.verify)
    monkeypatch.setattr(settings, "PAYPAL_WEBHOOK_ID", "WH-TEST")
    return s


def _create(client, headers):
    r = client.post(f"{P}/create-order", json={"plan_code": "plus"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["order_id"]


def _buy(client, headers):
    oid = _create(client, headers)
    r = client.post(f"{P}/capture-order", json={"order_id": oid}, headers=headers)
    assert r.status_code == 200, r.text
    return oid


def _plan(client, headers):
    return client.get(f"{P}/entitlement", headers=headers).json()["plan_code"]


def _add_sub(client, headers, i):
    return client.post("/api/v1/subscriptions", headers=headers, json={
        "name": f"Service {i}", "amount": 5, "currency": "USD", "billing_interval": "month"})


def _webhook(client, event):
    return client.post(f"{P}/webhook", content=json.dumps(event),
                       headers={"content-type": "application/json"})


def _event(kind, order_id, event_id):
    return {"id": event_id, "event_type": kind, "resource": {
        "id": "CAP-" + order_id, "status": "COMPLETED",
        "amount": {"currency_code": "USD", "value": "5.00"},
        "supplementary_data": {"related_ids": {"order_id": order_id}}}}


def test_plans_are_public(client):
    r = client.get("/api/v1/plans")
    assert r.status_code == 200
    assert {p["code"] for p in r.json()} == {"free", "plus"}


def test_create_order_uses_the_server_price(client, alice, paypal):
    r = client.post(f"{P}/create-order", json={"plan_code": "plus"}, headers=alice)
    assert r.status_code == 201
    assert r.json()["approve_url"].startswith("https://")
    assert paypal.created[0]["amount"] == "5.00" and paypal.created[0]["currency"] == "USD"


def test_client_cannot_choose_the_amount(client, alice, paypal):
    r = client.post(f"{P}/create-order", json={"plan_code": "plus", "amount": "0.01"}, headers=alice)
    assert r.status_code == 422
    assert paypal.created == []


def test_free_and_unknown_plans_cannot_be_bought(client, alice, paypal):
    assert client.post(f"{P}/create-order", json={"plan_code": "free"}, headers=alice).status_code == 400
    assert client.post(f"{P}/create-order", json={"plan_code": "gold"}, headers=alice).status_code == 404


def test_capture_unlocks_plus(client, alice, paypal):
    for i in range(5):
        assert _add_sub(client, alice, i).status_code == 201
    assert _add_sub(client, alice, 5).status_code == 403          # free limit
    assert _plan(client, alice) == "free"
    _buy(client, alice)
    assert _plan(client, alice) == "plus"
    assert _add_sub(client, alice, 5).status_code == 201          # limit lifted


def test_capture_twice_charges_and_activates_once(client, alice, paypal):
    oid = _buy(client, alice)
    r = client.post(f"{P}/capture-order", json={"order_id": oid}, headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "completed"
    assert paypal.captured == [oid]


def test_already_plus_cannot_buy_again(client, alice, paypal):
    _buy(client, alice)
    r = client.post(f"{P}/create-order", json={"plan_code": "plus"}, headers=alice)
    assert r.status_code == 409


def test_tampered_amount_is_rejected(client, alice, paypal):
    oid = _create(client, alice)
    paypal.capture_amount = "1.00"
    r = client.post(f"{P}/capture-order", json={"order_id": oid}, headers=alice)
    assert r.status_code == 400
    assert _plan(client, alice) == "free"
    assert client.get(f"{P}/orders", headers=alice).json()[0]["status"] == "failed"


def test_declined_payment_does_not_unlock(client, alice, paypal):
    oid = _create(client, alice)
    paypal.capture_status = "DECLINED"
    assert client.post(f"{P}/capture-order", json={"order_id": oid}, headers=alice).status_code == 402
    assert _plan(client, alice) == "free"


def test_cannot_capture_someone_elses_order(client, alice, bob, paypal):
    oid = _create(client, alice)
    assert client.post(f"{P}/capture-order", json={"order_id": oid}, headers=bob).status_code == 404
    assert _plan(client, bob) == "free" and paypal.captured == []


def test_refund_webhook_revokes_plus(client, alice, paypal):
    oid = _buy(client, alice)
    assert _plan(client, alice) == "plus"
    assert _webhook(client, _event("PAYMENT.CAPTURE.REFUNDED", oid, "EVT-R")).status_code == 200
    assert _plan(client, alice) == "free"
    assert client.get(f"{P}/orders", headers=alice).json()[0]["status"] == "refunded"


def test_duplicate_webhook_is_handled_once(client, alice, paypal, db):
    oid = _buy(client, alice)
    ev = _event("PAYMENT.CAPTURE.REFUNDED", oid, "EVT-DUP")
    assert _webhook(client, ev).status_code == 200
    assert _webhook(client, ev).status_code == 200
    rows = db.scalars(select(PayPalWebhookEvent).where(PayPalWebhookEvent.event_id == "EVT-DUP")).all()
    assert len(rows) == 1 and rows[0].status == "processed"


def test_capture_webhook_unlocks_if_browser_never_returned(client, alice, paypal):
    oid = _create(client, alice)
    assert _webhook(client, _event("PAYMENT.CAPTURE.COMPLETED", oid, "EVT-C")).status_code == 200
    assert _plan(client, alice) == "plus"


def test_bad_signature_changes_nothing(client, alice, paypal):
    oid = _buy(client, alice)
    paypal.verify = False
    assert _webhook(client, _event("PAYMENT.CAPTURE.REFUNDED", oid, "EVT-BAD")).status_code == 400
    assert _plan(client, alice) == "plus"


def test_webhook_unconfigured_returns_503(client, alice, paypal, monkeypatch):
    monkeypatch.setattr(settings, "PAYPAL_WEBHOOK_ID", "")
    assert _webhook(client, {"id": "X", "event_type": "Y"}).status_code == 503


def test_unrelated_events_are_ignored(client, paypal):
    assert _webhook(client, {"id": "EVT-U", "event_type": "BILLING.PLAN.CREATED", "resource": {}}).status_code == 200


def test_payment_endpoints_require_login(client):
    assert client.post(f"{P}/create-order", json={"plan_code": "plus"}).status_code == 401
    assert client.post(f"{P}/capture-order", json={"order_id": "ORDER1"}).status_code == 401
    assert client.get(f"{P}/entitlement").status_code == 401
    assert client.get(f"{P}/orders").status_code == 401


def _expire(db, email):
    user = db.scalar(select(User).where(User.email == email))
    ent = db.scalar(select(UserEntitlement).where(UserEntitlement.user_id == user.id))
    ent.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.flush()


def test_expired_plus_falls_back_to_free_and_can_be_bought_again(client, alice, paypal, db):
    _buy(client, alice)
    assert _plan(client, alice) == "plus"
    _expire(db, "alice@example.com")
    assert _plan(client, alice) == "free"
    for i in range(5):
        assert _add_sub(client, alice, i).status_code == 201
    assert _add_sub(client, alice, 5).status_code == 403     # the free limit applies again
    _buy(client, alice)                                      # renewing works
    assert _plan(client, alice) == "plus"
    assert _add_sub(client, alice, 5).status_code == 201


def test_denied_payment_webhook_revokes_plus(client, alice, paypal):
    oid = _buy(client, alice)
    assert _plan(client, alice) == "plus"
    assert _webhook(client, _event("PAYMENT.CAPTURE.DENIED", oid, "EVT-D")).status_code == 200
    assert _plan(client, alice) == "free"
    assert client.get(f"{P}/orders", headers=alice).json()[0]["status"] == "failed"

    