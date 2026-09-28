"""Chat model factory.

Two sources of models:
  * the server default (``LLM_MODEL`` via LangChain's ``init_chat_model``), and
  * a per-request **OpenAI-compatible** endpoint supplied by the browser (base URL + API key + model),
    e.g. OpenAI, OpenRouter, Groq, Together, DeepSeek, Azure OpenAI v1, vLLM, LM Studio or Ollama.
    The browser keeps these in sessionStorage and sends them as headers; the server never stores or
    logs the key.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache

from langchain.chat_models import init_chat_model

from ..config import get_settings

HEADER_BASE_URL = "x-llm-base-url"
HEADER_API_KEY = "x-llm-api-key"
HEADER_MODEL = "x-llm-model"
HEADER_VISION_MODEL = "x-llm-vision-model"


@dataclass(frozen=True)
class LLMOverride:
    base_url: str
    model: str
    api_key: str = field(default="", repr=False)  # never printed in logs/tracebacks
    vision_model: str | None = None

    @property
    def fingerprint(self) -> str:
        key_hash = hashlib.sha256(self.api_key.encode()).hexdigest()[:16]
        return f"{self.base_url}|{self.model}|{self.vision_model}|{key_hash}"

    @classmethod
    def from_headers(cls, headers) -> "LLMOverride | None":
        base = (headers.get(HEADER_BASE_URL) or "").strip().rstrip("/")
        model = (headers.get(HEADER_MODEL) or "").strip()
        if not base and not model:
            return None
        if not base or not model:
            raise ValueError("Both a base URL and a model name are required for a custom OpenAI-compatible endpoint")
        if not base.startswith(("http://", "https://")):
            raise ValueError("Base URL must start with http:// or https://")
        return cls(base_url=base, model=model, api_key=(headers.get(HEADER_API_KEY) or "").strip(),
                   vision_model=(headers.get(HEADER_VISION_MODEL) or "").strip() or None)


# Small LRU so repeated requests from the same browser reuse HTTP clients.
_openai_cache: "OrderedDict[str, object]" = OrderedDict()
_OPENAI_CACHE_MAX = 32


def openai_compatible_model(ov: LLMOverride, vision: bool = False):
    from langchain_openai import ChatOpenAI

    s = get_settings()
    name = ov.vision_model if vision and ov.vision_model else ov.model
    key = f"{ov.fingerprint}|{name}"
    if key in _openai_cache:
        _openai_cache.move_to_end(key)
        return _openai_cache[key]
    model = ChatOpenAI(
        model=name,
        base_url=ov.base_url,
        # Local servers (Ollama, LM Studio) accept any key but the client requires a non-empty one.
        api_key=ov.api_key or "not-needed",
        temperature=s.llm_temperature,
        max_tokens=s.llm_max_tokens,
        timeout=180,
        max_retries=2,
    )
    _openai_cache[key] = model
    while len(_openai_cache) > _OPENAI_CACHE_MAX:
        _openai_cache.popitem(last=False)
    return model


@lru_cache
def _default_model(vision: bool = False):
    s = get_settings()
    name = s.llm_vision_model if vision and s.llm_vision_model else s.llm_model
    return init_chat_model(name, temperature=s.llm_temperature, max_tokens=s.llm_max_tokens)


def get_model(vision: bool = False, override: LLMOverride | None = None):
    """The model for this run: the browser-supplied endpoint if present, else the server default."""
    if override is not None:
        return openai_compatible_model(override, vision)
    return _default_model(vision)
