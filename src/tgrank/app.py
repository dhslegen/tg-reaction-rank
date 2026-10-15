"""FastAPI 应用装配。单进程单 worker：同一 Telegram session 绝不能多实例并发。"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .api import auth, boards, chats, imports, settings, tg
from .boards import ensure_builtin
from .config import Env
from .context import AppContext
from .db import connect, migrate
from .scheduler import Scheduler
from .settings import load_settings
from .tg.manager import TgManager, TgState
from .tg.sync import Syncer

log = logging.getLogger(__name__)


class FrontendFiles(StaticFiles):
    """前端无构建、文件名不带 hash：每次都用 ETag 向服务器确认，升级后立即拿到新版本。"""

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def init_db(env: Env) -> None:
    env.data_dir.mkdir(parents=True, exist_ok=True)
    # 上次进程在导入中途退出留下的上传文件已无作业认领
    for leftover in (env.data_dir / "tmp").glob("import-*.json"):
        leftover.unlink(missing_ok=True)
    with connect(env.db_path) as conn:
        migrate(conn)
        ensure_builtin(conn)


async def _start_telegram(ctx: AppContext) -> None:
    """连接 Telegram 并续传未完成的历史回填。放在后台：网络慢时不能卡住服务启动。"""
    await ctx.tg.start()
    if ctx.tg.state is not TgState.AUTHORIZED:
        return
    with connect(ctx.env.db_path) as conn:
        pending = [r[0] for r in conn.execute("SELECT chat_id FROM chats WHERE sync_enabled = 1 AND history_complete = 0")]
    for chat_id in pending:
        await ctx.syncer.fetch_new(chat_id)


def create_app(env: Env, *, client_factory: Callable | None = None,
               sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> FastAPI:
    ctx = AppContext(env=env)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(env)
        ctx.tg = TgManager(env, client_factory=client_factory, sleep=sleep)
        ctx.syncer = Syncer(ctx.tg, env.db_path)
        ctx.background(_start_telegram(ctx))
        ctx.scheduler = Scheduler(ctx)
        with connect(env.db_path) as conn:
            ctx.scheduler.start(load_settings(conn))
        yield
        ctx.scheduler.shutdown()
        for task in list(ctx._tasks):
            task.cancel()
        await ctx.tg.stop()

    app = FastAPI(title="tg-reaction-rank", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ctx = ctx

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        # 只反映进程存活；Telegram 未登录不算不健康，否则首次部署会被反复重启
        return PlainTextResponse("ok")

    for module in (auth, chats, boards, settings, imports, tg):
        app.include_router(module.router)

    if env.forwarded_allow_ips:
        # 在应用层而非 uvicorn 参数里处理代理头：行为可测试，且 serve 时关闭 uvicorn 自带的那一层避免重复
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=env.forwarded_allow_ips)

    static_dir = resources.files("tgrank").joinpath("static")
    app.mount("/", FrontendFiles(directory=str(static_dir), html=True), name="static")
    return app
