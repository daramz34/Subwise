from sqlalchemy import select

from app.models import Category

CATS = "/api/v1/categories"
TAGS = "/api/v1/tags"
SUBS = "/api/v1/subscriptions"


def make_default(db, name="Streaming"):
    cat = Category(user_id=None, name=name, color="#112233", icon="film", is_default=True)
    db.add(cat)
    db.commit()
    return cat


# ---------------------------------------------------------------- categories
def test_list_shows_defaults_and_own_but_not_others(client, db, alice, bob):
    make_default(db)
    client.post(CATS, headers=alice, json={"name": "Alice only"})
    names = [c["name"] for c in client.get(CATS, headers=bob).json()]
    assert "Streaming" in names and "Alice only" not in names
    names = [c["name"] for c in client.get(CATS, headers=alice).json()]
    assert names[0] == "Streaming" and "Alice only" in names  # defaults first


def test_category_names_must_be_unique_including_defaults(client, db, alice):
    make_default(db, "Streaming")
    assert client.post(CATS, headers=alice, json={"name": "Mine"}).status_code == 201
    assert client.post(CATS, headers=alice, json={"name": "MINE"}).status_code == 409
    assert client.post(CATS, headers=alice, json={"name": "streaming"}).status_code == 409


def test_two_users_can_use_the_same_custom_name(client, alice, bob):
    assert client.post(CATS, headers=alice, json={"name": "Hobbies"}).status_code == 201
    assert client.post(CATS, headers=bob, json={"name": "Hobbies"}).status_code == 201


def test_default_categories_are_read_only(client, db, alice):
    cat = make_default(db)
    r = client.patch(f"{CATS}/{cat.id}", headers=alice, json={"name": "Renamed"})
    assert r.status_code == 403
    assert db.scalar(select(Category).where(Category.id == cat.id)).name == "Streaming"


def test_update_own_category(client, alice):
    cat = client.post(CATS, headers=alice, json={"name": "Old", "color": "#AABBCC"}).json()
    r = client.patch(f"{CATS}/{cat['id']}", headers=alice, json={"name": "New"})
    assert r.status_code == 200
    assert r.json()["name"] == "New" and r.json()["color"] == "#AABBCC"  # color untouched


def test_cannot_update_another_users_category(client, alice, bob):
    cat = client.post(CATS, headers=bob, json={"name": "Bob's"}).json()
    assert client.patch(f"{CATS}/{cat['id']}", headers=alice, json={"name": "Mine now"}).status_code == 404


def test_category_validation(client, alice):
    assert client.post(CATS, headers=alice, json={"name": "X", "color": "red"}).status_code == 422
    assert client.post(CATS, headers=alice, json={"name": ""}).status_code == 422
    assert client.post(CATS, headers=alice, json={"name": "X", "is_default": True}).status_code == 422


# ---------------------------------------------------------------- tags
def test_tags_are_private_and_unique_per_user(client, alice, bob):
    assert client.post(TAGS, headers=alice, json={"name": "work"}).status_code == 201
    assert client.post(TAGS, headers=alice, json={"name": "WORK"}).status_code == 409
    assert client.post(TAGS, headers=bob, json={"name": "work"}).status_code == 201  # Bob's own
    assert [t["name"] for t in client.get(TAGS, headers=alice).json()] == ["work"]


def test_delete_tag_removes_it_from_subscriptions(client, alice):
    tag = client.post(TAGS, headers=alice, json={"name": "work"}).json()
    sub = client.post(SUBS, headers=alice, json={
        "name": "Slack", "amount": "8.00", "currency": "USD", "tag_ids": [tag["id"]],
    }).json()
    assert client.delete(f"{TAGS}/{tag['id']}", headers=alice).status_code == 200
    assert client.get(f"{SUBS}/{sub['id']}", headers=alice).json()["tags"] == []
    assert client.get(TAGS, headers=alice).json() == []


def test_cannot_delete_another_users_tag(client, alice, bob):
    tag = client.post(TAGS, headers=bob, json={"name": "mine"}).json()
    assert client.delete(f"{TAGS}/{tag['id']}", headers=alice).status_code == 404
    assert len(client.get(TAGS, headers=bob).json()) == 1


def test_tag_endpoints_require_login(client):
    assert client.get(TAGS).status_code == 401
    assert client.get(CATS).status_code == 401