"""End-to-end API test against an isolated PostgreSQL database.

Requires TEST_DATABASE_URL and RUN_INTEGRATION_TESTS=1; Redis must be running.
Never runs destructive setup against the production/development database.
"""
import os
import uuid

import pytest


def test_auth_create_redirect_stats_delete():
    if os.getenv("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to enable integration tests")

    test_url = os.getenv("TEST_DATABASE_URL", "")
    if not test_url:
        pytest.fail("TEST_DATABASE_URL is required")

    from sqlalchemy.engine import make_url
    parsed = make_url(test_url)
    if parsed.database != "urlshortener_test":
        pytest.fail("Refusing to modify any database except urlshortener_test")

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base, get_db
    from app.main import app as fastapi_app
    from app import models as _models  # Register SQLAlchemy models

    engine = create_engine(test_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    # TestClient intentionally has no context manager: this avoids running
    # the application's lifespan, which uses the normal .env DATABASE_URL.
    # All request DB sessions are overridden below.
    def test_db():
        with session_factory() as session:
            yield session

    initialized = False
    try:
        Base.metadata.drop_all(bind=engine)
        initialized = True
        Base.metadata.create_all(bind=engine)
        fastapi_app.dependency_overrides[get_db] = test_db

        client = TestClient(fastapi_app)
        email = f"integration-{uuid.uuid4().hex}@example.com"
        credentials = {"email": email, "password": "StrongPassword123!"}

        registered = client.post("/api/v1/auth/register", json=credentials)
        assert registered.status_code == 201, registered.text

        logged_in = client.post("/api/v1/auth/login", json=credentials)
        assert logged_in.status_code == 200, logged_in.text
        token = logged_in.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        alias = f"test-{uuid.uuid4().hex[:12]}"
        created = client.post(
            "/api/v1/urls",
            headers=headers,
            json={"original_url": "https://example.com", "custom_alias": alias},
        )
        assert created.status_code == 201, created.text
        assert created.json()["short_code"] == alias

        redirected = client.get(f"/{alias}", follow_redirects=False)
        assert redirected.status_code == 302, redirected.text
        assert redirected.headers["location"].startswith("https://example.com")

        forbidden = client.get(f"/api/v1/urls/{alias}/stats")
        assert forbidden.status_code in (401, 403), forbidden.text

        stats = client.get(f"/api/v1/urls/{alias}/stats", headers=headers)
        assert stats.status_code == 200, stats.text
        assert stats.json()["short_code"] == alias

        deleted = client.delete(f"/api/v1/urls/{alias}", headers=headers)
        assert deleted.status_code == 204, deleted.text

        missing = client.get(f"/api/v1/urls/{alias}/stats", headers=headers)
        assert missing.status_code == 404, missing.text
    finally:
        fastapi_app.dependency_overrides.clear()
        if initialized:
            Base.metadata.drop_all(bind=engine)
        engine.dispose()
