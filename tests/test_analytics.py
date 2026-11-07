from datetime import datetime, timedelta, timezone

URL = "/api/v1/subscriptions"


def _today():
    return datetime.now(timezone.utc).date()


def _sub(client, headers, name, amount, interval="month", currency="USD", **extra):
    body = {"name": name, "amount": amount, "currency": currency, "billing_interval": interval, **extra}
    r = client.post(URL, json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _totals(client, headers):
    r = client.get("/api/v1/analytics/overview", headers=headers)
    assert r.status_code == 200, r.text
    return r.json(), {t["currency"]: t for t in r.json()["totals"]}


def test_monthly_and_yearly_equivalents(client, alice):
    _sub(client, alice, "Netflix", 10)
    _sub(client, alice, "Domain", 120, interval="year")
    _, t = _totals(client, alice)
    assert float(t["USD"]["monthly"]) == 20.0
    assert float(t["USD"]["yearly"]) == 240.0
    assert t["USD"]["count"] == 2


def test_currencies_are_never_summed(client, alice):
    _sub(client, alice, "Netflix", 10)
    _sub(client, alice, "Spotify", 8, currency="EUR")
    _, t = _totals(client, alice)
    assert float(t["USD"]["monthly"]) == 10.0
    assert float(t["EUR"]["monthly"]) == 8.0


def test_paused_and_archived_are_excluded(client, alice):
    _sub(client, alice, "Keep", 10)
    paused = _sub(client, alice, "Paused", 50)
    gone = _sub(client, alice, "Gone", 70)
    assert client.put(f"{URL}/{paused['id']}", json={"status": "paused"}, headers=alice).status_code == 200
    assert client.delete(f"{URL}/{gone['id']}", headers=alice).status_code == 200
    _, t = _totals(client, alice)
    assert float(t["USD"]["monthly"]) == 10.0


def test_shared_subscription_uses_my_share(client, alice):
    _sub(client, alice, "Family plan", 20, is_shared=True, my_share_percent=50)
    _, t = _totals(client, alice)
    assert float(t["USD"]["monthly"]) == 10.0


def test_weekly_and_every_n_intervals(client, alice):
    _sub(client, alice, "Weekly", 12, interval="week")            # 12 * 52/12 = 52 / month
    _sub(client, alice, "Quarterly", 30, interval_count=3)        # 30 / 3 = 10 / month
    _, t = _totals(client, alice)
    assert float(t["USD"]["monthly"]) == 62.0


def test_upcoming_renewals_window_and_rollover(client, alice):
    soon = _today() + timedelta(days=5)
    far = _today() + timedelta(days=90)
    stale = _today() - timedelta(days=3)   # past date: rolls forward a month, outside a 7-day window
    _sub(client, alice, "Soon", 10, next_renewal_date=soon.isoformat())
    _sub(client, alice, "Far", 10, next_renewal_date=far.isoformat())
    _sub(client, alice, "Stale", 10, next_renewal_date=stale.isoformat())
    r = client.get("/api/v1/analytics/overview?days=7", headers=alice)
    names = [u["name"] for u in r.json()["upcoming_renewals"]]
    assert names == ["Soon"]


def test_price_increase_is_reported_with_yearly_impact(client, alice):
    s = _sub(client, alice, "Netflix", 10)
    r = client.put(f"{URL}/{s['id']}", json={"amount": 12}, headers=alice)
    assert r.status_code == 200, r.text
    changes = client.get("/api/v1/analytics/price-changes", headers=alice).json()
    assert len(changes) == 1
    c = changes[0]
    assert c["name"] == "Netflix"
    assert float(c["change_percent"]) == 20.0
    assert float(c["yearly_impact"]) == 24.0


def test_no_price_change_without_a_change(client, alice):
    _sub(client, alice, "Netflix", 10)
    assert client.get("/api/v1/analytics/price-changes", headers=alice).json() == []


def test_analytics_are_private_and_need_login(client, alice, bob):
    _sub(client, alice, "Netflix", 10)
    data, _ = _totals(client, bob)
    assert data["totals"] == [] and data["subscription_count"] == 0
    assert client.get("/api/v1/analytics/overview").status_code == 401
    assert client.get("/api/v1/analytics/price-changes").status_code == 401