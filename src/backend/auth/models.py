"""Pydantic models for the auth module."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


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

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not _IDENT_RE.fullmatch(v):
            raise ValueError("username may only contain letters, digits, dot, underscore, and hyphen")
        return v


class UserOut(BaseModel):
    id: int
    username: str
    email: str = ""
    role: str
    created_at: str
    is_active: bool


class UserProfileUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=64)
    email: str | None = Field(default=None, max_length=254)
    current_password: str | None = None
    new_password: str | None = Field(default=None, min_length=8)

    @field_validator("username")
    @classmethod
    def validate_optional_username(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _IDENT_RE.fullmatch(v):
            raise ValueError("username may only contain letters, digits, dot, underscore, and hyphen")
        return v


class AdminUserUpdate(BaseModel):
    username: str = Field(min_length=3, max_length=64)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not _IDENT_RE.fullmatch(v):
            raise ValueError("username may only contain letters, digits, dot, underscore, and hyphen")
        return v


class ProjectCreate(BaseModel):
    project_key: str = Field(min_length=3, max_length=64)
    upstream_url: str = Field(default="", max_length=512)
    description: str = Field(default="", max_length=1000)

    @field_validator("project_key")
    @classmethod
    def validate_project_key(cls, v: str) -> str:
        if not _IDENT_RE.fullmatch(v):
            raise ValueError("project_key may only contain letters, digits, dot, underscore, and hyphen")
        return v

    @field_validator("upstream_url")
    @classmethod
    def validate_upstream_url(cls, v: str) -> str:
        if not v:
            return v
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("upstream_url must start with http:// or https://")
        return v


class ProjectUpdate(BaseModel):
    project_key: str | None = Field(default=None, min_length=3, max_length=64)
    upstream_url: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("project_key")
    @classmethod
    def validate_optional_project_key(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _IDENT_RE.fullmatch(v):
            raise ValueError("project_key may only contain letters, digits, dot, underscore, and hyphen")
        return v

    @field_validator("upstream_url")
    @classmethod
    def validate_optional_upstream_url(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("upstream_url must start with http:// or https://")
        return v


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
