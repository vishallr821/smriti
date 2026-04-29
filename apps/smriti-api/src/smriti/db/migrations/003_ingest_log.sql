CREATE TABLE ingest_log (
  ingest_id  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  provider_id TEXT       NOT NULL REFERENCES providers(provider_id),
  abha_id    TEXT        REFERENCES patients(abha_id),
  status     TEXT        NOT NULL CHECK (status IN ('success', 'partial', 'failed', 'quarantined')),
  counts     JSONB,
  errors     JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ingest_log_provider_idx ON ingest_log(provider_id);
CREATE INDEX ingest_log_abha_idx     ON ingest_log(abha_id);
