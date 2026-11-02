-- FAQ authority is immutable and shares publication ownership with documents.
CREATE TABLE IF NOT EXISTS {schema}.faq_items (
    evidence_key text PRIMARY KEY,
    knowledge_base_id text NOT NULL,
    item_id text NOT NULL,
    version text NOT NULL,
    standard_question text NOT NULL,
    similar_questions jsonb NOT NULL,
    answer text NOT NULL,
    conditions jsonb NOT NULL,
    source jsonb NOT NULL,
    UNIQUE (knowledge_base_id, item_id, version),
    UNIQUE (knowledge_base_id, evidence_key)
);
CREATE TABLE IF NOT EXISTS {schema}.faq_questions (
    question_key text PRIMARY KEY,
    knowledge_base_id text NOT NULL,
    evidence_key text NOT NULL,
    question_ordinal integer NOT NULL CHECK (question_ordinal >= 0),
    question text NOT NULL,
    UNIQUE (evidence_key, question_ordinal),
    FOREIGN KEY (knowledge_base_id, evidence_key)
        REFERENCES {schema}.faq_items (knowledge_base_id, evidence_key)
);
CREATE TABLE IF NOT EXISTS {schema}.faq_snapshot_members (
    knowledge_base_id text NOT NULL,
    snapshot_id text NOT NULL,
    evidence_key text NOT NULL,
    PRIMARY KEY (knowledge_base_id, snapshot_id, evidence_key),
    FOREIGN KEY (knowledge_base_id, snapshot_id)
        REFERENCES {schema}.snapshots (knowledge_base_id, snapshot_id),
    FOREIGN KEY (knowledge_base_id, evidence_key)
        REFERENCES {schema}.faq_items (knowledge_base_id, evidence_key)
);
CREATE TABLE IF NOT EXISTS {schema}.faq_vector_snapshots (
    knowledge_base_id text NOT NULL,
    snapshot_id text NOT NULL,
    binding jsonb NOT NULL,
    resource_table text NOT NULL,
    PRIMARY KEY (knowledge_base_id, snapshot_id),
    FOREIGN KEY (knowledge_base_id, snapshot_id)
        REFERENCES {schema}.snapshots (knowledge_base_id, snapshot_id)
);
-- Dimension is pinned in the manifest; actual per-snapshot vector collections
-- use typed vector(n) columns, built by the FAQ store with module3 embeddings.
