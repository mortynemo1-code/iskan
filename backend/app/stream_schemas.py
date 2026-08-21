from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class StreamStartRequest(BaseModel):
    profile: Literal["low", "medium", "high"] = "medium"
    mode: Literal["on_demand", "always_on", "scheduled", "trigger"] = "on_demand"


class StreamSessionItem(BaseModel):
    id: UUID
    employee_id: UUID | None
    employee_name: str | None
    department_name: str | None
    device_id: UUID
    hostname: str
    started_at: datetime
    ended_at: datetime | None
    profile: str
    status: str
    mode: str
    viewer_url: str
    whep_url: str
    hls_url: str


class AgentCommand(BaseModel):
    id: UUID
    command: str
    payload: dict


class CommandAck(BaseModel):
    success: bool = True
    message: str | None = Field(default=None, max_length=1000)


class ArchiveSpan(BaseModel):
    start: datetime
    duration: float
    url: str


class ArchiveClipRequest(BaseModel):
    employee_id: UUID
    start: datetime
    end: datetime


class ArchiveClipResponse(BaseModel):
    url: str


class PinRequest(BaseModel):
    employee_id: UUID
    start: datetime
    end: datetime
    reason: str | None = Field(default=None, max_length=1000)
