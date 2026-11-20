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
