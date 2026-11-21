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

class ClickEvent(Base):
    __tablename__ = "click_events"
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    url_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)
