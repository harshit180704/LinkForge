
from pathlib import Path
from textwrap import dedent

FILES = {
    "requirements.txt": """
fastapi>=0.115,<1
uvicorn[standard]>=0.30,<1
sqlalchemy>=2.0,<3
psycopg[binary]>=3.2,<4
pydantic-settings>=2.5,<3
pytest>=8,<10
httpx>=0.27,<1
""",

    ".env": """
DATABASE_URL=postgresql+psycopg://urluser:localdevpassword@localhost:5432/urlshortener
BASE_URL=http://localhost:8000
""",

    ".gitignore": """
.venv/
__pycache__/
*.pyc
.pypytest_cache/
.pytest_cache/
.env
*.db
.coverage
""",

    "docker-compose.yml": """
services:
  db:
    image: postgres:17
    environment:
      POSTGRES_USER: urluser
      POSTGRES_PASSWORD: localdevpassword
      POSTGRES_DB: urlshortener
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U urluser -d urlshortener"]
      interval: 5s
      timeout: 3s
      retries: 10

volumes:
  pgdata:
""",

    "Dockerfile": """
FROM python:3.12-slim

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
""",

    "app/__init__.py": "",

    "app/database.py": """
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Settings(BaseSettings):
    database_url: str
    base_url: str = "http://localhost:8000"

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as session:
        yield session
""",

    "app/models.py": """
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ShortURL(Base):
    __tablename__ = "short_urls"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    original_url: Mapped[str] = mapped_column(
        String(2048),
        nullable=False,
    )

    short_code: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    click_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
""",

    "app/schemas.py": """
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class URLCreate(BaseModel):
    original_url: HttpUrl
    custom_alias: str | None = Field(
        default=None,
        pattern=r"^[a-zA-Z0-9_-]{3,32}$",
    )
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

    "app/shortener.py": """
ALPHABET = (
    "0123456789"
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
)


def encode_base62(number: int) -> str:
    if number < 0:
        raise ValueError("ID cannot be negative")

    if number == 0:
        return "0"

    result = ""

    while number:
        number, remainder = divmod(number, 62)
        result = ALPHABET[remainder] + result

    return result


def decode_base62(code: str) -> int:
    number = 0

    for char in code:
        number = number * 62 + ALPHABET.index(char)

    return number
""",

    "app/main.py": """
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
""",

    "tests/test_shortener.py": """
import pytest

from app.shortener import (
    decode_base62,
    encode_base62,
)


@pytest.mark.parametrize(
    "number",
    [0, 1, 10, 61, 62, 125, 1000, 999999],
)
def test_roundtrip(number):
    assert decode_base62(
        encode_base62(number)
    ) == number


def test_known_values():
    assert encode_base62(10) == "a"
    assert encode_base62(61) == "Z"
    assert encode_base62(62) == "10"


def test_negative_id():
    with pytest.raises(ValueError):
        encode_base62(-1)


def test_invalid_character():
    with pytest.raises(ValueError):
        decode_base62("!")
""",
}

for filename, content in FILES.items():
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        raise SystemExit(
            f"Refusing to overwrite existing file: {path}"
        )

    path.write_text(
        dedent(content).lstrip(),
        encoding="utf-8",
    )
    print(f"Created {filename}")

print("\\nProject files generated successfully!")
