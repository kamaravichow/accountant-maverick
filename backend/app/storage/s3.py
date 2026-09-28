"""Amazon S3 (or any S3-compatible store: MinIO, R2, Wasabi) backend."""

from __future__ import annotations

from typing import Iterator

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .base import KEEP, Entry, NotFound, Storage, clean_path, guess_type, join


class S3Storage(Storage):
    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        region: str | None = None,
        endpoint_url: str | None = None,
        presign_expiry: int = 3600,
        client=None,
    ):
        self.bucket = bucket
        self.prefix = clean_path(prefix)
        self.presign_expiry = presign_expiry
        self.s3 = client or boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
        )

    # key <-> relative path -------------------------------------------------
    def _key(self, path: str) -> str:
        return join(self.prefix, clean_path(path))

    def _rel(self, key: str) -> str:
        return key[len(self.prefix) :].lstrip("/") if self.prefix else key

    def ensure_bucket(self) -> None:
        try:
            self.s3.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.s3.create_bucket(Bucket=self.bucket)

    # listing ---------------------------------------------------------------
    def list(self, prefix: str = "", recursive: bool = False) -> list[Entry]:
        key_prefix = self._key(prefix)
        key_prefix = f"{key_prefix}/" if key_prefix else ""
        paginator = self.s3.get_paginator("list_objects_v2")
        kwargs = {"Bucket": self.bucket, "Prefix": key_prefix}
        if not recursive:
            kwargs["Delimiter"] = "/"
        files: list[Entry] = []
        dirs: dict[str, Entry] = {}
        for page in paginator.paginate(**kwargs):
            for cp in page.get("CommonPrefixes", []):
                rel = self._rel(cp["Prefix"].rstrip("/"))
                dirs[rel] = Entry(path=rel, name=rel.rsplit("/", 1)[-1], is_dir=True)
            for obj in page.get("Contents", []):
                rel = self._rel(obj["Key"])
                name = rel.rsplit("/", 1)[-1]
                parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
                if recursive:
                    # synthesise intermediate folders
                    base = self._rel(key_prefix.rstrip("/"))
                    p = parent
                    while p and p != base and p.startswith(base):
                        dirs.setdefault(p, Entry(path=p, name=p.rsplit("/", 1)[-1], is_dir=True))
                        p = p.rsplit("/", 1)[0] if "/" in p else ""
                if name == KEEP or not name:
                    continue
                files.append(
                    Entry(
                        path=rel,
                        name=name,
                        is_dir=False,
                        size=obj["Size"],
                        modified=obj["LastModified"],
                        content_type=guess_type(name),
                    )
                )
        out = list(dirs.values()) + files
        return sorted(out, key=lambda e: (not e.is_dir, e.path.lower()))

    # objects ---------------------------------------------------------------
    def read_bytes(self, path: str) -> bytes:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=self._key(path))["Body"].read()
        except ClientError as exc:
            raise NotFound(path) from exc

    def iter_bytes(self, path: str, chunk_size: int = 1024 * 256) -> Iterator[bytes]:
        try:
            body = self.s3.get_object(Bucket=self.bucket, Key=self._key(path))["Body"]
        except ClientError as exc:
            raise NotFound(path) from exc
        return body.iter_chunks(chunk_size)

    def write_bytes(self, path: str, data: bytes, content_type: str | None = None) -> Entry:
        key = self._key(path)
        self.s3.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type or guess_type(path)
        )
        return self.stat(path)

    def delete(self, path: str) -> int:
        key = self._key(path)
        if self._head(key):
            self.s3.delete_object(Bucket=self.bucket, Key=key)
            return 1
        keys = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=f"{key}/"):
            keys += [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if not keys:
            raise NotFound(path)
        for i in range(0, len(keys), 1000):
            self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": keys[i : i + 1000]})
        return len([k for k in keys if not k["Key"].endswith(f"/{KEEP}")])

    def _head(self, key: str) -> dict | None:
        try:
            return self.s3.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            return None

    def _is_prefix(self, key: str) -> bool:
        resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=f"{key}/", MaxKeys=1)
        return resp.get("KeyCount", 0) > 0

    def exists(self, path: str) -> bool:
        key = self._key(path)
        return bool(self._head(key)) or self._is_prefix(key)

    def stat(self, path: str) -> Entry:
        rel = clean_path(path)
        key = self._key(rel)
        head = self._head(key)
        name = rel.rsplit("/", 1)[-1]
        if head:
            return Entry(
                path=rel,
                name=name,
                is_dir=False,
                size=head["ContentLength"],
                modified=head["LastModified"],
                content_type=head.get("ContentType") or guess_type(name),
            )
        if self._is_prefix(key):
            return Entry(path=rel, name=name, is_dir=True)
        raise NotFound(path)

    def copy(self, src: str, dst: str) -> None:
        self.s3.copy_object(
            Bucket=self.bucket,
            Key=self._key(dst),
            CopySource={"Bucket": self.bucket, "Key": self._key(src)},
        )

    # presigned URLs for direct browser <-> S3 streaming ---------------------
    def presigned_get(self, path: str, filename: str | None = None) -> str | None:
        params = {"Bucket": self.bucket, "Key": self._key(path)}
        if filename:
            params["ResponseContentDisposition"] = f'inline; filename="{filename}"'
        return self.s3.generate_presigned_url("get_object", Params=params, ExpiresIn=self.presign_expiry)

    def presigned_put(self, path: str, content_type: str | None = None) -> str | None:
        params = {"Bucket": self.bucket, "Key": self._key(path)}
        if content_type:
            params["ContentType"] = content_type
        return self.s3.generate_presigned_url("put_object", Params=params, ExpiresIn=self.presign_expiry)
