"""Storage abstraction used by the API and the agent.

All paths are POSIX-style and relative to a *company root* (``companies/<id>/``).
Folders are virtual on S3 and are materialised with a ``.keep`` marker object so
that empty folders survive and can be listed.
"""

from __future__ import annotations

import mimetypes
import posixpath
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator

KEEP = ".keep"


class StorageError(Exception):
    pass


class NotFound(StorageError):
    pass


@dataclass
class Entry:
    path: str  # full relative path (no leading slash); folders end without slash
    name: str
    is_dir: bool
    size: int = 0
    modified: datetime | None = None
    content_type: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "name": self.name,
            "is_dir": self.is_dir,
            "size": self.size,
            "modified": self.modified.isoformat() if self.modified else None,
            "content_type": self.content_type,
        }


def clean_path(path: str) -> str:
    """Normalise a user/agent supplied path and refuse traversal."""
    path = (path or "").replace("\\", "/").strip()
    parts = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise StorageError("Path traversal ('..') is not allowed")
        parts.append(part)
    return "/".join(parts)


def join(*parts: str) -> str:
    return clean_path(posixpath.join(*[p for p in parts if p]))


def guess_type(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


class Storage(ABC):
    """Byte-level object storage keyed by relative path."""

    @abstractmethod
    def list(self, prefix: str = "", recursive: bool = False) -> list[Entry]: ...

    @abstractmethod
    def read_bytes(self, path: str) -> bytes: ...

    @abstractmethod
    def iter_bytes(self, path: str, chunk_size: int = 1024 * 256) -> Iterator[bytes]: ...

    @abstractmethod
    def write_bytes(self, path: str, data: bytes, content_type: str | None = None) -> Entry: ...

    @abstractmethod
    def delete(self, path: str) -> int:
        """Delete a file, or a folder recursively. Returns number of objects removed."""

    @abstractmethod
    def exists(self, path: str) -> bool: ...

    @abstractmethod
    def stat(self, path: str) -> Entry: ...

    def mkdir(self, path: str) -> None:
        path = clean_path(path)
        if path:
            self.write_bytes(join(path, KEEP), b"", "text/plain")

    def copy(self, src: str, dst: str) -> None:
        self.write_bytes(dst, self.read_bytes(src), guess_type(dst))

    def move(self, src: str, dst: str) -> int:
        src, dst = clean_path(src), clean_path(dst)
        if not src or not dst:
            raise StorageError("Source and destination are required")
        if self.is_file(src):
            self.copy(src, dst)
            self.delete(src)
            return 1
        moved = 0
        for e in self.list(src, recursive=True):
            if e.is_dir:
                continue
            rel = e.path[len(src) :].lstrip("/")
            self.copy(e.path, join(dst, rel))
            moved += 1
        self.delete(src)
        return moved

    def is_file(self, path: str) -> bool:
        try:
            return not self.stat(path).is_dir
        except NotFound:
            return False

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        return self.read_bytes(path).decode(encoding, errors="replace")

    def write_text(self, path: str, text: str, content_type: str | None = None) -> Entry:
        return self.write_bytes(path, text.encode("utf-8"), content_type or guess_type(path))

    # Presigned URLs let the browser stream large files straight to/from S3.
    def presigned_get(self, path: str, filename: str | None = None) -> str | None:
        return None

    def presigned_put(self, path: str, content_type: str | None = None) -> str | None:
        return None


class ScopedStorage(Storage):
    """A view of another Storage rooted at a prefix (one per company)."""

    def __init__(self, inner: Storage, root: str):
        self.inner = inner
        self.root = clean_path(root)

    def _abs(self, path: str) -> str:
        return join(self.root, clean_path(path))

    def _rel(self, entry: Entry) -> Entry:
        rel = entry.path[len(self.root) :].lstrip("/")
        entry.path = rel
        return entry

    def list(self, prefix: str = "", recursive: bool = False) -> list[Entry]:
        return [self._rel(e) for e in self.inner.list(self._abs(prefix), recursive)]

    def read_bytes(self, path: str) -> bytes:
        return self.inner.read_bytes(self._abs(path))

    def iter_bytes(self, path: str, chunk_size: int = 1024 * 256) -> Iterator[bytes]:
        return self.inner.iter_bytes(self._abs(path), chunk_size)

    def write_bytes(self, path: str, data: bytes, content_type: str | None = None) -> Entry:
        return self._rel(self.inner.write_bytes(self._abs(path), data, content_type))

    def delete(self, path: str) -> int:
        if not clean_path(path):
            raise StorageError("Refusing to delete the company root")
        return self.inner.delete(self._abs(path))

    def exists(self, path: str) -> bool:
        return self.inner.exists(self._abs(path))

    def stat(self, path: str) -> Entry:
        return self._rel(self.inner.stat(self._abs(path)))

    def presigned_get(self, path: str, filename: str | None = None) -> str | None:
        return self.inner.presigned_get(self._abs(path), filename)

    def presigned_put(self, path: str, content_type: str | None = None) -> str | None:
        return self.inner.presigned_put(self._abs(path), content_type)
