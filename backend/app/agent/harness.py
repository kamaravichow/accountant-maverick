"""The agent harness: LangChain `create_agent` + accounting tools + skills + company context + memory."""

from __future__ import annotations

import time
from datetime import date

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    SummarizationMiddleware,
    TodoListMiddleware,
    ToolErrorMiddleware,
    dynamic_prompt,
)
from langchain.agents.middleware import ModelRequest

from ..config import get_settings
from ..workspace import get_workspace
from .context import AgentContext, active_fy, company_storage
from .llm import get_model
from .prompts import SYSTEM_PROMPT
from .skills import skills_index
from .tools import ALL_TOOLS

_prompt_cache: dict[tuple, tuple[float, str]] = {}
PROMPT_TTL = 20.0


def build_system_prompt(ctx: AgentContext) -> str:
    key = (ctx.company_id, ctx.fy)
    hit = _prompt_cache.get(key)
    if hit and time.monotonic() - hit[0] < PROMPT_TTL:
        return hit[1]
    ws = get_workspace()
    try:
        prof = ws.get_company(ctx.company_id)
        company_name = prof.name
        company_context = ws.context_summary(ctx.company_id)
    except Exception:
        company_name, company_context = "(unknown company)", "Company profile not found."
    cs = company_storage(ctx)
    prompt = SYSTEM_PROMPT.format(
        today=date.today().strftime("%d %B %Y"),
        company_name=company_name,
        company_id=ctx.company_id,
        fy=active_fy(ctx),
        skills=skills_index(cs),
        company_context=company_context,
    )
    _prompt_cache[key] = (time.monotonic(), prompt)
    return prompt


@dynamic_prompt
def company_prompt(request: ModelRequest) -> str:
    return build_system_prompt(request.runtime.context)


def tool_error_to_model(exc: Exception) -> str:
    """Return tool failures to the model (so it can fix arguments or try another route) instead of
    aborting the run. File-not-found and validation problems are the common cases."""
    return f"Tool error ({type(exc).__name__}): {str(exc)[:600]}"


def build_agent(checkpointer=None, model=None):
    s = get_settings()
    model = model or get_model()
    middleware = [
        company_prompt,
        ToolErrorMiddleware(on_error=tool_error_to_model),
        TodoListMiddleware(),
        SummarizationMiddleware(model=model, trigger=("tokens", 120_000), keep=("messages", 24)),
        ModelCallLimitMiddleware(run_limit=s.agent_recursion_limit, exit_behavior="end"),
    ]
    return create_agent(
        model=model,
        tools=ALL_TOOLS,
        middleware=middleware,
        context_schema=AgentContext,
        checkpointer=checkpointer,
        name="maverick",
    )
