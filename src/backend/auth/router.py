"""Auth API router: login, users, projects, tokens."""
from __future__ import annotations

import secrets
import string

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from backend.auth.database import get_db
from backend.auth.dependencies import get_current_user, require_admin
from backend.auth.models import (
    AdminUserUpdate,
    GenerateTokenRequest,
    LoginRequest,
    ProjectCreate,
    ProjectOut,
    ProjectTokenOut,
    ProjectUpdate,
    TokenResponse,
    UserCreate,
    UserOut,
    UserProfileUpdate,
)
from backend.auth.security import (
    create_access_token,
    generate_token,
    hash_password,
    hash_token,
    token_hint,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Helper ─────────────────────────────────────────────────────────────────

def _random_project_id(length: int = 10) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ── Auth ───────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute(
        "SELECT password_hash, role, is_active FROM users WHERE username = ?",
        (body.username,),
    ) as cur:
        row = await cur.fetchone()

    if not row or not row["is_active"] or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token({"sub": body.username, "role": row["role"]})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(user: dict = Depends(get_current_user)):
    return UserOut(
        id=user["id"],
        username=user["username"],
        email=user.get("email", "") or "",
        role=user["role"],
        created_at="",
        is_active=bool(user["is_active"]),
    )


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: UserProfileUpdate,
    user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    if body.username is not None and body.username != user["username"]:
        raise HTTPException(status_code=400, detail="You cannot change your own username")

    if body.new_password:
        if not body.current_password:
            raise HTTPException(status_code=400, detail="current_password required to set a new password")
        if not verify_password(body.current_password, user["password_hash"]):
            raise HTTPException(status_code=400, detail="Current password is incorrect")

    username = body.username if body.username is not None else None
    email = body.email if body.email is not None else None
    password_hash = hash_password(body.new_password) if body.new_password else None

    if any(v is not None for v in (username, email, password_hash)):
        try:
            await db.execute(
                """
                UPDATE users
                SET username = COALESCE(?, username),
                    email = COALESCE(?, email),
                    password_hash = COALESCE(?, password_hash)
                WHERE id = ?
                """,
                (username, email, password_hash, user["id"]),
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            raise HTTPException(status_code=409, detail="Username already taken")

    async with db.execute(
        "SELECT id, username, email, role, created_at, is_active FROM users WHERE id = ?",
        (user["id"],),
    ) as cur:
        row = await cur.fetchone()
    return UserOut(
        id=row["id"],
        username=row["username"],
        email=row["email"] or "",
        role=row["role"],
        created_at=row["created_at"],
        is_active=bool(row["is_active"]),
    )


# ── Users (admin only) ─────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserOut])
async def list_users(
    _: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute(
        "SELECT id, username, role, created_at, is_active FROM users ORDER BY id"
    ) as cur:
        rows = await cur.fetchall()
    return [UserOut(**dict(r)) for r in rows]


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    _: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    hashed = hash_password(body.password)
    try:
        async with db.execute(
            "INSERT INTO users(username, password_hash, role) VALUES(?,?,?) RETURNING id, username, role, created_at, is_active",
            (body.username, hashed, body.role),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail="Username already exists")
    return UserOut(**dict(row))


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    current: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    if user_id == current["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    await db.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
    await db.commit()


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: AdminUserUpdate,
    current: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute(
        "SELECT id, username, email, role, created_at, is_active FROM users WHERE id = ?",
        (user_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    if row["id"] == current["id"] and body.username != row["username"]:
        raise HTTPException(status_code=400, detail="You cannot change your own username")

    if row["role"] != "viewer" and body.username != row["username"]:
        raise HTTPException(status_code=400, detail="Only viewer usernames can be changed")

    if body.username != row["username"]:
        try:
            await db.execute("UPDATE users SET username = ? WHERE id = ?", (body.username, user_id))
            await db.commit()
        except aiosqlite.IntegrityError:
            raise HTTPException(status_code=409, detail="Username already exists")

    async with db.execute(
        "SELECT id, username, email, role, created_at, is_active FROM users WHERE id = ?",
        (user_id,),
    ) as cur:
        updated = await cur.fetchone()
    return UserOut(**dict(updated))


# ── Projects ───────────────────────────────────────────────────────────────

@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(
    _: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute(
        "SELECT id, project_key, project_id, upstream_url, description, created_at, is_active FROM projects ORDER BY id"
    ) as cur:
        rows = await cur.fetchall()
    return [ProjectOut(**dict(r)) for r in rows]


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectCreate,
    _: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    pid = _random_project_id()
    try:
        async with db.execute(
            """INSERT INTO projects(project_key, project_id, upstream_url, description)
               VALUES(?,?,?,?)
               RETURNING id, project_key, project_id, upstream_url, description, created_at, is_active""",
            (body.project_key, pid, body.upstream_url, body.description),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail="project_key already exists")
    return ProjectOut(**dict(row))


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: int,
    _: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    await db.execute("UPDATE projects SET is_active = 0 WHERE id = ?", (project_id,))
    await db.commit()


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    _: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    if body.project_key is None and body.upstream_url is None and body.description is None:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        await db.execute(
            """
            UPDATE projects
            SET project_key = COALESCE(?, project_key),
                upstream_url = COALESCE(?, upstream_url),
                description = COALESCE(?, description)
            WHERE id = ?
            """,
            (body.project_key, body.upstream_url, body.description, project_id),
        )
        await db.commit()
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail="project_key already exists")
    async with db.execute(
        "SELECT id, project_key, project_id, upstream_url, description, created_at, is_active FROM projects WHERE id = ?",
        (project_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectOut(**dict(row))


# ── Tokens ─────────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/tokens", response_model=list[ProjectTokenOut])
async def list_tokens(
    project_id: int,
    _: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute(
        "SELECT id, project_id, token_type, token_hint, version, created_at, is_active FROM project_tokens WHERE project_id = ? ORDER BY id",
        (project_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [ProjectTokenOut(**dict(r)) for r in rows]


@router.post("/projects/{project_id}/tokens", response_model=ProjectTokenOut, status_code=201)
async def generate_project_token(
    project_id: int,
    body: GenerateTokenRequest,
    _: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    # Verify project exists
    async with db.execute("SELECT id FROM projects WHERE id = ? AND is_active = 1", (project_id,)) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Project not found")

    raw = generate_token()
    digest = hash_token(raw)
    hint = token_hint(raw)

    async with db.execute(
        """INSERT INTO project_tokens(project_id, token_type, token_hash, token_hint, version)
           VALUES(?,?,?,?,1)
           RETURNING id, project_id, token_type, token_hint, version, created_at, is_active""",
        (project_id, body.token_type, digest, hint),
    ) as cur:
        row = await cur.fetchone()
    await db.commit()

    out = ProjectTokenOut(**dict(row))
    out.token = raw  # one-time reveal
    return out


@router.post("/tokens/{token_id}/rotate", response_model=ProjectTokenOut)
async def rotate_token(
    token_id: int,
    _: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Revoke the old token and issue a new one with version+1."""
    async with db.execute(
        "SELECT id, project_id, token_type, version FROM project_tokens WHERE id = ? AND is_active = 1",
        (token_id,),
    ) as cur:
        old = await cur.fetchone()
    if not old:
        raise HTTPException(status_code=404, detail="Token not found or already revoked")

    new_version = old["version"] + 1
    raw = generate_token()
    digest = hash_token(raw)
    hint = token_hint(raw)

    # Revoke old, insert new in one transaction
    await db.execute("UPDATE project_tokens SET is_active = 0 WHERE id = ?", (token_id,))
    async with db.execute(
        """INSERT INTO project_tokens(project_id, token_type, token_hash, token_hint, version)
           VALUES(?,?,?,?,?)
           RETURNING id, project_id, token_type, token_hint, version, created_at, is_active""",
        (old["project_id"], old["token_type"], digest, hint, new_version),
    ) as cur:
        row = await cur.fetchone()
    await db.commit()

    out = ProjectTokenOut(**dict(row))
    out.token = raw  # one-time reveal
    return out


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(
    token_id: int,
    _: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    await db.execute("UPDATE project_tokens SET is_active = 0 WHERE id = ?", (token_id,))
    await db.commit()
