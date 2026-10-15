"""进程内单例的集合，挂在 app.state.ctx 上供路由使用。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .auth import LoginLimiter
from .config import Env


@dataclass
class AppContext:
    env: Env
    limiter: LoginLimiter = field(default_factory=LoginLimiter)
    jobs: Any = None        # jobs.JobRegistry
    tg: Any = None          # tg.manager.TgManager
    scheduler: Any = None   # scheduler.Scheduler
