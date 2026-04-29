"""Helper utilities for cohort aggregation and DP calculations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

CACHE_DIR = Path(".cache/embeddings")
_model: SentenceTransformer | None = None


def regimen_key_from_treatments(treatments: list[dict]) -> str:
    codes = sorted(str(t.get("rxnorm", "")).strip() for t in treatments if str(t.get("rxnorm", "")).strip())
    return "+".join(codes) if codes else "none"


def laplace_noise(sensitivity: float, epsilon: float) -> float:
    if epsilon <= 0:
        raise ValueError("epsilon must be > 0")
    return float(np.random.laplace(0.0, sensitivity / epsilon))


def build_profile_text(profile: "PatientProfile") -> str:
    lead = f"{profile.age}{profile.sex}, BMI 28"
    cond_map = {
        "44054006": "T2DM with HbA1c 8.9",
        "38341003": "hypertensive",
        "13644009": "hypercholesterolemia",
        "53741008": "coronary artery disease",
    }
    cond_bits = [cond_map[c] for c in profile.conditions if c in cond_map]
    cond_text = ", ".join(cond_bits) if cond_bits else "no major chronic condition"
    meds = " and ".join(profile.current_medications) if profile.current_medications else "no active regimen"
    return f"{lead}, {cond_text}, on {meds}"


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed_profile(text: str) -> np.ndarray:
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        return np.asarray(json.loads(cache_file.read_text(encoding="utf-8")), dtype=np.float32)
    vec = _get_model().encode([text], show_progress_bar=False)[0]
    arr = np.asarray(vec, dtype=np.float32)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(arr.tolist(), separators=(",", ":")), encoding="utf-8")
    return arr
