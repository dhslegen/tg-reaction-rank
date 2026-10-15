"""进程内单例的集合，挂在 app.state.ctx 上供路由使用。"""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

from .auth import LoginLimiter
from .config import Env
from .jobs import JobRegistry


@dataclass
class AppContext:
    env: Env
    limiter: LoginLimiter = field(default_factory=LoginLimiter)
    jobs: JobRegistry = field(default_factory=JobRegistry)
    tg: Any = None          # tg.manager.TgManager
    syncer: Any = None      # tg.sync.Syncer
    scheduler: Any = None   # scheduler.Scheduler
    _tasks: set[asyncio.Task] = field(default_factory=set)

    def background(self, coro: Coroutine) -> asyncio.Task:
        """启动后台任务并持有引用，防止被垃圾回收中途取消。"""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
