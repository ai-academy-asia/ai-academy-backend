"""Shared fixtures and helpers for the auth endpoint tests."""
import pytest

PASSWORD = "Passw0rd!"


def _login(client, email, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def student(make_student):
    account, headers = make_student(email="bat@student.test")
    return account, headers
