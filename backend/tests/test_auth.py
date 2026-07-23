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


def test_every_non_health_route_requires_authentication(anon_client):
    """Auth is enforced at the ROUTER level so a new route is protected by default.
    Previously only sessions.py carried the dependency, leaving the task catalog,
    gym job triggers, QA data and the whole dataset export open to anyone."""
    public_ok = anon_client.get("/health")
    assert public_ok.status_code == 200, "health must stay public for probes"

    for method, path in [
        ("get", "/api/tasks"),
        ("get", "/api/qa/tasks"),
        ("get", "/api/gym/tasks"),
        ("get", "/api/gym/status"),
        ("get", "/api/export/samples"),
        ("get", "/api/export/dataset.jsonl"),
        ("post", "/api/gym/tasks/M1/x/run-review"),
        ("post", "/api/admin/reset-sessions"),
    ]:
        r = getattr(anon_client, method)(path, **({"json": {}} if method == "post" else {}))
        assert r.status_code == 401, f"{method.upper()} {path} must be 401, got {r.status_code}"


def test_privileged_surfaces_require_the_reviewer_role(client, reviewer_client):
    """A plain annotator must not adjudicate which sample ships, nor pull the whole
    dataset; a reviewer may."""
    assert client.post("/api/qa/tasks/GYM-2041/adjudicate", json={"sessionId": str(__import__("uuid").uuid4())}).status_code == 403
    assert client.get("/api/export/dataset.jsonl").status_code == 403
    assert reviewer_client.get("/api/export/dataset.jsonl").status_code == 200


def test_prod_refuses_to_start_with_a_forgeable_secret(monkeypatch):
    """With the shipped default secret anyone can mint a token for any account,
    which makes every route gate meaningless — so prod must fail closed at boot."""
    import pytest

    from app.main import _assert_prod_safe
    from app.config import settings as st

    monkeypatch.setattr(st, "env", "prod")
    monkeypatch.setattr(st, "auth_secret", "dev-insecure-auth-secret-change-me")
    monkeypatch.setattr(st, "auto_create_all", False)
    with pytest.raises(RuntimeError, match="AUTH_SECRET"):
        _assert_prod_safe()

    monkeypatch.setattr(st, "auth_secret", "a-real-production-secret")
    _assert_prod_safe()  # now fine

    monkeypatch.setattr(st, "auto_create_all", True)   # prod must use migrations
    with pytest.raises(RuntimeError, match="auto_create_all"):
        _assert_prod_safe()


def test_seeded_dev_accounts_never_land_in_prod(monkeypatch, db_session):
    """The 5 seeded accounts share a public dev password (one is a reviewer)."""
    from app.config import settings as st
    from app.seed import seed_annotators

    monkeypatch.setattr(st, "env", "prod")
    assert seed_annotators(db_session) == 0
