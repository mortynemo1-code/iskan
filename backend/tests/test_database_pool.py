import asyncio

import pytest

from app import analytics, database


class FakeAcquire:
    """Stands in for asyncpg's PoolAcquireContext."""

    def __init__(self, pool: "FakePool") -> None:
        self.pool = pool

    async def __aenter__(self) -> object:
        self.pool.checked_out += 1
        return object()

    async def __aexit__(self, *_: object) -> bool:
        self.pool.checked_out -= 1
        return False


class FakePool:
    def __init__(self) -> None:
        self.checked_out = 0

    def acquire(self, timeout: float | None = None) -> FakeAcquire:
        self.timeout = timeout
        return FakeAcquire(self)


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch) -> FakePool:
    fake = FakePool()
    monkeypatch.setattr(database, "_pool", fake)
    return fake


def test_connection_is_returned_after_a_successful_block(pool: FakePool) -> None:
    async def scenario() -> None:
        async with database.connection():
            assert pool.checked_out == 1

    asyncio.run(scenario())
    assert pool.checked_out == 0


def test_connection_is_returned_when_the_block_raises(pool: FakePool) -> None:
    async def scenario() -> None:
        with pytest.raises(RuntimeError):
            async with database.connection():
                raise RuntimeError("request failed")

    asyncio.run(scenario())
    assert pool.checked_out == 0


def test_acquire_waits_only_for_a_bounded_time(pool: FakePool) -> None:
    async def scenario() -> None:
        async with database.connection():
            pass

    asyncio.run(scenario())
    assert pool.timeout == database.POOL_ACQUIRE_TIMEOUT_SECONDS


def test_route_dependency_releases_when_the_request_fails(pool: FakePool) -> None:
    """A failing request must not strand its connection.

    FastAPI closes a yield-dependency by throwing into it. The dependency has to
    hand that exception to the context manager holding the connection -- an
    `async for` loop over `connection()` silently skips the release instead.
    """

    async def scenario() -> None:
        dependency = analytics.db()
        await dependency.asend(None)
        assert pool.checked_out == 1
        with pytest.raises(RuntimeError):
            await dependency.athrow(RuntimeError("unauthorised"))

    asyncio.run(scenario())
    assert pool.checked_out == 0
