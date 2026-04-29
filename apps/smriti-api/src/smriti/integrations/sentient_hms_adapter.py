"""
Sentient HMS → Smriti integration spec (PRD §13.1).

This module documents the expected outbound payload shape that Sentient HMS
must produce when pushing records to Smriti's /provider/ingest and
/provider/bulk-ingest endpoints.  It is a SPEC file, not runtime code.

──────────────────────────────────────────────────────────────────────────────
FIELD MAPPING — Sentient HMS table/column → FHIR resource/field
──────────────────────────────────────────────────────────────────────────────

  IPD module
  ──────────
  Encounter.encounter_id          → Encounter.id
  Encounter.patient_uhid          → Encounter.subject.reference  ("Patient/<abha_id>")
  Encounter.encounter_type        → Encounter.class (ICD-10 encounter code)
  Encounter.admit_date            → Encounter.period.start
  Encounter.discharge_date        → Encounter.period.end
  Encounter.attending_doctor_id   → Encounter.participant[0].individual.reference

  Diagnoses module
  ────────────────
  Diagnosis.icd10_code            → Condition.code.coding[0].code   (system: "http://hl7.org/fhir/sid/icd-10")
  Diagnosis.diagnosis_name        → Condition.code.coding[0].display
  Diagnosis.status                → Condition.clinicalStatus.coding[0].code
  Diagnosis.onset_date            → Condition.onsetDateTime

  Lab module
  ──────────
  LabResult.test_loinc            → Observation.code.coding[0].code  (system: "http://loinc.org")
  LabResult.test_name             → Observation.code.coding[0].display
  LabResult.result_value          → Observation.valueString (or valueQuantity)
  LabResult.result_unit           → Observation.valueQuantity.unit
  LabResult.reported_at           → Observation.effectiveDateTime
  LabResult.reference_range_low   → Observation.referenceRange[0].low.value
  LabResult.reference_range_high  → Observation.referenceRange[0].high.value

  Pharmacy module
  ───────────────
  PrescriptionLine.rxnorm_code    → MedicationRequest.medicationCodeableConcept.coding[0].code
  PrescriptionLine.drug_name      → MedicationRequest.medicationCodeableConcept.coding[0].display
  PrescriptionLine.dose           → MedicationRequest.dosageInstruction[0].text
  PrescriptionLine.frequency      → MedicationRequest.dosageInstruction[0].timing.code.text
  PrescriptionLine.start_date     → MedicationRequest.authoredOn
  PrescriptionLine.end_date       → MedicationRequest.dispenseRequest.validityPeriod.end

──────────────────────────────────────────────────────────────────────────────
SAMPLE FHIR BUNDLE — a complete patient encounter push
──────────────────────────────────────────────────────────────────────────────

SAMPLE_BUNDLE: dict = {
    "resourceType": "Bundle",
    "type": "transaction",
    "entry": [
        # ── Encounter ──────────────────────────────────────────────────────
        {
            "resource": {
                "resourceType": "Encounter",
                "id": "enc-sentient-20240301-001",
                "status": "finished",
                "class": {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": "IMP",
                    "display": "inpatient encounter",
                },
                "subject": {
                    "reference": "Patient/91-8765-4321-0001"
                },
                "period": {
                    "start": "2024-03-01T08:00:00+05:30",
                    "end": "2024-03-05T11:30:00+05:30",
                },
                "participant": [
                    {
                        "individual": {
                            "reference": "Practitioner/hpr-doc-007",
                            "display": "Dr. Priya Sharma",
                        }
                    }
                ],
            }
        },
        # ── Condition (Diagnosis) ───────────────────────────────────────────
        {
            "resource": {
                "resourceType": "Condition",
                "id": "cond-sentient-001",
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
                            "code": "E11.9",
                            "display": "Type 2 diabetes mellitus without complications",
                        }
                    ]
                },
                "subject": {"reference": "Patient/91-8765-4321-0001"},
                "onsetDateTime": "2019-06-01",
                "encounter": {"reference": "Encounter/enc-sentient-20240301-001"},
            }
        },
        # ── Observation (Lab) ───────────────────────────────────────────────
        {
            "resource": {
                "resourceType": "Observation",
                "id": "obs-sentient-hba1c-001",
                "status": "final",
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "4548-4",
                            "display": "Hemoglobin A1c/Hemoglobin.total in Blood",
                        }
                    ]
                },
                "subject": {"reference": "Patient/91-8765-4321-0001"},
                "effectiveDateTime": "2024-03-02T09:15:00+05:30",
                "valueQuantity": {
                    "value": 9.2,
                    "unit": "%",
                    "system": "http://unitsofmeasure.org",
                    "code": "%",
                },
                "referenceRange": [{"low": {"value": 4.0}, "high": {"value": 5.6}}],
            }
        },
        # ── MedicationRequest (Pharmacy) ────────────────────────────────────
        {
            "resource": {
                "resourceType": "MedicationRequest",
                "id": "medrx-sentient-001",
                "status": "active",
                "intent": "order",
                "medicationCodeableConcept": {
                    "coding": [
                        {
                            "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                            "code": "860975",
                            "display": "Metformin 500 MG Oral Tablet",
                        }
                    ]
                },
                "subject": {"reference": "Patient/91-8765-4321-0001"},
                "authoredOn": "2024-03-03",
                "dosageInstruction": [
                    {
                        "text": "500 mg twice daily with meals",
                        "timing": {"code": {"text": "BD"}},
                    }
                ],
                "dispenseRequest": {
                    "validityPeriod": {
                        "start": "2024-03-03",
                        "end": "2024-09-03",
                    }
                },
            }
        },
    ],
}

──────────────────────────────────────────────────────────────────────────────
EXAMPLE HTTP CALLS from Sentient HMS smriti_connector module
──────────────────────────────────────────────────────────────────────────────

# Single record (fires after each IPD/lab/pharmacy save)
POST https://smriti.internal/api/v1/provider/ingest
X-Provider-API-Key: sk_sentient_demo
Content-Type: application/json

{
  "abha_id": "91-8765-4321-0001",
  "record_type": "observation",
  "format": "fhir",
  "payload": {
    "resourceType": "Observation",
    "id": "obs-sentient-hba1c-001",
    "status": "final",
    "code": {
      "coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "Hemoglobin A1c"}]
    },
    "subject": {"reference": "Patient/91-8765-4321-0001"},
    "effectiveDateTime": "2024-03-02T09:15:00+05:30",
    "valueQuantity": {"value": 9.2, "unit": "%"}
  }
}

→ 200 OK
{
  "ingest_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "success",
  "counts": {"inserted": 1, "merged": 0, "conflicts": 0, "quarantined": 0},
  "errors": []
}


# Full encounter bundle (fires at discharge)
POST https://smriti.internal/api/v1/provider/bulk-ingest
X-Provider-API-Key: sk_sentient_demo
Content-Type: application/json

{
  "abha_id": "91-8765-4321-0001",
  "fhir_bundle": { ... SAMPLE_BUNDLE above ... }
}

→ 200 OK
{
  "total_entries": 4,
  "counts": {"inserted": 3, "merged": 0, "conflicts": 0, "quarantined": 0},
  "errors": []
}


# Status check (displayed as "Synced to Smriti" toast in HMS UI)
GET https://smriti.internal/api/v1/provider/status/f47ac10b-58cc-4372-a567-0e02b2c3d479
X-Provider-API-Key: sk_sentient_demo

→ 200 OK
{
  "ingest_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "provider_id": "sentient_hms",
  "abha_id": "91-8765-4321-0001",
  "status": "success",
  "counts": {"inserted": 1, "merged": 0, "conflicts": 0, "quarantined": 0},
  "errors": [],
  "created_at": "2024-03-02T09:16:43Z"
}

──────────────────────────────────────────────────────────────────────────────
IMPLEMENTATION NOTE for Sentient HMS smriti_connector (~150 lines TypeScript)
──────────────────────────────────────────────────────────────────────────────

1. Subscribe to internal event bus topics:
     ipd.encounter.saved  →  POST /provider/ingest  (record_type="encounter")
     lab.result.reported  →  POST /provider/ingest  (record_type="observation")
     pharmacy.rx.issued   →  POST /provider/ingest  (record_type="medicationrequest")
     ipd.discharge.final  →  POST /provider/bulk-ingest  (full FHIR bundle)

2. Map each event payload to the FHIR shape shown in FIELD MAPPING above.

3. Use SMRITI_API_KEY env var (= PROVIDER_KEY_SENTIENT_HMS on the Smriti side).

4. On 200 OK: store ingest_id in local discharge summary, show "Synced ✓" toast.
   On 4xx/5xx: log to Sentient HMS error queue; do NOT block the clinical save.

5. Retry: exponential backoff × 3, then dead-letter queue for manual review.
"""
