"""Filesystem storage backend (development / single-node deployments)."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .base import KEEP, Entry, NotFound, Storage, clean_path, guess_type


class LocalStorage(Storage):
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, path: str) -> Path:
        p = (self.root / clean_path(path)).resolve()
        if p != self.root and self.root not in p.parents:
            raise NotFound(path)
        return p

    def _entry(self, p: Path) -> Entry:
        st = p.stat()
        rel = p.relative_to(self.root).as_posix()
        return Entry(
            path=rel,
            name=p.name,
            is_dir=p.is_dir(),
            size=0 if p.is_dir() else st.st_size,
            modified=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
            content_type=None if p.is_dir() else guess_type(p.name),
        )

    def list(self, prefix: str = "", recursive: bool = False) -> list[Entry]:
        base = self._p(prefix)
        if not base.exists():
            return []
        if base.is_file():
            return [self._entry(base)]
        it = base.rglob("*") if recursive else base.iterdir()
        out = [self._entry(p) for p in it if p.name != KEEP]
        return sorted(out, key=lambda e: (not e.is_dir, e.path.lower()))

    def read_bytes(self, path: str) -> bytes:
        p = self._p(path)
        if not p.is_file():
            raise NotFound(path)
        return p.read_bytes()

    def iter_bytes(self, path: str, chunk_size: int = 1024 * 256) -> Iterator[bytes]:
        p = self._p(path)
        if not p.is_file():
            raise NotFound(path)

        def gen() -> Iterator[bytes]:
            with p.open("rb") as fh:
                while chunk := fh.read(chunk_size):
                    yield chunk

        return gen()

    def write_bytes(self, path: str, data: bytes, content_type: str | None = None) -> Entry:
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return self._entry(p)

    def mkdir(self, path: str) -> None:
        self._p(path).mkdir(parents=True, exist_ok=True)

    def delete(self, path: str) -> int:
        p = self._p(path)
        if not p.exists():
            raise NotFound(path)
        if p.is_dir():
            n = sum(1 for x in p.rglob("*") if x.is_file())
            shutil.rmtree(p)
            return n
        p.unlink()
        return 1

    def exists(self, path: str) -> bool:
        return self._p(path).exists()

    def stat(self, path: str) -> Entry:
        p = self._p(path)
        if not p.exists():
            raise NotFound(path)
        return self._entry(p)
