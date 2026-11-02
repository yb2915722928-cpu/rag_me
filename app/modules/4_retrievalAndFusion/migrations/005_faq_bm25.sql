-- FAQ question corpus registry. Physical indexes are built and verified by prepare.
-- Requires the fixed pg_search release and immutability function from migration 003.
CREATE TABLE IF NOT EXISTS {schema}.faq_bm25_resources (
    knowledge_base_id text NOT NULL,
    snapshot_id text NOT NULL,
    table_name text NOT NULL UNIQUE,
    index_name text NOT NULL UNIQUE,
    analyzer_fingerprint text NOT NULL,
    analyzer_definition jsonb NOT NULL,
    index_definition text NOT NULL,
    item_keys jsonb NOT NULL CHECK (jsonb_typeof(item_keys) = 'array'),
    PRIMARY KEY (knowledge_base_id, snapshot_id),
    FOREIGN KEY (knowledge_base_id, snapshot_id)
        REFERENCES {schema}.snapshots(knowledge_base_id, snapshot_id)
);
