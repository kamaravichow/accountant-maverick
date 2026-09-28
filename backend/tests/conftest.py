import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """Fresh local-storage workspace per test."""
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("CHECKPOINTER", "memory")
    from app import config, storage, workspace as ws

    config.get_settings.cache_clear()
    storage.get_storage.cache_clear()
    ws._workspace = None
    yield ws.get_workspace()
    config.get_settings.cache_clear()
    storage.get_storage.cache_clear()
    ws._workspace = None
