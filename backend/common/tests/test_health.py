import pytest
from django.test import Client


def test_health_answers_without_the_database(client: Client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_ready_checks_the_database(client: Client) -> None:
    response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "up"}


def test_api_docs_are_public(client: Client) -> None:
    assert client.get("/api/schema/").status_code == 200
    assert client.get("/api/docs/").status_code == 200
