import os

os.environ.update(
    DEBUG="true",
    SECRET_KEY="test-secret-key-test-secret-key-1234",
    DATABASE_URL="sqlite:///./test.db",
    RATE_LIMIT_ENABLED="false",
)

import pytest
from fastapi.testclient import TestClient

from core.database import engine
from main import app
from models import Base


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


def register_and_login(client, email, role="customer"):
    r = client.post(
        "/auth/register",
        json={"email": email, "password": "password123", "full_name": "Test User", "role": role},
    )
    assert r.status_code == 201, r.text
    r = client.post("/auth/login", data={"username": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
