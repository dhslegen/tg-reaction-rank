"""内存中的后台作业登记表：导入等耗时操作立即返回 job_id，前端轮询进度。"""
from __future__ import annotations

import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

KEEP = 50


@dataclass
class Job:
    id: str
    kind: str
    state: str = "running"          # running | done | failed
    processed: int = 0
    error: str | None = None
    result: dict[str, Any] | None = None
    started_at: float = field(default_factory=time.time)

    def view(self) -> dict:
        return {"id": self.id, "kind": self.kind, "state": self.state, "processed": self.processed,
                "error": self.error, "result": self.result}


class JobRegistry:
    def __init__(self):
        self._jobs: OrderedDict[str, Job] = OrderedDict()

    def create(self, kind: str) -> Job:
        job = Job(secrets.token_hex(8), kind)
        self._jobs[job.id] = job
        while len(self._jobs) > KEEP:
            self._jobs.popitem(last=False)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)
