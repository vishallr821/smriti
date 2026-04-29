"""W1 ingestion agent."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import pdfplumber
import structlog
from fhir.resources.bundle import Bundle
from hl7apy.parser import parse_message
from pydantic import BaseModel

from smriti.db.connection import get_pool
from smriti.llm.router import get_router
from smriti.schemas.clinical import RawClinicalEntity, SourceRecord

logger = structlog.get_logger("w1_ingestion")


class IngestionError(RuntimeError):
    pass


class _ExtractedEntities(BaseModel):
    entities: list[RawClinicalEntity]


class IngestionAgent:
    async def _quarantine(self, source_provider: str, payload: str, reason: str) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO quarantine (source_provider, raw_payload, reason, detected_at)
                VALUES ($1, $2, $3, $4)
                """,
                source_provider,
                payload,
                reason,
                datetime.now(UTC),
            )

    async def run(self, source_record: SourceRecord) -> list[RawClinicalEntity]:
        start = time.perf_counter()
        logger.info("entry", agent="w1", format=source_record.format, provider=source_record.provider_id)
        try:
            if source_record.format == "manual":
                rows = source_record.payload.get("entities", [])
                return [RawClinicalEntity.model_validate(item) for item in rows]
            if source_record.format == "fhir":
                return self._from_fhir(source_record)
            if source_record.format == "hl7":
                return self._from_hl7(source_record)
            if source_record.format == "pdf":
                return await self._from_pdf(source_record)
            raise IngestionError(f"Unsupported source format: {source_record.format}")
        except Exception as exc:
            await self._quarantine(source_record.provider_id, str(source_record.payload), f"ingestion_error: {exc}")
            raise IngestionError(str(exc)) from exc
        finally:
            logger.info("exit", agent="w1", latency_ms=int((time.perf_counter() - start) * 1000))

    def _from_fhir(self, source_record: SourceRecord) -> list[RawClinicalEntity]:
        entities: list[RawClinicalEntity] = []
        payload = source_record.payload

        resource_type = payload.get("resourceType", "")

        # Single clinical resource (not a Bundle) — treat it as a one-element list.
        if resource_type and resource_type != "Bundle":
            entries: list[dict] = [payload]
        else:
            # Bundle path — try the typed fhir.resources parser first, fall back to dict walk.
            try:
                bundle = Bundle.model_validate(payload)
                entries = [e.resource.model_dump() for e in (bundle.entry or []) if e.resource is not None]
            except Exception:
                entries = [e.get("resource", {}) for e in payload.get("entry", [])]

        for idx, resource in enumerate(entries):
            if not resource:
                continue
            rtype = resource.get("resourceType")
            rid = resource.get("id") or f"{rtype}-{idx}"
            if rtype == "Condition":
                display = resource.get("code", {}).get("text") or "Condition"
                entities.append(
                    RawClinicalEntity(
                        entity_type="condition",
                        display_name=str(display),
                        raw_value=str(display),
                        source_provider=source_record.provider_id,
                        source_record_id=str(rid),
                        attributes={"status": resource.get("clinicalStatus", {}).get("text")},
                    )
                )
            elif rtype == "MedicationStatement":
                med = resource.get("medicationCodeableConcept", {}).get("text") or "Medication"
                entities.append(
                    RawClinicalEntity(
                        entity_type="medication",
                        display_name=str(med),
                        raw_value=str(med),
                        source_provider=source_record.provider_id,
                        source_record_id=str(rid),
                        attributes={"status": resource.get("status"), "dose": resource.get("dosage", [{}])[0].get("text")},
                    )
                )
            elif rtype == "MedicationRequest":
                med = resource.get("medicationCodeableConcept", {}).get("text") or "Medication"
                entities.append(
                    RawClinicalEntity(
                        entity_type="medication",
                        display_name=str(med),
                        raw_value=str(med),
                        source_provider=source_record.provider_id,
                        source_record_id=str(rid),
                        attributes={"status": resource.get("status"), "dose": resource.get("dosageInstruction", [{}])[0].get("text")},
                    )
                )
            elif rtype == "Observation":
                obs = resource.get("code", {}).get("text") or "Observation"
                raw = obs
                value_quantity = resource.get("valueQuantity")
                if value_quantity is not None and value_quantity.get("value") is not None:
                    raw = f"{obs}: {value_quantity.get('value')} {value_quantity.get('unit', '')}".strip()
                entities.append(
                    RawClinicalEntity(
                        entity_type="observation",
                        display_name=str(obs),
                        raw_value=str(raw),
                        source_provider=source_record.provider_id,
                        source_record_id=str(rid),
                        attributes={},
                    )
                )
            elif rtype == "AllergyIntolerance":
                code = resource.get("code", {}).get("text") or "Allergy"
                status = resource.get("clinicalStatus", {}).get("text") or resource.get("status")
                entities.append(
                    RawClinicalEntity(
                        entity_type="allergy",
                        display_name=str(code),
                        raw_value=str(code),
                        source_provider=source_record.provider_id,
                        source_record_id=str(rid),
                        attributes={"status": status},
                    )
                )
        return entities

    def _from_hl7(self, source_record: SourceRecord) -> list[RawClinicalEntity]:
        msg = parse_message(str(source_record.payload.get("message", "")))
        entities: list[RawClinicalEntity] = []
        for idx, seg in enumerate(msg.children):
            name = seg.name.upper()
            if name == "DG1":
                text = str(seg.to_er7())
                entities.append(
                    RawClinicalEntity(
                        entity_type="condition",
                        display_name="HL7 Diagnosis",
                        raw_value=text,
                        source_provider=source_record.provider_id,
                        source_record_id=f"DG1-{idx}",
                        attributes={},
                    )
                )
        return entities

    async def _from_pdf(self, source_record: SourceRecord) -> list[RawClinicalEntity]:
        pdf_path = source_record.payload.get("path")
        if not pdf_path:
            raise IngestionError("PDF path missing")
        extracted_text = ""
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                extracted_text += (page.extract_text() or "") + "\n"
        prompt = (
            "Extract structured clinical entities as JSON.\n"
            "Return schema: {entities:[{entity_type,display_name,raw_value,source_provider,source_record_id,attributes,confidence}]}\n"
            f"source_provider={source_record.provider_id}\n"
            f"text:\n{extracted_text}"
        )
        response = await get_router().call(
            role="ingestion_extraction",
            prompt=prompt,
            schema=_ExtractedEntities,
        )
        return response.entities
