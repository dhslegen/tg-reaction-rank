"""定时任务装配。用 APScheduler 3（AsyncIOScheduler + 内存 jobstore）：

- cron 按部署时区 TZ 解析（含夏令时），设置页改节奏后 reschedule 立即生效；
- max_instances=1 + coalesce 防止同一任务叠跑、停机后补跑风暴；
- 任务定义全部由 DB 里的设置派生，启动时重建，不需要持久化 jobstore。
任务之间的 Telegram 请求互斥由 TgManager 的锁负责，这里不再加锁。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .backup import make_backup
from .context import AppContext
from .db import connect
from .push import send_digest
from .settings import Settings, load_settings

log = logging.getLogger(__name__)
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
LABELS = {"fetch_new": "拉取新消息", "refresh_recent": "刷新近期反应", "calibrate": "全量校准",
          "push": "精华推送", "backup": "数据库备份"}
GRACE = {"push": 6 * 3600, "calibrate": 6 * 3600, "backup": 6 * 3600}  # 停机错过后，几小时内恢复仍补跑


def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


class Scheduler:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.aps = AsyncIOScheduler(timezone=ctx.env.tz)

    def _triggers(self, s: Settings) -> dict:
        tz = self.ctx.env.tz
        ch, cm = _hm(s.sync.calibrate_time)
        triggers = {
            "fetch_new": IntervalTrigger(minutes=s.sync.new_interval_min, timezone=tz),
            "refresh_recent": IntervalTrigger(minutes=s.sync.refresh_interval_min, timezone=tz),
            "calibrate": CronTrigger(day_of_week=WEEKDAYS[s.sync.calibrate_weekday], hour=ch, minute=cm, timezone=tz),
            "backup": CronTrigger(hour=3, minute=30, timezone=tz),
        }
        if s.push.enabled:
            ph, pm = _hm(s.push.time)
            if s.push.frequency == "weekly":
                triggers["push"] = CronTrigger(day_of_week=WEEKDAYS[s.push.weekday], hour=ph, minute=pm, timezone=tz)
            else:
                triggers["push"] = CronTrigger(day=s.push.monthday, hour=ph, minute=pm, timezone=tz)
        return triggers

    def _func(self, job_id: str):
        return {"fetch_new": self._fetch_new, "refresh_recent": self._refresh_recent, "calibrate": self._calibrate,
                "push": self._push, "backup": self._backup}[job_id]

    def start(self, settings: Settings) -> None:
        self.apply(settings)
        self.aps.start()

    def apply(self, settings: Settings) -> None:
        wanted = self._triggers(settings)
        for job_id in LABELS:
            existing = self.aps.get_job(job_id)
            if job_id not in wanted:
                if existing:
                    existing.remove()
            elif existing:
                existing.reschedule(trigger=wanted[job_id])
            else:
                self.aps.add_job(self._func(job_id), wanted[job_id], id=job_id, name=LABELS[job_id],
                                 max_instances=1, coalesce=True, misfire_grace_time=GRACE.get(job_id, 600))

    def run_now(self, job_id: str) -> bool:
        job = self.aps.get_job(job_id)
        if job is None:
            return False
        job.modify(next_run_time=datetime.now(self.ctx.env.tz))
        return True

    def view(self) -> list[dict]:
        out = []
        for job_id, label in LABELS.items():
            job = self.aps.get_job(job_id)
            nxt = job.next_run_time if job else None
            out.append({"id": job_id, "label": label, "next_run": int(nxt.timestamp()) if nxt else None})
        return out

    def shutdown(self) -> None:
        if self.aps.running:
            self.aps.shutdown(wait=False)

    # ---------- 任务体：运行时从 DB 读设置，保证改完立即用新值 ----------
    def _settings(self) -> Settings:
        with connect(self.ctx.env.db_path) as conn:
            return load_settings(conn)

    async def _fetch_new(self) -> None:
        await self.ctx.syncer.run_all("fetch_new")

    async def _refresh_recent(self) -> None:
        await self.ctx.syncer.run_all("refresh_recent", days=self._settings().sync.refresh_days)

    async def _calibrate(self) -> None:
        await self.ctx.syncer.run_all("calibrate")

    async def _push(self) -> None:
        env = self.ctx.env
        await send_digest(self.ctx.tg, env.db_path, env.tz, datetime.now(env.tz))

    async def _backup(self) -> None:
        env = self.ctx.env
        try:
            path = await asyncio.to_thread(make_backup, env.db_path, env.data_dir / "backups", datetime.now(env.tz))
            log.info("已备份数据库到 %s", path)
        except Exception:
            log.exception("数据库备份失败")
