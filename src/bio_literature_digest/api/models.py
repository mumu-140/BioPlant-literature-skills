from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ReviewProvider = Literal["placeholder", "http-json", "nvidia-chat"]
SummaryProvider = Literal["placeholder", "http-json", "tencent-tmt", "nvidia-chat"]


class RunRequest(BaseModel):
    """Safe remote options accepted when starting a digest run."""

    model_config = ConfigDict(extra="forbid")

    window_start: datetime | None = None
    window_end: datetime | None = None
    skip_email: bool = True
    allow_review_pending: bool = True
    summary_provider: SummaryProvider | None = None
    review_provider: ReviewProvider | None = None

    @model_validator(mode="after")
    def validate_window(self) -> "RunRequest":
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("window_start and window_end must be provided together")
        if self.window_start and (self.window_start.utcoffset() is None or self.window_end.utcoffset() is None):
            raise ValueError("window_start and window_end must include a timezone")
        if self.window_start and self.window_end and self.window_start >= self.window_end:
            raise ValueError("window_start must be earlier than window_end")
        return self


class ArtifactInfo(BaseModel):
    name: str
    size: int = Field(ge=0)
    download_url: str


class RunStatus(BaseModel):
    id: str
    status: Literal["queued", "running", "success", "failed", "interrupted"]
    created_at_utc: str
    started_at_utc: str = ""
    finished_at_utc: str = ""
    exit_code: int | None = None
    current_step: str = ""
    failure_message: str = ""
    artifacts: list[ArtifactInfo] = Field(default_factory=list)


class RunAccepted(BaseModel):
    id: str
    status: str
    status_url: str


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    display_name: str = Field(min_length=1, max_length=100)
    role: Literal["admin", "operator", "viewer"]


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["admin", "operator", "viewer"] | None = None
    is_active: bool | None = None


class UserView(BaseModel):
    id: str
    username: str
    display_name: str
    role: str
    token_prefix: str
    is_active: bool
    created_at_utc: str
    updated_at_utc: str


class UserCreated(UserView):
    token: str


class TokenRotated(BaseModel):
    user_id: str
    token: str
