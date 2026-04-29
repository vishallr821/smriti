from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from smriti.auth import ClinicianClaims
from smriti.config import settings
from smriti.main import app
from smriti.schemas.briefing import Briefing
from smriti.schemas.encounter import EncounterContext, RetrievalPlan

READ_SCOPE_ORDER = ["conditions", "medications", "observations", "allergies"]


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FakeAcquire(self.conn)


class FakeEmbedder:
    def encode(self, texts, show_progress_bar=False):
        return [[0.01] * 384 for _ in texts]


class FakeConn:
    def __init__(self):
        self.now = datetime.now(UTC)
        self.providers = {"sentient_hms": True, "mock_apollo": True}
        self.patients = {
            "ABHA-PRIYA": {
                "abha_id": "ABHA-PRIYA",
                "display_name": "Priya Sharma",
                "dob": date(1979, 5, 17),
                "sex": "F",
            }
        }
        self.conditions: list[dict] = []
        self.medications: list[dict] = []
        self.observations: list[dict] = []
        self.allergies: list[dict] = []
        self.conflicts: list[dict] = []
        self.episodes: list[dict] = []
        self.consents: list[dict] = []
        self.audit_log: list[dict] = []
        self.record_chunks: list[dict] = []
        self.quarantine: list[dict] = []
        self.redaction_keys: list[dict] = []
        self.llm_guard_events: list[dict] = []
        self.cohort_patients = _cohort_rows()
        self.terminology = [
            {"system": "snomed", "code": "44054006", "display_name": "Type 2 diabetes mellitus", "score": 0.91},
            {"system": "icd10", "code": "E11", "display_name": "Type 2 diabetes mellitus", "score": 0.89},
            {"system": "snomed", "code": "38341003", "display_name": "Essential hypertension", "score": 0.90},
            {"system": "rxnorm", "code": "6809", "display_name": "Metformin", "score": 0.92},
            {"system": "loinc", "code": "4548-4", "display_name": "Hemoglobin A1c/Hemoglobin.total in Blood", "score": 0.93},
            {"system": "snomed", "code": "91936005", "display_name": "Allergy to penicillin", "score": 0.90},
        ]

    def transaction(self):
        return FakeTransaction()

    async def fetchrow(self, query, *args):
        if "FROM providers" in query:
            provider_id = args[0]
            return {"provider_id": provider_id} if self.providers.get(provider_id) else None
        if "ORDER BY id DESC LIMIT 1 FOR UPDATE" in query:
            return {"this_hash": self.audit_log[-1]["this_hash"]} if self.audit_log else None
        if "SELECT dob, sex" in query:
            return self.patients.get(args[0])
        if "FROM episodes" in query:
            abha_id, code, provider, start_date = args
            for row in reversed(self.episodes):
                if (
                    row["abha_id"] == abha_id
                    and row["primary_diagnosis_code"] == code
                    and provider in row["source_providers"]
                    and row["start_date"] >= start_date
                ):
                    return {"id": row["id"]}
            return None
        if "WHERE id = $1::uuid" in query:
            record_id = args[0]
            for table_name in ("conditions", "medications", "observations", "allergies"):
                if f"FROM {table_name}" not in query:
                    continue
                for row in getattr(self, table_name):
                    if row["id"] == record_id:
                        return row
            return None
        return None

    async def fetchval(self, query, *args):
        if "INSERT INTO conditions" in query:
            row_id = uuid4()
            self.conditions.append(
                {
                    "id": row_id,
                    "abha_id": args[0],
                    "source_provider": args[1],
                    "source_record_id": args[2],
                    "snomed_code": args[3],
                    "icd10_code": args[4],
                    "display_name": args[5],
                    "status": args[6] or "active",
                    "ingested_at": args[7],
                    "confidence": args[8],
                    "raw_value": args[9],
                }
            )
            return row_id
        if "INSERT INTO medications" in query:
            row_id = uuid4()
            self.medications.append(
                {
                    "id": row_id,
                    "abha_id": args[0],
                    "source_provider": args[1],
                    "source_record_id": args[2],
                    "rxnorm_code": args[3],
                    "display_name": args[4],
                    "dose": args[5],
                    "start_date": args[6],
                    "end_date": args[7],
                    "ingested_at": args[8],
                    "raw_value": args[9],
                }
            )
            return row_id
        if "INSERT INTO observations" in query:
            row_id = uuid4()
            raw_value = str(args[5])
            numeric_value = None
            if ":" in raw_value:
                rhs = raw_value.split(":", 1)[1].strip().split(" ", 1)[0]
                try:
                    numeric_value = float(rhs)
                except ValueError:
                    numeric_value = None
            self.observations.append(
                {
                    "id": row_id,
                    "abha_id": args[0],
                    "source_provider": args[1],
                    "source_record_id": args[2],
                    "loinc_code": args[3],
                    "display_name": args[4],
                    "value_numeric": numeric_value,
                    "value_text": raw_value,
                    "unit": "%",
                    "abnormal_flag": "H" if numeric_value and numeric_value >= 7.0 else None,
                    "observed_at": args[6],
                    "ingested_at": args[7],
                }
            )
            return row_id
        if "INSERT INTO allergies" in query:
            row_id = uuid4()
            self.allergies.append(
                {
                    "id": row_id,
                    "abha_id": args[0],
                    "source_provider": args[1],
                    "source_record_id": args[2],
                    "substance_code": args[3],
                    "substance_name": args[4],
                    "status": args[5] or "active",
                    "ingested_at": args[6],
                }
            )
            return row_id
        if "INSERT INTO episodes" in query:
            row_id = uuid4()
            self.episodes.append(
                {
                    "id": row_id,
                    "abha_id": args[0],
                    "primary_diagnosis_code": args[1],
                    "primary_diagnosis_name": args[2],
                    "start_date": args[3],
                    "source_providers": args[4],
                    "summary": args[5],
                }
            )
            return row_id
        return None

    async def fetch(self, query, *args):
        if "FROM consents" in query:
            abha_id, now, actor_id = args
            rows = []
            for consent in self.consents:
                if consent["abha_id"] != abha_id:
                    continue
                if consent.get("revoked_at") is not None:
                    continue
                expires_at = consent.get("expires_at")
                if expires_at is not None and expires_at <= now:
                    continue
                if consent["grantee_class"] not in {"any_md", actor_id}:
                    continue
                rows.append({"id": consent["id"], "scope": consent["scope"], "grantee_class": consent["grantee_class"]})
            return rows
        if "FROM terminology_index" in query and "ORDER BY embedding" in query:
            systems = set(args[1])
            return [row for row in self.terminology if row["system"] in systems][:5]
        if "FROM terminology_index" in query and "ORDER BY id" in query:
            return [{"display_name": row["display_name"]} for row in self.terminology]
        if "FROM cohort_patients" in query:
            return list(self.cohort_patients)
        if "SELECT display_name FROM conditions" in query:
            abha_id = args[0]
            return [{"display_name": row["display_name"]} for row in self.conditions if row["abha_id"] == abha_id][:5]
        if "FROM conditions" in query:
            abha_id = args[0]
            rows = [row for row in self.conditions if row["abha_id"] == abha_id]
            if "status = 'active'" in query:
                rows = [row for row in rows if row.get("status") == "active"]
            return rows
        if "FROM medications" in query:
            abha_id = args[0]
            rows = [row for row in self.medications if row["abha_id"] == abha_id]
            return rows
        if "FROM observations" in query:
            abha_id = args[0]
            rows = [row for row in self.observations if row["abha_id"] == abha_id]
            if "loinc_code = $2" in query:
                rows = [row for row in rows if row.get("loinc_code") == args[1]]
            return rows
        if "FROM conflicts" in query:
            abha_id = args[0]
            return [row for row in self.conflicts if row["abha_id"] == abha_id and row.get("resolution") is None]
        if "FROM allergies" in query:
            abha_id = args[0]
            rows = [row for row in self.allergies if row["abha_id"] == abha_id]
            if "status = 'active'" in query:
                rows = [row for row in rows if row.get("status") == "active"]
            return rows
        return []

    async def execute(self, query, *args):
        if "INSERT INTO record_chunks" in query:
            self.record_chunks.append({"abha_id": args[0], "source_table": args[1], "source_id": args[2], "chunk_text": args[3]})
            return
        if "INSERT INTO conflicts" in query:
            self.conflicts.append(
                {
                    "id": uuid4(),
                    "abha_id": args[0],
                    "conflict_type": args[1],
                    "severity": args[2],
                    "source_a": args[3],
                    "source_b": args[4],
                    "detected_at": args[5],
                    "resolution": None,
                }
            )
            return
        if "INSERT INTO quarantine" in query:
            self.quarantine.append({"source_provider": args[0], "reason": args[2]})
            return
        if "INSERT INTO redaction_keys" in query:
            self.redaction_keys.append({"abha_id": args[0], "placeholder": args[1]})
            return
        if "INSERT INTO llm_guard_events" in query:
            self.llm_guard_events.append({"agent": args[0], "event_type": args[1]})
            return
        if "INSERT INTO audit_log" in query:
            self.audit_log.append(
                {
                    "id": len(self.audit_log) + 1,
                    "abha_id": args[0],
                    "actor_id": args[1],
                    "actor_role": args[2],
                    "action": args[3],
                    "scope": args[4],
                    "consent_id": args[5],
                    "payload_hash": args[6],
                    "prev_hash": args[7],
                    "this_hash": args[8],
                    "created_at": datetime.fromisoformat(args[9]).astimezone(UTC),
                }
            )


def _cohort_rows():
    rows = []
    for _ in range(14):
        rows.append({"treatments": [{"rxnorm": "6809", "dose": "500mg BID"}], "outcomes": {"hba1c_3mo_change": -0.7}})
    for _ in range(13):
        rows.append(
            {
                "treatments": [{"rxnorm": "6809", "dose": "500mg BID"}, {"rxnorm": "1991302", "dose": "0.5mg weekly"}],
                "outcomes": {"hba1c_3mo_change": -1.4},
            }
        )
    return rows


def clinician_claims() -> ClinicianClaims:
    return ClinicianClaims(
        hpr_id="HPR-DR-001",
        name="Dr. Arjun Mehta",
        role="MD",
        provider_id="sentient_hms",
        exp=int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    )


def clinician_headers() -> dict[str, str]:
    claims = clinician_claims()
    token = jwt.encode(
        {
            "hpr_id": claims.hpr_id,
            "name": claims.name,
            "role": claims.role,
            "provider_id": claims.provider_id,
            "exp": claims.exp,
        },
        settings.clinician_jwt_key,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def grant_consent(conn: FakeConn, scope: list[str], *, revoked: bool = False) -> None:
    conn.consents.append(
        {
            "id": uuid4(),
            "abha_id": "ABHA-PRIYA",
            "scope": list(scope),
            "grantee_class": "HPR-DR-001",
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
            "revoked_at": datetime.now(UTC) if revoked else None,
        }
    )


def seed_priya_records(conn: FakeConn) -> None:
    now = conn.now
    conn.conditions = [
        {
            "id": uuid4(),
            "abha_id": "ABHA-PRIYA",
            "display_name": "Type 2 diabetes mellitus",
            "status": "active",
            "snomed_code": "44054006",
            "icd10_code": "E11",
            "source_provider": "sentient_hms",
            "source_record_id": "cond-1",
            "ingested_at": now,
            "confidence": 1.0,
            "raw_value": "Type 2 diabetes mellitus",
        },
        {
            "id": uuid4(),
            "abha_id": "ABHA-PRIYA",
            "display_name": "Essential hypertension",
            "status": "active",
            "snomed_code": "38341003",
            "icd10_code": None,
            "source_provider": "sentient_hms",
            "source_record_id": "cond-2",
            "ingested_at": now,
            "confidence": 1.0,
            "raw_value": "Essential hypertension",
        },
    ]
    conn.medications = [
        {
            "id": uuid4(),
            "abha_id": "ABHA-PRIYA",
            "display_name": "Metformin",
            "rxnorm_code": "6809",
            "dose": "500mg BID",
            "source_provider": "sentient_hms",
            "source_record_id": "med-1",
            "start_date": date.today() - timedelta(days=180),
            "end_date": None,
            "ingested_at": now,
            "raw_value": "Metformin",
        }
    ]
    conn.observations = [
        {
            "id": uuid4(),
            "abha_id": "ABHA-PRIYA",
            "display_name": "Hemoglobin A1c/Hemoglobin.total in Blood",
            "loinc_code": "4548-4",
            "value_numeric": 9.2,
            "value_text": "Hemoglobin A1c/Hemoglobin.total in Blood: 9.2 %",
            "unit": "%",
            "abnormal_flag": "H",
            "source_provider": "sentient_hms",
            "source_record_id": "obs-1",
            "observed_at": now,
            "ingested_at": now,
        }
    ]
    conn.allergies = [
        {
            "id": uuid4(),
            "abha_id": "ABHA-PRIYA",
            "substance_name": "Penicillin",
            "substance_code": "91936005",
            "status": "active",
            "source_provider": "sentient_hms",
            "source_record_id": "alg-1",
            "ingested_at": now,
        }
    ]
    conn.conflicts = [
        {
            "id": uuid4(),
            "abha_id": "ABHA-PRIYA",
            "conflict_type": "allergy_disagreement",
            "severity": "high",
            "source_a": {"source_provider": "sentient_hms", "substance_name": "Penicillin"},
            "source_b": {"source_provider": "mock_apollo", "substance_name": "No known allergy"},
            "detected_at": now,
            "resolution": None,
        }
    ]


def patch_fake_pool(monkeypatch: pytest.MonkeyPatch, conn: FakeConn) -> None:
    async def _pool_value():
        return FakePool(conn)

    targets = [
        "smriti.agents.consent_guard.get_pool",
        "smriti.agents.audit.get_pool",
        "smriti.agents.readers.dag.get_pool",
        "smriti.agents.readers.r2_context_retrieval.get_pool",
        "smriti.agents.readers.r3_cohort.get_pool",
        "smriti.routes.clinician.get_pool",
        "smriti.agents.writers.w1_ingestion.get_pool",
        "smriti.agents.writers.w2_pii_redaction.get_pool",
        "smriti.agents.writers.w3_normalization.get_pool",
        "smriti.agents.writers.w4_reconciliation.get_pool",
        "smriti.agents.writers.w5_episode_linker.get_pool",
        "smriti.agents.writers.dag.get_pool",
    ]
    for target in targets:
        monkeypatch.setattr(target, _pool_value)


def patch_reader_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_synthesis_run(
        self,
        encounter,
        retrieved_context,
        conflicts,
        cohort_panel,
        risk_flags,
        exclusions,
    ):
        return Briefing(
            summary=f"Briefing for {encounter.chief_complaint or encounter.encounter_type}",
            top_facts=retrieved_context.top_facts,
            conflicts=conflicts,
            medication_timeline=[] if "medications" in exclusions else retrieved_context.medications,
            cohort_panel=cohort_panel,
            risk_flags=risk_flags,
            exclusions=list(exclusions),
        )

    monkeypatch.setattr("smriti.agents.readers.r5_synthesis.SynthesisAgent.run", _fake_synthesis_run)
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.embed_profile", lambda _text: np.array([0.01] * 384))
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.laplace_noise", lambda sensitivity, epsilon: 0.0)


def patch_writer_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("smriti.agents.writers.w3_normalization.SentenceTransformer", lambda *_a, **_k: FakeEmbedder())
    monkeypatch.setattr("smriti.agents.writers.dag.SentenceTransformer", lambda *_a, **_k: FakeEmbedder())
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.embed_profile", lambda _text: np.array([0.01] * 384))
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.laplace_noise", lambda sensitivity, epsilon: 0.0)
    monkeypatch.setattr("smriti.agents.writers.dag._embedder", None)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_briefing_endpoint_full_consent_returns_briefing_json(monkeypatch, client):
    conn = FakeConn()
    seed_priya_records(conn)
    grant_consent(conn, READ_SCOPE_ORDER)
    patch_fake_pool(monkeypatch, conn)
    patch_reader_pipeline(monkeypatch)

    response = await client.post(
        "/api/v1/clinician/briefing",
        headers=clinician_headers(),
        json={
            "abha_id": "ABHA-PRIYA",
            "encounter": {"chief_complaint": "Routine T2DM follow-up", "encounter_type": "routine"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["briefing_id"]
    assert payload["top_facts"]
    assert payload["exclusions"] == []
    assert int(response.headers["X-Latency-Ms"]) >= 0


@pytest.mark.asyncio
async def test_briefing_endpoint_no_consent_returns_403(monkeypatch, client):
    conn = FakeConn()
    seed_priya_records(conn)
    patch_fake_pool(monkeypatch, conn)
    patch_reader_pipeline(monkeypatch)

    response = await client.post(
        "/api/v1/clinician/briefing",
        headers=clinician_headers(),
        json={
            "abha_id": "ABHA-PRIYA",
            "encounter": {"chief_complaint": "Routine T2DM follow-up", "encounter_type": "routine"},
        },
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_briefing_endpoint_partial_consent_excludes_medications(monkeypatch, client):
    conn = FakeConn()
    seed_priya_records(conn)
    grant_consent(conn, ["conditions", "observations", "allergies"])
    patch_fake_pool(monkeypatch, conn)
    patch_reader_pipeline(monkeypatch)

    response = await client.post(
        "/api/v1/clinician/briefing",
        headers=clinician_headers(),
        json={
            "abha_id": "ABHA-PRIYA",
            "encounter": {"chief_complaint": "Routine T2DM follow-up", "encounter_type": "routine"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["exclusions"] == ["medications"]
    assert payload["medication_timeline"] == []
    assert all(item["source"]["table"] != "medications" for item in payload["top_facts"])


@pytest.mark.asyncio
async def test_briefing_endpoint_reflects_mid_test_consent_toggle(monkeypatch, client):
    conn = FakeConn()
    seed_priya_records(conn)
    grant_consent(conn, READ_SCOPE_ORDER)
    patch_fake_pool(monkeypatch, conn)
    patch_reader_pipeline(monkeypatch)

    first = await client.post(
        "/api/v1/clinician/briefing",
        headers=clinician_headers(),
        json={
            "abha_id": "ABHA-PRIYA",
            "encounter": {"chief_complaint": "Routine T2DM follow-up", "encounter_type": "routine"},
        },
    )
    assert first.status_code == 200
    assert first.json()["exclusions"] == []

    conn.consents[0]["revoked_at"] = datetime.now(UTC)
    grant_consent(conn, ["conditions", "observations", "allergies"])

    second = await client.post(
        "/api/v1/clinician/briefing",
        headers=clinician_headers(),
        json={
            "abha_id": "ABHA-PRIYA",
            "encounter": {"chief_complaint": "Routine T2DM follow-up", "encounter_type": "routine"},
        },
    )

    assert second.status_code == 200
    payload = second.json()
    assert payload["exclusions"] == ["medications"]
    assert payload["medication_timeline"] == []


@pytest.mark.asyncio
async def test_query_endpoint_routes_r1_then_r2(monkeypatch, client):
    conn = FakeConn()
    seed_priya_records(conn)
    grant_consent(conn, READ_SCOPE_ORDER)
    patch_fake_pool(monkeypatch, conn)

    async def _fake_query_run(self, encounter: EncounterContext) -> RetrievalPlan:
        assert encounter.nl_query == "show medication history"
        return RetrievalPlan(intent="medication_history", parameters={})

    monkeypatch.setattr("smriti.agents.readers.r1_query_router.QueryRouterAgent.run", _fake_query_run)

    response = await client.post(
        "/api/v1/clinician/query",
        headers=clinician_headers(),
        json={"abha_id": "ABHA-PRIYA", "query": "show medication history"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["medications"]
    assert payload["conditions"] == []


@pytest.mark.asyncio
async def test_source_endpoint_requires_active_read_consent(monkeypatch, client):
    conn = FakeConn()
    seed_priya_records(conn)
    grant_consent(conn, ["conditions"])
    patch_fake_pool(monkeypatch, conn)

    condition_id = str(conn.conditions[0]["id"])
    allowed = await client.get(f"/api/v1/clinician/source/conditions/{condition_id}", headers=clinician_headers())
    assert allowed.status_code == 200
    assert allowed.json()["display_name"] == "Type 2 diabetes mellitus"

    medication_id = str(conn.medications[0]["id"])
    denied = await client.get(f"/api/v1/clinician/source/medications/{medication_id}", headers=clinician_headers())
    assert denied.status_code == 403


@pytest.mark.asyncio
@pytest.mark.slow
async def test_briefing_endpoint_priya_real_groq_completes_under_8_seconds(monkeypatch, client):
    if not os.getenv("GROQ_API_KEY"):
        pytest.skip("GROQ_API_KEY not configured for the slow real-Groq latency check")

    conn = FakeConn()
    seed_priya_records(conn)
    grant_consent(conn, READ_SCOPE_ORDER)
    patch_fake_pool(monkeypatch, conn)
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.embed_profile", lambda _text: np.array([0.01] * 384))
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.laplace_noise", lambda sensitivity, epsilon: 0.0)

    response = await client.post(
        "/api/v1/clinician/briefing",
        headers=clinician_headers(),
        json={
            "abha_id": "ABHA-PRIYA",
            "encounter": {"chief_complaint": "Routine T2DM follow-up", "encounter_type": "routine"},
        },
    )

    assert response.status_code == 200
    assert int(response.headers["X-Latency-Ms"]) < 8000
