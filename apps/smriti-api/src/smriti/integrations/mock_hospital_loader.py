"""
Load Priya's Apollo cardiac history into MockHospital's HAPI FHIR server.

Includes the deliberately-conflicting penicillin allergy entry (Mock Apollo
says "no known allergy"; Sentient HMS has already recorded it as active).

Run with:
    make fhir-seed
or directly:
    cd apps/smriti-api
    uv run python -m smriti.integrations.mock_hospital_loader
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

import httpx

# ── Patient identity ────────────────────────────────────────────────────────
PRIYA_ABHA = "91-8765-4321-0001"
PRIYA_DISPLAY = "Priya Sharma"

# ── The conflicting Apollo FHIR bundle ─────────────────────────────────────
# Sentient HMS (provider A) already recorded a penicillin allergy as active.
# Mock Apollo (provider B) sends "no known allergy" — triggers allergy_disagreement
# in W4 reconciliation, which is the WOW moment for the demo.

APOLLO_BUNDLE: dict = {
    "resourceType": "Bundle",
    "type": "transaction",
    "entry": [
        # ── Encounter: cardiac admission ───────────────────────────────────
        {
            "fullUrl": "urn:uuid:enc-apollo-cardiac-2023",
            "request": {"method": "PUT", "url": "Encounter/enc-apollo-cardiac-2023"},
            "resource": {
                "resourceType": "Encounter",
                "id": "enc-apollo-cardiac-2023",
                "status": "finished",
                "class": {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": "IMP",
                    "display": "inpatient encounter",
                },
                "type": [
                    {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": "305354007",
                                "display": "Ward stay",
                            }
                        ]
                    }
                ],
                "subject": {"reference": f"Patient/{PRIYA_ABHA}", "display": PRIYA_DISPLAY},
                "period": {
                    "start": "2023-08-14T08:00:00+05:30",
                    "end": "2023-08-19T14:30:00+05:30",
                },
                "serviceProvider": {
                    "display": "Mock Apollo Hospital – Cardiology"
                },
            },
        },

        # ── Condition: STEMI (the stent procedure trigger) ─────────────────
        {
            "fullUrl": "urn:uuid:cond-apollo-stemi",
            "request": {"method": "PUT", "url": "Condition/cond-apollo-stemi"},
            "resource": {
                "resourceType": "Condition",
                "id": "cond-apollo-stemi",
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                            "code": "resolved",
                        }
                    ]
                },
                "verificationStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                            "code": "confirmed",
                        }
                    ]
                },
                "code": {
                    "coding": [
                        {
                            "system": "http://hl7.org/fhir/sid/icd-10",
                            "code": "I21.0",
                            "display": "Acute transmural myocardial infarction of anterior wall",
                        },
                        {
                            "system": "http://snomed.info/sct",
                            "code": "57054005",
                            "display": "Acute myocardial infarction",
                        },
                    ],
                    "text": "Acute STEMI — anterior wall",
                },
                "subject": {"reference": f"Patient/{PRIYA_ABHA}"},
                "onsetDateTime": "2023-08-14",
                "encounter": {"reference": "Encounter/enc-apollo-cardiac-2023"},
            },
        },

        # ── Procedure: drug-eluting stent ─────────────────────────────────
        {
            "fullUrl": "urn:uuid:proc-apollo-stent",
            "request": {"method": "PUT", "url": "Procedure/proc-apollo-stent"},
            "resource": {
                "resourceType": "Procedure",
                "id": "proc-apollo-stent",
                "status": "completed",
                "code": {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "36969009",
                            "display": "Placement of stent in coronary artery",
                        }
                    ],
                    "text": "Percutaneous coronary intervention with drug-eluting stent (LAD)",
                },
                "subject": {"reference": f"Patient/{PRIYA_ABHA}"},
                "performedDateTime": "2023-08-15T10:00:00+05:30",
                "encounter": {"reference": "Encounter/enc-apollo-cardiac-2023"},
                "note": [
                    {
                        "text": (
                            "Patient underwent primary PCI. Single drug-eluting stent placed in "
                            "proximal LAD. Post-procedure TIMI 3 flow achieved. "
                            "Patient discharged on dual antiplatelet therapy."
                        )
                    }
                ],
            },
        },

        # ── Condition: post-MI left ventricular dysfunction ───────────────
        {
            "fullUrl": "urn:uuid:cond-apollo-lvdys",
            "request": {"method": "PUT", "url": "Condition/cond-apollo-lvdys"},
            "resource": {
                "resourceType": "Condition",
                "id": "cond-apollo-lvdys",
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                            "code": "active",
                        }
                    ]
                },
                "code": {
                    "coding": [
                        {
                            "system": "http://hl7.org/fhir/sid/icd-10",
                            "code": "I50.1",
                            "display": "Left ventricular failure",
                        }
                    ],
                    "text": "Post-MI left ventricular dysfunction, EF 38%",
                },
                "subject": {"reference": f"Patient/{PRIYA_ABHA}"},
                "onsetDateTime": "2023-08-16",
                "encounter": {"reference": "Encounter/enc-apollo-cardiac-2023"},
            },
        },

        # ── Observation: post-procedure troponin peak ──────────────────────
        {
            "fullUrl": "urn:uuid:obs-apollo-trop",
            "request": {"method": "PUT", "url": "Observation/obs-apollo-trop"},
            "resource": {
                "resourceType": "Observation",
                "id": "obs-apollo-trop",
                "status": "final",
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "10839-9",
                            "display": "Troponin I.cardiac [Mass/volume] in Serum or Plasma",
                        }
                    ]
                },
                "subject": {"reference": f"Patient/{PRIYA_ABHA}"},
                "effectiveDateTime": "2023-08-14T10:30:00+05:30",
                "valueQuantity": {
                    "value": 48.7,
                    "unit": "ng/mL",
                    "system": "http://unitsofmeasure.org",
                    "code": "ng/mL",
                },
                "interpretation": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                                "code": "H",
                                "display": "High",
                            }
                        ]
                    }
                ],
                "referenceRange": [{"high": {"value": 0.04, "unit": "ng/mL"}}],
            },
        },

        # ── Observation: echocardiogram EF ────────────────────────────────
        {
            "fullUrl": "urn:uuid:obs-apollo-ef",
            "request": {"method": "PUT", "url": "Observation/obs-apollo-ef"},
            "resource": {
                "resourceType": "Observation",
                "id": "obs-apollo-ef",
                "status": "final",
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "8806-2",
                            "display": "Left ventricular Ejection fraction by US",
                        }
                    ]
                },
                "subject": {"reference": f"Patient/{PRIYA_ABHA}"},
                "effectiveDateTime": "2023-08-16T14:00:00+05:30",
                "valueQuantity": {
                    "value": 38.0,
                    "unit": "%",
                    "system": "http://unitsofmeasure.org",
                    "code": "%",
                },
                "interpretation": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                                "code": "L",
                                "display": "Low",
                            }
                        ]
                    }
                ],
                "referenceRange": [{"low": {"value": 55.0, "unit": "%"}}],
            },
        },

        # ── MedicationRequest: aspirin (DAPT) ─────────────────────────────
        {
            "fullUrl": "urn:uuid:medrx-apollo-aspirin",
            "request": {"method": "PUT", "url": "MedicationRequest/medrx-apollo-aspirin"},
            "resource": {
                "resourceType": "MedicationRequest",
                "id": "medrx-apollo-aspirin",
                "status": "active",
                "intent": "order",
                "medicationCodeableConcept": {
                    "coding": [
                        {
                            "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                            "code": "1191",
                            "display": "Aspirin 75 MG Oral Tablet",
                        }
                    ],
                    "text": "Aspirin 75 mg OD (DAPT)",
                },
                "subject": {"reference": f"Patient/{PRIYA_ABHA}"},
                "authoredOn": "2023-08-19",
                "dosageInstruction": [{"text": "75 mg once daily with food"}],
                "encounter": {"reference": "Encounter/enc-apollo-cardiac-2023"},
            },
        },

        # ── MedicationRequest: clopidogrel (DAPT) ─────────────────────────
        {
            "fullUrl": "urn:uuid:medrx-apollo-clopi",
            "request": {"method": "PUT", "url": "MedicationRequest/medrx-apollo-clopi"},
            "resource": {
                "resourceType": "MedicationRequest",
                "id": "medrx-apollo-clopi",
                "status": "active",
                "intent": "order",
                "medicationCodeableConcept": {
                    "coding": [
                        {
                            "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                            "code": "32968",
                            "display": "Clopidogrel 75 MG Oral Tablet",
                        }
                    ],
                    "text": "Clopidogrel 75 mg OD (DAPT)",
                },
                "subject": {"reference": f"Patient/{PRIYA_ABHA}"},
                "authoredOn": "2023-08-19",
                "dosageInstruction": [{"text": "75 mg once daily"}],
                "encounter": {"reference": "Encounter/enc-apollo-cardiac-2023"},
            },
        },

        # ── MedicationRequest: carvedilol ─────────────────────────────────
        {
            "fullUrl": "urn:uuid:medrx-apollo-carve",
            "request": {"method": "PUT", "url": "MedicationRequest/medrx-apollo-carve"},
            "resource": {
                "resourceType": "MedicationRequest",
                "id": "medrx-apollo-carve",
                "status": "active",
                "intent": "order",
                "medicationCodeableConcept": {
                    "coding": [
                        {
                            "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                            "code": "20352",
                            "display": "Carvedilol 6.25 MG Oral Tablet",
                        }
                    ],
                    "text": "Carvedilol 6.25 mg BD (for LV dysfunction)",
                },
                "subject": {"reference": f"Patient/{PRIYA_ABHA}"},
                "authoredOn": "2023-08-19",
                "dosageInstruction": [{"text": "6.25 mg twice daily"}],
            },
        },

        # ── AllergyIntolerance: THE CONFLICT ──────────────────────────────
        # Sentient HMS has active penicillin allergy; Apollo recorded "no known allergy".
        # W4 will detect allergy_disagreement with severity=high.
        {
            "fullUrl": "urn:uuid:allergy-apollo-pencillin-nka",
            "request": {
                "method": "PUT",
                "url": "AllergyIntolerance/allergy-apollo-penicillin-nka",
            },
            "resource": {
                "resourceType": "AllergyIntolerance",
                "id": "allergy-apollo-penicillin-nka",
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                            "code": "inactive",
                            "display": "Inactive",
                        }
                    ],
                    "text": "no_known_allergy",
                },
                "verificationStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                            "code": "unconfirmed",
                        }
                    ]
                },
                "code": {
                    "coding": [
                        {
                            "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                            "code": "7980",
                            "display": "Penicillin",
                        }
                    ],
                    "text": "No known allergy to Penicillin",
                },
                "patient": {"reference": f"Patient/{PRIYA_ABHA}"},
                "recordedDate": "2023-08-14",
                "note": [
                    {
                        "text": (
                            "Patient denied any known drug allergies on admission. "
                            "Pre-op screening negative. Administered amoxicillin prophylaxis "
                            "without adverse reaction."
                        )
                    }
                ],
            },
        },
    ],
}


# ── Smriti ingest payload ───────────────────────────────────────────────────

SMRITI_BULK_PAYLOAD = {
    "abha_id": PRIYA_ABHA,
    "fhir_bundle": APOLLO_BUNDLE,
}


# ── Loader ──────────────────────────────────────────────────────────────────


def _load_to_hapi(hapi_base_url: str, timeout: int = 30) -> None:
    """POST the Apollo bundle directly to HAPI FHIR (for FHIR server seeding)."""
    url = f"{hapi_base_url.rstrip('/')}/Bundle"
    print(f"[mock_hospital_loader] Posting bundle to HAPI FHIR: {url}")
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            url,
            json=APOLLO_BUNDLE,
            headers={"Content-Type": "application/fhir+json"},
        )
    resp.raise_for_status()
    out = resp.json()
    entry_count = len(out.get("entry", []))
    print(f"[mock_hospital_loader] HAPI FHIR accepted bundle: {entry_count} entries")


def _load_to_smriti(smriti_base_url: str, api_key: str, timeout: int = 60) -> None:
    """POST the Apollo bundle to Smriti's /provider/bulk-ingest."""
    url = f"{smriti_base_url.rstrip('/')}/api/v1/provider/bulk-ingest"
    print(f"[mock_hospital_loader] Posting bundle to Smriti: {url}")
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            url,
            json=SMRITI_BULK_PAYLOAD,
            headers={
                "X-Provider-API-Key": api_key,
                "Content-Type": "application/json",
            },
        )

    if not resp.is_success:
        print(f"[mock_hospital_loader] ERROR {resp.status_code}: {resp.text}", file=sys.stderr)
        resp.raise_for_status()

    result = resp.json()
    print(f"[mock_hospital_loader] Smriti ingest result:")
    print(f"  total_entries : {result.get('total_entries')}")
    print(f"  processed     : {result.get('processed')}")
    print(f"  skipped       : {result.get('skipped')}")
    counts = result.get("counts", {})
    print(f"  inserted      : {counts.get('inserted', 0)}")
    print(f"  merged        : {counts.get('merged', 0)}")
    print(f"  conflicts     : {counts.get('conflicts', 0)}")
    print(f"  quarantined   : {counts.get('quarantined', 0)}")
    errors = result.get("errors", [])
    if errors:
        print(f"  errors ({len(errors)}):")
        for e in errors:
            print(f"    - {e}")
    if counts.get("conflicts", 0) > 0:
        print()
        print("[mock_hospital_loader] Penicillin conflict detected — check conflicts table.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed Priya's Apollo cardiac history into MockHospital HAPI FHIR "
                    "and push it to Smriti for ingest."
    )
    parser.add_argument(
        "--hapi-url",
        default="http://localhost:8080/fhir",
        help="HAPI FHIR base URL (default: http://localhost:8080/fhir)",
    )
    parser.add_argument(
        "--smriti-url",
        default="http://localhost:8000",
        help="Smriti API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-key",
        default="sk_apollo_demo",
        help="Provider API key for mock_apollo (default: sk_apollo_demo)",
    )
    parser.add_argument(
        "--skip-hapi",
        action="store_true",
        help="Skip posting to HAPI FHIR (only ingest into Smriti)",
    )
    parser.add_argument(
        "--skip-smriti",
        action="store_true",
        help="Skip posting to Smriti (only seed HAPI FHIR)",
    )
    parser.add_argument(
        "--dump-bundle",
        action="store_true",
        help="Print the bundle JSON and exit (dry run)",
    )
    args = parser.parse_args()

    if args.dump_bundle:
        print(json.dumps(APOLLO_BUNDLE, indent=2))
        return

    if not args.skip_hapi:
        try:
            _load_to_hapi(args.hapi_url)
        except Exception as exc:
            print(
                f"[mock_hospital_loader] WARNING: HAPI FHIR seeding failed: {exc}\n"
                "  Is the HAPI FHIR server running? Run: make dev-fhir",
                file=sys.stderr,
            )

    if not args.skip_smriti:
        try:
            _load_to_smriti(args.smriti_url, args.api_key)
        except Exception as exc:
            print(
                f"[mock_hospital_loader] ERROR: Smriti ingest failed: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
