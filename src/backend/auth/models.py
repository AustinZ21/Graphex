"""Pydantic models for the auth module."""
from __future__ import annotations

from pydantic import BaseModel, Field


# ── Request / response models ──────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8)
    role: str = Field(default="viewer", pattern="^(admin|viewer)$")


class UserOut(BaseModel):
    id: int
    username: str
    email: str = ""
    role: str
    created_at: str
    is_active: bool


class UserProfileUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=64)
    email: str | None = None
    current_password: str | None = None
    new_password: str | None = Field(default=None, min_length=8)


class AdminUserUpdate(BaseModel):
    username: str = Field(min_length=3, max_length=64)


class ProjectCreate(BaseModel):
    project_key: str = Field(min_length=3, max_length=64)
    upstream_url: str = Field(default="")
    description: str = Field(default="")


class ProjectUpdate(BaseModel):
    project_key: str | None = Field(default=None, min_length=3, max_length=64)
    upstream_url: str | None = None
    description: str | None = None


class ProjectOut(BaseModel):
    id: int
    project_key: str
    project_id: str
    upstream_url: str
    description: str
    created_at: str
    is_active: bool


class ProjectTokenOut(BaseModel):
    id: int
    project_id: int
    token_type: str
    token_hint: str
    version: int
    created_at: str
    is_active: bool
    # Only populated on creation/rotation (never stored in plaintext):
    token: str | None = None


class GenerateTokenRequest(BaseModel):
    token_type: str = Field(pattern="^(mcp|edge_agent)$")
