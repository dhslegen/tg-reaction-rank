"""FastAPI 应用装配。单进程单 worker：同一 Telegram session 绝不能多实例并发。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from importlib import resources

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .api import auth, boards, chats, imports, settings
from .boards import ensure_builtin
from .config import Env
from .context import AppContext
from .db import connect, migrate


def init_db(env: Env) -> None:
    env.data_dir.mkdir(parents=True, exist_ok=True)
    # 上次进程在导入中途退出留下的上传文件已无作业认领
    for leftover in (env.data_dir / "tmp").glob("import-*.json"):
        leftover.unlink(missing_ok=True)
    with connect(env.db_path) as conn:
        migrate(conn)
        ensure_builtin(conn)


def create_app(env: Env) -> FastAPI:
    ctx = AppContext(env=env)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(env)
        yield

    app = FastAPI(title="tg-reaction-rank", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ctx = ctx

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        # 只反映进程存活；Telegram 未登录不算不健康，否则首次部署会被反复重启
        return PlainTextResponse("ok")

    for module in (auth, chats, boards, settings, imports):
        app.include_router(module.router)

    if env.forwarded_allow_ips:
        # 在应用层而非 uvicorn 参数里处理代理头：行为可测试，且 serve 时关闭 uvicorn 自带的那一层避免重复
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=env.forwarded_allow_ips)

    static_dir = resources.files("tgrank").joinpath("static")
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    return app
