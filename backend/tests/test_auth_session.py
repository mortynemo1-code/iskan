import asyncio
from datetime import timedelta
from uuid import UUID

from fastapi import Request, Response

from app.auth import CurrentUser, _create_session
from app.config import Settings


class FakeConnection:
    def __init__(self) -> None:
        self.arguments: tuple[object, ...] | None = None

    async def execute(self, _: str, *arguments: object) -> None:
        self.arguments = arguments


def test_refresh_session_uses_timedelta_for_postgres_interval() -> None:
    conn = FakeConnection()
    user = CurrentUser(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        login="admin",
        display_name="Admin",
        role="superadmin",
        employee_id=None,
        scope_type="organization",
        permissions=frozenset(),
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/totp/confirm",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )
    settings = Settings(jwt_secret="x" * 48, refresh_token_days=14)

    asyncio.run(_create_session(conn, user, request, Response(), settings))

    assert conn.arguments is not None
    assert conn.arguments[4] == timedelta(days=14)
