CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE IF NOT EXISTS {schema}.content (
    evidence_key text PRIMARY KEY,
    knowledge_base_id text NOT NULL,
    document_id text NOT NULL,
    document_version text NOT NULL,
    chunk_id text NOT NULL,
    chunk_version text NOT NULL,
    body text NOT NULL,
    source jsonb NOT NULL,
    metadata jsonb NOT NULL,
    parent_key text,
    UNIQUE (knowledge_base_id, document_id, document_version, chunk_id, chunk_version),
    CHECK (source <> '{{}}'::jsonb)
);
CREATE INDEX IF NOT EXISTS content_knowledge_base ON {schema}.content (knowledge_base_id);

CREATE TABLE IF NOT EXISTS {schema}.snapshots (
    knowledge_base_id text NOT NULL,
    snapshot_id text NOT NULL,
    manifest jsonb NOT NULL,
    published_at timestamptz,
    PRIMARY KEY (knowledge_base_id, snapshot_id)
);

CREATE TABLE IF NOT EXISTS {schema}.snapshot_members (
    knowledge_base_id text NOT NULL,
    snapshot_id text NOT NULL,
    evidence_key text NOT NULL REFERENCES {schema}.content(evidence_key),
    PRIMARY KEY (knowledge_base_id, snapshot_id, evidence_key),
    FOREIGN KEY (knowledge_base_id, snapshot_id)
        REFERENCES {schema}.snapshots(knowledge_base_id, snapshot_id)
);

CREATE TABLE IF NOT EXISTS {schema}.publications (
    knowledge_base_id text PRIMARY KEY,
    snapshot_id text NOT NULL,
    FOREIGN KEY (knowledge_base_id, snapshot_id)
        REFERENCES {schema}.snapshots(knowledge_base_id, snapshot_id)
);
