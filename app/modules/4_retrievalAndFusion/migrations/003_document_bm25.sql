-- Source-derived SQL for PostgreSQL 17.11 / vector 0.8.6 / pg_search 0.26.4.
-- Runtime also verifies versions: IF NOT EXISTS alone never upgrades extensions.
CREATE EXTENSION IF NOT EXISTS vector VERSION '0.8.6';
CREATE EXTENSION IF NOT EXISTS pg_search VERSION '0.26.4';

CREATE TABLE IF NOT EXISTS {schema}.bm25_resources (
    knowledge_base_id text NOT NULL,
    snapshot_id text NOT NULL,
    table_name text NOT NULL UNIQUE,
    index_name text NOT NULL UNIQUE,
    analyzer_fingerprint text NOT NULL,
    analyzer_definition jsonb NOT NULL,
    index_definition text NOT NULL,
    evidence_keys jsonb NOT NULL CHECK (jsonb_typeof(evidence_keys) = 'array'),
    PRIMARY KEY (knowledge_base_id, snapshot_id),
    FOREIGN KEY (knowledge_base_id, snapshot_id)
        REFERENCES {schema}.snapshots(knowledge_base_id, snapshot_id)
);

CREATE OR REPLACE FUNCTION {schema}.reject_bm25_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'BM25 snapshot corpus is immutable; prepare a new snapshot';
END;
$$;
