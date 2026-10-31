"""Optional real PostgreSQL tests; require TEST_DATABASE_URL and pgvector >= 0.8.

Each test uses an isolated schema. No database execution is claimed when skipped.
"""
from dataclasses import asdict, replace
import json
import os
import unittest
import uuid

from app.models.embedding import ChunkRecord, EmbeddingContractError, EmbeddingMetadata, EmbeddingRoleConfig, IndexSchemeVersion, LogicalIndexIdentity, content_fingerprint
from app.models.db.pgvector import DuplicateRequestAttempt, FingerprintConflict, LegacyChunkRecord, PhysicalIndexConfig, PostgresVectorStore, _resource_names


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "set TEST_DATABASE_URL for real PostgreSQL/pgvector tests")
class PgVectorIndexingTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.psycopg = psycopg
        self.dsn = os.environ["TEST_DATABASE_URL"]
        self.schema = "pgvector_test_" + uuid.uuid4().hex
        with psycopg.connect(self.dsn) as connection:
            connection.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            connection.execute('CREATE SCHEMA "' + self.schema + '"')
        self.addCleanup(self.cleanup_schema)
        self.store = PostgresVectorStore(self.dsn, connect=self.connect, metadata_fields={"category": str, "page": int})
        self.store.migrate()
        self.scheme = IndexSchemeVersion(EmbeddingMetadata("test", "model", "r1", 3, chunking_policy="test:v1",
            document_role=EmbeddingRoleConfig("document", "encoder", "doc: "), query_role=EmbeddingRoleConfig("query", "encoder", "q: ")))
        self.chunk = ChunkRecord("a", "doc", "v1", "alpha", {"category": "manual", "page": 1}, "c1")
        self.identity = LogicalIndexIdentity("doc", "v1", "a", self.scheme.identity, "c1")

    def connect(self, dsn):
        return self.psycopg.connect(dsn, options="-c search_path=" + self.schema + ",public")

    def cleanup_schema(self):
        with self.psycopg.connect(self.dsn) as connection:
            connection.execute('DROP SCHEMA "' + self.schema + '" CASCADE')

    def insert_rows(self):
        self.store.upsert(self.scheme, self.chunk, (1, 0, 0))
        self.store.upsert(self.scheme, replace(self.chunk, chunk_id="b", text="beta", metadata={"category": "other", "page": 2}), (0, 1, 0))

    def test_idempotence_conflict_and_deleted_tombstone(self):
        self.store.upsert(self.scheme, self.chunk, (1, 0, 0))
        first = self.store.search(self.scheme, (1, 0, 0))[0]
        self.store.upsert(self.scheme, self.chunk, (0, 1, 0))
        after = self.store.search(self.scheme, (1, 0, 0))[0]
        self.assertAlmostEqual(after.score, 1)
        self.assertEqual(first.generated_at, after.generated_at)
        self.assertEqual(after.chunk.chunk_version, "c1")
        self.assertEqual(after.content_fingerprint, content_fingerprint("alpha", self.scheme.metadata, "document")[1])
        with self.assertRaises(FingerprintConflict):
            self.store.upsert(self.scheme, replace(self.chunk, text="changed"), (1, 0, 0))
        self.assertEqual(self.store.search(self.scheme, (1, 0, 0))[0].chunk.text, "alpha")
        self.store.delete(self.identity)
        with self.assertRaisesRegex(ValueError, "deleted"):
            self.store.upsert(self.scheme, self.chunk, (1, 0, 0))
        self.assertEqual(self.store.search(self.scheme, (1, 0, 0)), [])

    def test_multiple_physical_resources_and_exact_filters_threshold(self):
        self.insert_rows()
        configs = [PhysicalIndexConfig(), PhysicalIndexConfig("hnsw", {"m": 4, "ef_construction": 16}, {"ef_search": 20}),
                   PhysicalIndexConfig("ivfflat", {"lists": 1}, {"probes": 1})]
        for config in configs:
            with self.subTest(config=config.algorithm):
                self.store.register_physical_config(self.scheme, config)
                hits = self.store.search(self.scheme, (1, 0, 0), config=config, limit=2, candidate_limit=2,
                    filters={"document_id": "doc", "document_version": "v1", "metadata.category": "manual"}, score_threshold=0.9)
                self.assertEqual([hit.chunk.chunk_id for hit in hits], ["a"])
        self.assertEqual(len({_resource_names(self.scheme, config)[0] for config in configs}), 3)
        self.store.delete(self.identity)
        for config in configs:
            self.assertEqual([hit.chunk.chunk_id for hit in self.store.search(self.scheme, (1, 0, 0), config=config)], ["b"])

    def test_metadata_only_update_refreshes_all_physical_filters_and_retains_provenance(self):
        self.insert_rows()
        before = self.store.search(self.scheme, (1, 0, 0))[0]
        configs = [PhysicalIndexConfig(), PhysicalIndexConfig("hnsw", {"m": 4, "ef_construction": 16}),
                   PhysicalIndexConfig("ivfflat", {"lists": 1})]
        for config in configs:
            self.store.register_physical_config(self.scheme, config)
        changed = replace(self.chunk, metadata={"category": "updated", "page": 3})
        self.store.upsert(self.scheme, changed, (0, 1, 0))
        for config in configs:
            with self.subTest(config=config.algorithm):
                self.assertEqual(self.store.search(self.scheme, (1, 0, 0), config=config,
                    filters={"metadata.category": "manual"}), [])
                hits = self.store.search(self.scheme, (1, 0, 0), config=config,
                    filters={"metadata.category": "updated"})
                self.assertEqual(hits[0].chunk, changed)
                self.assertAlmostEqual(hits[0].score, 1)
                self.assertEqual(hits[0].generated_at, before.generated_at)
                self.assertEqual(hits[0].content_fingerprint, before.content_fingerprint)
                resource, _ = _resource_names(self.scheme, config)
                with self.connect(self.dsn) as connection:
                    self.assertEqual(connection.execute('SELECT metadata FROM "' + resource + '" WHERE chunk_id=%s', (changed.chunk_id,)).fetchone()[0], changed.metadata)

    def test_mixed_dimensions_have_distinct_typed_partial_indexes(self):
        other = IndexSchemeVersion(replace(self.scheme.metadata, dimensions=4))
        self.store.upsert(self.scheme, self.chunk, (1, 0, 0))
        self.store.upsert(other, self.chunk, (1, 0, 0, 0))
        config = PhysicalIndexConfig("hnsw", {"m": 4, "ef_construction": 16})
        for target, vector in ((self.scheme, (1, 0, 0)), (other, (1, 0, 0, 0))):
            self.store.register_physical_config(target, config)
            self.assertAlmostEqual(self.store.search(target, vector, config=config)[0].score, 1)
            _, index = _resource_names(target, config)
            with self.connect(self.dsn) as connection:
                definition = connection.execute("SELECT pg_get_indexdef(to_regclass(%s))", (index,)).fetchone()[0]
            self.assertIn("vector(" + str(target.metadata.dimensions) + ")", definition)
            self.assertIn("vector_cosine_ops", definition)
            self.assertIn(target.identity, definition)

    def test_activation_rollback_revalidates_and_audits(self):
        self.insert_rows()
        expected = [("doc", "v1", "a", "c1"), ("doc", "v1", "b", "c1")]
        exact = PhysicalIndexConfig()
        hnsw = PhysicalIndexConfig("hnsw", {"m": 4, "ef_construction": 16})
        arguments = dict(expected_count=2, expected_keys=expected, representative_key=expected[0], representative_vector=(1, 0, 0), actor="test", reason="validated deployment")
        self.store.validate_and_activate(self.scheme, config=exact, **arguments)
        self.store.validate_and_activate(self.scheme, config=hnsw, **arguments)
        self.assertEqual(self.store.active_config(self.scheme), hnsw)
        self.store.rollback(self.scheme, config=exact, **arguments)
        self.assertEqual(self.store.active_config(self.scheme), exact)
        with self.connect(self.dsn) as connection:
            audit = connection.execute("SELECT action,actor,reason FROM index_activation_audit ORDER BY audit_id").fetchall()
        self.assertEqual([row[0] for row in audit], ["activate", "activate", "rollback"])
        resource, _ = _resource_names(self.scheme, hnsw)
        with self.connect(self.dsn) as connection:
            connection.execute('UPDATE "' + resource + '" SET metadata=\'{"category":"corrupt"}\'::jsonb')
        with self.assertRaisesRegex(ValueError, "validation failed"):
            self.store.rollback(self.scheme, config=hnsw, **arguments)
        self.assertEqual(self.store.active_config(self.scheme), exact)

    def test_unknown_restart_durable_payload_and_explicit_retry(self):
        digest = content_fingerprint("alpha", self.scheme.metadata, "document")[1]
        payload = {"idempotency_key": "batch", "request_id": "request1", "texts": ["alpha"], "keys": [self.identity.key]}
        attempt = self.store.reserve_batch_attempts([self.identity], [digest], request_payload=payload)[0]
        self.store.resolve_attempt(attempt.attempt_id, "unknown", error="timeout")
        restarted = PostgresVectorStore(self.dsn, connect=self.connect)
        restored = restarted.get_attempt_for_identity(self.identity)
        self.assertEqual(restored.request_payload, payload)
        self.assertIsNone(restarted.get_chunk(self.scheme, self.identity))
        with self.assertRaises(DuplicateRequestAttempt):
            restarted.reserve_attempt(self.identity, digest, idempotency_key="different")
        with self.assertRaises(ValueError):
            restarted.retry_attempt(attempt.attempt_id)
        restarted.resolve_attempt(attempt.attempt_id, "retryable", error="operator: provider confirms not accepted")
        retried = restarted.retry_attempt(attempt.attempt_id, request_payload=dict(payload, request_id="request2", idempotency_key="batch2"))
        self.assertEqual(retried.status, "pending")
        restarted.resolve_attempt(attempt.attempt_id, "succeeded", result_payload={"vector": [1, 0, 0]})
        self.assertEqual(restarted.get_attempt(attempt.attempt_id).result_payload["vector"], [1, 0, 0])
        restarted.upsert(self.scheme, self.chunk, (1, 0, 0))
        self.assertEqual(restarted.get_chunk(self.scheme, self.identity)[1], (1, 0, 0))

    def test_batch_reservation_conflict_rolls_back_every_new_item(self):
        other = replace(self.identity, chunk_id="b")
        self.store.reserve_attempt(other, "a" * 64, idempotency_key="existing")
        with self.assertRaises(DuplicateRequestAttempt):
            self.store.reserve_batch_attempts([self.identity, other], ["a" * 64, "a" * 64], request_payload={"idempotency_key": "batch"})
        self.assertIsNone(self.store.get_attempt_for_identity(self.identity))

    def test_schema_upgrade_leaves_old_rows_explicitly_unverifiable(self):
        # Recreate only the legacy canonical tables within this test's isolated schema.
        with self.connect(self.dsn) as connection:
            connection.execute("DROP TABLE indexed_chunks CASCADE")
            connection.execute("CREATE TABLE indexed_chunks(document_id text NOT NULL,document_version text NOT NULL,chunk_id text NOT NULL,"
                "scheme_identity text REFERENCES embedding_schemes(identity),body text NOT NULL,metadata jsonb NOT NULL,vector vector NOT NULL,"
                "status text NOT NULL DEFAULT 'stored',error_code text,error_reason text,retry_count int DEFAULT 0,updated_at timestamptz DEFAULT now(),"
                "PRIMARY KEY(document_id,document_version,chunk_id,scheme_identity))")
            old_metadata = asdict(replace(self.scheme.metadata, document_role=None, query_role=None))
            connection.execute("INSERT INTO embedding_schemes VALUES (%s,%s::jsonb,3)", ("old-format:scheme", json.dumps(old_metadata)))
            connection.execute("INSERT INTO indexed_chunks(document_id,document_version,chunk_id,scheme_identity,body,metadata,vector) "
                "VALUES ('doc','v1','a','old-format:scheme','alpha','{}','[1,0,0]')")
        self.store.migrate()
        hit = self.store.search_legacy("old-format:scheme", (1, 0, 0))[0]
        self.assertIsInstance(hit.chunk, LegacyChunkRecord)
        self.assertIsNone(hit.chunk.chunk_version)
        self.assertIsNone(hit.content_fingerprint)
        self.assertIsNone(hit.generated_at)
        self.assertEqual(hit.scheme_identity, "old-format:scheme")

    def test_sql_trigger_rejects_unverified_insert_and_provenance_mutation(self):
        self.store.upsert(self.scheme, self.chunk, (1, 0, 0))
        with self.assertRaises(self.psycopg.Error):
            with self.connect(self.dsn) as connection:
                connection.execute("UPDATE indexed_chunks SET content_fingerprint=%s", ("a" * 64,))
        with self.assertRaises(self.psycopg.Error):
            with self.connect(self.dsn) as connection:
                connection.execute("INSERT INTO indexed_chunks(document_id,document_version,chunk_id,scheme_identity,body,metadata,vector) "
                    "VALUES ('doc','v1','legacy',%s,'old','{}','[1,0,0]')", (self.scheme.identity,))

    def test_dimension_mismatch_rejected_before_write(self):
        with self.assertRaises(EmbeddingContractError):
            self.store.upsert(self.scheme, self.chunk, (1, 0))

    def test_scheme_deletion_drops_physical_resources_but_keeps_tombstones_attempts_and_audit(self):
        self.insert_rows()
        digest = content_fingerprint(self.chunk.text, self.scheme.metadata, "document")[1]
        attempt = self.store.reserve_attempt(self.identity, digest, idempotency_key="retained-attempt")
        self.store.resolve_attempt(attempt.attempt_id, "retryable", error="provider confirmed not accepted")
        configs = [PhysicalIndexConfig(), PhysicalIndexConfig("hnsw", {"m": 4, "ef_construction": 16}),
                   PhysicalIndexConfig("ivfflat", {"lists": 1})]
        for config in configs:
            self.store.register_physical_config(self.scheme, config)
        activation = dict(expected_count=2, expected_keys=[("doc", "v1", "a", "c1"), ("doc", "v1", "b", "c1")],
            representative_vector=(1, 0, 0), actor="test", reason="deletion regression")
        self.store.validate_and_activate(self.scheme, config=configs[0], **activation)
        with self.assertRaisesRegex(ValueError, "active"):
            self.store.delete_scheme(self.scheme)
        self.assertEqual(self.store.active_binding(), (self.scheme, configs[0]))
        with self.connect(self.dsn) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM physical_index_configs WHERE scheme_identity=%s", (self.scheme.identity,)).fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT count(*) FROM indexed_chunks WHERE scheme_identity=%s AND status='stored'", (self.scheme.identity,)).fetchone()[0], 2)
        other = IndexSchemeVersion(replace(self.scheme.metadata, chunking_policy="test:v2"))
        self.store.upsert(other, self.chunk, (1, 0, 0))
        self.store.validate_and_activate(other, expected_count=1, expected_keys=[("doc", "v1", "a", "c1")],
            representative_vector=(1, 0, 0), actor="test", reason="switch before deletion")
        with self.connect(self.dsn) as connection:
            before = connection.execute("SELECT row_id,body,content_fingerprint,generated_at FROM indexed_chunks WHERE scheme_identity=%s ORDER BY row_id", (self.scheme.identity,)).fetchall()
            audit_before = connection.execute("SELECT count(*) FROM index_activation_audit").fetchone()[0]
        self.store.delete_scheme(self.scheme)
        self.store.delete_scheme(self.scheme)  # Repeated cleanup preserves already deleted identities.
        with self.connect(self.dsn) as connection:
            after = connection.execute("SELECT row_id,body,content_fingerprint,generated_at FROM indexed_chunks WHERE scheme_identity=%s AND status='deleted' ORDER BY row_id", (self.scheme.identity,)).fetchall()
            self.assertEqual(after, before)
            self.assertEqual(connection.execute("SELECT count(*) FROM physical_index_configs WHERE scheme_identity=%s", (self.scheme.identity,)).fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM index_activation_audit").fetchone()[0], audit_before)
            for config in configs:
                resource, index = _resource_names(self.scheme, config)
                self.assertIsNone(connection.execute("SELECT to_regclass(%s)", (resource,)).fetchone()[0])
                if config.algorithm != "exact":
                    self.assertIsNone(connection.execute("SELECT to_regclass(%s)", (index,)).fetchone()[0])
        self.assertEqual(self.store.get_attempt(attempt.attempt_id).status, "retryable")
        with self.assertRaisesRegex(ValueError, "deleted"):
            self.store.retry_attempt(attempt.attempt_id)
        with self.assertRaisesRegex(ValueError, "deleted"):
            self.store.upsert(self.scheme, self.chunk, (1, 0, 0))
        self.assertEqual(self.store.active_scheme(), other)

    def test_deleted_chunk_blocks_retry_without_changing_persisted_attempt(self):
        self.store.upsert(self.scheme, self.chunk, (1, 0, 0))
        digest = content_fingerprint(self.chunk.text, self.scheme.metadata, "document")[1]
        attempt = self.store.reserve_attempt(self.identity, digest, idempotency_key="original",
            request_payload={"idempotency_key": "original", "texts": [self.chunk.text]})
        self.store.resolve_attempt(attempt.attempt_id, "retryable", request_id="original-provider-id", error="not accepted")
        before = self.store.get_attempt(attempt.attempt_id)
        self.store.delete(self.identity)
        with self.assertRaisesRegex(ValueError, "deleted"):
            self.store.retry_attempt(attempt.attempt_id, idempotency_key="new-key",
                request_payload={"idempotency_key": "retry", "texts": [self.chunk.text]})
        self.assertEqual(self.store.get_attempt(attempt.attempt_id), before)
        self.assertIsNone(self.store.get_chunk(self.scheme, self.identity))


if __name__ == "__main__":
    unittest.main()
