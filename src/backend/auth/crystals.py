"""CRYSTALS/CNSA 2.0 communication profile checks for agent-facing paths."""
from __future__ import annotations

from fastapi import HTTPException, Request, status

CRYSTALS_PROFILE_HEADER = "x-cga-communication-profile"
CRYSTALS_KEM_HEADER = "x-cga-key-establishment"
CRYSTALS_SIGNATURE_HEADER = "x-cga-signature"
CRYSTALS_TRANSPORT_HEADER = "x-cga-transport-scope"

CRYSTALS_PROFILE = "CRYSTALS-CNSA-2.0"
CRYSTALS_KEM = "ML-KEM-1024"
CRYSTALS_SIGNATURE = "ML-DSA-87"
CRYSTALS_TRANSPORT_SCOPES = frozenset({"local-ipc", "pqc-tls", "hybrid-pqc-tls"})


def crystal_suite_headers(transport_scope: str = "local-ipc") -> dict[str, str]:
    return {
        "X-CGA-Communication-Profile": CRYSTALS_PROFILE,
        "X-CGA-Key-Establishment": CRYSTALS_KEM,
        "X-CGA-Signature": CRYSTALS_SIGNATURE,
        "X-CGA-Transport-Scope": transport_scope,
    }


def validate_crystal_suite_headers(raw_headers: dict[bytes, bytes]) -> str | None:
    profile = raw_headers.get(CRYSTALS_PROFILE_HEADER.encode(), b"").decode()
    kem = raw_headers.get(CRYSTALS_KEM_HEADER.encode(), b"").decode()
    signature = raw_headers.get(CRYSTALS_SIGNATURE_HEADER.encode(), b"").decode()
    transport_scope = raw_headers.get(CRYSTALS_TRANSPORT_HEADER.encode(), b"").decode()

    if profile != CRYSTALS_PROFILE:
        return "Missing or invalid CRYSTALS communication profile"
    if kem != CRYSTALS_KEM:
        return "Missing or invalid CRYSTALS key establishment profile"
    if signature != CRYSTALS_SIGNATURE:
        return "Missing or invalid CRYSTALS signature profile"
    if transport_scope not in CRYSTALS_TRANSPORT_SCOPES:
        return "Missing or invalid CRYSTALS transport scope"
    return None


async def require_crystal_suite(request: Request) -> None:
    raw_headers = {name.lower(): value for name, value in request.scope.get("headers", [])}
    if error := validate_crystal_suite_headers(raw_headers):
        raise HTTPException(status_code=status.HTTP_426_UPGRADE_REQUIRED, detail=error)