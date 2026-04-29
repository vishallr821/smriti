"""Shared helpers for demo scripts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from smriti.auth import ClinicianClaims
from smriti.config import settings
from smriti.db.connection import get_pool
from smriti.schemas.clinical import SourceRecord

READ_SCOPE_ORDER = ["conditions", "medications", "observations", "allergies"]
PRIYA_ABHA = "ABHA-PRIYA"


def sentient_bundle() -> dict:
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"resource": {"resourceType": "Condition", "id": "c1", "code": {"text": "Type 2 diabetes mellitus"}, "clinicalStatus": {"text": "active"}}},
            {"resource": {"resourceType": "Condition", "id": "c2", "code": {"text": "Essential hypertension"}, "clinicalStatus": {"text": "active"}}},
            {"resource": {"resourceType": "MedicationStatement", "id": "m1", "medicationCodeableConcept": {"text": "Metformin"}}},
            {"resource": {"resourceType": "Observation", "id": "o1", "code": {"text": "Hemoglobin A1c/Hemoglobin.total in Blood"}, "valueQuantity": {"value": 9.2, "unit": "%"}}},
            {"resource": {"resourceType": "AllergyIntolerance", "id": "a1", "code": {"text": "Allergy to penicillin"}, "clinicalStatus": {"text": "active"}}},
        ],
    }


def apollo_bundle() -> dict:
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"resource": {"resourceType": "AllergyIntolerance", "id": "a2", "code": {"text": "Allergy to penicillin"}, "clinicalStatus": {"text": "no_known_allergy"}}},
            {"resource": {"resourceType": "Condition", "id": "c3", "code": {"text": "Type 2 diabetes mellitus"}, "clinicalStatus": {"text": "active"}}},
        ],
    }


def clinician_claims() -> ClinicianClaims:
    return ClinicianClaims(
        hpr_id="HPR-DR-001",
        name="Dr. Arjun Mehta",
        role="MD",
        provider_id="sentient_hms",
        exp=int((datetime.now(UTC) + timedelta(hours=8)).timestamp()),
    )


def source_record(provider_id: str, payload: dict) -> SourceRecord:
    return SourceRecord(
        provider_id=provider_id,
        record_type="bundle",
        payload=payload,
        format="fhir",
        received_at=datetime.now(UTC),
    )


async def ensure_priya_patient() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO patients (abha_id, display_name, dob, sex, registered_at)
            VALUES ($1, $2, $3, $4, now())
            ON CONFLICT (abha_id)
            DO UPDATE SET display_name = EXCLUDED.display_name, dob = EXCLUDED.dob, sex = EXCLUDED.sex
            """,
            PRIYA_ABHA,
            "Priya Sharma",
            date(1979, 5, 17),
            "F",
        )


async def set_priya_consent(*, include_medications: bool) -> None:
    scope = ["conditions", "observations", "allergies"]
    if include_medications:
        scope.insert(1, "medications")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE consents
                SET revoked_at = now()
                WHERE abha_id = $1
                  AND revoked_at IS NULL
                  AND grantee_class IN ('any_md', $2)
                """,
                PRIYA_ABHA,
                "HPR-DR-001",
            )
            await conn.execute(
                """
                INSERT INTO consents (id, abha_id, scope, grantee_class, granted_at, expires_at, revoked_at)
                VALUES ($1, $2, $3::consent_scope[], $4, now(), now() + interval '24 hours', NULL)
                """,
                uuid4(),
                PRIYA_ABHA,
                scope,
                "HPR-DR-001",
            )


async def audit_count() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM audit_log")
    return int(val or 0)
