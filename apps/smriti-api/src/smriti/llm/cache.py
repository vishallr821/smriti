"""Disk cache for LLM responses, intended for demo fallback."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from smriti.config import settings

if TYPE_CHECKING:
    from smriti.schemas.briefing import Briefing
    from smriti.schemas.encounter import EncounterContext


CACHE_DIR = Path(".cache/llm")
_PRIYA_CACHE = "demo_briefing_priya.json"
_PRIYA_NO_MEDS_CACHE = "demo_briefing_priya_no_meds.json"
_PRIYA_KEYS = {
    "abha-priya",
    "abha_priya",
    "abha-priya-demo",
    "91-8765-4321-0001",
    "91876543210001",
    "12-3456-7890-1234",
    "12345678901234",
}


def build_cache_key(role: str, prompt: str, schema_name: str) -> str:
    material = f"{role}{prompt}{schema_name}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def get_cached(key: str) -> dict[str, Any] | None:
    cache_file = CACHE_DIR / f"{key}.json"
    if not cache_file.exists():
        return None
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        return None


def set_cached(key: str, response: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{key}.json"
    cache_file.write_text(json.dumps(response, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def _normalize_abha(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum() or ch in {"-", "_"})


def _is_priya_abha(abha_id: str) -> bool:
    normalized = _normalize_abha(abha_id)
    if normalized in _PRIYA_KEYS:
        return True
    compact_digits = "".join(ch for ch in abha_id if ch.isdigit())
    return compact_digits in {"91876543210001", "12345678901234"}


def _pick_demo_file(abha_id: str, exclusions: list[str]) -> Path | None:
    if not _is_priya_abha(abha_id):
        return None
    normalized_exclusions = sorted({str(item).strip().lower() for item in exclusions if str(item).strip()})
    if not normalized_exclusions:
        return CACHE_DIR / _PRIYA_CACHE
    if normalized_exclusions == ["medications"]:
        return CACHE_DIR / _PRIYA_NO_MEDS_CACHE
    return None


def _refresh_cached_briefing(briefing: "Briefing") -> "Briefing":
    now = datetime.now(UTC)
    refreshed = briefing.model_copy(deep=True)
    refreshed.id = str(uuid4())
    refreshed.generated_at = now
    refreshed.latency_ms = refreshed.latency_ms if refreshed.latency_ms is not None else 4200
    return refreshed


def get_demo_cached_briefing(
    abha_id: str,
    encounter: "EncounterContext",
    exclusions: list[str],
) -> "Briefing | None":
    if not settings.demo_cache:
        return None

    # The cache is curated only for Priya's briefing paths.
    if encounter.encounter_type not in {"routine", "urgent", "emergency"}:
        return None

    cache_file = _pick_demo_file(abha_id, exclusions)
    if cache_file is None or not cache_file.exists():
        return None

    try:
        from smriti.schemas.briefing import Briefing

        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        cached = Briefing.model_validate(payload)
    except Exception:
        return None

    return _refresh_cached_briefing(cached)
