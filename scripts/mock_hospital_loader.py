"""Load Priya's Apollo Hospital data into the mock FHIR server and then ingest into Smriti."""
import asyncio
import httpx
import json
from datetime import datetime

PRIYA_ABHA = "12-3456-7890-1234"
APOLLO_PROVIDER_KEY = "sk_apollo_demo"
SMRITI_API = "http://localhost:8000"

# Priya's cardiac timeline from Apollo (2023 stent)
APOLLO_BUNDLE = {
    "resourceType": "Bundle",
    "type": "collection",
    "entry": [
        {
            "resource": {
                "resourceType": "Patient",
                "id": "priya-apollo",
                "identifier": [{"system": "https://healthid.ndhm.gov.in", "value": PRIYA_ABHA}],
                "name": [{"text": "Priya Sharma"}],
                "gender": "female",
                "birthDate": "1978-04-12"
            }
        },
        {
            "resource": {
                "resourceType": "Condition",
                "id": "cond-cad",
                "subject": {"reference": "Patient/priya-apollo"},
                "code": {"coding": [{"system": "http://snomed.info/sct", "code": "53741008", "display": "Coronary arteriosclerosis"}]},
                "onsetDateTime": "2023-08-10",
                "clinicalStatus": {"coding": [{"code": "active"}]}
            }
        },
        {
            "resource": {
                "resourceType": "Procedure",
                "id": "proc-stent",
                "subject": {"reference": "Patient/priya-apollo"},
                "code": {"coding": [{"system": "http://snomed.info/sct", "code": "36969009", "display": "Placement of stent in coronary artery"}]},
                "performedDateTime": "2023-08-12",
                "status": "completed"
            }
        },
        {
            "resource": {
                "resourceType": "MedicationRequest",
                "id": "med-aspirin",
                "subject": {"reference": "Patient/priya-apollo"},
                "medicationCodeableConcept": {"coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "1191", "display": "Aspirin"}]},
                "dosageInstruction": [{"text": "75mg daily"}],
                "authoredOn": "2023-08-12",
                "status": "active"
            }
        },
        {
            "resource": {
                "resourceType": "MedicationRequest",
                "id": "med-clopidogrel",
                "subject": {"reference": "Patient/priya-apollo"},
                "medicationCodeableConcept": {"coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "32968", "display": "Clopidogrel"}]},
                "dosageInstruction": [{"text": "75mg daily"}],
                "authoredOn": "2023-08-12",
                "status": "active"
            }
        },
        {
            "resource": {
                "resourceType": "AllergyIntolerance",
                "id": "allergy-penicillin",
                "patient": {"reference": "Patient/priya-apollo"},
                "code": {"coding": [{"system": "http://snomed.info/sct", "code": "91936005", "display": "Allergy to penicillin"}]},
                "clinicalStatus": {"coding": [{"code": "active"}]},
                "type": "allergy",
                "category": ["medication"],
                "criticality": "high",
                "recordedDate": "2023-08-08"
            }
        }
    ]
}

async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("Ingesting Apollo data into Smriti...")

        response = await client.post(
            f"{SMRITI_API}/api/v1/provider/bulk-ingest",
            headers={
                "X-Provider-API-Key": APOLLO_PROVIDER_KEY,
                "Content-Type": "application/json"
            },
            json={
                "abha_id": PRIYA_ABHA,
                "fhir_bundle": APOLLO_BUNDLE
            }
        )

        if response.status_code == 200:
            result = response.json()
            print(f"Ingested Apollo data")
            print(f"  Inserted: {result['counts']['inserted']}")
            print(f"  Merged: {result['counts']['merged']}")
            print(f"  Conflicts: {result['counts']['conflicts']}")
            print(f"  Quarantined: {result['counts']['quarantined']}")

            if result['counts']['conflicts'] > 0:
                print(f"\nConflict detected (penicillin allergy disagreement)")
        else:
            print(f"Failed: {response.status_code}")
            print(response.text)

if __name__ == "__main__":
    asyncio.run(main())
