"""T1 done-when: 401 without token; /users returns 2."""
from conftest import AUTH


def test_no_token_401(client):
    assert client.get("/users").status_code == 401


def test_wrong_token_401(client):
    assert client.get("/users", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_users_returns_two(client):
    r = client.get("/users", headers=AUTH)
    assert r.status_code == 200
    users = r.json()
    assert [u["name"] for u in users] == ["William", "Jordan"]
    assert [u["is_demo"] for u in users] == [False, True]
