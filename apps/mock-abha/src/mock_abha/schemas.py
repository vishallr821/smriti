"""Request and response schemas for MockABHA APIs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OtpInitRequest(BaseModel):
    mobile_or_aadhaar: str = Field(min_length=1)


class OtpInitResponse(BaseModel):
    txn_id: str
    expires_in: int = 600


class OtpVerifyRequest(BaseModel):
    txn_id: str
    otp: str


class OtpVerifyResponse(BaseModel):
    abha_id: str
    abha_address: str
    jwt: str


class ProfileRequest(BaseModel):
    jwt: str


class ProfileResponse(BaseModel):
    name: str
    dob: str
    sex: str
    mobile_masked: str


class ConsentRequestCreate(BaseModel):
    abha_id: str
    requester_hpr_id: str
    scope: list[str]
    purpose: str
    expires_in: int


class ConsentRequestCreateResponse(BaseModel):
    consent_request_id: str
    status: str = "pending"


class ConsentGrantRequest(BaseModel):
    consent_request_id: str


class ConsentGrantResponse(BaseModel):
    consent_id: str
    signed_token: str


class ConsentTokenResponse(BaseModel):
    consent_id: str
    token_claims: dict[str, object]
