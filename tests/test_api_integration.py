import os
import pytest
from fastapi.testclient import TestClient

@pytest.mark.skipif(not os.getenv("RUN_INTEGRATION_TESTS"), reason="Set RUN_INTEGRATION_TESTS=1 and TEST_DATABASE_URL")
def test_auth_create_redirect_stats_delete(monkeypatch):
    test_url = os.environ.get("TEST_DATABASE_URL")
    assert test_url and "urlshortener_test" in test_url, "Use an isolated test database"
    monkeypatch.setenv("DATABASE_URL", test_url)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base, get_db
    from app.main import app
    from app import models
    import uuid
    engine = create_engine(test_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    def override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            email = f"{uuid.uuid4().hex}@example.com"
            r = client.post("/api/v1/auth/register", json={"email":email,"password":"StrongPassword123!"})
            assert r.status_code == 201, r.text
            token = r.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            r = client.post("/api/v1/urls", headers=headers, json={
                "original_url":"https://example.com", "custom_alias":f"t{uuid.uuid4().hex[:12]}"
            })
            assert r.status_code == 201, r.text
            code = r.json()["short_code"]
            r = client.get(f"/{code}", follow_redirects=False)
            assert r.status_code == 302
            assert r.headers["location"].startswith("https://example.com")
            assert client.get(f"/api/v1/urls/{code}/stats", headers=headers).status_code == 200
            assert client.delete(f"/api/v1/urls/{code}", headers=headers).status_code == 204
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
