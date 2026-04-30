"""Patient-facing API stubs (PRD 11.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from smriti.auth import PatientClaims, current_patient
from smriti.db.connection import get_pool

router = APIRouter(prefix="/api/v1", tags=["patient"])


def _not_implemented(phase: str) -> None:
    raise HTTPException(status_code=501, detail=f"Not implemented ({phase})")


@router.post("/auth/abha/otp")
async def auth_abha_otp(_: PatientClaims = Depends(current_patient)):
    _not_implemented("Phase 2")


@router.post("/auth/abha/verify")
async def auth_abha_verify(_: PatientClaims = Depends(current_patient)):
    _not_implemented("Phase 2")


@router.get("/me")
async def me(_: PatientClaims = Depends(current_patient)):
    _not_implemented("Phase 3")


@router.get("/me/timeline")
async def me_timeline(_: PatientClaims = Depends(current_patient)):
    _not_implemented("Phase 3")


@router.get("/me/conflicts")
async def me_conflicts(_: PatientClaims = Depends(current_patient)):
    _not_implemented("Phase 4")


@router.get("/me/audit")
async def me_audit(patient: PatientClaims = Depends(current_patient)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, abha_id, actor_id, actor_role, action, scope, consent_id, payload_hash, prev_hash, this_hash, created_at
            FROM audit_log
            WHERE abha_id = $1
            ORDER BY created_at DESC
            LIMIT 200
            """,
            patient.abha_id,
        )

    def _iso(v: Any) -> str | None:
        return v.isoformat() if isinstance(v, datetime) else None

    data = [
        {
            "id": int(row["id"]),
            "abha_id": row["abha_id"],
            "actor_id": row["actor_id"],
            "actor_role": row["actor_role"],
            "action": row["action"],
            "scope": list(row["scope"] or []),
            "consent_id": str(row["consent_id"]) if row["consent_id"] else None,
            "payload_hash": row["payload_hash"],
            "prev_hash": row["prev_hash"],
            "this_hash": row["this_hash"],
            "created_at": _iso(row["created_at"]),
        }
        for row in rows
    ]
    return {"count": len(data), "data": data}


@router.get("/me/consents")
async def me_consents(patient: PatientClaims = Depends(current_patient)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, abha_id, scope, grantee_class, granted_at, expires_at, revoked_at
            FROM consents
            WHERE abha_id = $1
            ORDER BY granted_at DESC
            LIMIT 200
            """,
            patient.abha_id,
        )

    def _iso(v: Any) -> str | None:
        return v.isoformat() if isinstance(v, datetime) else None

    data = [
        {
            "id": str(row["id"]),
            "abha_id": row["abha_id"],
            "scope": list(row["scope"] or []),
            "grantee_class": row["grantee_class"],
            "granted_at": _iso(row["granted_at"]),
            "expires_at": _iso(row["expires_at"]),
            "revoked_at": _iso(row["revoked_at"]),
            "active": row["revoked_at"] is None,
        }
        for row in rows
    ]
    return {"count": len(data), "data": data}


@router.post("/me/consents")
async def create_me_consent(_: PatientClaims = Depends(current_patient)):
    _not_implemented("Phase 5")


@router.delete("/me/consents/{id}")
async def revoke_me_consent(id: str, _: PatientClaims = Depends(current_patient)):
    _not_implemented("Phase 5")


@router.post("/me/upload")
async def upload_me_document(_: PatientClaims = Depends(current_patient)):
    _not_implemented("Phase 4")
