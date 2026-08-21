from collections.abc import AsyncIterator

import asyncpg

from .config import get_settings

_pool: asyncpg.Pool | None = None


def _asyncpg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def connect_database() -> None:
    global _pool
    _pool = await asyncpg.create_pool(_asyncpg_dsn(get_settings().database_url))


async def disconnect_database() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def connection() -> AsyncIterator[asyncpg.Connection]:
    if _pool is None:
        raise RuntimeError("Database is not connected")
    async with _pool.acquire() as conn:
        yield conn
