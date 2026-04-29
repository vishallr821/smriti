"""Provider-facing ingest API (PRD §11.3, §13.1)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from smriti.agents.writers.dag import WriterResult, run_writer_dag
from smriti.auth import ProviderClaims, current_provider
from smriti.db.connection import get_pool
from smriti.schemas.clinical import SourceRecord

logger = structlog.get_logger("provider_routes")

router = APIRouter(prefix="/api/v1", tags=["provider"])

# FHIR resource types we understand — anything else is skipped but not fatal.
_KNOWN_FHIR_TYPES = frozenset({
    "Condition", "MedicationRequest", "MedicationStatement",
    "Observation", "AllergyIntolerance", "Encounter",
})

# Maximum bundle entries per request — prevents memory DoS.
_BUNDLE_ENTRY_LIMIT = 500


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    """Single-record ingest body."""

    abha_id: str | None = None
    aadhaar_hash: str | None = None
    record_type: str
    payload: dict[str, Any]
    format: str = "fhir"


class IngestCounts(BaseModel):
    inserted: int = 0
    merged: int = 0
    conflicts: int = 0
    quarantined: int = 0


class IngestResponse(BaseModel):
    ingest_id: str
    status: str
    counts: IngestCounts
    errors: list[str] = Field(default_factory=list)


class BulkIngestRequest(BaseModel):
    abha_id: str
    fhir_bundle: dict[str, Any]


class BulkIngestResponse(BaseModel):
    total_entries: int
    processed: int
    skipped: int
    counts: IngestCounts
    errors: list[str] = Field(default_factory=list)


class IngestStatusResponse(BaseModel):
    ingest_id: str
    provider_id: str
    abha_id: str | None
    status: str
    counts: IngestCounts | None
    errors: list[str] = Field(default_factory=list)
    created_at: datetime


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_bundle_entry(entry: Any, idx: int) -> tuple[dict[str, Any] | None, str | None]:
    """
    Returns (resource_dict, None) on success, or (None, error_msg) on failure.
    Unknown FHIR types → (None, None) meaning silently skip.
    """
    if not isinstance(entry, dict):
        return None, f"entry[{idx}]: not a JSON object"

    resource = entry.get("resource", entry)
    if not isinstance(resource, dict):
        return None, f"entry[{idx}]: 'resource' field is not a JSON object"

    resource_type = resource.get("resourceType")
    if not isinstance(resource_type, str) or not resource_type.strip():
        return None, f"entry[{idx}]: missing or invalid 'resourceType'"

    # Unknown types are quietly skipped — forward-compatible with future FHIR versions.
    if resource_type not in _KNOWN_FHIR_TYPES:
        return None, None  # (skip signal)

    return resource, None


def _resolve_abha(req: IngestRequest) -> str:
    if req.abha_id:
        return req.abha_id
    if req.aadhaar_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="aadhaar_hash lookup not yet implemented; provide abha_id directly",
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Request must include abha_id or aadhaar_hash for ABHA matching",
    )


def _writer_result_to_status(result: WriterResult) -> str:
    if result.quarantined:
        return "quarantined"
    if result.conflicts > 0 and result.inserted == 0 and result.merged == 0:
        return "partial"
    if result.inserted > 0 or result.merged > 0:
        return "success"
    return "failed"


async def _log_ingest(
    *,
    provider_id: str,
    abha_id: str | None,
    ingest_status: str,
    counts: dict[str, int],
    errors: list[str],
) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        ingest_id = await conn.fetchval(
            """
            INSERT INTO ingest_log (provider_id, abha_id, status, counts, errors)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
            RETURNING ingest_id
            """,
            provider_id,
            abha_id,
            ingest_status,
            json.dumps(counts),
            json.dumps(errors),
        )
    return str(ingest_id)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/provider/ingest", response_model=IngestResponse)
async def provider_ingest(
    body: IngestRequest,
    provider: ProviderClaims = Depends(current_provider),
) -> IngestResponse:
    abha_id = _resolve_abha(body)

    if not isinstance(body.payload, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="payload must be a JSON object",
        )

    source_record = SourceRecord(
        provider_id=provider.provider_id,
        record_type=body.record_type,
        payload=body.payload,
        format=body.format,  # type: ignore[arg-type]
        received_at=datetime.now(UTC),
    )

    result = await run_writer_dag(
        source_record=source_record,
        abha_id=abha_id,
        actor_id=provider.provider_id,
        actor_role="provider",
    )

    ingest_status = _writer_result_to_status(result)
    counts = {
        "inserted": result.inserted,
        "merged": result.merged,
        "conflicts": result.conflicts,
        "quarantined": 1 if result.quarantined else 0,
    }
    errors: list[str] = []

    ingest_id = await _log_ingest(
        provider_id=provider.provider_id,
        abha_id=abha_id,
        ingest_status=ingest_status,
        counts=counts,
        errors=errors,
    )

    logger.info(
        "provider_ingest",
        ingest_id=ingest_id,
        provider_id=provider.provider_id,
        abha_id=abha_id,
        status=ingest_status,
    )

    return IngestResponse(
        ingest_id=ingest_id,
        status=ingest_status,
        counts=IngestCounts(**counts),
        errors=errors,
    )


@router.post("/provider/bulk-ingest", response_model=BulkIngestResponse)
async def provider_bulk_ingest(
    body: BulkIngestRequest,
    provider: ProviderClaims = Depends(current_provider),
) -> BulkIngestResponse:
    bundle = body.fhir_bundle

    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fhir_bundle must be a FHIR Bundle resource (resourceType='Bundle')",
        )

    raw_entries: list[Any] = bundle.get("entry", [])
    if not isinstance(raw_entries, list) or not raw_entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="FHIR Bundle contains no entries",
        )

    if len(raw_entries) > _BUNDLE_ENTRY_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bundle exceeds maximum entry limit of {_BUNDLE_ENTRY_LIMIT}",
        )

    aggregate = IngestCounts()
    all_errors: list[str] = []
    processed = 0
    skipped = 0

    # Bundle-level raw_text (e.g. a note or narrative attached to the whole bundle)
    # is propagated to every entry so W2's injection guard can scan it.
    bundle_raw_text: str | None = bundle.get("raw_text") if isinstance(bundle.get("raw_text"), str) else None

    for idx, raw_entry in enumerate(raw_entries):
        resource, err = _validate_bundle_entry(raw_entry, idx)

        if err is not None:
            all_errors.append(err)
            continue  # bad structure — skip, don't crash whole bundle

        if resource is None:
            # Unknown FHIR type — silently skip.
            skipped += 1
            continue

        resource_type = resource.get("resourceType", "Unknown")
        record_type = resource_type.lower()

        # Inject bundle-level raw_text into each resource's payload so W2 can scan it.
        payload = dict(resource)
        if bundle_raw_text and "raw_text" not in payload:
            payload["raw_text"] = bundle_raw_text

        source_record = SourceRecord(
            provider_id=provider.provider_id,
            record_type=record_type,
            payload=payload,
            format="fhir",
            received_at=datetime.now(UTC),
        )

        try:
            result = await run_writer_dag(
                source_record=source_record,
                abha_id=body.abha_id,
                actor_id=provider.provider_id,
                actor_role="provider",
            )
            aggregate.inserted += result.inserted
            aggregate.merged += result.merged
            aggregate.conflicts += result.conflicts
            if result.quarantined:
                aggregate.quarantined += 1
            processed += 1
        except Exception as exc:
            # One bad resource must never block the rest of the bundle.
            all_errors.append(f"entry[{idx}] ({resource_type}): {exc}")

    # Determine aggregate status for the log.
    if aggregate.quarantined > 0 and processed == 0:
        bulk_status = "quarantined"
    elif all_errors:
        bulk_status = "partial"
    elif aggregate.inserted > 0 or aggregate.merged > 0:
        bulk_status = "success"
    else:
        bulk_status = "failed"

    await _log_ingest(
        provider_id=provider.provider_id,
        abha_id=body.abha_id,
        ingest_status=bulk_status,
        counts={
            "inserted": aggregate.inserted,
            "merged": aggregate.merged,
            "conflicts": aggregate.conflicts,
            "quarantined": aggregate.quarantined,
        },
        errors=all_errors,
    )

    logger.info(
        "provider_bulk_ingest",
        provider_id=provider.provider_id,
        abha_id=body.abha_id,
        total_entries=len(raw_entries),
        processed=processed,
        skipped=skipped,
        inserted=aggregate.inserted,
        errors=len(all_errors),
    )

    return BulkIngestResponse(
        total_entries=len(raw_entries),
        processed=processed,
        skipped=skipped,
        counts=aggregate,
        errors=all_errors,
    )


@router.get("/provider/status/{ingest_id}", response_model=IngestStatusResponse)
async def provider_ingest_status(
    ingest_id: str,
    provider: ProviderClaims = Depends(current_provider),
) -> IngestStatusResponse:
    try:
        parsed_id = UUID(ingest_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ingest_id must be a valid UUID",
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ingest_log WHERE ingest_id = $1",
            parsed_id,
        )

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingest record not found")

    if row["provider_id"] != provider.provider_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    raw_counts: dict[str, Any] = json.loads(row["counts"]) if row["counts"] else {}
    raw_errors: list[str] = json.loads(row["errors"]) if row["errors"] else []

    counts = IngestCounts(
        inserted=raw_counts.get("inserted", 0),
        merged=raw_counts.get("merged", 0),
        conflicts=raw_counts.get("conflicts", 0),
        quarantined=raw_counts.get("quarantined", 0),
    )

    return IngestStatusResponse(
        ingest_id=str(row["ingest_id"]),
        provider_id=row["provider_id"],
        abha_id=row["abha_id"],
        status=row["status"],
        counts=counts,
        errors=raw_errors,
        created_at=row["created_at"],
    )
