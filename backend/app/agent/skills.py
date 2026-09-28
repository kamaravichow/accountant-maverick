"""Skills: task playbooks loaded on demand (progressive disclosure).

The system prompt lists only each skill's name + one-line description; the agent calls
``load_skill`` to pull the full instructions when a task matches. Built-in skills live in
``backend/skills/<name>/SKILL.md``; a firm can add its own per client in
``_context/skills/<name>.md`` (same front-matter format), which override built-ins by name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..config import get_settings
from ..storage import ScopedStorage

FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)


@dataclass
class Skill:
    name: str
    description: str
    body: str
    source: str


def parse_skill(text: str, source: str) -> Skill | None:
    m = FRONT.match(text)
    if not m:
        return None
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"')
    if "name" not in meta:
        return None
    return Skill(meta["name"], meta.get("description", ""), m.group(2).strip(), source)


@lru_cache
def builtin_skills() -> dict[str, Skill]:
    out = {}
    root: Path = get_settings().skills_dir
    for p in sorted(root.glob("*/SKILL.md")):
        sk = parse_skill(p.read_text(encoding="utf-8"), f"builtin:{p.parent.name}")
        if sk:
            out[sk.name] = sk
    return out


def company_skills(cs: ScopedStorage | None) -> dict[str, Skill]:
    out: dict[str, Skill] = {}
    if cs is None:
        return out
    try:
        entries = cs.list("_context/skills")
    except Exception:
        return out
    for e in entries:
        if not e.is_dir and e.name.endswith(".md"):
            sk = parse_skill(cs.read_text(e.path), f"company:{e.path}")
            if sk:
                out[sk.name] = sk
    return out


def all_skills(cs: ScopedStorage | None = None) -> dict[str, Skill]:
    return {**builtin_skills(), **company_skills(cs)}


def skills_index(cs: ScopedStorage | None = None) -> str:
    return "\n".join(f"- {s.name}: {s.description}" for s in all_skills(cs).values())
