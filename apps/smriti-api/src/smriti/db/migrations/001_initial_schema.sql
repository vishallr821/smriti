-- ============================================================
-- Smriti Schema v1.0
-- ============================================================

-- Required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- Identity
-- ============================================================

CREATE TABLE patients (
  abha_id          TEXT PRIMARY KEY,                -- 14-digit ABHA, the only stored identifier
  aadhaar_hash     BYTEA,                           -- SHA-256(aadhaar || system_salt), nullable, NEVER raw
  display_name     TEXT NOT NULL,
  dob              DATE,
  sex              TEXT CHECK (sex IN ('M','F','O')),
  preferred_lang   TEXT DEFAULT 'en',
  registered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_active_at   TIMESTAMPTZ
);

CREATE INDEX patients_aadhaar_hash_idx ON patients USING hash (aadhaar_hash);

-- ============================================================
-- Provider registry (which hospitals are connected)
-- ============================================================

CREATE TABLE providers (
  provider_id      TEXT PRIMARY KEY,                -- 'sentient_hms', 'mock_apollo', etc.
  display_name     TEXT NOT NULL,
  hfr_id           TEXT,                            -- ABDM Health Facility Registry ID
  api_endpoint     TEXT,
  active           BOOLEAN DEFAULT true
);

-- ============================================================
-- Clinical data (all carry provenance + ingestion metadata)
-- ============================================================

CREATE TABLE conditions (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  abha_id          TEXT NOT NULL REFERENCES patients(abha_id),
  source_provider  TEXT NOT NULL REFERENCES providers(provider_id),
  source_record_id TEXT NOT NULL,
  snomed_code      TEXT,
  icd10_code       TEXT,
  display_name     TEXT NOT NULL,
  status           TEXT CHECK (status IN ('active','resolved','inactive','refuted')),
  onset_date       DATE,
  resolved_date    DATE,
  episode_id       UUID,
  ingested_at      TIMESTAMPTZ DEFAULT now(),
  confidence       NUMERIC DEFAULT 1.0,
  raw_value        TEXT,                            -- pre-normalization
  UNIQUE (source_provider, source_record_id)
);
CREATE INDEX conditions_patient_idx ON conditions(abha_id);
CREATE INDEX conditions_snomed_idx ON conditions(snomed_code);

CREATE TABLE medications (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  abha_id          TEXT NOT NULL REFERENCES patients(abha_id),
  source_provider  TEXT NOT NULL REFERENCES providers(provider_id),
  source_record_id TEXT NOT NULL,
  rxnorm_code      TEXT,
  display_name     TEXT NOT NULL,
  dose             TEXT,
  frequency        TEXT,
  route            TEXT,
  start_date       DATE,
  end_date         DATE,
  episode_id       UUID,
  ingested_at      TIMESTAMPTZ DEFAULT now(),
  raw_value        TEXT,
  UNIQUE (source_provider, source_record_id)
);
CREATE INDEX medications_patient_idx ON medications(abha_id);
CREATE INDEX medications_rxnorm_idx ON medications(rxnorm_code);
CREATE INDEX medications_dates_idx ON medications(start_date, end_date);

CREATE TABLE observations (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  abha_id          TEXT NOT NULL REFERENCES patients(abha_id),
  source_provider  TEXT NOT NULL REFERENCES providers(provider_id),
  source_record_id TEXT NOT NULL,
  loinc_code       TEXT,
  display_name     TEXT NOT NULL,
  value_numeric    NUMERIC,
  value_text       TEXT,
  unit             TEXT,
  ref_low          NUMERIC,
  ref_high         NUMERIC,
  abnormal_flag    TEXT,
  observed_at      TIMESTAMPTZ NOT NULL,
  episode_id       UUID,
  ingested_at      TIMESTAMPTZ DEFAULT now(),
  UNIQUE (source_provider, source_record_id)
);
CREATE INDEX observations_patient_loinc_idx ON observations(abha_id, loinc_code, observed_at DESC);

CREATE TABLE allergies (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  abha_id          TEXT NOT NULL REFERENCES patients(abha_id),
  source_provider  TEXT NOT NULL REFERENCES providers(provider_id),
  source_record_id TEXT NOT NULL,
  substance_code   TEXT,
  substance_name   TEXT NOT NULL,
  reaction         TEXT,
  severity         TEXT,
  status           TEXT CHECK (status IN ('active','resolved','refuted','no_known_allergy')),
  onset_date       DATE,
  ingested_at      TIMESTAMPTZ DEFAULT now(),
  UNIQUE (source_provider, source_record_id)
);

-- ============================================================
-- Episodes
-- ============================================================

CREATE TABLE episodes (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  abha_id          TEXT NOT NULL REFERENCES patients(abha_id),
  primary_diagnosis_code TEXT,
  primary_diagnosis_name TEXT,
  start_date       DATE NOT NULL,
  end_date         DATE,
  source_providers TEXT[],
  summary          TEXT
);
CREATE INDEX episodes_patient_idx ON episodes(abha_id);

-- ============================================================
-- Conflicts (first-class clinical signal)
-- ============================================================

CREATE TABLE conflicts (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  abha_id          TEXT NOT NULL REFERENCES patients(abha_id),
  conflict_type    TEXT NOT NULL,        -- 'allergy_disagreement', 'med_disagreement', 'diagnosis_disagreement'
  severity         TEXT,
  source_a         JSONB NOT NULL,
  source_b         JSONB NOT NULL,
  detected_at      TIMESTAMPTZ DEFAULT now(),
  resolution       TEXT,                 -- null = unresolved
  resolved_at      TIMESTAMPTZ,
  resolved_by      TEXT
);
CREATE INDEX conflicts_patient_idx ON conflicts(abha_id) WHERE resolution IS NULL;

-- ============================================================
-- Consent
-- ============================================================

CREATE TYPE consent_scope AS ENUM ('conditions','medications','observations','allergies','mental_health','reproductive','genetic');

CREATE TABLE consents (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  abha_id          TEXT NOT NULL REFERENCES patients(abha_id),
  scope            consent_scope[] NOT NULL,
  grantee_class    TEXT NOT NULL,        -- 'any_md', 'emergency', specific HPR id
  granted_at       TIMESTAMPTZ DEFAULT now(),
  expires_at       TIMESTAMPTZ,
  revoked_at       TIMESTAMPTZ
);
CREATE INDEX consents_active_idx ON consents(abha_id) WHERE revoked_at IS NULL;

-- ============================================================
-- Audit log (hash-chained)
-- ============================================================

CREATE TABLE audit_log (
  id               BIGSERIAL PRIMARY KEY,
  abha_id          TEXT REFERENCES patients(abha_id),
  actor_id         TEXT,
  actor_role       TEXT,
  action           TEXT NOT NULL,        -- 'read.briefing', 'write.condition', 'consent.toggle', etc.
  scope            TEXT[],
  consent_id       UUID REFERENCES consents(id),
  payload_hash     TEXT NOT NULL,
  prev_hash        TEXT NOT NULL,
  this_hash        TEXT NOT NULL,
  created_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX audit_log_patient_idx ON audit_log(abha_id, created_at DESC);

-- ============================================================
-- RAG store: per-patient narrative chunks
-- ============================================================

CREATE TABLE record_chunks (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  abha_id          TEXT NOT NULL REFERENCES patients(abha_id),
  source_table     TEXT NOT NULL,        -- 'conditions', 'medications', etc.
  source_id        UUID NOT NULL,
  chunk_text       TEXT NOT NULL,
  chunk_vector     vector(384),
  created_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX record_chunks_vector_idx ON record_chunks USING ivfflat (chunk_vector vector_cosine_ops) WITH (lists = 100);
CREATE INDEX record_chunks_patient_idx ON record_chunks(abha_id);

-- ============================================================
-- Cohort store (synthetic, pre-seeded)
-- ============================================================

CREATE TABLE cohort_patients (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  age              INT NOT NULL,
  sex              TEXT NOT NULL,
  conditions       JSONB NOT NULL,       -- array of SNOMED codes
  treatments       JSONB NOT NULL,       -- array of {rxnorm, start_offset_days, dose}
  outcomes         JSONB NOT NULL,       -- {hba1c_3mo_change, bp_control, readmit_90d}
  profile_text     TEXT NOT NULL,
  profile_vector   vector(384) NOT NULL
);
CREATE INDEX cohort_vector_idx ON cohort_patients USING ivfflat (profile_vector vector_cosine_ops) WITH (lists = 50);

-- ============================================================
-- Terminology dictionaries (pre-loaded)
-- ============================================================

CREATE TABLE terminology_index (
  id               BIGSERIAL PRIMARY KEY,
  system           TEXT NOT NULL,        -- 'snomed', 'icd10', 'loinc', 'rxnorm'
  code             TEXT NOT NULL,
  display_name     TEXT NOT NULL,
  synonyms         TEXT[],
  embedding        vector(384) NOT NULL,
  UNIQUE (system, code)
);
CREATE INDEX terminology_vector_idx ON terminology_index USING ivfflat (embedding vector_cosine_ops) WITH (lists = 200);

-- ============================================================
-- Redaction key store (separate, stricter RLS)
-- ============================================================

CREATE TABLE redaction_keys (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  abha_id          TEXT NOT NULL REFERENCES patients(abha_id),
  placeholder      TEXT NOT NULL,
  real_value_enc   BYTEA NOT NULL,       -- encrypted with field-level key
  created_at       TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- LLM guard events
-- ============================================================

CREATE TABLE llm_guard_events (
  id               BIGSERIAL PRIMARY KEY,
  agent            TEXT NOT NULL,
  event_type       TEXT NOT NULL,        -- 'injection_detected', 'pii_leak_blocked', 'schema_violation'
  details          JSONB,
  abha_id          TEXT,
  created_at       TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- Quarantine (rejected ingestions)
-- ============================================================

CREATE TABLE quarantine (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  source_provider  TEXT,
  raw_payload      TEXT,
  reason           TEXT NOT NULL,
  detected_at      TIMESTAMPTZ DEFAULT now(),
  reviewed         BOOLEAN DEFAULT false
);

-- ============================================================
-- Row-Level Security
-- ============================================================

ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE conditions ENABLE ROW LEVEL SECURITY;
ALTER TABLE medications ENABLE ROW LEVEL SECURITY;
ALTER TABLE observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE allergies ENABLE ROW LEVEL SECURITY;
ALTER TABLE conflicts ENABLE ROW LEVEL SECURITY;
ALTER TABLE consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE record_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE redaction_keys ENABLE ROW LEVEL SECURITY;

-- Patient-side: a patient can only see their own rows
CREATE POLICY patient_self_read ON patients
  FOR SELECT USING (auth.uid()::text = abha_id);

CREATE POLICY conditions_patient_read ON conditions
  FOR SELECT USING (auth.uid()::text = abha_id);

-- (similar policies on other clinical tables)

-- Service-role bypass: the API gateway uses the service role key,
-- which bypasses RLS. All clinician-side access goes through the
-- gateway and is gated by C1 Consent Guard before any query runs.