-- 要求 PostgreSQL 13+、pgvector >= 0.8.0；现有记录的来源绑定仍标记为不可验证。
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS embedding_schemes (
 identity text PRIMARY KEY, metadata jsonb NOT NULL,
 dimensions integer NOT NULL CHECK(dimensions BETWEEN 1 AND 16000)
);
CREATE TABLE IF NOT EXISTS index_registry (
 identity text PRIMARY KEY REFERENCES embedding_schemes(identity),
 is_active boolean NOT NULL DEFAULT false, validated_at timestamptz,
 expected_item_count bigint CHECK(expected_item_count >= 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_index_scheme ON index_registry(is_active) WHERE is_active;
CREATE TABLE IF NOT EXISTS indexed_chunks (
 document_id text NOT NULL, document_version text NOT NULL, chunk_id text NOT NULL,
 scheme_identity text NOT NULL REFERENCES embedding_schemes(identity),
 body text NOT NULL, metadata jsonb NOT NULL, vector vector,
 status text NOT NULL DEFAULT 'stored' CHECK(status IN ('pending','embedded','stored','failed','deleted')),
 error_code text, error_reason text, retry_count integer NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
 updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE indexed_chunks ADD COLUMN IF NOT EXISTS row_id bigserial;
ALTER TABLE indexed_chunks ADD COLUMN IF NOT EXISTS chunk_version text;
ALTER TABLE indexed_chunks ADD COLUMN IF NOT EXISTS content_fingerprint text;
ALTER TABLE indexed_chunks ADD COLUMN IF NOT EXISTS fingerprint_algorithm text;
ALTER TABLE indexed_chunks ADD COLUMN IF NOT EXISTS generated_at timestamptz;
ALTER TABLE indexed_chunks ADD COLUMN IF NOT EXISTS provenance_state text NOT NULL DEFAULT 'legacy/unverifiable';
ALTER TABLE indexed_chunks ALTER COLUMN vector DROP NOT NULL;
ALTER TABLE indexed_chunks DROP CONSTRAINT IF EXISTS indexed_chunks_pkey;
CREATE UNIQUE INDEX IF NOT EXISTS indexed_chunks_row_key ON indexed_chunks(row_id);
CREATE UNIQUE INDEX IF NOT EXISTS indexed_chunks_logical_key ON indexed_chunks
 (document_id,document_version,chunk_id,chunk_version,scheme_identity) WHERE chunk_version IS NOT NULL;
CREATE INDEX IF NOT EXISTS indexed_chunks_scheme_idx ON indexed_chunks(scheme_identity) WHERE status='stored';
CREATE TABLE IF NOT EXISTS physical_index_configs (
 scheme_identity text NOT NULL REFERENCES embedding_schemes(identity), identity text NOT NULL,
 algorithm text NOT NULL CHECK(algorithm IN ('exact','hnsw','ivfflat')),
 build_parameters jsonb NOT NULL, query_parameters jsonb NOT NULL,
 resource_table text NOT NULL UNIQUE, index_name text,
 is_active boolean NOT NULL DEFAULT false, validated_at timestamptz,
 PRIMARY KEY(scheme_identity,identity)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_serving_config ON physical_index_configs(is_active) WHERE is_active;
CREATE TABLE IF NOT EXISTS index_activation_audit (
 audit_id bigserial PRIMARY KEY, scheme_identity text NOT NULL, config_identity text NOT NULL,
 previous_scheme text, previous_config text, actor text NOT NULL CHECK(actor <> ''),
 reason text NOT NULL CHECK(reason <> ''), action text NOT NULL CHECK(action IN ('activate','rollback')),
 validation_report jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS embedding_request_attempts (
 attempt_id text PRIMARY KEY, document_id text NOT NULL, document_version text NOT NULL,
 chunk_id text NOT NULL, chunk_version text NOT NULL, scheme_identity text NOT NULL,
 content_fingerprint text NOT NULL CHECK(content_fingerprint ~ '^[0-9a-f]{64}$'),
 fingerprint_algorithm text NOT NULL DEFAULT 'sha256' CHECK(fingerprint_algorithm='sha256'),
 idempotency_key text NOT NULL UNIQUE CHECK(idempotency_key <> ''), request_id text,
 status text NOT NULL CHECK(status IN ('pending','unknown','succeeded','failed','retryable')),
 request_payload jsonb,
 error text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(document_id,document_version,chunk_id,chunk_version,scheme_identity)
);
ALTER TABLE embedding_request_attempts ADD COLUMN IF NOT EXISTS result_payload jsonb;
ALTER TABLE embedding_request_attempts ADD COLUMN IF NOT EXISTS request_payload jsonb;
ALTER TABLE embedding_request_attempts DROP CONSTRAINT IF EXISTS embedding_request_attempts_status_check;
ALTER TABLE embedding_request_attempts ADD CONSTRAINT embedding_request_attempts_status_check
 CHECK(status IN ('pending','unknown','succeeded','failed','retryable'));
CREATE OR REPLACE FUNCTION check_indexed_chunk_dimensions() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected integer; registered_metadata jsonb;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF OLD.status='deleted' AND NEW IS DISTINCT FROM OLD THEN
   RAISE EXCEPTION 'deleted index identity is immutable';
  END IF;
  IF (NEW.document_id,NEW.document_version,NEW.chunk_id,NEW.chunk_version,NEW.scheme_identity,
      NEW.content_fingerprint,NEW.fingerprint_algorithm,NEW.body,NEW.vector,NEW.generated_at,NEW.provenance_state)
     IS DISTINCT FROM
     (OLD.document_id,OLD.document_version,OLD.chunk_id,OLD.chunk_version,OLD.scheme_identity,
      OLD.content_fingerprint,OLD.fingerprint_algorithm,OLD.body,OLD.vector,OLD.generated_at,OLD.provenance_state) THEN
   RAISE EXCEPTION 'index identity and vector provenance are immutable';
  END IF;
 END IF;
 IF TG_OP='INSERT' AND (NEW.provenance_state <> 'verified' OR NEW.chunk_version IS NULL OR NEW.chunk_version=''
     OR NEW.fingerprint_algorithm IS DISTINCT FROM 'sha256' OR NEW.content_fingerprint IS NULL
     OR NEW.content_fingerprint !~ '^[0-9a-f]{64}$' OR NEW.generated_at IS NULL) THEN
  RAISE EXCEPTION 'new index rows require verified provenance';
 END IF;
 SELECT dimensions,metadata INTO expected,registered_metadata FROM embedding_schemes WHERE identity=NEW.scheme_identity FOR SHARE;
 IF TG_OP='INSERT' AND (jsonb_typeof(registered_metadata->'document_role') IS DISTINCT FROM 'object'
     OR jsonb_typeof(registered_metadata->'query_role') IS DISTINCT FROM 'object') THEN
  RAISE EXCEPTION 'legacy/unverifiable schemes cannot accept new index rows';
 END IF;
 IF NEW.vector IS NOT NULL AND (expected IS NULL OR vector_dims(NEW.vector) <> expected OR vector_norm(NEW.vector)=0) THEN
  RAISE EXCEPTION 'vector dimension or cosine norm does not match index scheme';
 END IF;
 IF NEW.status='stored' AND NEW.vector IS NULL THEN
  RAISE EXCEPTION 'stored index item requires a vector';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS indexed_chunk_dimensions ON indexed_chunks;
CREATE TRIGGER indexed_chunk_dimensions BEFORE INSERT OR UPDATE ON indexed_chunks
 FOR EACH ROW EXECUTE FUNCTION check_indexed_chunk_dimensions();
CREATE OR REPLACE FUNCTION check_embedding_scheme_dimensions() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.metadata IS DISTINCT FROM OLD.metadata OR NEW.dimensions IS DISTINCT FROM OLD.dimensions THEN
  RAISE EXCEPTION 'registered embedding scheme is immutable';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS embedding_scheme_dimensions ON embedding_schemes;
CREATE TRIGGER embedding_scheme_dimensions BEFORE UPDATE ON embedding_schemes
 FOR EACH ROW EXECUTE FUNCTION check_embedding_scheme_dimensions();
CREATE OR REPLACE FUNCTION sync_physical_vector_resources() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE resource record;
BEGIN
 FOR resource IN SELECT resource_table FROM physical_index_configs WHERE scheme_identity=NEW.scheme_identity LOOP
  IF NEW.status='stored' AND NEW.provenance_state='verified' THEN
   EXECUTE format('INSERT INTO %I(row_id,scheme_identity,vector,document_id,document_version,chunk_id,chunk_version,metadata) VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT(row_id) DO UPDATE SET metadata=EXCLUDED.metadata',resource.resource_table)
    USING NEW.row_id,NEW.scheme_identity,NEW.vector,NEW.document_id,NEW.document_version,NEW.chunk_id,NEW.chunk_version,NEW.metadata;
  ELSE
   EXECUTE format('DELETE FROM %I WHERE row_id=$1',resource.resource_table) USING NEW.row_id;
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS indexed_chunks_resource_sync ON indexed_chunks;
CREATE TRIGGER indexed_chunks_resource_sync AFTER INSERT OR UPDATE ON indexed_chunks
 FOR EACH ROW EXECUTE FUNCTION sync_physical_vector_resources();
