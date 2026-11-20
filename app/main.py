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
