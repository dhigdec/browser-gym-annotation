"""Auth — login-gated platform, cookie sessions, closed registration."""

from app import auth as authmod
from app.models import Annotator


def _make(db, email, password="secret1", **kw):
    db.add(Annotator(email=email, password_hash=authmod.hash_password(password), **kw))
    db.commit()


def test_protected_route_requires_auth(anon_client):
    # a mutating session route is gated — no cookie → 401
    assert anon_client.post("/api/tasks/GYM-2041/sessions", json={}).status_code == 401


def test_login_sets_cookie_and_me_returns_profile(anon_client, db_session):
    _make(db_session, "lena@x.io", display_name="Lena", avatar_hue=120)
    r = anon_client.post("/api/auth/login", json={"email": "lena@x.io", "password": "secret1"})
    assert r.status_code == 200 and r.json()["email"] == "lena@x.io"
    me = anon_client.get("/api/auth/me")  # the login cookie now rides on the client
    assert me.status_code == 200
    body = me.json()
    assert body["displayName"] == "Lena" and body["avatarHue"] == 120
    assert body["stats"]["sessions"] == 0 and body["stats"]["submitted"] == 0


def test_login_wrong_password_401(anon_client, db_session):
    _make(db_session, "max@x.io", password="right1")
    assert anon_client.post("/api/auth/login", json={"email": "max@x.io", "password": "wrong1"}).status_code == 401


def test_deactivated_account_cannot_login(anon_client, db_session):
    _make(db_session, "gone@x.io", is_active=False)
    assert anon_client.post("/api/auth/login", json={"email": "gone@x.io", "password": "secret1"}).status_code == 403


def test_registration_is_closed(anon_client):
    assert anon_client.post("/api/auth/register", json={"email": "new@x.io", "password": "abc123"}).status_code == 403


def test_forged_token_is_rejected(anon_client):
    anon_client.cookies.set("bg_auth", "not.a.valid.token")
    assert anon_client.get("/api/auth/me").status_code == 401
