"""PII redaction and restoration primitives using local Presidio."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerResult
from presidio_analyzer import RecognizerRegistry
from presidio_anonymizer import AnonymizerEngine

from smriti.db.connection import get_pool


class AadhaarDetectedError(ValueError):
    """Raised when Aadhaar reaches W2, which is a hard policy violation."""


@dataclass(slots=True)
class RedactionResult:
    redacted_text: str
    redaction_map: dict[str, str]
    detected_entities: list[str]


class PIIRedactor:
    _clinical_whitelist: set[str] | None = None

    def __init__(self) -> None:
        # Keep Presidio local and deterministic with pattern recognizers only.
        registry = RecognizerRegistry(supported_languages=["en"])
        self.analyzer = AnalyzerEngine(registry=registry, nlp_engine=None, supported_languages=["en"])
        self.anonymizer = AnonymizerEngine()

        self._add_pattern_recognizers()

    def _add_pattern_recognizers(self) -> None:
        self.analyzer.registry.add_recognizer(
            PatternRecognizer(
                supported_entity="PHONE_NUMBER",
                patterns=[Pattern("phone_india", r"\b(?:\+91[\s-]?)?[6-9]\d{9}\b", 0.6)],
            )
        )
        self.analyzer.registry.add_recognizer(
            PatternRecognizer(
                supported_entity="EMAIL_ADDRESS",
                patterns=[Pattern("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", 0.7)],
            )
        )
        self.analyzer.registry.add_recognizer(
            PatternRecognizer(
                supported_entity="IN_PAN",
                patterns=[Pattern("pan", r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", 0.8)],
            )
        )
        self.analyzer.registry.add_recognizer(
            PatternRecognizer(
                supported_entity="IN_AADHAAR",
                patterns=[Pattern("aadhaar", r"\b\d{12}\b", 1.0)],
            )
        )
        self.analyzer.registry.add_recognizer(
            PatternRecognizer(
                supported_entity="PERSON",
                patterns=[Pattern("person_title", r"\b(?:Mr|Mrs|Ms|Dr)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b", 0.55)],
            )
        )
        self.analyzer.registry.add_recognizer(
            PatternRecognizer(
                supported_entity="DATE_TIME",
                patterns=[
                    Pattern("date_iso", r"\b\d{4}-\d{2}-\d{2}\b", 0.6),
                    Pattern("date_dmy", r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", 0.6),
                ],
            )
        )
        self.analyzer.registry.add_recognizer(
            PatternRecognizer(
                supported_entity="LOCATION",
                patterns=[
                    Pattern(
                        "address",
                        r"\b\d{1,4}[\w\s,.-]{6,}(?:Road|Rd|Street|St|Nagar|Colony|Lane|Ln|Avenue|Ave)\b",
                        0.55,
                    )
                ],
            )
        )

    @classmethod
    def _get_clinical_whitelist(cls) -> set[str]:
        if cls._clinical_whitelist is not None:
            return cls._clinical_whitelist

        whitelist = {
            "Type 2 diabetes mellitus",
            "Essential hypertension",
            "Metformin",
            "Hemoglobin A1c/Hemoglobin.total in Blood",
        }

        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                cls._clinical_whitelist = whitelist
                return whitelist
        except RuntimeError:
            pass

        async def _load() -> set[str]:
            pool = await get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT display_name
                    FROM terminology_index
                    ORDER BY id
                    LIMIT 200
                    """
                )
                out = {str(r["display_name"]) for r in rows if r.get("display_name")}
                return out or whitelist

        try:
            cls._clinical_whitelist = asyncio.run(_load())
        except Exception:
            cls._clinical_whitelist = whitelist
        return cls._clinical_whitelist

    @staticmethod
    def _extract_year(value: str) -> str:
        m = re.search(r"\b(19|20)\d{2}\b", value)
        return m.group(0) if m else "YEAR"

    @staticmethod
    def _is_valid_aadhaar(aadhaar: str) -> bool:
        # Verhoeff checksum validation.
        d = [
            [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
            [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
            [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
            [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
            [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
            [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
            [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
            [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
            [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
            [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
        ]
        p = [
            [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
            [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
            [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
            [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
            [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
            [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
            [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
            [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
        ]
        inv = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]
        c = 0
        digits = [int(x) for x in aadhaar[::-1]]
        for i, item in enumerate(digits):
            c = d[c][p[i % 8][item]]
        return inv[c] == 0

    def redact(self, text: str) -> RedactionResult:
        whitelist = self._get_clinical_whitelist()
        entities: list[RecognizerResult] = self.analyzer.analyze(
            text=text,
            language="en",
            entities=["PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "IN_PAN", "IN_AADHAAR", "DATE_TIME", "LOCATION"],
        )

        allowed_entities = []
        for entity in entities:
            original = text[entity.start : entity.end]
            if original in whitelist:
                continue
            if entity.entity_type == "IN_AADHAAR" and original.isdigit() and self._is_valid_aadhaar(original):
                raise AadhaarDetectedError("Aadhaar detected in W2 payload")
            allowed_entities.append(entity)

        redaction_map: dict[str, str] = {}
        detected_entities: list[str] = []

        for entity in sorted(allowed_entities, key=lambda e: e.start, reverse=True):
            original = text[entity.start : entity.end]
            if entity.entity_type == "DATE_TIME":
                placeholder = f"<YEAR:{self._extract_year(original)}>"
            elif entity.entity_type == "PERSON":
                placeholder = "<PERSON>"
            elif entity.entity_type == "PHONE_NUMBER":
                placeholder = "<PHONE>"
            elif entity.entity_type == "EMAIL_ADDRESS":
                placeholder = "<EMAIL>"
            elif entity.entity_type == "IN_PAN":
                placeholder = "<PAN>"
            elif entity.entity_type == "LOCATION":
                placeholder = "<ADDRESS>"
            else:
                placeholder = f"<{entity.entity_type}>"

            redaction_map[original] = placeholder
            detected_entities.append(entity.entity_type)
            text = text[: entity.start] + placeholder + text[entity.end :]

        return RedactionResult(
            redacted_text=text,
            redaction_map=redaction_map,
            detected_entities=sorted(set(detected_entities)),
        )

    def restore(self, text: str, redaction_map: dict[str, str]) -> str:
        inverse: dict[str, str] = {}
        for original, placeholder in redaction_map.items():
            inverse.setdefault(placeholder, original)
        restored = text
        for placeholder, original in inverse.items():
            restored = restored.replace(placeholder, original)
        return restored
