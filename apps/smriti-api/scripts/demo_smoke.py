"""Full end-to-end demo smoke simulation."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from jose import jwt

from smriti.agents.writers.dag import run_writer_dag
from smriti.agents.writers.w3_normalization import NormalizationAgent
from smriti.config import settings
from smriti.schemas.clinical import NormalizedClinicalEntity

from _demo_common import (
    PRIYA_ABHA,
    apollo_bundle,
    audit_count,
    clinician_claims,
    ensure_priya_patient,
    sentient_bundle,
    set_priya_consent,
    source_record,
)


_original_normalization_run = NormalizationAgent.run


async def _demo_normalization_run(self: NormalizationAgent, entities):
    out: list[NormalizedClinicalEntity] = []
    for entity in entities:
        candidates = await self._top_candidates(entity)
        if candidates:
            out.append(self._apply_code(entity, str(candidates[0]["code"]), str(candidates[0]["system"])))
        else:
            out.append(NormalizedClinicalEntity.model_validate(entity.model_dump() | {"confidence": 0.4}))
    return out


def _clinician_headers() -> dict[str, str]:
    claims = clinician_claims()
    payload = {
        "hpr_id": claims.hpr_id,
        "name": claims.name,
        "role": claims.role,
        "provider_id": claims.provider_id,
        "exp": int((datetime.now(UTC) + timedelta(hours=8)).timestamp()),
    }
    token = jwt.encode(payload, settings.clinician_jwt_key, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


async def run_smoke() -> None:
    NormalizationAgent.run = _demo_normalization_run
    try:
        await ensure_priya_patient()
        await run_writer_dag(source_record("sentient_hms", sentient_bundle()), PRIYA_ABHA)
        await run_writer_dag(source_record("mock_apollo", apollo_bundle()), PRIYA_ABHA)
        await set_priya_consent(include_medications=True)

        audit_before = await audit_count()
        headers = _clinician_headers()

        base_url = os.getenv("SMRITI_API_URL", "http://localhost:8000")
        async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
            first_started = time.perf_counter()
            first = await client.post(
                "/api/v1/clinician/briefing",
                headers=headers,
                json={
                    "abha_id": PRIYA_ABHA,
                    "encounter": {"chief_complaint": "T2DM follow-up", "encounter_type": "routine"},
                },
            )
            first_elapsed_ms = int((time.perf_counter() - first_started) * 1000)
            assert first.status_code == 200, first.text
            first_json = first.json()
            assert first_json.get("briefing_id")
            assert first_json.get("summary")
            assert first_json.get("top_facts")
            assert first_json.get("cohort_panel")
            assert first_json.get("risk_flags") is not None
            assert first_json.get("exclusions") == []
            assert int(first.headers.get("X-Latency-Ms", "999999")) < 8000
            assert first_elapsed_ms < 8000

            await set_priya_consent(include_medications=False)

            second = await client.post(
                "/api/v1/clinician/briefing",
                headers=headers,
                json={
                    "abha_id": PRIYA_ABHA,
                    "encounter": {"chief_complaint": "T2DM follow-up", "encounter_type": "routine"},
                },
            )
            assert second.status_code == 200, second.text
            second_json = second.json()
            assert second_json.get("exclusions") == ["medications"]

            await set_priya_consent(include_medications=True)

            query_started = time.perf_counter()
            query = await client.post(
                "/api/v1/clinician/query",
                headers=headers,
                json={"abha_id": PRIYA_ABHA, "query": "Lab trend"},
            )
            query_elapsed_ms = int((time.perf_counter() - query_started) * 1000)
            assert query.status_code == 200, query.text
            query_json = query.json()
            assert "top_facts" in query_json
            assert query_elapsed_ms < 3000

        audit_after = await audit_count()
        audit_delta = audit_after - audit_before
        assert audit_delta == 3, f"Expected 3 new audit entries, got {audit_delta}"

        print("demo smoke assertions passed")
        print(f"briefing latency ms: {first_elapsed_ms}")
        print(f"query latency ms: {query_elapsed_ms}")
        print(f"audit delta: {audit_delta}")
    finally:
        NormalizationAgent.run = _original_normalization_run


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    try:
        subprocess.run(["make", "demo-reset"], check=True, cwd=repo_root)
    except FileNotFoundError:
        reset_cmds = [
            ["python", "-m", "uv", "run", "--project", "apps/smriti-api", "--env-file", ".env", "python", "apps/smriti-api/scripts/demo_reset.py"],
            ["python", "-m", "uv", "run", "--project", "apps/smriti-api", "--env-file", ".env", "python", "-m", "smriti.db.migrate"],
            ["python", "-m", "uv", "run", "--project", "apps/smriti-api", "--env-file", ".env", "python", "scripts/load_terminology.py"],
            ["python", "-m", "uv", "run", "--project", "apps/smriti-api", "--env-file", ".env", "python", "scripts/generate_cohort.py"],
            ["python", "-m", "uv", "run", "--project", "apps/smriti-api", "--env-file", ".env", "python", "apps/smriti-api/scripts/cache_demo_briefing.py"],
        ]
        for cmd in reset_cmds:
            subprocess.run(cmd, check=True, cwd=repo_root)
    asyncio.run(run_smoke())


if __name__ == "__main__":
    main()
