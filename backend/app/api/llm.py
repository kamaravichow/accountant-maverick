"""Endpoints for browser-supplied OpenAI-compatible models (connection test, model listing)."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request
from langchain_core.messages import HumanMessage

from ..agent.llm import LLMOverride, get_model

router = APIRouter()


def override_from(request: Request, require_model: bool = True) -> LLMOverride:
    h = request.headers
    if not require_model and h.get("x-llm-base-url") and not h.get("x-llm-model"):
        return LLMOverride(base_url=h["x-llm-base-url"].strip().rstrip("/"), model="",
                           api_key=(h.get("x-llm-api-key") or "").strip())
    try:
        ov = LLMOverride.from_headers(h)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if ov is None:
        raise HTTPException(400, "Send X-LLM-Base-URL and X-LLM-Model headers")
    return ov


@router.get("/llm/models")
async def list_models(request: Request):
    """Proxy GET {base_url}/models so the settings dialog can offer a model picker."""
    ov = override_from(request, require_model=False)
    headers = {"Authorization": f"Bearer {ov.api_key}"} if ov.api_key else {}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"{ov.base_url}/models", headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not reach {ov.base_url}: {type(exc).__name__}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code if r.status_code in (401, 403, 404) else 502,
                            f"{ov.base_url}/models returned {r.status_code}")
    data = r.json()
    items = data.get("data", data if isinstance(data, list) else [])
    return sorted({m.get("id") for m in items if isinstance(m, dict) and m.get("id")})


@router.post("/llm/test")
async def test_model(request: Request):
    """One tiny completion + one tool call, to confirm the endpoint can drive the agent."""
    ov = override_from(request)
    model = get_model(override=ov)
    try:
        reply = await model.ainvoke([HumanMessage("Reply with the single word OK.")])
    except Exception as exc:
        raise HTTPException(502, f"Model call failed: {type(exc).__name__}: {str(exc)[:300]}")

    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    tools_ok = False
    try:
        msg = await model.bind_tools([add]).ainvoke([HumanMessage("Use the add tool to add 2 and 3.")])
        tools_ok = bool(getattr(msg, "tool_calls", None))
    except Exception:
        tools_ok = False
    text = reply.content if isinstance(reply.content, str) else str(reply.content)
    return {"ok": True, "model": ov.model, "reply": text[:200], "tool_calling": tools_ok,
            "warning": None if tools_ok else "This model did not return a tool call - the agent needs a model with "
                                              "function/tool calling support."}
