"""JWT verification helpers and FastAPI auth dependencies."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Header, HTTPException, Request, status
from jose import JWTError, jwt
from pydantic import BaseModel

from .config import settings

# Provider API keys: env-stored map of key → (provider_id, display_name).
# Real implementation: providers_keys table with hashed keys.
_PROVIDER_KEY_MAP: dict[str, tuple[str, str]] = {}


def _build_provider_key_map() -> dict[str, tuple[str, str]]:
    mapping: dict[str, tuple[str, str]] = {}
    known = {
        "PROVIDER_KEY_SENTIENT_HMS": ("sentient_hms", "Sentient HMS Demo Hospital"),
        "PROVIDER_KEY_MOCK_APOLLO": ("mock_apollo", "Mock Apollo Hospital"),
    }
    for env_var, (provider_id, display_name) in known.items():
        key = os.getenv(env_var, "").strip()
        if key:
            mapping[key] = (provider_id, display_name)
    return mapping


def _get_provider_key_map() -> dict[str, tuple[str, str]]:
    global _PROVIDER_KEY_MAP
    if not _PROVIDER_KEY_MAP:
        _PROVIDER_KEY_MAP = _build_provider_key_map()
    return _PROVIDER_KEY_MAP


class ProviderClaims(BaseModel):
    provider_id: str
    display_name: str


def verify_provider_api_key(api_key: str) -> ProviderClaims:
    mapping = _get_provider_key_map()
    entry = mapping.get(api_key)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing provider API key",
        )
    provider_id, display_name = entry
    return ProviderClaims(provider_id=provider_id, display_name=display_name)


async def current_provider(
    request: Request,
    x_provider_api_key: Annotated[str | None, Header()] = None,
) -> ProviderClaims:
    if not x_provider_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Provider-API-Key header",
        )
    claims = verify_provider_api_key(x_provider_api_key)
    request.state.actor_id = claims.provider_id
    request.state.actor_role = "provider"
    return claims


class PatientClaims(BaseModel):
    abha_id: str
    abha_address: str
    exp: int


class ClinicianClaims(BaseModel):
    hpr_id: str
    name: str
    role: str
    provider_id: str
    exp: int


def verify_patient_jwt(token: str) -> PatientClaims:
    try:
        payload = jwt.decode(
            token,
            settings.mock_abha_signing_key,
            algorithms=["HS256"],
            options={"verify_aud": False},
            issuer="mock-abha",
        )
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    abha_id = payload.get("sub")
    abha_address = payload.get("abha_address")
    exp = payload.get("exp")
    if not abha_id or not abha_address or exp is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid patient claims")

    return PatientClaims(abha_id=str(abha_id), abha_address=str(abha_address), exp=int(exp))


def verify_clinician_jwt(token: str) -> ClinicianClaims:
    try:
        payload = jwt.decode(
            token,
            settings.clinician_jwt_key,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    hpr_id = payload.get("hpr_id")
    name = payload.get("name")
    role = payload.get("role")
    provider_id = payload.get("provider_id")
    exp = payload.get("exp")
    if not all([hpr_id, name, role, provider_id]) or exp is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid clinician claims")

    return ClinicianClaims(
        hpr_id=str(hpr_id),
        name=str(name),
        role=str(role),
        provider_id=str(provider_id),
        exp=int(exp),
    )


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header")
    return parts[1].strip()


async def current_patient(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> PatientClaims:
    token = _extract_bearer_token(authorization)
    claims = verify_patient_jwt(token)
    request.state.actor_id = claims.abha_id
    request.state.actor_role = "patient"
    request.state.abha_id = claims.abha_id
    return claims


async def current_clinician(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> ClinicianClaims:
    token = _extract_bearer_token(authorization)
    claims = verify_clinician_jwt(token)
    request.state.actor_id = claims.hpr_id
    request.state.actor_role = claims.role
    request.state.provider_id = claims.provider_id
    return claims
