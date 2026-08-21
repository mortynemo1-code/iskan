import asyncio
from uuid import UUID

from app.auth import CurrentUser, visible_employee_ids


USER_ID = UUID("00000000-0000-0000-0000-000000000001")
OWN_EMPLOYEE = UUID("00000000-0000-0000-0000-000000000010")
EXPLICIT_EMPLOYEE = UUID("00000000-0000-0000-0000-000000000011")
DEPARTMENT_EMPLOYEE = UUID("00000000-0000-0000-0000-000000000012")


class FakeConnection:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def fetch(self, query: str, *_: object) -> list[dict]:
        self.queries.append(query)
        if "user_employee_scope" in query and "WITH RECURSIVE" not in query:
            return [{"employee_id": EXPLICIT_EMPLOYEE}]
        if "WITH RECURSIVE" in query:
            return [{"id": DEPARTMENT_EMPLOYEE}]
        return []


def make_user(scope_type: str, employee_id: UUID | None = OWN_EMPLOYEE) -> CurrentUser:
    return CurrentUser(
        id=USER_ID,
        login="user",
        display_name="User",
        role="manager",
        employee_id=employee_id,
        scope_type=scope_type,
        permissions=frozenset({"timeline:view"}),
    )


def test_organization_scope_sees_everyone_without_scope_queries() -> None:
    conn = FakeConnection()
    assert asyncio.run(visible_employee_ids(conn, make_user("organization"))) is None
    assert conn.queries == []


def test_department_scope_includes_own_explicit_and_nested_department_employees() -> None:
    conn = FakeConnection()
    visible = asyncio.run(visible_employee_ids(conn, make_user("department")))
    assert visible == {OWN_EMPLOYEE, EXPLICIT_EMPLOYEE, DEPARTMENT_EMPLOYEE}
    assert any("WITH RECURSIVE" in query for query in conn.queries)


def test_employee_scope_does_not_expand_departments() -> None:
    conn = FakeConnection()
    visible = asyncio.run(visible_employee_ids(conn, make_user("employee")))
    assert visible == {OWN_EMPLOYEE, EXPLICIT_EMPLOYEE}
    assert not any("WITH RECURSIVE" in query for query in conn.queries)
