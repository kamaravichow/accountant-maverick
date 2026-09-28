"""FastAPI entrypoint: REST + SSE API under /api and the built web UI at /."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import chat, routes
from .config import get_settings

log = logging.getLogger("maverick")


def require_token(request: Request) -> None:
    token = get_settings().app_token
    if not token:
        return
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {token}" and request.query_params.get("token") != token:
        raise HTTPException(401, "Invalid or missing token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    app.state.agent = None
    saver_cm = None
    try:
        from .agent.harness import build_agent

        if s.checkpointer == "sqlite":
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            s.checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
            saver_cm = AsyncSqliteSaver.from_conn_string(str(s.checkpoint_db))
            saver = await saver_cm.__aenter__()
        else:
            from langgraph.checkpoint.memory import InMemorySaver

            saver = InMemorySaver()
        app.state.agent = build_agent(checkpointer=saver)
        log.info("Agent ready with model %s", s.llm_model)
    except Exception as exc:  # the file/formula APIs still work without an LLM
        log.warning("Agent disabled: %s", exc)
    yield
    if saver_cm is not None:
        await saver_cm.__aexit__(None, None, None)


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Accountant Maverick", version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    deps = [Depends(require_token)]
    app.include_router(routes.router, prefix="/api", dependencies=deps)
    app.include_router(chat.router, prefix="/api", dependencies=deps)

    @app.get("/api/health")
    def health(request: Request):
        return {"ok": True, "agent": request.app.state.agent is not None, "storage": s.storage_backend,
                "model": s.llm_model, "web_search": bool(s.tinyfish_api_key), "auth": bool(s.app_token)}

    if s.static_dir.exists():
        app.mount("/assets", StaticFiles(directory=s.static_dir / "assets"), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            root = s.static_dir.resolve()
            f = (root / full_path).resolve()
            if full_path and f.is_file() and root in f.parents:
                return FileResponse(f)
            return FileResponse(s.static_dir / "index.html")

    return app


app = create_app()
