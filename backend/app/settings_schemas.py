from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


ScopeType = Literal["global", "department", "employee"]


class ColorSchemeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    colors: dict[str, str]
    patterns_enabled: bool = False

    @model_validator(mode="after")
    def validate_colors(self) -> "ColorSchemeCreate":
        required = {"PRODUCTIVE", "NEUTRAL", "UNPRODUCTIVE", "IDLE", "LOCKED", "BREAK", "ABSENCE", "OFFLINE"}
        if not required.issubset(self.colors): raise ValueError("Не заданы все состояния")
        if any(len(color) != 7 or not color.startswith("#") for color in self.colors.values()): raise ValueError("Цвет должен быть #RRGGBB")
        return self


class ColorSchemeItem(ColorSchemeCreate):
    id: UUID
    is_default: bool
    created_at: datetime


class ThresholdSchemeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    rules: list[dict] = Field(min_length=1, max_length=20)
    scope_type: ScopeType = "global"
    scope_id: UUID | None = None

    @model_validator(mode="after")
    def validate_rules(self) -> "ThresholdSchemeCreate":
        minimums = []
        for rule in self.rules:
            if not {"min", "code", "label", "color"}.issubset(rule): raise ValueError("Порог требует min, code, label, color")
            minimum = float(rule["min"])
            if minimum < 0 or minimum > 100: raise ValueError("Порог вне 0–100")
            minimums.append(minimum)
        if 0 not in minimums: raise ValueError("Должен быть порог с min=0")
        return self


class ThresholdSchemeItem(ThresholdSchemeCreate):
    id: UUID
    is_default: bool
    created_at: datetime


class AppearanceSettings(BaseModel):
    color_scheme_id: UUID
    threshold_scheme_id: UUID
    color_scheme: ColorSchemeItem | None = None
    threshold_scheme: ThresholdSchemeItem | None = None


class ScopedSettingsUpdate(BaseModel):
    scope_type: ScopeType = "global"
    scope_id: UUID | None = None
    value: dict


class ScopedSettingsItem(ScopedSettingsUpdate):
    key: str
    updated_at: datetime


class RetentionPolicy(BaseModel):
    id: UUID | None = None
    data_type: Literal["screenshots", "video", "events"]
    scope_type: ScopeType = "global"
    scope_id: UUID | None = None
    days: int = Field(ge=1, le=3650)


class AuditItem(BaseModel):
    id: int
    user_id: UUID | None
    user_name: str | None
    action: str
    object_type: str
    object_id: str | None
    target_employee_id: UUID | None
    target_employee_name: str | None
    ip_address: str | None
    user_agent: str | None
    details: dict
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditItem]
    total: int
    page: int
    per_page: int


class NotificationItem(BaseModel):
    id: int
    notification_type: str
    payload: dict
    is_read: bool
    created_at: datetime
