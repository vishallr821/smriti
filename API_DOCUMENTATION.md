# Smriti API Documentation

**Backend Base URL:** `http://localhost:8000`  
**API Version:** `v1`  
**Health Check:** `GET /health`

---

## Table of Contents

1. [Authentication](#authentication)
2. [System Endpoints](#system-endpoints)
3. [Clinician APIs](#clinician-apis)
4. [Provider APIs](#provider-apis)
5. [Patient APIs](#patient-apis-stubs)
6. [Data Schemas](#data-schemas)
7. [Error Handling](#error-handling)
8. [System Architecture](#system-architecture)

---

## Authentication

### Provider Authentication
**Method:** API Key in Header  
**Header:** `X-Provider-API-Key`  
**Keys (from .env):**
- `PROVIDER_KEY_MOCK_APOLLO=sk_apollo_demo` → Mock Apollo Hospital
- `PROVIDER_KEY_SENTIENT_HMS=sk_sentient_demo` → Sentient HMS Demo

**Response Type:** `ProviderClaims`
```json
{
  "provider_id": "mock_apollo",
  "display_name": "Mock Apollo Hospital"
}
```

### Clinician Authentication
**Method:** JWT Token (not yet implemented, Phase 6)  
**Token Location:** Authorization header or URL parameter  
**Claims Schema:**
```json
{
  "hpr_id": "string",
  "name": "string",
  "role": "string"
}
```

### Patient Authentication
**Method:** JWT Token (not yet implemented, Phase 2-5)  
**Claims Schema:**
```json
{
  "abha_id": "12-3456-7890-1234",
  "abha_address": "string",
  "exp": 1234567890
}
```

---

## System Endpoints

### Health Check
```
GET /health
```
**Authentication:** None  
**Response (200 OK):**
```json
{
  "status": "ok",
  "checks": {
    "database": true,
    "mock_abha": true,
    "groq": true
  }
}
```
**Status Values:** `"ok"` (all services healthy) | `"degraded"` (some services down)

### Version Info
```
GET /version
```
**Authentication:** None  
**Response (200 OK):**
```json
{
  "app_version": "0.1.0",
  "git_commit": "b94f940"
}
```

---

## Clinician APIs

### 1. Generate Patient Briefing
```
POST /api/v1/clinician/briefing
```

**Authentication:** Required (JWT)  
**Scopes Required:** `["briefing"]`

**Request Body:**
```json
{
  "abha_id": "12-3456-7890-1234",
  "encounter": {
    "chief_complaint": "Chest pain",
    "encounter_type": "urgent",
    "nl_query": null
  }
}
```

**encounter.encounter_type:** `"routine"` | `"urgent"` | `"emergency"`

**Response Headers:**
- `X-Latency-Ms`: Milliseconds to generate briefing
- `X-Demo-Cache`: `"true"` if response was cached (demo mode)

**Response (200 OK):**
```json
{
  "briefing_id": "550e8400-e29b-41d4-a716-446655440000",
  "generated_at": "2026-04-29T15:48:12.551103Z",
  "summary": "Priya Sharma, 45F with coronary artery disease s/p stent placement (Aug 2023). Currently on aspirin + clopidogrel for dual antiplatelet therapy. Penicillin allergy noted.",
  "top_facts": [
    {
      "fact": "Coronary arteriosclerosis with stent placement",
      "source": {
        "table": "conditions",
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "provider": "Apollo Hospital",
        "date": "2023-08-12T00:00:00Z"
      },
      "date": "2023-08-12T00:00:00Z",
      "confidence": 0.95
    }
  ],
  "conflicts": [
    {
      "entity_type": "allergy",
      "source_a": {
        "provider": "Apollo",
        "value": "Penicillin allergy (high criticality)"
      },
      "source_b": {
        "provider": "Sentient HMS",
        "value": "No penicillin allergy recorded"
      },
      "status": "unresolved"
    }
  ],
  "medication_timeline": [
    {
      "medication": "Aspirin",
      "dose": "75mg daily",
      "start_date": "2023-08-12",
      "end_date": null,
      "provider": "Apollo Hospital",
      "status": "active"
    }
  ],
  "cohort_panel": {
    "label": "Patients like Priya",
    "n_total": 47,
    "privacy": {
      "k_anonymity": 10,
      "epsilon": 1.0
    },
    "buckets": [
      {
        "regimen": "Aspirin + Clopidogrel",
        "n": 23,
        "outcome_metric": "HbA1c",
        "outcome_value": -1.4,
        "outcome_ci": 0.2,
        "outcome_unit": "%",
        "outcome_timeframe": "3mo"
      }
    ]
  },
  "risk_flags": [
    {
      "flag": "Dual antiplatelet therapy — high bleeding risk",
      "severity": "high",
      "justification": "Patient on aspirin + clopidogrel without indication of acute coronary syndrome"
    }
  ],
  "exclusions": [],
  "disclaimers": "Smriti surfaces existing records. It does not diagnose, treat, or replace clinical judgment. Verify all facts at their source.",
  "latency_ms": 4200
}
```

**Error Responses:**
- `403 Forbidden` - Consent denied for patient
- `404 Not Found` - Patient not found
- `400 Bad Request` - Invalid encounter context
- `500 Internal Server Error` - Processing error

---

### 2. Natural Language Query
```
POST /api/v1/clinician/query
```

**Authentication:** Required (JWT)  
**Scopes Required:** None (query-specific)

**Request Body:**
```json
{
  "abha_id": "12-3456-7890-1234",
  "query": "What medications is the patient taking?"
}
```

**Query Examples (Recognized Intents):**
- "Lab trend" → Lab values over time
- "Medication history" → All past/current medications
- "Allergies" → Known allergies
- "Drug interactions" → Medication interaction check
- "Similar patients" → Cohort lookup
- "Brief me" → General briefing

**Response (200 OK):**
```json
{
  "top_facts": [
    {
      "fact": "Aspirin 75mg daily",
      "source": {
        "table": "medications",
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "provider": "Apollo Hospital",
        "date": "2023-08-12T00:00:00Z"
      },
      "date": "2023-08-12T00:00:00Z",
      "confidence": 0.98
    }
  ],
  "medications": [
    {
      "medication": "Aspirin",
      "dose": "75mg",
      "frequency": "daily",
      "start_date": "2023-08-12",
      "status": "active"
    },
    {
      "medication": "Clopidogrel",
      "dose": "75mg",
      "frequency": "daily",
      "start_date": "2023-08-12",
      "status": "active"
    }
  ],
  "conflicts": [],
  "observations": [],
  "allergies": [],
  "conditions": []
}
```

---

### 3. Get Source Record Details
```
GET /api/v1/clinician/source/{table}/{id}
```

**Authentication:** Required (JWT)  
**Scopes Required:** Depends on table:
- `"conditions"` → Read conditions
- `"medications"` → Read medications
- `"observations"` → Read observations
- `"allergies"` → Read allergies

**Path Parameters:**
- `table`: `"conditions"` | `"medications"` | `"observations"` | `"allergies"`
- `id`: UUID of the source record

**Example:**
```
GET /api/v1/clinician/source/medications/550e8400-e29b-41d4-a716-446655440000
```

**Response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "abha_id": "12-3456-7890-1234",
  "provider_id": "apollo",
  "record_type": "MedicationRequest",
  "payload": {
    "resourceType": "MedicationRequest",
    "medicationCodeableConcept": {
      "coding": [
        {
          "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
          "code": "1191",
          "display": "Aspirin"
        }
      ]
    },
    "dosageInstruction": [
      {
        "text": "75mg daily"
      }
    ],
    "status": "active"
  },
  "format": "fhir",
  "received_at": "2023-08-12T10:30:00Z",
  "ingested_at": "2026-04-29T15:48:12.551103Z"
}
```

**Error Responses:**
- `400 Bad Request` - Invalid table or UUID format
- `403 Forbidden` - Consent denied for this data
- `404 Not Found` - Record not found

---

## Provider APIs

### 1. Single Record Ingest
```
POST /api/v1/provider/ingest
```

**Authentication:** Required (X-Provider-API-Key header)

**Request Body:**
```json
{
  "abha_id": "12-3456-7890-1234",
  "record_type": "Condition",
  "format": "fhir",
  "payload": {
    "resourceType": "Condition",
    "id": "cond-cad",
    "subject": {
      "reference": "Patient/priya-apollo"
    },
    "code": {
      "coding": [
        {
          "system": "http://snomed.info/sct",
          "code": "53741008",
          "display": "Coronary arteriosclerosis"
        }
      ]
    },
    "onsetDateTime": "2023-08-10",
    "clinicalStatus": {
      "coding": [
        {
          "code": "active"
        }
      ]
    }
  }
}
```

**Alternative: Use aadhaar_hash instead of abha_id (not yet implemented)**

**Response (200 OK):**
```json
{
  "ingest_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "success",
  "counts": {
    "inserted": 1,
    "merged": 0,
    "conflicts": 0,
    "quarantined": 0
  },
  "errors": []
}
```

**Status Values:**
- `"success"` - Record inserted/merged successfully
- `"partial"` - Some conflicts but data ingested
- `"quarantined"` - Data flagged for review
- `"failed"` - Ingestion failed

**Error Responses:**
- `401 Unauthorized` - Invalid/missing API key
- `400 Bad Request` - Missing abha_id and aadhaar_hash
- `422 Unprocessable Entity` - Invalid payload structure

---

### 2. Bulk FHIR Bundle Ingest
```
POST /api/v1/provider/bulk-ingest
```

**Authentication:** Required (X-Provider-API-Key header)

**Request Body:**
```json
{
  "abha_id": "12-3456-7890-1234",
  "fhir_bundle": {
    "resourceType": "Bundle",
    "type": "collection",
    "entry": [
      {
        "resource": {
          "resourceType": "Patient",
          "id": "priya-apollo",
          "identifier": [
            {
              "system": "https://healthid.ndhm.gov.in",
              "value": "12-3456-7890-1234"
            }
          ],
          "name": [
            {
              "text": "Priya Sharma"
            }
          ],
          "gender": "female",
          "birthDate": "1978-04-12"
        }
      },
      {
        "resource": {
          "resourceType": "Condition",
          "id": "cond-cad",
          "code": {
            "coding": [
              {
                "system": "http://snomed.info/sct",
                "code": "53741008",
                "display": "Coronary arteriosclerosis"
              }
            ]
          }
        }
      }
    ]
  }
}
```

**Maximum Entries:** 500 per bundle

**Supported FHIR Resource Types:**
- `Condition` → Medical conditions
- `MedicationRequest` → Prescribed medications
- `MedicationStatement` → Medication history
- `Observation` → Lab results, vitals
- `AllergyIntolerance` → Allergies
- `Encounter` → Visit/admission records
- (Others silently skipped for forward compatibility)

**Response (200 OK):**
```json
{
  "total_entries": 5,
  "processed": 5,
  "skipped": 0,
  "counts": {
    "inserted": 4,
    "merged": 1,
    "conflicts": 0,
    "quarantined": 0
  },
  "errors": []
}
```

**Error Responses:**
- `400 Bad Request` - Invalid bundle structure
- `401 Unauthorized` - Invalid API key
- `422 Unprocessable Entity` - Bundle exceeds 500 entries

---

### 3. Check Ingest Status
```
GET /api/v1/provider/status/{ingest_id}
```

**Authentication:** Required (X-Provider-API-Key header)

**Path Parameters:**
- `ingest_id`: UUID returned from `/provider/ingest` or `/provider/bulk-ingest`

**Response (200 OK):**
```json
{
  "ingest_id": "550e8400-e29b-41d4-a716-446655440000",
  "provider_id": "apollo",
  "abha_id": "12-3456-7890-1234",
  "status": "success",
  "counts": {
    "inserted": 4,
    "merged": 1,
    "conflicts": 0,
    "quarantined": 0
  },
  "errors": [],
  "created_at": "2026-04-29T15:48:12.551103Z"
}
```

**Error Responses:**
- `400 Bad Request` - Invalid UUID format
- `403 Forbidden` - Ingest belongs to different provider
- `404 Not Found` - Ingest record not found

---

## Patient APIs (Stubs)

All patient endpoints return `501 Not Implemented` (stub phases):

```
POST /api/v1/auth/abha/otp
POST /api/v1/auth/abha/verify
GET /api/v1/me
GET /api/v1/me/timeline
GET /api/v1/me/conflicts
GET /api/v1/me/audit
GET /api/v1/me/consents
POST /api/v1/me/consents
DELETE /api/v1/me/consents/{id}
POST /api/v1/me/upload
```

**Timeline:** Phases 2-5 (future implementation)

---

## Data Schemas

### EncounterContext
```json
{
  "chief_complaint": "string (optional)",
  "nl_query": "string (optional)",
  "encounter_type": "routine | urgent | emergency (default: routine)"
}
```

### Fact (Citation)
```json
{
  "fact": "string - Human-readable statement",
  "source": {
    "table": "conditions | medications | observations | allergies",
    "id": "UUID - Record ID",
    "provider": "string - Provider name",
    "date": "ISO 8601 datetime"
  },
  "date": "ISO 8601 datetime",
  "confidence": "float 0-1"
}
```

### CohortPanel
```json
{
  "label": "Patients like [Name]",
  "n_total": 47,
  "privacy": {
    "k_anonymity": 10,
    "epsilon": 1.0
  },
  "buckets": [
    {
      "regimen": "Aspirin + Clopidogrel",
      "n": 23,
      "outcome_metric": "HbA1c",
      "outcome_value": -1.4,
      "outcome_ci": 0.2,
      "outcome_unit": "%",
      "outcome_timeframe": "3mo"
    }
  ]
}
```

### SourceRecord (Ingestion)
```json
{
  "provider_id": "string",
  "record_type": "string (e.g., Condition, MedicationRequest)",
  "payload": "object - FHIR resource or custom data",
  "format": "fhir | hl7 | pdf | manual",
  "received_at": "ISO 8601 datetime"
}
```

### IngestCounts
```json
{
  "inserted": 0,
  "merged": 0,
  "conflicts": 0,
  "quarantined": 0
}
```

---

## Error Handling

### HTTP Status Codes

| Code | Meaning | Example |
|------|---------|---------|
| 200 | Success | Briefing generated |
| 400 | Bad Request | Invalid UUID format |
| 401 | Unauthorized | Missing or invalid API key |
| 403 | Forbidden | Consent denied for patient |
| 404 | Not Found | Patient/record not found |
| 422 | Unprocessable Entity | Invalid payload structure |
| 500 | Internal Error | Database connection failure |
| 501 | Not Implemented | Patient API (Phase 2-6) |

### Error Response Format
```json
{
  "detail": "string - Human-readable error message"
}
```

**Common Error Details:**
- `"forbidden"` - Consent/scope violation
- `"consent_denied"` - Patient has revoked access
- `"auth_required"` - Missing credentials
- `"internal_server_error"` - Backend failure
- `"unsupported_source_table"` - Invalid table name
- `"invalid_source_id"` - Malformed UUID

---

## System Architecture

### Request Flow

```
Provider/Clinician Request
        ↓
    [Auth Middleware] - Verify JWT or API key
        ↓
    [Request ID Middleware] - Generate trace ID
        ↓
    [Rate Limit Middleware] - Check quotas
        ↓
    [Consent Middleware] - Check ABDM consent (if applicable)
        ↓
    [Route Handler] - Process request
        ↓
    [Response] - Return result (with latency headers)
```

### Backend Service Ports

| Service | Port | Purpose |
|---------|------|---------|
| Smriti API | 8000 | Main backend |
| Mock ABHA | 8001 | ABHA auth mock |
| HAPI FHIR | 8082 | FHIR server |
| Ollama | 11434 | Local embeddings (optional) |
| Supabase | 6543 | PostgreSQL pooler |

### External Dependencies

| Service | Config | Purpose |
|---------|--------|---------|
| Supabase (Postgres) | `SUPABASE_URL` | Clinical data store |
| Groq LLM | `GROQ_API_KEY` | LLM processing |
| Ollama | `OLLAMA_BASE_URL` | Embeddings (optional) |

### Database Tables

- `patients` - Patient demographics
- `conditions` - Medical conditions
- `medications` - Medication records
- `observations` - Lab/vital observations
- `allergies` - Allergy records
- `ingest_log` - Provider data ingestion audit trail
- `conflicts` - Data reconciliation conflicts
- `audit_log` - Access audit trail (future phase)

---

## Sample Usage

### 1. Ingest Patient Data (Provider)
```bash
curl -X POST http://localhost:8000/api/v1/provider/bulk-ingest \
  -H "X-Provider-API-Key: sk_apollo_demo" \
  -H "Content-Type: application/json" \
  -d @scripts/mock_hospital_loader.py
```

### 2. Get Patient Briefing (Clinician)
```bash
curl -X POST http://localhost:8000/api/v1/clinician/briefing \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "abha_id": "12-3456-7890-1234",
    "encounter": {
      "chief_complaint": "Follow-up for cardiac history",
      "encounter_type": "routine"
    }
  }'
```

### 3. Query Patient Data (Clinician)
```bash
curl -X POST http://localhost:8000/api/v1/clinician/query \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "abha_id": "12-3456-7890-1234",
    "query": "What medications is the patient currently taking?"
  }'
```

### 4. Get Source Citation (Clinician)
```bash
curl -X GET "http://localhost:8000/api/v1/clinician/source/medications/550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer <JWT_TOKEN>"
```

---

## Connecting Points Summary

### Inbound Connections
1. **Clinician UI (Next.js)** → Smriti API (clinician endpoints)
2. **Provider EHR/HMS** → Smriti API (provider ingest endpoints)
3. **Patient App** → Smriti API (patient endpoints, TBD)

### Outbound Connections
1. **Smriti API** → Supabase PostgreSQL (data persistence)
2. **Smriti API** → Groq LLM (briefing synthesis)
3. **Smriti API** → HAPI FHIR (FHIR validation, future)
4. **Smriti API** → Mock ABHA (consent/auth simulation)
5. **Smriti API** → Ollama (embeddings, optional)

### Data Flow
```
EHR/Provider → bulk-ingest → Writer Pipeline → DB
                                    ↓
                            [Reconciliation]
                                    ↓
                              Clinical DB
                                    ↓
Reader Pipeline ← briefing endpoint ← Clinician UI
     ↓                                    ↓
  LLM, Cohort, Risk                   Audit Log
     ↓
   Response
```
