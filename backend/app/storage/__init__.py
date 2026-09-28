from functools import lru_cache

from ..config import get_settings
from .base import Entry, NotFound, ScopedStorage, Storage, StorageError, clean_path, join

__all__ = [
    "Entry",
    "NotFound",
    "ScopedStorage",
    "Storage",
    "StorageError",
    "clean_path",
    "join",
    "get_storage",
]


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "s3":
        from .s3 import S3Storage

        store = S3Storage(
            bucket=s.s3_bucket,
            prefix=s.s3_prefix,
            region=s.s3_region,
            endpoint_url=s.s3_endpoint_url,
            presign_expiry=s.s3_presign_expiry_seconds,
        )
        if s.s3_endpoint_url:  # MinIO/dev: create the bucket on first run
            store.ensure_bucket()
        return store
    from .local import LocalStorage

    return LocalStorage(s.local_storage_root)
