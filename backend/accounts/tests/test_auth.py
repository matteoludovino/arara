from collections.abc import Callable
from typing import Any

import pytest
from rest_framework.test import APIClient

from accounts.models import Role, User
from conftest import PASSWORD

pytestmark = pytest.mark.django_db


def csrf_client() -> APIClient:
    """A browser-like client: CSRF is enforced, as it is for the real SPA."""
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/auth/csrf")
    return client


def login(client: APIClient, email: str, password: str = PASSWORD, token: bool = True) -> Any:
    headers = {"X-CSRFToken": client.cookies["csrftoken"].value} if token else {}
    return client.post("/api/auth/login", {"email": email, "password": password}, format="json", headers=headers)


def test_sign_in_returns_who_and_what(make_user: Callable[..., User]) -> None:
    user = make_user(Role.CASHIER)
    client = csrf_client()
    response = login(client, user.email)
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "cashier"
    assert body["capabilities"] == ["pos.cash", "pos.sell", "stock.view"]
    assert [loc["code"] for loc in body["locations"]] == ["CENTRO"]
    assert client.get("/api/auth/me").json()["email"] == user.email


def test_email_is_case_insensitive(make_user: Callable[..., User]) -> None:
    user = make_user(email="ana@arara.test")
    assert login(csrf_client(), "  ANA@Arara.TEST ").status_code == 200
    assert user.email == "ana@arara.test"


def test_wrong_password_and_unknown_email_get_the_same_answer(make_user: Callable[..., User]) -> None:
    user = make_user()
    wrong = login(csrf_client(), user.email, "not-the-password")
    unknown = login(csrf_client(), "nobody@arara.test")
    assert wrong.status_code == unknown.status_code == 400
    assert wrong.json() == unknown.json() == {"detail": "E-mail ou senha incorretos."}


def test_sign_in_requires_the_csrf_token(make_user: Callable[..., User]) -> None:
    # Without it, another site could sign the visitor into an account of its choosing.
    user = make_user()
    assert login(csrf_client(), user.email, token=False).status_code == 403


def test_writes_require_the_csrf_token_once_signed_in(make_user: Callable[..., User]) -> None:
    user = make_user()
    client = csrf_client()
    assert login(client, user.email).status_code == 200
    assert client.post("/api/auth/logout").status_code == 403
    token = client.cookies["csrftoken"].value
    assert client.post("/api/auth/logout", headers={"X-CSRFToken": token}).status_code == 204
    assert client.get("/api/auth/me").status_code == 403


def test_deactivation_ends_existing_sessions(make_user: Callable[..., User]) -> None:
    user = make_user()
    client = csrf_client()
    assert login(client, user.email).status_code == 200
    user.is_active = False
    user.save()
    assert client.get("/api/auth/me").status_code == 403
    assert login(csrf_client(), user.email).status_code == 400


def test_sign_in_is_rate_limited(make_user: Callable[..., User]) -> None:
    user = make_user()
    client = csrf_client()
    statuses = [login(client, user.email, "wrong-password").status_code for _ in range(11)]
    assert statuses[:10] == [400] * 10
    assert statuses[10] == 429


def test_the_api_denies_by_default() -> None:
    assert APIClient().get("/api/users").status_code == 403
    assert APIClient().get("/api/locations").status_code == 403
