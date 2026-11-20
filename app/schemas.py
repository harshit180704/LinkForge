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
