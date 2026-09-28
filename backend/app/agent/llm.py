"""Chat model factory (provider-agnostic via LangChain's init_chat_model)."""

from __future__ import annotations

from functools import lru_cache

from langchain.chat_models import init_chat_model

from ..config import get_settings


@lru_cache
def get_model(vision: bool = False):
    s = get_settings()
    name = (s.llm_vision_model if vision and s.llm_vision_model else s.llm_model)
    return init_chat_model(name, temperature=s.llm_temperature, max_tokens=s.llm_max_tokens)
