from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import AuditLog, Category, Plan, Subscription, User, UserEntitlement

API = "/api/v1/subscriptions"
PAYMENT = {"amount": "15.99", "currency": "USD", "payment_date": "2026-02-01"}


# ---------------------------------------------------------------- helpers
def payload(**over):
    body = {"name": "Netflix", "amount": "15.99", "currency": "USD"}
    body.update(over)
    return body


def create(client, headers, **over):
    r = client.post(API, headers=headers, json=payload(**over))
    assert r.status_code == 201, r.text
    return r.json()


def fill(client, headers, n):
    return [create(client, headers, name=f"Service {i}") for i in range(n)]


def upgrade_to_plus(db, email):
    user = db.scalar(select(User).where(User.email == email))
    plus = db.scalar(select(Plan).where(Plan.code == "plus"))
    ent = db.scalar(select(UserEntitlement).where(UserEntitlement.user_id == user.id))
    ent.plan = plus
    db.commit()


def history(client, headers, sub_id):
    r = client.get(f"{API}/{sub_id}/price-history", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- create and validation
def test_create_subscription_writes_first_price_history(client, alice):
    sub = create(client, alice, start_date="2026-01-15")
    assert sub["name"] == "Netflix"
    assert Decimal(sub["amount"]) == Decimal("15.99")
    assert sub["source"] == "manual" and sub["status"] == "active"

    rows = history(client, alice, sub["id"])
    assert len(rows) == 1
    assert rows[0]["previous_amount"] is None
    assert rows[0]["effective_date"] == "2026-01-15"


def test_create_requires_login(client):
    assert client.post(API, json=payload()).status_code == 401


def test_currency_is_uppercased(client, alice):
    assert create(client, alice, currency="ngn")["currency"] == "NGN"


@pytest.mark.parametrize("bad", [
    {"currency": "US"},
    {"currency": "12$"},
    {"amount": "-1"},
    {"interval_count": 0},
    {"billing_interval": "fortnight"},
    {"status": "trial"},                                  # trial needs trial_end_date
    {"my_share_percent": "50.00"},                        # only valid when is_shared is true
    {"user_id": "00000000-0000-0000-0000-000000000001"},  # clients can't set ownership
    {"website_url": "javascript:alert(1)"},
])
def test_create_rejects_bad_input(client, alice, bad):
    assert client.post(API, headers=alice, json=payload(**bad)).status_code == 422


def test_trial_with_end_date_is_accepted(client, alice):
    sub = create(client, alice, status="trial", trial_end_date="2026-12-01", trial_converts_amount="9.99")
    assert sub["status"] == "trial" and sub["trial_end_date"] == "2026-12-01"


# ---------------------------------------------------------------- data isolation
def test_user_cannot_touch_another_users_subscription(client, alice, bob):
    sid = create(client, alice)["id"]
    attempts = [
        ("GET", f"{API}/{sid}", None),
        ("PUT", f"{API}/{sid}", {"name": "Hacked"}),
        ("PATCH", f"{API}/{sid}/status", {"status": "paused"}),
        ("DELETE", f"{API}/{sid}", None),
        ("GET", f"{API}/{sid}/price-history", None),
        ("GET", f"{API}/{sid}/payments", None),
        ("POST", f"{API}/{sid}/payments", PAYMENT),
    ]
    for method, url, body in attempts:
        r = client.request(method, url, headers=bob, json=body)
        assert r.status_code == 404, f"{method} {url} returned {r.status_code}"

    assert client.get(API, headers=bob).json()["total"] == 0
    mine = client.get(f"{API}/{sid}", headers=alice).json()
    assert mine["name"] == "Netflix" and mine["status"] == "active"  # untouched


# ---------------------------------------------------------------- price history
def test_price_change_creates_history_row(client, alice):
    sub = create(client, alice)
    r = client.put(f"{API}/{sub['id']}", headers=alice, json={"amount": "19.99"})
    assert r.status_code == 200 and Decimal(r.json()["amount"]) == Decimal("19.99")

    rows = history(client, alice, sub["id"])
    assert len(rows) == 2
    assert Decimal(rows[-1]["amount"]) == Decimal("19.99")
    assert Decimal(rows[-1]["previous_amount"]) == Decimal("15.99")
    assert Decimal(rows[0]["amount"]) == Decimal("15.99")  # the old row is untouched


def test_unchanged_price_creates_no_history_row(client, alice):
    sub = create(client, alice)
    client.put(f"{API}/{sub['id']}", headers=alice, json={"name": "Netflix Premium"})
    client.put(f"{API}/{sub['id']}", headers=alice, json={"amount": "15.99"})  # same price re-sent
    assert len(history(client, alice, sub["id"])) == 1


def test_price_change_uses_given_effective_date(client, alice):
    sub = create(client, alice)
    client.put(f"{API}/{sub['id']}", headers=alice,
               json={"amount": "17.99", "price_effective_date": "2026-06-01"})
    changed_price = next(
        row for row in history(client, alice, sub["id"])
        if Decimal(row["amount"]) == Decimal("17.99")
    )
    assert changed_price["effective_date"] == "2026-06-01"


# ---------------------------------------------------------------- plan limit
def test_free_plan_blocks_the_sixth_subscription(client, alice):
    fill(client, alice, 5)
    r = client.post(API, headers=alice, json=payload(name="One too many"))
    assert r.status_code == 403
    assert "Upgrade" in r.json()["detail"]


def test_archived_subscriptions_do_not_count_toward_the_limit(client, alice):
    subs = fill(client, alice, 5)
    client.delete(f"{API}/{subs[0]['id']}", headers=alice)
    assert client.post(API, headers=alice, json=payload(name="Fits now")).status_code == 201


def test_plus_plan_has_no_limit(client, db, alice):
    upgrade_to_plus(db, "alice@example.com")
    fill(client, alice, 7)
    assert client.get(API, headers=alice).json()["total"] == 7


# ---------------------------------------------------------------- duplicates
def test_duplicate_warning_then_acknowledge(client, alice):
    first = create(client, alice)
    r = client.post(API, headers=alice, json=payload(name="  netflix "))  # case and spacing ignored
    assert r.status_code == 409
    assert r.json()["similar_subscription_ids"] == [first["id"]]

    r = client.post(API, headers=alice, json=payload(acknowledge_duplicate=True))
    assert r.status_code == 201


def test_duplicate_check_ignores_other_users_and_archived(client, alice, bob):
    first = create(client, alice)
    assert client.post(API, headers=bob, json=payload()).status_code == 201   # another user's Netflix
    client.delete(f"{API}/{first['id']}", headers=alice)
    assert client.post(API, headers=alice, json=payload()).status_code == 201  # archived one is ignored


# ---------------------------------------------------------------- categories and tags on subscriptions
def test_default_category_can_be_used(client, db, alice):
    cat = Category(user_id=None, name="Streaming", color="#112233", icon="film", is_default=True)
    db.add(cat)
    db.commit()
    sub = create(client, alice, category_id=str(cat.id))
    assert sub["category"]["name"] == "Streaming"


def test_cannot_use_another_users_category(client, alice, bob):
    theirs = client.post("/api/v1/categories", headers=bob, json={"name": "Bob only"}).json()
    r = client.post(API, headers=alice, json=payload(category_id=theirs["id"]))
    assert r.status_code == 404


def test_tags_attach_replace_and_filter(client, alice):
    work = client.post("/api/v1/tags", headers=alice, json={"name": "work"}).json()
    fun = client.post("/api/v1/tags", headers=alice, json={"name": "fun"}).json()
    a = create(client, alice, name="Slack", tag_ids=[work["id"]])
    b = create(client, alice, name="Netflix", tag_ids=[fun["id"]])
    assert [t["name"] for t in a["tags"]] == ["work"]

    r = client.get(API, headers=alice, params={"tag_id": work["id"]}).json()
    assert [s["name"] for s in r["items"]] == ["Slack"]

    r = client.put(f"{API}/{b['id']}", headers=alice, json={"tag_ids": [work["id"], fun["id"]]})
    assert sorted(t["name"] for t in r.json()["tags"]) == ["fun", "work"]
    r = client.put(f"{API}/{b['id']}", headers=alice, json={"tag_ids": []})
    assert r.json()["tags"] == []


def test_cannot_attach_another_users_tag(client, alice, bob):
    theirs = client.post("/api/v1/tags", headers=bob, json={"name": "private"}).json()
    r = client.post(API, headers=alice, json=payload(tag_ids=[theirs["id"]]))
    assert r.status_code == 404


# ---------------------------------------------------------------- listing
def test_list_filter_search_sort_and_pagination(client, alice):
    create(client, alice, name="Netflix", amount="15.99")
    create(client, alice, name="Spotify", amount="9.99", status="paused")
    create(client, alice, name="Adobe", amount="54.99", merchant="Adobe Inc")

    def names(**params):
        r = client.get(API, headers=alice, params=params).json()
        return [s["name"] for s in r["items"]], r["total"]

    assert names(sort="amount", order="asc")[0] == ["Spotify", "Netflix", "Adobe"]
    assert names(sort="amount", order="desc")[0] == ["Adobe", "Netflix", "Spotify"]
    assert names(sort="name", order="asc")[0] == ["Adobe", "Netflix", "Spotify"]
    assert names(status="paused") == (["Spotify"], 1)
    assert names(q="net") == (["Netflix"], 1)
    assert names(q="adobe inc") == (["Adobe"], 1)  # matches the merchant field too

    page2, total = names(sort="name", page=2, page_size=2)
    assert page2 == ["Spotify"] and total == 3


def test_search_treats_percent_as_a_literal_character(client, alice):
    create(client, alice)
    r = client.get(API, headers=alice, params={"q": "%"}).json()
    assert r["total"] == 0


def test_list_rejects_bad_query_params(client, alice):
    assert client.get(API, headers=alice, params={"sort": "password"}).status_code == 422
    assert client.get(API, headers=alice, params={"page": 0}).status_code == 422
    assert client.get(API, headers=alice, params={"page_size": 1000}).status_code == 422


# ---------------------------------------------------------------- archive, status, edits
def test_delete_archives_instead_of_deleting(client, db, alice):
    sub = create(client, alice)
    assert client.delete(f"{API}/{sub['id']}", headers=alice).status_code == 200

    assert client.get(API, headers=alice).json()["total"] == 0
    assert client.get(API, headers=alice, params={"include_archived": "true"}).json()["total"] == 1
    assert client.get(f"{API}/{sub['id']}", headers=alice).json()["archived_at"] is not None
    assert db.scalar(select(Subscription).where(Subscription.name == "Netflix")) is not None  # row still exists
    # An archived subscription can't be edited or archived again
    assert client.put(f"{API}/{sub['id']}", headers=alice, json={"name": "x"}).status_code == 404
    assert client.delete(f"{API}/{sub['id']}", headers=alice).status_code == 404


def test_status_changes_and_cancelled_on(client, alice):
    sub = create(client, alice)
    r = client.patch(f"{API}/{sub['id']}/status", headers=alice, json={"status": "paused"})
    assert r.status_code == 200 and r.json()["status"] == "paused"

    r = client.patch(f"{API}/{sub['id']}/status", headers=alice, json={"status": "cancelled"})
    assert r.json()["cancelled_on"] == datetime.now(timezone.utc).date().isoformat()

    r = client.patch(f"{API}/{sub['id']}/status", headers=alice, json={"status": "active"})
    assert r.json()["cancelled_on"] is None  # reactivating clears it


def test_trial_status_needs_an_end_date(client, alice):
    sub = create(client, alice)
    r = client.patch(f"{API}/{sub['id']}/status", headers=alice, json={"status": "trial"})
    assert r.status_code == 422 and "trial_end_date" in r.json()["detail"]

    r = client.put(f"{API}/{sub['id']}", headers=alice, json={"status": "trial"})
    assert r.status_code == 422
    # The failed update must not have changed anything
    assert client.get(f"{API}/{sub['id']}", headers=alice).json()["status"] == "active"

    r = client.put(f"{API}/{sub['id']}", headers=alice,
                   json={"status": "trial", "trial_end_date": "2026-12-01"})
    assert r.status_code == 200


def test_turning_sharing_off_resets_the_share(client, alice):
    sub = create(client, alice, is_shared=True, my_share_percent="33.33")
    assert Decimal(sub["my_share_percent"]) == Decimal("33.33")
    r = client.put(f"{API}/{sub['id']}", headers=alice, json={"is_shared": False})
    assert Decimal(r.json()["my_share_percent"]) == Decimal("100")


def test_update_rejects_nulls_for_required_fields_and_unknown_fields(client, alice):
    sub = create(client, alice)
    assert client.put(f"{API}/{sub['id']}", headers=alice, json={"amount": None}).status_code == 422
    assert client.put(f"{API}/{sub['id']}", headers=alice, json={"user_id": "x"}).status_code == 422


# ---------------------------------------------------------------- bulk
def test_bulk_pause_ignores_other_users_subscriptions(client, alice, bob):
    a1 = create(client, alice, name="A")
    a2 = create(client, alice, name="B")
    b1 = create(client, bob, name="C")

    r = client.post(f"{API}/bulk", headers=alice,
                    json={"action": "pause", "ids": [a1["id"], a2["id"], b1["id"]]})
    assert r.status_code == 200 and r.json()["detail"].startswith("2 subscription(s) updated")

    for sid in (a1["id"], a2["id"]):
        assert client.get(f"{API}/{sid}", headers=alice).json()["status"] == "paused"
    assert client.get(f"{API}/{b1['id']}", headers=bob).json()["status"] == "active"  # Bob's untouched


def test_bulk_set_category_needs_a_category(client, alice):
    sub = create(client, alice)
    r = client.post(f"{API}/bulk", headers=alice, json={"action": "set_category", "ids": [sub["id"]]})
    assert r.status_code == 422


# ---------------------------------------------------------------- payments
def test_record_and_list_payments(client, alice):
    sub = create(client, alice)
    r = client.post(f"{API}/{sub['id']}/payments", headers=alice, json=PAYMENT)
    assert r.status_code == 201
    pay = r.json()
    assert pay["source"] == "manual" and pay["verified"] is False

    client.post(f"{API}/{sub['id']}/payments", headers=alice, json={**PAYMENT, "payment_date": "2026-03-01"})
    listed = client.get(f"{API}/{sub['id']}/payments", headers=alice).json()
    assert [p["payment_date"] for p in listed] == ["2026-03-01", "2026-02-01"]  # newest first


def test_payment_cannot_claim_to_be_verified(client, alice):
    sub = create(client, alice)
    r = client.post(f"{API}/{sub['id']}/payments", headers=alice, json={**PAYMENT, "verified": True})
    assert r.status_code == 422


# ---------------------------------------------------------------- audit log
def test_audit_log_records_create_update_and_archive(client, db, alice):
    sub = create(client, alice)
    client.put(f"{API}/{sub['id']}", headers=alice, json={"amount": "19.99"})
    client.delete(f"{API}/{sub['id']}", headers=alice)

    import uuid
    rows = list(db.scalars(select(AuditLog).where(AuditLog.entity_id == uuid.UUID(sub["id"]))))
    assert {r.action for r in rows} == {"create", "update", "archive"}

    update = next(r for r in rows if r.action == "update")
    assert Decimal(update.old_values["amount"]) == Decimal("15.99")
    assert Decimal(update.new_values["amount"]) == Decimal("19.99")