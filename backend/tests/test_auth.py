from app.models import Role


def login(client, email, password):
    return client.post("/api/auth/login", data={"username": email, "password": password})


def test_login_returns_token_that_identifies_the_user(client, make_user):
    user, _ = make_user(Role.labeler, password="s3cret-pass")

    response = login(client, user.email, "s3cret-pass")
    assert response.status_code == 200
    token = response.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == user.email
    assert me.json()["role"] == "labeler"
    assert "password_hash" not in me.json()


def test_login_email_is_case_insensitive(client, make_user):
    user, _ = make_user(Role.labeler, password="s3cret-pass")
    assert login(client, user.email.upper(), "s3cret-pass").status_code == 200


def test_login_rejects_wrong_password_and_unknown_email(client, make_user):
    user, _ = make_user(Role.labeler, password="s3cret-pass")
    assert login(client, user.email, "wrong-password").status_code == 401
    assert login(client, "nobody@example.com", "s3cret-pass").status_code == 401


def test_protected_routes_need_a_valid_token(client):
    assert client.get("/api/auth/me").status_code == 401
    bad = {"Authorization": "Bearer not-a-real-token"}
    assert client.get("/api/auth/me", headers=bad).status_code == 401


def test_only_admins_can_create_users(client, admin, make_user):
    _, labeler = make_user(Role.labeler)
    body = {"email": "new@example.com", "password": "password123", "role": "labeler"}

    assert client.post("/api/users", json=body, headers=labeler).status_code == 403
    assert client.post("/api/users", json=body, headers=admin).status_code == 201
    assert client.post("/api/users", json=body, headers=admin).status_code == 409
