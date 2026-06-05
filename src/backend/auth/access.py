"""Project access helpers shared by account-authenticated routes."""
from __future__ import annotations

from fastapi import HTTPException, status

from backend.auth.pgshim import Connection


async def project_access_control_enabled(db: Connection) -> bool:
    async with db.execute("SELECT 1 FROM user_groups WHERE is_active = 1 LIMIT 1") as cur:
        return await cur.fetchone() is not None


async def accessible_project_ids(db: Connection, user: dict) -> set[int] | None:
    if user.get("role") == "admin":
        return None
    if not await project_access_control_enabled(db):
        return None

    async with db.execute(
        """
        SELECT DISTINCT pga.project_id
        FROM user_group_members ugm
        JOIN user_groups ug ON ug.id = ugm.group_id AND ug.is_active = 1
        JOIN project_group_access pga ON pga.group_id = ug.id
        WHERE ugm.user_id = ?
        ORDER BY pga.project_id
        """,
        (int(user["id"]),),
    ) as cur:
        rows = await cur.fetchall()
    return {int(row["project_id"]) for row in rows}


async def user_can_access_project(db: Connection, user: dict, project_db_id: int) -> bool:
    allowed_project_ids = await accessible_project_ids(db, user)
    if allowed_project_ids is None:
        return True
    return int(project_db_id) in allowed_project_ids


async def require_project_access(db: Connection, user: dict, project_db_id: int) -> None:
    if await user_can_access_project(db, user, project_db_id):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project access denied")


def id_filter_sql(column_name: str, ids: set[int]) -> tuple[str, tuple[int, ...]]:
    if not ids:
        return "1 = 0", ()
    ordered_ids = tuple(sorted(ids))
    placeholders = ",".join("?" for _ in ordered_ids)
    return f"{column_name} IN ({placeholders})", ordered_ids