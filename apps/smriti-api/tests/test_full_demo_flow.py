from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from smriti.agents.readers import run_reader_dag
from smriti.agents.writers.dag import run_writer_dag
from smriti.schemas.clinical import SourceRecord
from smriti.schemas.encounter import EncounterContext
from tests.test_briefing_endpoint import (
    READ_SCOPE_ORDER,
    FakeConn,
    clinician_claims,
    grant_consent,
    patch_fake_pool,
    patch_reader_pipeline,
    patch_writer_pipeline,
)


def _source_record(provider_id: str, payload: dict) -> SourceRecord:
    return SourceRecord(
        provider_id=provider_id,
        record_type="bundle",
        payload=payload,
        format="fhir",
        received_at=datetime.now(UTC),
    )


def _sentient_bundle() -> dict:
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


def _apollo_bundle() -> dict:
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"resource": {"resourceType": "AllergyIntolerance", "id": "a2", "code": {"text": "No known allergy"}, "clinicalStatus": {"text": "no_known_allergy"}}},
            {"resource": {"resourceType": "Condition", "id": "c3", "code": {"text": "Type 2 diabetes mellitus"}, "clinicalStatus": {"text": "active"}}},
        ],
    }


@pytest.mark.asyncio
async def test_full_demo_flow_writer_then_reader_then_consent_toggle(monkeypatch):
    conn = FakeConn()
    grant_consent(conn, READ_SCOPE_ORDER)
    patch_fake_pool(monkeypatch, conn)
    patch_reader_pipeline(monkeypatch)
    patch_writer_pipeline(monkeypatch)

    await run_writer_dag(_source_record("sentient_hms", _sentient_bundle()), "ABHA-PRIYA")
    await run_writer_dag(_source_record("mock_apollo", _apollo_bundle()), "ABHA-PRIYA")

    briefing = await run_reader_dag(
        "ABHA-PRIYA",
        EncounterContext(chief_complaint="Routine T2DM follow-up", encounter_type="routine"),
        clinician_claims(),
    )

    assert briefing.top_facts
    assert all(fact.source is not None for fact in briefing.top_facts)
    assert any(conflict.get("conflict_type") == "allergy_disagreement" for conflict in briefing.conflicts)
    assert briefing.cohort_panel is not None and briefing.cohort_panel.buckets
    assert briefing.risk_flags == []

    conn.consents[0]["revoked_at"] = datetime.now(UTC)
    grant_consent(conn, ["conditions", "observations", "allergies"])

    redacted = await run_reader_dag(
        "ABHA-PRIYA",
        EncounterContext(chief_complaint="Routine T2DM follow-up", encounter_type="routine"),
        clinician_claims(),
    )

    assert "medications" in redacted.exclusions
    assert redacted.medication_timeline == []
    assert redacted.cohort_panel is not None and redacted.cohort_panel.buckets == []
    assert all(fact.source.table != "medications" for fact in redacted.top_facts)
