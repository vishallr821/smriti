"""JWT signing utilities for MockABHA."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from .config import settings


def sign_abha_token(abha_id: str, abha_address: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": abha_id,
        "abha_address": abha_address,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "iss": "mock-abha",
    }
    return jwt.encode(payload, settings.mock_abha_signing_key, algorithm="HS256")


def sign_consent_token(claims: dict[str, Any]) -> str:
    now = datetime.now(UTC)
    payload = {
        **claims,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "iss": "mock-abha",
    }
    return jwt.encode(payload, settings.mock_abha_signing_key, algorithm="HS256")


def verify_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.mock_abha_signing_key,
        algorithms=["HS256"],
        issuer="mock-abha",
    )
