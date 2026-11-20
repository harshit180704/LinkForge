from pathlib import Path
from textwrap import dedent
import shutil

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"
if not (APP / "main.py").exists() or not (ROOT / "docker-compose.yml").exists():
    raise SystemExit("Run this from your existing scalable-url-shortener project folder.")

files = {
"app/database.py": r"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

class Settings(BaseSettings):
    database_url: str
    base_url: str = "http://localhost:8000"
    redis_url: str = "redis://localhost:6380/0"
    jwt_secret: str
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    with SessionLocal() as db:
        yield db
""",
"app/models.py": r"""
from datetime import datetime, timezone
from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))

class ShortURL(Base):
    __tablename__ = "short_urls"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    original_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    short_code: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    click_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    owner_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)

class ProcessedClick(Base):
    __tablename__ = "processed_clicks"
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
""",
"app/schemas.py": r"""
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, HttpUrl

class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class URLCreate(BaseModel):
    original_url: HttpUrl
    custom_alias: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{3,32}$")
    expires_at: datetime | None = None

class URLResponse(BaseModel):
    id: int
    original_url: str
    short_code: str
    short_url: str
    click_count: int
    created_at: datetime
    expires_at: datetime | None
    model_config = {"from_attributes": True}
""",
"app/auth.py": r"""
from datetime import datetime, timedelta, timezone
import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.database import get_db, settings
from app.models import User

password_hasher = PasswordHash.recommended()
bearer = HTTPBearer()

def hash_password(password: str) -> str:
    return password_hasher.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return password_hasher.verify(password, hashed)

def make_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=12)},
        settings.jwt_secret, algorithm="HS256"
    )

def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (InvalidTokenError, ValueError, KeyError, TypeError):
        raise HTTPException(401, "Invalid or expired token")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(401, "User not found")
    return user
""",
"app/redis_client.py": r"""
import redis
from app.database import settings
client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
""",
"app/main.py": r"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import current_user, hash_password, make_token, verify_password
from app.database import Base, engine, get_db, settings
from app.models import ShortURL, User
from app.redis_client import client as redis_client
from app.schemas import Credentials, Token, URLCreate, URLResponse
from app.shortener import encode_base62

CACHE_TTL = 300
STREAM = "url_clicks"
RESERVED = {"health", "docs", "redoc", "openapi.json", "api"}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Safe additive migration for the existing local PostgreSQL database.
    # Existing URLs remain intact and owner_id stays NULL for legacy records.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE short_urls ADD COLUMN IF NOT EXISTS owner_id BIGINT"))
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(title="Scalable URL Shortener", version="2.0", lifespan=lifespan)

def response_for(url: ShortURL) -> URLResponse:
    return URLResponse(
        id=url.id, original_url=url.original_url, short_code=url.short_code,
        short_url=f"{settings.base_url}/{url.short_code}",
        click_count=url.click_count, created_at=url.created_at, expires_at=url.expires_at,
    )

def find_url(db: Session, code: str):
    return db.scalar(select(ShortURL).where(ShortURL.short_code == code))

def limit(key: str, max_requests: int, seconds: int):
    # Redis atomic INCR; fail closed on Redis outage for protected writes.
    try:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, seconds)
    except Exception:
        raise HTTPException(503, "Rate limiter unavailable")
    if count > max_requests:
        raise HTTPException(429, "Too many requests")

@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}

@app.post("/api/v1/auth/register", response_model=Token, status_code=201)
def register(data: Credentials, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    limit(f"register:{ip}", 10, 3600)
    user = User(email=data.email.lower(), password_hash=hash_password(data.password))
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email already registered")
    return Token(access_token=make_token(user.id))

@app.post("/api/v1/auth/login", response_model=Token)
def login(data: Credentials, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    limit(f"login:{ip}", 30, 3600)
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    return Token(access_token=make_token(user.id))

@app.post("/api/v1/urls", response_model=URLResponse, status_code=201)
def create_url(data: URLCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    limit(f"create:{user.id}", 60, 3600)
    if data.expires_at:
        if data.expires_at.tzinfo is None or data.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(422, "Expiry must be a future timezone-aware timestamp")
    if data.custom_alias and data.custom_alias.lower() in RESERVED:
        raise HTTPException(422, "Reserved alias")
    # Use ~ prefix (not allowed in custom aliases) to prevent future collisions.
    # Existing Day 1 codes (e.g. '1') continue to work.
    url = ShortURL(original_url=str(data.original_url), expires_at=data.expires_at, owner_id=user.id)
    try:
        db.add(url)
        db.flush()
        code = data.custom_alias or ("~" + encode_base62(url.id))
        if find_url(db, code):
            raise HTTPException(409, "Alias already exists")
        url.short_code = code
        db.commit()
        db.refresh(url)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Alias already exists")
    except Exception:
        db.rollback()
        raise
    return response_for(url)

def owned_url(db: Session, code: str, user: User):
    url = find_url(db, code)
    if url is None or url.owner_id != user.id:
        raise HTTPException(404, "URL not found")
    return url

@app.get("/api/v1/urls/{code}/stats")
def stats(code: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    url = owned_url(db, code, user)
    return {"short_code": code, "click_count": url.click_count,
            "created_at": url.created_at, "expires_at": url.expires_at}

@app.delete("/api/v1/urls/{code}", status_code=204)
def delete_url(code: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    url = owned_url(db, code, user)
    db.delete(url)
    db.commit()
    try:
        redis_client.delete(f"url:{code}")
    except Exception:
        pass

@app.get("/{code}")
def redirect(code: str, db: Session = Depends(get_db)):
    if code in RESERVED:
        raise HTTPException(404, "Not found")
    destination = None
    try:
        cached = redis_client.get(f"url:{code}")
        if cached:
            destination = json.loads(cached)
    except Exception:
        pass
    if destination is None:
        url = find_url(db, code)
        if not url:
            raise HTTPException(404, "URL not found")
        destination = {
            "url": url.original_url,
            "expires_at": url.expires_at.isoformat() if url.expires_at else None,
            "id": url.id,
        }
        try:
            redis_client.setex(f"url:{code}", CACHE_TTL, json.dumps(destination))
        except Exception:
            pass
    if destination["expires_at"]:
        if datetime.fromisoformat(destination["expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(410, "URL expired")
    # Queue failure does not prevent redirect. This is best-effort analytics.
    try:
        redis_client.xadd(STREAM, {"url_id": str(destination["id"])}, maxlen=100000, approximate=True)
    except Exception:
        pass
    return RedirectResponse(destination["url"], status_code=302)
""",
"app/worker.py": r"""
import logging
import time
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal
from app.models import ProcessedClick, ShortURL
from app.redis_client import client

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("click-worker")
STREAM = "url_clicks"
GROUP = "analytics"
CONSUMER = "local-worker"

def process(event_id: str, url_id: int):
    with SessionLocal() as db:
        try:
            db.add(ProcessedClick(event_id=event_id))
            db.flush()  # unique event ID makes retries idempotent
            db.execute(update(ShortURL).where(ShortURL.id == url_id).values(
                click_count=ShortURL.click_count + 1
            ))
            db.commit()
        except IntegrityError:
            db.rollback()  # already processed

def run():
    try:
        client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise
    log.info("Click worker started")
    while True:
        try:
            # Reclaim abandoned pending messages from a crashed consumer.
            next_id = "0-0"
            while True:
                next_id, pending, _ = client.xautoclaim(
                    STREAM, GROUP, CONSUMER, min_idle_time=30000,
                    start_id=next_id, count=100
                )
                for event_id, fields in pending:
                    process(event_id, int(fields["url_id"]))
                    client.xack(STREAM, GROUP, event_id)
                if next_id == "0-0" or not pending:
                    break
            entries = client.xreadgroup(
                GROUP, CONSUMER, {STREAM: ">"}, count=20, block=2000
            )
            for _, messages in entries:
                for event_id, fields in messages:
                    process(event_id, int(fields["url_id"]))
                    client.xack(STREAM, GROUP, event_id)
        except Exception:
            log.exception("Worker error; retrying")
            time.sleep(2)

if __name__ == "__main__":
    run()
""",
"compose.redis.yml": r"""
services:
  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    ports:
      - "127.0.0.1:6380:6379"
    volumes:
      - redisdata:/data

volumes:
  redisdata:
""",
"tests/test_api_integration.py": r"""
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
""",
}
# Prevent overwriting local changes silently.
backup = ROOT / "backend-backup"
if backup.exists():
    raise SystemExit("backend-backup already exists. Stop to avoid overwriting backups.")
backup.mkdir()
for relative, contents in files.items():
    target = ROOT / relative
    if target.exists():
        saved = backup / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, saved)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dedent(contents).lstrip(), encoding="utf-8")

req = ROOT / "requirements.txt"
with req.open("a", encoding="utf-8") as f:
    f.write("\nredis>=5,<7\nPyJWT>=2.8,<3\npwdlib[argon2]>=0.2,<1\nemail-validator>=2,<3\n")

env = ROOT / ".env"
env_text = env.read_text(encoding="utf-8") if env.exists() else ""
if "DATABASE_URL=" not in env_text:
    raise SystemExit("Missing DATABASE_URL in .env; check your existing configuration.")
if "REDIS_URL=" not in env_text:
    env_text += "\nREDIS_URL=redis://localhost:6380/0\n"
if "JWT_SECRET=" not in env_text:
    import secrets
    env_text += "JWT_SECRET=" + secrets.token_urlsafe(48) + "\n"
env.write_text(env_text, encoding="utf-8")

ignore = ROOT / ".gitignore"
with ignore.open("a", encoding="utf-8") as f:
    f.write("\nbackend-backup/\n*.dump\n")
print("Upgrade files generated. Existing DATABASE_URL and PostgreSQL volume preserved.")
print("Original source files saved to backend-backup/.")
print("Next: pip install -r requirements.txt; docker compose -f docker-compose.yml -f compose.redis.yml up -d")
