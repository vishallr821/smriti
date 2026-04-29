"""In-memory thread-safe store for MockABHA demo flows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4


@dataclass
class Patient:
    abha_id: str
    name: str
    dob: str
    sex: str
    mobile: str

    @property
    def abha_address(self) -> str:
        normalized = self.name.lower().replace(" ", ".")
        return f"{normalized}@abdm"


class MockAbhaStore:
    """Simple in-memory store protected by a single asyncio lock."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._patients_by_abha: dict[str, Patient] = {
            "12-3456-7890-1234": Patient(
                abha_id="12-3456-7890-1234",
                name="Priya Sharma",
                dob="1978-04-12",
                sex="F",
                mobile="9876543210",
            ),
            "98-7654-3210-9876": Patient(
                abha_id="98-7654-3210-9876",
                name="Rajesh Kumar",
                dob="1965-09-23",
                sex="M",
                mobile="9876543211",
            ),
            "55-5555-5555-5555": Patient(
                abha_id="55-5555-5555-5555",
                name="Demo Patient",
                dob="1990-01-01",
                sex="M",
                mobile="9999999999",
            ),
        }
        self._transactions: dict[str, dict[str, Any]] = {}
        self._consent_requests: dict[str, dict[str, Any]] = {}
        self._consents: dict[str, dict[str, Any]] = {}

    async def init_otp(self, mobile_or_aadhaar: str) -> str:
        async with self._lock:
            patient = self._resolve_patient(mobile_or_aadhaar)
            txn_id = str(uuid4())
            self._transactions[txn_id] = {
                "abha_id": patient.abha_id,
                "expires_at": datetime.now(UTC) + timedelta(seconds=600),
            }
            return txn_id

    async def consume_otp_transaction(self, txn_id: str) -> Patient | None:
        async with self._lock:
            txn = self._transactions.get(txn_id)
            if not txn:
                return None
            if datetime.now(UTC) > txn["expires_at"]:
                self._transactions.pop(txn_id, None)
                return None
            abha_id = txn["abha_id"]
            return self._patients_by_abha.get(abha_id)

    async def get_patient(self, abha_id: str) -> Patient | None:
        async with self._lock:
            return self._patients_by_abha.get(abha_id)

    async def create_consent_request(
        self,
        abha_id: str,
        requester_hpr_id: str,
        scope: list[str],
        purpose: str,
        expires_in: int,
    ) -> str:
        async with self._lock:
            consent_request_id = str(uuid4())
            self._consent_requests[consent_request_id] = {
                "consent_request_id": consent_request_id,
                "abha_id": abha_id,
                "requester_hpr_id": requester_hpr_id,
                "scope": scope,
                "purpose": purpose,
                "expires_in": expires_in,
                "status": "pending",
                "created_at": datetime.now(UTC).isoformat(),
            }
            return consent_request_id

    async def grant_consent(self, consent_request_id: str) -> dict[str, Any] | None:
        async with self._lock:
            request = self._consent_requests.get(consent_request_id)
            if not request:
                return None
            request["status"] = "granted"

            consent_id = str(uuid4())
            consent = {
                "consent_id": consent_id,
                "consent_request_id": consent_request_id,
                "abha_id": request["abha_id"],
                "requester_hpr_id": request["requester_hpr_id"],
                "scope": request["scope"],
                "purpose": request["purpose"],
                "expires_in": request["expires_in"],
                "granted_at": datetime.now(UTC).isoformat(),
            }
            self._consents[consent_id] = consent
            return consent

    async def get_consent(self, consent_id: str) -> dict[str, Any] | None:
        async with self._lock:
            return self._consents.get(consent_id)

    async def set_consent_token(self, consent_id: str, signed_token: str) -> None:
        async with self._lock:
            consent = self._consents.get(consent_id)
            if consent is not None:
                consent["signed_token"] = signed_token

    def _resolve_patient(self, mobile_or_aadhaar: str) -> Patient:
        for patient in self._patients_by_abha.values():
            if patient.mobile == mobile_or_aadhaar:
                return patient

        # Demo behavior: accept any 12-digit Aadhaar-like input and map to Priya.
        if mobile_or_aadhaar.isdigit() and len(mobile_or_aadhaar) == 12:
            return self._patients_by_abha["12-3456-7890-1234"]

        # Default fallback keeps the demo moving for unknown inputs.
        return self._patients_by_abha["55-5555-5555-5555"]
