from __future__ import annotations

import asyncio
import logging
import secrets

from fastapi import APIRouter, HTTPException, UploadFile

from ..desktop import DesktopFormatError
from ..importer import run_import
from .deps import Admin, Ctx

router = APIRouter(prefix="/api", tags=["imports"], dependencies=[Admin])
log = logging.getLogger(__name__)
CHUNK = 1 << 20


@router.post("/imports", status_code=202)
async def upload(file: UploadFile, ctx: Ctx):
    """先把文件落盘再后台导入：大文件导入可能要几分钟，同步等待会被反向代理超时打断。"""
    tmp_dir = ctx.env.data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_dir / f"import-{secrets.token_hex(8)}.json"
    with open(path, "wb") as out:
        while chunk := await file.read(CHUNK):
            out.write(chunk)

    job = ctx.jobs.create("import")

    def work():
        try:
            result = run_import(ctx.env.db_path, path, ctx.env.tz, progress=lambda n: setattr(job, "processed", n))
            job.result, job.state = result.view(), "done"
        except DesktopFormatError as e:
            job.error, job.state = str(e), "failed"
        except Exception as e:  # 未预期错误也要让前端看到，而不是永远转圈
            log.exception("导入失败")
            job.error, job.state = f"导入失败：{e}", "failed"
        finally:
            path.unlink(missing_ok=True)

    ctx.background(asyncio.to_thread(work))
    return {"job_id": job.id}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, ctx: Ctx):
    job = ctx.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "没有这个作业")
    return job.view()
