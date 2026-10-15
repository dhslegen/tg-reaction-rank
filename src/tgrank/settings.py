"""运行期设置：存 DB（meta.settings 一个 JSON），网页修改后立即生效。"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _check_hhmm(v: str) -> str:
    if not _HHMM.match(v):
        raise ValueError("时间格式应为 HH:MM，例如 09:00")
    return v


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class SyncSettings(_Model):
    new_interval_min: int = Field(10, ge=5, le=1440)
    refresh_interval_min: int = Field(60, ge=15, le=1440)
    refresh_days: int = Field(7, ge=1, le=90)
    calibrate_weekday: int = Field(6, ge=0, le=6)   # 0 = 周一 … 6 = 周日
    calibrate_time: str = "04:00"

    _hhmm = field_validator("calibrate_time")(_check_hhmm)


class PushSettings(_Model):
    enabled: bool = True
    frequency: Literal["weekly", "monthly"] = "weekly"
    weekday: int = Field(0, ge=0, le=6)              # weekly 时生效
    monthday: int = Field(1, ge=1, le=28)            # monthly 时生效；不提供 29–31 避免短月跳过
    time: str = "09:00"
    range_days: int | None = Field(None, ge=1, le=366)  # 为空则跟随频率：weekly 7 天，monthly 30 天
    target: str = "me"                               # 'me' = 收藏夹；否则为私人频道的 marked id

    _hhmm = field_validator("time")(_check_hhmm)

    @field_validator("target")
    @classmethod
    def _check_target(cls, v: str) -> str:
        v = v.strip()
        if v != "me" and not re.fullmatch(r"-?\d+", v):
            raise ValueError("推送目标只能是 me（收藏夹）或频道 id")
        return v

    @property
    def effective_range_days(self) -> int:
        return self.range_days or (7 if self.frequency == "weekly" else 30)


class Settings(_Model):
    sync: SyncSettings = SyncSettings()
    push: PushSettings = PushSettings()


def load_settings(conn: sqlite3.Connection) -> Settings:
    row = conn.execute("SELECT value FROM meta WHERE key = 'settings'").fetchone()
    return Settings.model_validate(json.loads(row[0])) if row else Settings()


def save_settings(conn: sqlite3.Connection, s: Settings) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES ('settings', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (s.model_dump_json(),),
    )
