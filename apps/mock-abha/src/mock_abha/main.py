"""Mock ABHA service endpoints for demo ABDM-compatible flows."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

from .config import settings
from .jwt_signer import sign_abha_token, sign_consent_token, verify_token
from .schemas import (
    ConsentGrantRequest,
    ConsentGrantResponse,
    ConsentRequestCreate,
    ConsentRequestCreateResponse,
    ConsentTokenResponse,
    OtpInitRequest,
    OtpInitResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
    ProfileRequest,
    ProfileResponse,
)
from .store import MockAbhaStore

logger = logging.getLogger("mock_abha")

app = FastAPI(
    title="Mock ABHA Service",
    description="Mock Ayushman Bharat Health Account service",
    version="0.1.0",
)
store = MockAbhaStore()


def _mask_mobile(mobile: str) -> str:
    return f"XXXXXX{mobile[-4:]}"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/abha/otp/init", response_model=OtpInitResponse)
async def abha_otp_init(payload: OtpInitRequest) -> OtpInitResponse:
    txn_id = await store.init_otp(payload.mobile_or_aadhaar)
    return OtpInitResponse(txn_id=txn_id, expires_in=600)


@app.post("/abha/otp/verify", response_model=OtpVerifyResponse)
async def abha_otp_verify(payload: OtpVerifyRequest) -> OtpVerifyResponse:
    logger.warning("MOCK OTP MODE — accepts only 123456")
    if payload.otp != "123456":
        raise HTTPException(status_code=401, detail="Invalid OTP")

    patient = await store.consume_otp_transaction(payload.txn_id)
    if patient is None:
        raise HTTPException(status_code=401, detail="Invalid or expired transaction")

    token = sign_abha_token(patient.abha_id, patient.abha_address)
    return OtpVerifyResponse(
        abha_id=patient.abha_id,
        abha_address=patient.abha_address,
        jwt=token,
    )


@app.post("/abha/profile", response_model=ProfileResponse)
async def abha_profile(payload: ProfileRequest) -> ProfileResponse:
    claims = verify_token(payload.jwt)
    abha_id = str(claims.get("sub", ""))
    patient = await store.get_patient(abha_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    return ProfileResponse(
        name=patient.name,
        dob=patient.dob,
        sex=patient.sex,
        mobile_masked=_mask_mobile(patient.mobile),
    )


@app.post("/hie/consent/request", response_model=ConsentRequestCreateResponse)
async def hie_consent_request(
    payload: ConsentRequestCreate,
) -> ConsentRequestCreateResponse:
    patient = await store.get_patient(payload.abha_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    consent_request_id = await store.create_consent_request(
        abha_id=payload.abha_id,
        requester_hpr_id=payload.requester_hpr_id,
        scope=payload.scope,
        purpose=payload.purpose,
        expires_in=payload.expires_in,
    )
    return ConsentRequestCreateResponse(consent_request_id=consent_request_id, status="pending")


@app.post("/hie/consent/grant", response_model=ConsentGrantResponse)
async def hie_consent_grant(payload: ConsentGrantRequest) -> ConsentGrantResponse:
    consent = await store.grant_consent(payload.consent_request_id)
    if consent is None:
        raise HTTPException(status_code=404, detail="Consent request not found")

    signed_token = sign_consent_token(
        {
            "sub": consent["abha_id"],
            "consent_id": consent["consent_id"],
            "consent_request_id": consent["consent_request_id"],
            "requester_hpr_id": consent["requester_hpr_id"],
            "scope": consent["scope"],
            "purpose": consent["purpose"],
        }
    )
    await store.set_consent_token(consent["consent_id"], signed_token)
    return ConsentGrantResponse(consent_id=consent["consent_id"], signed_token=signed_token)


@app.get("/hie/consent/{consent_id}", response_model=ConsentTokenResponse)
async def hie_consent_fetch(consent_id: str) -> ConsentTokenResponse:
    consent = await store.get_consent(consent_id)
    if consent is None:
        raise HTTPException(status_code=404, detail="Consent not found")

    token_claims = {
        "sub": consent["abha_id"],
        "consent_id": consent["consent_id"],
        "consent_request_id": consent["consent_request_id"],
        "requester_hpr_id": consent["requester_hpr_id"],
        "scope": consent["scope"],
        "purpose": consent["purpose"],
        "signed_token": consent.get("signed_token", ""),
    }
    return ConsentTokenResponse(consent_id=consent_id, token_claims=token_claims)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.port)
