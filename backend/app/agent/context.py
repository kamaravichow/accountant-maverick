"""Per-run context injected into every tool call (which company / FY the chat is about)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..storage import ScopedStorage
from ..workspace import current_fy, get_workspace

MAX_TOOL_OUTPUT = 24000


@dataclass
class AgentContext:
    company_id: str
    fy: str | None = None
    user_name: str | None = None


def company_storage(ctx: AgentContext) -> ScopedStorage:
    return get_workspace().company_storage(ctx.company_id)


def active_fy(ctx: AgentContext) -> str:
    if ctx.fy:
        return ctx.fy
    try:
        years = get_workspace().get_company(ctx.company_id).financial_years
        cur = current_fy()
        return cur if cur in years else (years[-1] if years else cur)
    except Exception:
        return current_fy()


def dump(obj: Any, limit: int = MAX_TOOL_OUTPUT) -> str:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str, indent=1)
    if len(text) > limit:
        text = text[:limit] + f"\n... [truncated {len(text) - limit} chars - write full results to a workpaper file " \
                              "and read slices instead]"
    return text
