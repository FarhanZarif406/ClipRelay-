"""Video storage: a local folder or any S3-compatible bucket (STORAGE_BACKEND=local|s3)."""

import os
import shutil
import tempfile
from contextlib import contextmanager
from collections.abc import Iterator
from functools import lru_cache

from app.config import get_settings


class LocalStorage:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def _path(self, key: str) -> str:
        path = os.path.abspath(os.path.join(self.root, key))
        if not path.startswith(self.root):
            raise ValueError("invalid storage key")
        return path

    def save(self, local_path: str, key: str) -> str:
        dest = self._path(key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest):
            os.remove(dest)
        shutil.move(local_path, dest)
        return key

    @contextmanager
    def local_copy(self, key: str) -> Iterator[str]:
        yield self._path(key)

    def delete(self, key: str) -> None:
        try:
            os.remove(self._path(key))
        except FileNotFoundError:
            pass

    def local_path(self, key: str) -> str | None:
        path = self._path(key)
        return path if os.path.exists(path) else None

    def url(self, key: str) -> str | None:
        return None


class S3Storage:
    def __init__(self):
        import boto3

        s = get_settings()
        self.bucket = s.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url or None,
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key_id or None,
            aws_secret_access_key=s.s3_secret_access_key or None,
        )

    def save(self, local_path: str, key: str) -> str:
        self.client.upload_file(local_path, self.bucket, key, ExtraArgs={"ContentType": "video/mp4"})
        os.remove(local_path)
        return key

    @contextmanager
    def local_copy(self, key: str) -> Iterator[str]:
        fd, path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        try:
            self.client.download_file(self.bucket, key, path)
            yield path
        finally:
            os.remove(path)

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def local_path(self, key: str) -> str | None:
        return None

    def url(self, key: str) -> str | None:
        """A short-lived link the browser can play the file from."""
        return self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=3600)

    def test(self) -> None:
        self.client.head_bucket(Bucket=self.bucket)


@lru_cache
def get_storage() -> LocalStorage | S3Storage:
    s = get_settings()
    return S3Storage() if s.storage_backend == "s3" else LocalStorage(s.storage_local_path)
