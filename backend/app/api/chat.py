"""Chat: stream agent runs over Server-Sent Events, and keep a per-company thread index."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..agent.context import AgentContext
from ..workspace import CONTEXT, get_workspace

router = APIRouter()
THREADS = f"{CONTEXT}/threads.json"


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None
    fy: str | None = None
    attachments: list[str] = []  # workspace paths the user pointed at


def _threads(company_id: str) -> list[dict]:
    cs = get_workspace().company_storage(company_id)
    try:
        return json.loads(cs.read_text(THREADS))
    except Exception:
        return []


def _save_thread(company_id: str, thread_id: str, title: str) -> None:
    cs = get_workspace().company_storage(company_id)
    threads = _threads(company_id)
    now = datetime.now(timezone.utc).isoformat()
    for t in threads:
        if t["id"] == thread_id:
            t["updated_at"] = now
            break
    else:
        threads.insert(0, {"id": thread_id, "title": title[:80], "created_at": now, "updated_at": now})
    cs.write_text(THREADS, json.dumps(threads[:200], indent=1))


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text", ""))
        elif isinstance(b, str):
            out.append(b)
    return "".join(out)


def _config(company_id: str, thread_id: str) -> dict:
    return {"configurable": {"thread_id": f"{company_id}:{thread_id}"}, "recursion_limit": 250}


async def run_stream(agent, company_id: str, req: ChatRequest) -> AsyncIterator[dict]:
    thread_id = req.thread_id or uuid.uuid4().hex[:12]
    _save_thread(company_id, thread_id, req.message)
    yield {"event": "thread", "data": json.dumps({"thread_id": thread_id})}
    text = req.message
    if req.attachments:
        text += "\n\n[Files referenced by the user: " + ", ".join(req.attachments) + "]"
    ctx = AgentContext(company_id=company_id, fy=req.fy)
    seen_tool_calls: set[str] = set()
    try:
        async for mode, chunk in agent.astream(
            {"messages": [HumanMessage(text)]},
            config=_config(company_id, thread_id),
            context=ctx,
            stream_mode=["messages", "updates"],
        ):
            if mode == "messages":
                msg, meta = chunk
                if isinstance(msg, AIMessageChunk) and meta.get("langgraph_node") == "model":
                    t = _text_of(msg.content)
                    if t:
                        yield {"event": "token", "data": json.dumps({"text": t})}
            elif mode == "updates":
                for node, update in (chunk or {}).items():
                    if not isinstance(update, dict):
                        continue
                    for m in update.get("messages", []) or []:
                        if isinstance(m, AIMessage):
                            for tc in m.tool_calls or []:
                                if tc["id"] in seen_tool_calls:
                                    continue
                                seen_tool_calls.add(tc["id"])
                                yield {"event": "tool_start", "data": json.dumps(
                                    {"id": tc["id"], "name": tc["name"], "args": tc["args"]}, default=str)}
                        elif isinstance(m, ToolMessage):
                            yield {"event": "tool_end", "data": json.dumps(
                                {"id": m.tool_call_id, "name": m.name, "status": getattr(m, "status", "success"),
                                 "output": _text_of(m.content)[:4000]}, default=str)}
                    if "todos" in update:
                        yield {"event": "todos", "data": json.dumps(update["todos"], default=str)}
        yield {"event": "done", "data": json.dumps({"thread_id": thread_id})}
    except Exception as exc:  # surface errors to the UI instead of dropping the stream
        yield {"event": "error", "data": json.dumps({"message": f"{type(exc).__name__}: {exc}"})}


@router.post("/companies/{company_id}/chat")
async def chat(company_id: str, req: ChatRequest, request: Request):
    try:
        get_workspace().get_company(company_id)
    except Exception:
        raise HTTPException(404, "Company not found")
    agent = request.app.state.agent
    if agent is None:
        raise HTTPException(503, "Agent is not configured - set LLM_MODEL and the provider API key.")
    return EventSourceResponse(run_stream(agent, company_id, req), ping=15)


@router.get("/companies/{company_id}/threads")
def list_threads(company_id: str):
    return _threads(company_id)


@router.get("/companies/{company_id}/threads/{thread_id}")
async def get_thread(company_id: str, thread_id: str, request: Request):
    agent = request.app.state.agent
    if agent is None:
        return {"messages": []}
    state = await agent.aget_state(_config(company_id, thread_id))
    out = []
    for m in (state.values or {}).get("messages", []):
        if isinstance(m, HumanMessage):
            out.append({"role": "user", "content": _text_of(m.content)})
        elif isinstance(m, AIMessage):
            out.append({"role": "assistant", "content": _text_of(m.content),
                        "tool_calls": [{"id": t["id"], "name": t["name"], "args": t["args"]} for t in m.tool_calls]})
        elif isinstance(m, ToolMessage):
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "name": m.name,
                        "content": _text_of(m.content)[:4000]})
    return {"thread_id": thread_id, "messages": out, "todos": (state.values or {}).get("todos", [])}
