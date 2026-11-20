from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db, settings
from app.models import ShortURL
from app.schemas import URLCreate, URLResponse
from app.shortener import encode_base62


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Scalable URL Shortener",
    version="1.0.0",
    lifespan=lifespan,
)


def to_response(url: ShortURL) -> URLResponse:
    return URLResponse(
        id=url.id,
        original_url=url.original_url,
        short_code=url.short_code,
        short_url=f"{settings.base_url}/{url.short_code}",
        click_count=url.click_count,
        created_at=url.created_at,
        expires_at=url.expires_at,
    )


def find_url(db: Session, code: str):
    return db.scalar(
        select(ShortURL).where(
            ShortURL.short_code == code
        )
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post(
    "/api/v1/urls",
    response_model=URLResponse,
    status_code=201,
)
def create_url(
    payload: URLCreate,
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)

    if payload.expires_at is not None:
        expiry = payload.expires_at

        if expiry.tzinfo is None:
            raise HTTPException(
                422,
                "Expiry must include a timezone",
            )

        if expiry <= now:
            raise HTTPException(
                422,
                "Expiry must be in the future",
            )

    if payload.custom_alias:
        if find_url(db, payload.custom_alias):
            raise HTTPException(409, "Alias already exists")

    url = ShortURL(
        original_url=str(payload.original_url),
        expires_at=payload.expires_at,
    )

    try:
        db.add(url)
        db.flush()

        url.short_code = (
            payload.custom_alias
            or encode_base62(url.id)
        )

        db.commit()
        db.refresh(url)

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            "Short code already exists",
        )

    return to_response(url)


@app.get("/api/v1/urls/{code}/stats")
def get_stats(
    code: str,
    db: Session = Depends(get_db),
):
    url = find_url(db, code)

    if not url:
        raise HTTPException(404, "URL not found")

    return {
        "short_code": code,
        "click_count": url.click_count,
        "created_at": url.created_at,
        "expires_at": url.expires_at,
    }


@app.delete(
    "/api/v1/urls/{code}",
    status_code=204,
)
def delete_url(
    code: str,
    db: Session = Depends(get_db),
):
    url = find_url(db, code)

    if not url:
        raise HTTPException(404, "URL not found")

    db.delete(url)
    db.commit()


@app.get("/{code}")
def redirect_url(
    code: str,
    db: Session = Depends(get_db),
):
    url = find_url(db, code)

    if not url:
        raise HTTPException(404, "URL not found")

    if url.expires_at is not None:
        if url.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(410, "URL expired")

    db.execute(
        update(ShortURL)
        .where(ShortURL.id == url.id)
        .values(click_count=ShortURL.click_count + 1)
    )
    db.commit()

    return RedirectResponse(
        url.original_url,
        status_code=302,
    )
