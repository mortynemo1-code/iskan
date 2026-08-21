from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ScreenshotUploadResponse(BaseModel):
    id: int
    duplicate: bool
    duplicate_of_id: int | None


class ScreenshotItem(BaseModel):
    id: int
    employee_id: UUID | None
    employee_name: str | None
    device_id: UUID
    hostname: str
    taken_at: datetime
    monitor_index: int
    width: int
    height: int
    size_bytes: int
    is_blurred: bool
    duplicate_of_id: int | None
    state: str | None
    category_id: int | None
    category_name: str | None
    app_name: str | None
    url_domain: str | None
    thumbnail_url: str
    image_url: str


class ScreenshotList(BaseModel):
    items: list[ScreenshotItem]
    next_before: datetime | None
