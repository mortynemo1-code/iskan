from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

from .config import get_settings

_pool: asyncpg.Pool | None = None

POOL_MIN_SIZE = 5
POOL_MAX_SIZE = 20
POOL_ACQUIRE_TIMEOUT_SECONDS = 10.0


def _asyncpg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def connect_database() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        _asyncpg_dsn(get_settings().database_url),
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
    )


async def disconnect_database() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def connection() -> AsyncIterator[asyncpg.Connection]:
    if _pool is None:
        raise RuntimeError("Database is not connected")
    # A bounded wait surfaces pool starvation as a failed request instead of hanging forever.
    async with _pool.acquire(timeout=POOL_ACQUIRE_TIMEOUT_SECONDS) as conn:
        yield conn
