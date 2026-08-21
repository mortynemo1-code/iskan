import asyncio
import io

from minio import Minio

from .config import Settings, get_settings


class ObjectStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = Minio(
            self.settings.minio_endpoint,
            access_key=self.settings.minio_access_key,
            secret_key=self.settings.minio_secret_key,
            secure=self.settings.minio_secure,
        )

    async def ensure_bucket(self) -> None:
        exists = await asyncio.to_thread(self.client.bucket_exists, self.settings.minio_bucket)
        if not exists:
            await asyncio.to_thread(self.client.make_bucket, self.settings.minio_bucket)

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        await self.ensure_bucket()
        await asyncio.to_thread(
            self.client.put_object,
            self.settings.minio_bucket,
            key,
            io.BytesIO(data),
            len(data),
            content_type,
        )

    async def put_file(self, key: str, path: str, content_type: str = "application/octet-stream") -> None:
        await self.ensure_bucket()
        await asyncio.to_thread(
            self.client.fput_object,
            self.settings.minio_bucket,
            key,
            path,
            content_type,
        )

    async def get_bytes(self, key: str) -> bytes:
        response = await asyncio.to_thread(self.client.get_object, self.settings.minio_bucket, key)
        try:
            return await asyncio.to_thread(response.read)
        finally:
            response.close()
            response.release_conn()

    async def remove(self, key: str) -> None:
        await asyncio.to_thread(self.client.remove_object, self.settings.minio_bucket, key)
