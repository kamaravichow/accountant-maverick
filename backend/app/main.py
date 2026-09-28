"""FastAPI entrypoint: REST + SSE API under /api and the built web UI at /."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import chat, llm, routes
from .config import get_settings

log = logging.getLogger("maverick")


def require_token(request: Request) -> None:
    token = get_settings().app_token
    if not token:
        return
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {token}" and request.query_params.get("token") != token:
        raise HTTPException(401, "Invalid or missing token")


PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "google_genai": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY", "mistralai": "MISTRAL_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
    "azure_openai": "AZURE_OPENAI_API_KEY", "together": "TOGETHER_API_KEY", "fireworks": "FIREWORKS_API_KEY",
}


def missing_provider_key(model_id: str) -> str | None:
    """Name of the env var the server model needs but lacks (LangChain only fails at call time)."""
    import os

    provider = model_id.split(":", 1)[0] if ":" in model_id else ""
    var = PROVIDER_KEYS.get(provider)
    return var if var and not os.environ.get(var) else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    app.state.agent = None
    saver_cm = None
    # The checkpointer is needed even without a server-side model: browsers may bring their own
    # OpenAI-compatible endpoint, and chat history must persist either way.
    if s.checkpointer == "sqlite":
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        s.checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
        saver_cm = AsyncSqliteSaver.from_conn_string(str(s.checkpoint_db))
        app.state.checkpointer = await saver_cm.__aenter__()
    else:
        from langgraph.checkpoint.memory import InMemorySaver

        app.state.checkpointer = InMemorySaver()
    try:
        from .agent.harness import build_agent

        missing = missing_provider_key(s.llm_model)
        if missing:
            raise RuntimeError(f"{missing} not set")
        app.state.agent = build_agent(checkpointer=app.state.checkpointer)
        log.info("Default agent ready with model %s", s.llm_model)
    except Exception as exc:  # e.g. no provider key: users can still bring their own endpoint
        log.warning("Server default model unavailable (%s); browser-supplied endpoints only", type(exc).__name__)
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
    app.include_router(llm.router, prefix="/api", dependencies=deps)

    @app.get("/api/health")
    def health(request: Request):
        return {"ok": True, "agent": request.app.state.agent is not None, "byo_llm": True, "storage": s.storage_backend,
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
