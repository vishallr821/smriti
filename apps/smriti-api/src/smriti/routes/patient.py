"""Patient-facing API stubs (PRD 11.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from smriti.auth import PatientClaims, current_patient

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
async def me_audit(_: PatientClaims = Depends(current_patient)):
    _not_implemented("Phase 5")


@router.get("/me/consents")
async def me_consents(_: PatientClaims = Depends(current_patient)):
    _not_implemented("Phase 5")


@router.post("/me/consents")
async def create_me_consent(_: PatientClaims = Depends(current_patient)):
    _not_implemented("Phase 5")


@router.delete("/me/consents/{id}")
async def revoke_me_consent(id: str, _: PatientClaims = Depends(current_patient)):
    _not_implemented("Phase 5")


@router.post("/me/upload")
async def upload_me_document(_: PatientClaims = Depends(current_patient)):
    _not_implemented("Phase 4")
