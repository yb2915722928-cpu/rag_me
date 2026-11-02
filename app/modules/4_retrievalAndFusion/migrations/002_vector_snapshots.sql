CREATE TABLE IF NOT EXISTS {schema}.vector_snapshots (
    knowledge_base_id text NOT NULL,
    snapshot_id text NOT NULL,
    binding jsonb NOT NULL,
    resource_table text NOT NULL UNIQUE,
    PRIMARY KEY (knowledge_base_id, snapshot_id),
    FOREIGN KEY (knowledge_base_id, snapshot_id)
        REFERENCES {schema}.snapshots(knowledge_base_id, snapshot_id)
);
