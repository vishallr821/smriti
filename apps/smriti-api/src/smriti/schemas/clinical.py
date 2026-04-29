"""Clinical schemas for writer pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RawClinicalEntity(BaseModel):
    entity_type: Literal["condition", "medication", "observation", "allergy"]
    display_name: str
    raw_value: str
    source_provider: str
    source_record_id: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0


class NormalizedClinicalEntity(RawClinicalEntity):
    snomed_code: str | None = None
    icd10_code: str | None = None
    loinc_code: str | None = None
    rxnorm_code: str | None = None


class SourceRecord(BaseModel):
    provider_id: str
    record_type: str
    payload: dict[str, Any]
    format: Literal["fhir", "hl7", "pdf", "manual"]
    received_at: datetime


class ReconciliationResult(BaseModel):
    inserts: list[dict[str, Any]] = Field(default_factory=list)
    merges: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
