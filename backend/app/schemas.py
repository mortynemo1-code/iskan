from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from .activity import validate_interval


class RegisterRequest(BaseModel):
    installation_token: str
    hostname: str = Field(min_length=1, max_length=255)
    machine_guid: str = Field(min_length=1, max_length=255)
    os_version: str = Field(min_length=1, max_length=255)
    agent_version: str = Field(min_length=1, max_length=50)


class RegisterResponse(BaseModel):
    device_id: UUID
    device_token: str
    heartbeat_interval_seconds: int
    approval_required: bool = True


class HeartbeatRequest(BaseModel):
    agent_version: str = Field(min_length=1, max_length=50)
    activity_state: str | None = None
    cpu_percent: float = Field(default=0, ge=0, le=100)
    ram_mb: int = Field(default=0, ge=0)


class HeartbeatResponse(BaseModel):
    server_time: datetime
    next_heartbeat_seconds: int
    commands: list[dict] = Field(default_factory=list)


class PresenceItem(BaseModel):
    device_id: UUID
    employee_id: UUID | None
    employee_name: str | None
    department_name: str | None
    hostname: str
    is_approved: bool
    is_online: bool
    status: str
    last_seen: datetime | None
    seconds_since_seen: int | None


class ActivityEventInput(BaseModel):
    event_uuid: UUID
    ts_start: datetime
    ts_end: datetime
    state: str
    process_name: str | None = Field(default=None, max_length=255)
    app_name: str | None = Field(default=None, max_length=255)
    window_title: str | None = Field(default=None, max_length=1024)
    url_domain: str | None = Field(default=None, max_length=255)
    url_path: str | None = Field(default=None, max_length=2048)
    windows_session_id: int | None = None
    is_remote: bool = False
    keystrokes: int = Field(default=0, ge=0)
    clicks: int = Field(default=0, ge=0)
    mouse_distance: int = Field(default=0, ge=0)
    windows_sid: str | None = Field(default=None, max_length=200)
    windows_username: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_event(self) -> "ActivityEventInput":
        validate_interval(self.ts_start, self.ts_end, self.state)
        return self


class ActivityBatchRequest(BaseModel):
    sent_at: datetime
    events: Annotated[list[ActivityEventInput], Field(min_length=1, max_length=5000)]

    @model_validator(mode="after")
    def validate_batch_order(self) -> "ActivityBatchRequest":
        if self.sent_at.tzinfo is None:
            raise ValueError("sent_at must contain a timezone")
        groups: dict[tuple[str | None, int | None], list[ActivityEventInput]] = {}
        seen: set[UUID] = set()
        for event in self.events:
            if event.event_uuid in seen: continue
            seen.add(event.event_uuid)
            groups.setdefault((event.windows_sid, event.windows_session_id), []).append(event)
        for group in groups.values():
            ordered = sorted(group, key=lambda item: item.ts_start)
            if any(current.ts_start < previous.ts_end for previous, current in zip(ordered, ordered[1:])):
                raise ValueError("Events in one Windows session must not overlap")
        return self


class ActivityBatchResponse(BaseModel):
    accepted: int
    duplicates: int


class TimelineSegment(BaseModel):
    event_uuid: UUID
    ts_start: datetime
    ts_end: datetime
    duration_sec: int
    state: str
    app_name: str | None
    process_name: str | None
    window_title: str | None
    url_domain: str | None
    url_path: str | None
    category_id: int | None


class TimelineTotals(BaseModel):
    productive: int = 0
    neutral: int = 0
    unproductive: int = 0
    idle: int = 0
    locked: int = 0
    break_time: int = 0


class EmployeeTimeline(BaseModel):
    device_id: UUID
    employee_id: UUID | None
    employee_name: str | None
    department_name: str | None
    hostname: str
    segments: list[TimelineSegment]
    totals: TimelineTotals


class TimelineResponse(BaseModel):
    range_start: datetime
    range_end: datetime
    employees: list[EmployeeTimeline]


class AgentConfig(BaseModel):
    activity_poll_interval_sec: int = Field(default=2, ge=1, le=5)
    idle_threshold_sec: int = Field(default=300, ge=60, le=1800)
    batch_interval_sec: int = Field(default=60, ge=30, le=300)
    batch_size: int = Field(default=500, ge=1, le=5000)
    collect_window_titles: bool = True
    collect_browser_urls: bool = True
    personal_time_enabled: bool = True
    screenshot_enabled: bool = True
    screenshot_interval_sec: int = Field(default=300, ge=60, le=3600)
    screenshot_random_offset: bool = True
    screenshot_all_monitors: bool = False
    screenshot_multi_monitor_mode: str = Field(default="merge", pattern="^(merge|separate)$")
    screenshot_max_long_side: int = Field(default=1600, ge=640, le=3840)
    screenshot_quality: int = Field(default=70, ge=30, le=95)
    screenshot_on_unproductive: bool = False
    screenshot_blur_mode: str = Field(default="none", pattern="^(none|full|private_apps)$")
    private_app_patterns: list[str] = Field(default_factory=list, max_length=100)
    employee_timezone: str = "UTC"
    work_schedule: dict | None = None
    holiday_dates: list[str] = Field(default_factory=list)
    schedule_grace_minutes: int = Field(default=60, ge=0, le=240)
    collect_outside_schedule_activity: bool = True
    treat_media_playback_as_activity: bool = True
    video_recording_mode: str = Field(default="on_demand", pattern="^(off|on_demand|always_on|scheduled|trigger)$")
    video_profile: str = Field(default="medium", pattern="^(low|medium|high)$")
    video_schedule_windows: list[dict] = Field(default_factory=list, max_length=32)
    video_trigger_minutes: int = Field(default=5, ge=1, le=240)
    video_on_demand_timeout_minutes: int = Field(default=30, ge=1, le=480)
    privacy_contact: str = Field(default="Ответственный назначается работодателем", max_length=300)
    privacy_retention_notice: str = Field(default="Сроки хранения задаются политикой организации", max_length=300)


class AgentSystemEventRequest(BaseModel):
    code: str = Field(pattern="^[a-z0-9_]{2,50}$")
    occurred_at: datetime
    windows_session_id: int | None = None
    details: dict = Field(default_factory=dict)
