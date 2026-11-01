"""SQL 结构与事务契约测试；不模拟 PostgreSQL，也不证明 SQL 已在 PostgreSQL 中执行。"""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from app.models.embedding import (
    ChunkRecord, EmbeddingContractError, EmbeddingMetadata, EmbeddingRoleConfig,
    IndexSchemeVersion, LogicalIndexIdentity, content_fingerprint,
)
from app.models.db.pgvector import (
    DuplicateRequestAttempt, FingerprintConflict, LegacyChunkRecord,
    PhysicalIndexConfig, PostgresVectorStore, _resource_names, _scheme_from_metadata,
)


def scheme(dimensions=3):
    return IndexSchemeVersion(EmbeddingMetadata("test", "model", "r1", dimensions,
        chunking_policy="chunks:v1", document_role=EmbeddingRoleConfig("document", "encoder", "doc: "),
        query_role=EmbeddingRoleConfig("query", "encoder", "query: ")))


def chunk(text="alpha"):
    return ChunkRecord("a", "doc", "v1", text, {"category": "manual", "page": 1}, "c1")


def identity(value=None):
    return LogicalIndexIdentity("doc", "v1", "a", (value or scheme()).identity, "c1")


class Cursor:
    def __init__(self, handler=lambda sql, params: None):
        self.handler = handler
        self.statements = []
        self.rowcount = 1
        self.result = None

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        self.statements.append((sql, params))
        self.result = self.handler(sql, params)

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result or []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Connection:
    def __init__(self, cursor):
        self.current = cursor
        self.commits = self.rollbacks = self.closes = 0

    def cursor(self):
        return self.current

    def __enter__(self):
        return self

    def __exit__(self, kind, *args):
        if kind is None:
            self.commits += 1
        else:
            self.rollbacks += 1
        return False

    def close(self):
        self.closes += 1


class PgVectorSqlContractTests(unittest.TestCase):
    def setUp(self):
        self.scheme = scheme()
        self.cursor = Cursor(self.handler)
        self.connection = Connection(self.cursor)
        self.store = PostgresVectorStore("unused", connect=lambda _: self.connection,
            metadata_fields={"category": str, "page": int, "visible": bool, "weight": float})
        self.config_row = None
        self.existing = None
        self.attempt_fingerprint = None
        self.search_rows = []

    def handler(self, sql, params):
        if sql.startswith("SELECT metadata,dimensions FROM embedding_schemes"):
            return asdict(self.scheme.metadata), self.scheme.metadata.dimensions
        if sql.startswith("SELECT algorithm,build_parameters"):
            return self.config_row
        if sql.startswith("SELECT content_fingerprint FROM embedding_request_attempts"):
            return self.attempt_fingerprint
        if sql.startswith("SELECT content_fingerprint,fingerprint_algorithm,status FROM indexed_chunks"):
            return self.existing or (content_fingerprint("alpha", self.scheme.metadata, "document")[1], "sha256", "stored")
        if sql.startswith("WITH "):
            return self.search_rows
        return None

    def statements(self):
        return [sql for sql, _ in self.cursor.statements]

    def test_exact_materializes_before_distance_order_and_stably_limits_ties(self):
        self.store.search(self.scheme, (1, 0, 0), limit=2, candidate_limit=5,
            filters={"document_id": "doc", "document_version": "v1", "metadata.page": 1}, score_threshold=0.8)
        sql, params = self.cursor.statements[-1]
        self.assertIn("eligible AS MATERIALIZED", sql)
        self.assertIn("provenance_state='verified'", sql)
        self.assertIn("ORDER BY vector::vector(3) <=> %s::vector,document_id,document_version,chunk_id,chunk_version,row_id", sql)
        self.assertIn("metadata @> %s::jsonb", sql)
        self.assertIn("WHERE n.distance <= %s", sql)
        self.assertEqual(params[-3], 5)
        self.assertAlmostEqual(params[-2], 0.2)
        self.assertEqual(params[-1], 2)
        self.assertEqual(self.connection.commits, 1)

    def test_ann_names_only_selected_resource_and_sets_local_parameters(self):
        config = PhysicalIndexConfig("hnsw", {"m": 8, "ef_construction": 32}, {"ef_search": 40})
        resource, index = _resource_names(self.scheme, config)
        self.config_row = (config.algorithm, dict(config.build_parameters), dict(config.query_parameters), resource, index)
        self.store.search(self.scheme, (1, 0, 0), config=config, query_parameters={"ef_search": 60})
        self.assertIn(("SELECT set_config(%s,%s,true)", ("hnsw.ef_search", "60")), self.cursor.statements)
        sql = self.statements()[-1]
        self.assertIn('FROM "' + resource + '"', sql)
        self.assertIn("scheme_identity='" + self.scheme.identity + "'", sql)
        self.assertNotIn("eligible AS MATERIALIZED", sql)
        self.assertEqual(self.connection.closes, 1)

    def test_explicit_exact_ignores_ann_and_rejects_ann_query_knobs(self):
        with self.assertRaises(ValueError):
            self.store.search(self.scheme, (1, 0, 0), config=PhysicalIndexConfig(), query_parameters={"ef_search": 2})
        self.assertEqual(self.connection.rollbacks, 1)
        self.assertFalse(any("set_config" in sql for sql in self.statements()))

    def test_threshold_and_candidate_validation_occurs_before_database(self):
        for options in ({"score_threshold": 0.5, "distance_threshold": 0.5}, {"score_threshold": 2},
                        {"distance_threshold": float("nan")}, {"candidate_limit": 1, "limit": 2}, {"limit": True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.store.search(self.scheme, (1, 0, 0), **options)
        self.assertEqual(self.cursor.statements, [])

    def test_typed_metadata_filters_reject_undeclared_or_wrong_types(self):
        for filters in ({"metadata.unknown": 1}, {"metadata.page": True}, {"visible": 1}, {"weight": float("inf")}, {"document_id": 1}):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                self.store.search(self.scheme, (1, 0, 0), filters=filters)
        self.assertEqual(self.cursor.statements, [])

    def test_search_hit_reconstructs_provenance_and_chunk_revision(self):
        now = datetime.now(timezone.utc)
        self.search_rows = [("doc", "v1", "a", "alpha", {"page": 1}, "c1", 0.25, "a" * 64, "sha256", now)]
        hit = self.store.search(self.scheme, (1, 0, 0))[0]
        self.assertEqual(hit.score, 0.75)
        self.assertEqual(hit.chunk.chunk_version, "c1")
        self.assertEqual((hit.content_fingerprint, hit.fingerprint_algorithm, hit.generated_at), ("a" * 64, "sha256", now))

    def test_upsert_serializes_asdict_nested_roles_and_never_updates_existing_vector(self):
        self.store.upsert(self.scheme, chunk(), (1, 0, 0))
        metadata = next(params[1] for sql, params in self.cursor.statements if sql.startswith("INSERT INTO embedding_schemes"))
        self.assertEqual(json.loads(metadata)["document_role"]["instruction"], "doc: ")
        self.assertTrue(any("pg_advisory_xact_lock(hashtextextended" in sql for sql in self.statements()))
        self.assertTrue(any("DO NOTHING" in sql and "INSERT INTO indexed_chunks" in sql for sql in self.statements()))
        self.assertFalse(any("SET vector=" in sql for sql in self.statements()))

    def test_same_fingerprint_updates_metadata_without_replacing_vector_or_provenance(self):
        updated = replace(chunk(), metadata={"category": "updated", "page": 2})
        self.store.upsert(self.scheme, updated, (0, 1, 0))
        sql, params = next((sql, params) for sql, params in self.cursor.statements if sql.startswith("UPDATE indexed_chunks"))
        self.assertEqual(json.loads(params[0]), updated.metadata)
        self.assertNotIn("vector=", sql)
        self.assertNotIn("generated_at=", sql)
        self.assertNotIn("content_fingerprint=", sql)
        self.assertEqual(self.connection.commits, 1)

    def test_fingerprint_conflict_rolls_back_preserving_existing_row(self):
        self.existing = ("b" * 64, "sha256", "stored")
        with self.assertRaises(FingerprintConflict):
            self.store.upsert(self.scheme, chunk(), (1, 0, 0))
        self.assertEqual(self.connection.rollbacks, 1)
        self.assertFalse(any(sql.startswith("UPDATE indexed_chunks") for sql in self.statements()))

    def test_reserved_identity_fingerprint_conflict_is_checked_before_canonical_insert(self):
        self.attempt_fingerprint = ("b" * 64,)
        with self.assertRaises(FingerprintConflict):
            self.store.upsert(self.scheme, chunk(), (1, 0, 0))
        self.assertFalse(any(sql.startswith("INSERT INTO indexed_chunks") for sql in self.statements()))

    def test_deleted_identity_cannot_be_resurrected(self):
        self.existing = (content_fingerprint("alpha", self.scheme.metadata, "document")[1], "sha256", "deleted")
        with self.assertRaisesRegex(ValueError, "deleted"):
            self.store.upsert(self.scheme, chunk(), (1, 0, 0))
        self.assertEqual(self.connection.rollbacks, 1)

    def test_bad_vectors_fingerprint_and_naive_timestamp_reject_before_write(self):
        for vector in ((0, 0, 0), (1, 0), (float("nan"), 0, 0), (1e40, 0, 0), (2, 0, 0)):
            with self.subTest(vector=vector), self.assertRaises(EmbeddingContractError):
                self.store.upsert(self.scheme, chunk(), vector)
        with self.assertRaises(FingerprintConflict):
            self.store.upsert(self.scheme, chunk(), (1, 0, 0), content_fingerprint="a" * 64)
        with self.assertRaises(EmbeddingContractError):
            self.store.upsert(self.scheme, chunk(), (1, 0, 0), generated_at=datetime.now())
        self.assertEqual(self.cursor.statements, [])

    def test_legacy_metadata_cannot_accept_new_writes(self):
        old = IndexSchemeVersion(replace(self.scheme.metadata, document_role=None, query_role=None))
        with self.assertRaises(EmbeddingContractError):
            self.store.upsert(old, chunk(), (1, 0, 0))
        self.assertEqual(self.cursor.statements, [])

    def test_metadata_roundtrip_rebuilds_nested_role_configs(self):
        restored = _scheme_from_metadata(json.dumps(asdict(self.scheme.metadata)))
        self.assertEqual(restored, self.scheme)
        self.assertIsInstance(restored.metadata.query_role, EmbeddingRoleConfig)

    def test_ann_build_uses_typed_partial_cosine_expression(self):
        config = PhysicalIndexConfig("hnsw", {"m": 8, "ef_construction": 32})
        self.store.register_physical_config(self.scheme, config)
        ddl = next(sql for sql in self.statements() if sql.startswith("CREATE INDEX"))
        self.assertIn("USING hnsw ((vector::vector(3)) vector_cosine_ops)", ddl)
        self.assertIn("WITH (ef_construction=32,m=8)", ddl)
        self.assertIn("WHERE scheme_identity='" + self.scheme.identity + "'", ddl)
        self.assertNotEqual(_resource_names(self.scheme, config), _resource_names(self.scheme, PhysicalIndexConfig("ivfflat", {"lists": 1})))

    def test_ann_dimension_limit_rejects_before_database(self):
        with self.assertRaisesRegex(ValueError, "2000"):
            self.store.register_physical_config(scheme(2001), PhysicalIndexConfig("hnsw"))
        self.assertEqual(self.cursor.statements, [])

    def test_actual_pgvector_parameter_bounds_and_cross_constraints(self):
        for algorithm, build, query in (("hnsw", {"m": 1}, {}), ("hnsw", {"m": 101}, {}),
                ("hnsw", {"ef_construction": 1001}, {}), ("hnsw", {"m": 40, "ef_construction": 64}, {}),
                ("hnsw", {}, {"ef_search": 1001}), ("hnsw", {}, {"ef_search": 0}),
                ("ivfflat", {"lists": 32769}, {}), ("ivfflat", {"lists": 2}, {"probes": 3}),
                ("ivfflat", {}, {"probes": 32769}), ("exact", {}, {"probes": 1}),
                ("hnsw", {"m": True}, {}), ("hnsw", {"m);DROP TABLE x;--": 1}, {})):
            with self.subTest(algorithm=algorithm, build=build, query=query), self.assertRaises(ValueError):
                PhysicalIndexConfig(algorithm, build, query)
        PhysicalIndexConfig("hnsw", {"m": 100, "ef_construction": 1000}, {"ef_search": 1000})
        PhysicalIndexConfig("ivfflat", {"lists": 32768}, {"probes": 32768})

    def test_config_is_immutable_and_parameter_order_is_irrelevant(self):
        first = PhysicalIndexConfig("hnsw", {"m": 8, "ef_construction": 32})
        second = PhysicalIndexConfig("hnsw", {"ef_construction": 32, "m": 8})
        self.assertEqual(first.identity, second.identity)
        with self.assertRaises(TypeError):
            first.build_parameters["m"] = 9

    def test_activation_requires_actor_reason_and_four_part_manifest(self):
        for options in ({"actor": "", "reason": "test", "expected_keys": [("doc", "v1", "a", "c1")]},
                        {"actor": "test", "reason": "", "expected_keys": [("doc", "v1", "a", "c1")]},
                        {"actor": "test", "reason": "test", "expected_keys": [("doc", "v1", "a")]}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.store.validate_and_activate(self.scheme, expected_count=1, representative_vector=(1, 0, 0), **options)
        self.assertEqual(self.cursor.statements, [])

    def test_schema_upgrade_keeps_legacy_nullable_and_enforces_new_provenance(self):
        sql = Path(__file__).parents[2].joinpath("app/models/db/pgvector_schema.sql").read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS chunk_version text;", sql)
        self.assertIn("DEFAULT 'legacy/unverifiable'", sql)
        self.assertIn("new index rows require verified provenance", sql)
        self.assertIn("deleted index identity is immutable", sql)
        self.assertIn("NEW.body,NEW.vector,NEW.generated_at", sql)
        self.assertNotIn("NEW.body,NEW.metadata,NEW.vector", sql)
        self.assertIn("ON CONFLICT(row_id) DO UPDATE SET metadata=EXCLUDED.metadata", sql)
        self.assertIn("one_active_serving_config", sql)
        self.assertIn("result_payload jsonb", sql)
        self.assertNotIn("digest(", sql)

    def test_atomic_batch_reservations_store_full_payload_and_distinct_item_keys(self):
        ids = [identity(), replace(identity(), chunk_id="b")]
        payload = {"idempotency_key": "batch", "request_id": "provider-request", "texts": ["alpha", "beta"]}
        original = self.cursor.handler
        self.cursor.handler = lambda sql, params: (params[0],) if sql.startswith("INSERT INTO embedding_request_attempts") else original(sql, params)
        attempts = self.store.reserve_batch_attempts(ids, ["a" * 64, "b" * 64], request_payload=payload)
        self.assertEqual(self.connection.commits, 1)
        self.assertNotEqual(attempts[0].idempotency_key, attempts[1].idempotency_key)
        self.assertEqual(attempts[0].request_payload, payload)
        self.assertEqual(attempts[0].identity, ids[0])
        inserts = [(sql, params) for sql, params in self.cursor.statements if sql.startswith("INSERT INTO embedding_request_attempts")]
        self.assertEqual(len(inserts), 2)
        self.assertNotIn("vector", inserts[0][0])
        self.assertEqual(json.loads(inserts[0][1][-1]), payload)

    def test_duplicate_unknown_is_blocked_and_batch_rolls_back(self):
        def handler(sql, params):
            if sql.startswith("SELECT content_fingerprint,status FROM embedding_request_attempts"):
                return "a" * 64, "unknown"
            return None
        self.cursor.handler = handler
        with self.assertRaises(DuplicateRequestAttempt):
            self.store.reserve_attempt(identity(), "a" * 64, idempotency_key="repeat")
        self.assertEqual(self.connection.rollbacks, 1)

    def test_canonical_conflict_or_tombstone_blocks_request_reservation(self):
        for existing in (("b" * 64, "stored"), ("a" * 64, "deleted")):
            self.cursor.handler = lambda sql, params: existing if sql.startswith("SELECT content_fingerprint,status FROM indexed_chunks") else None
            with self.subTest(existing=existing), self.assertRaises(ValueError):
                self.store.reserve_attempt(identity(), "a" * 64, idempotency_key="k")
        self.assertFalse(any(sql.startswith("INSERT INTO embedding_request_attempts") for sql in self.statements()))

    def test_pending_unknown_failed_cannot_retry(self):
        for status in ("pending", "unknown", "failed", "succeeded"):
            self.cursor.handler = lambda sql, params: (("doc", "v1", "a", "c1", self.scheme.identity, status, "a" * 64)
                if sql.startswith("SELECT document_id,document_version,chunk_id,chunk_version,scheme_identity,status") else None)
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, "retryable"):
                self.store.retry_attempt("attempt")
        self.assertFalse(any(sql.startswith("UPDATE embedding_request_attempts") for sql in self.statements()))

    def test_terminal_resolution_rejects_result_changes(self):
        self.cursor.handler = lambda sql, params: ("succeeded", {"vector": [1, 0, 0]})
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.store.resolve_attempt("attempt", "succeeded", result_payload={"vector": [0, 1, 0]})
        self.assertEqual(self.connection.rollbacks, 1)
    def test_boolean_thresholds_and_nonnumeric_vector_components_are_rejected(self):
        for options in ({"score_threshold": True}, {"distance_threshold": False}, {"score_threshold": "0.5"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.store.search(self.scheme, (1, 0, 0), **options)
        for vector in ((True, 0, 0), ("1", 0, 0), (None, 0, 0)):
            with self.subTest(vector=vector), self.assertRaises(EmbeddingContractError):
                self.store.search(self.scheme, vector)
        self.assertEqual(self.cursor.statements, [])

    def test_ann_default_parameter_is_explicitly_transaction_local(self):
        config = PhysicalIndexConfig("hnsw")
        resource, index = _resource_names(self.scheme, config)
        self.config_row = ("hnsw", {}, {}, resource, index)
        self.store.search(self.scheme, (1, 0, 0), config=config)
        self.assertIn(("SELECT set_config(%s,%s,true)", ("hnsw.ef_search", "40")), self.cursor.statements)

    def test_active_binding_uses_one_join_snapshot_and_rebuilds_configs(self):
        config = PhysicalIndexConfig("hnsw", {"m": 8, "ef_construction": 32}, {"ef_search": 20})
        self.cursor.handler = lambda sql, params: (self.scheme.identity, asdict(self.scheme.metadata), "hnsw", dict(config.build_parameters), dict(config.query_parameters))
        active_scheme, active_config = self.store.active_binding()
        self.assertEqual((active_scheme, active_config), (self.scheme, config))
        self.assertEqual(len(self.cursor.statements), 1)
        self.assertIn("WHERE r.is_active AND p.is_active", self.statements()[0])

    def activation_handler(self, corrupt=None):
        config = PhysicalIndexConfig()
        resource, _ = _resource_names(self.scheme, config)
        normal = self.handler
        now = datetime.now(timezone.utc)
        def handler(sql, params):
            if sql.startswith("SELECT identity FROM physical_index_configs"):
                return (config.identity,)
            if sql.startswith("SELECT algorithm,build_parameters"):
                return ("exact", {}, {}, resource, None)
            if sql.startswith("SELECT document_id,document_version,chunk_id,chunk_version,status"):
                revision = "wrong" if corrupt == "manifest" else "c1"
                return [("doc", "v1", "a", revision, "stored", "verified", 3, "a" * 64, now)]
            if sql.startswith("SELECT to_regclass"):
                return (resource,)
            if sql.startswith("SELECT count(*)"):
                return (1 if corrupt == "resource" and "IS DISTINCT FROM" in sql else 0,)
            if sql.startswith("WITH "):
                return [("doc", "v1", "a", "alpha", {}, "c1", 0 if corrupt != "representative" else 1, "a" * 64, "sha256", now)]
            return normal(sql, params)
        return handler

    def activate(self, rollback=False):
        method = self.store.rollback if rollback else self.store.validate_and_activate
        return method(self.scheme, expected_count=1, expected_keys=[("doc", "v1", "a", "c1")],
            representative_vector=(1, 0, 0), actor="operator", reason="verified manifest")

    def test_activation_and_rollback_revalidate_in_transaction_and_audit_actor_reason(self):
        self.cursor.handler = self.activation_handler()
        self.assertTrue(self.activate()["physical_health"])
        self.assertTrue(self.activate(rollback=True)["identities_valid"])
        audits = [params for sql, params in self.cursor.statements if sql.startswith("INSERT INTO index_activation_audit")]
        self.assertEqual([(params[4], params[5], params[6]) for params in audits],
            [("operator", "verified manifest", "activate"), ("operator", "verified manifest", "rollback")])
        self.assertTrue(any("LOCK TABLE index_registry IN EXCLUSIVE MODE" in sql for sql in self.statements()))
        self.assertTrue(any("FROM embedding_schemes WHERE identity=%s FOR UPDATE" in sql for sql in self.statements()))

    def test_activation_rejects_manifest_resource_or_representative_without_switching(self):
        for corrupt in ("manifest", "resource", "representative"):
            with self.subTest(corrupt=corrupt):
                self.cursor.statements.clear()
                self.cursor.handler = self.activation_handler(corrupt)
                with self.assertRaisesRegex(ValueError, "validation failed"):
                    self.activate()
                self.assertFalse(any(sql.startswith("UPDATE index_registry SET is_active") for sql in self.statements()))
                self.assertFalse(any(sql.startswith("INSERT INTO index_activation_audit") for sql in self.statements()))
        self.assertEqual(self.connection.rollbacks, 3)

    def test_physical_health_rejects_wrong_options_predicate_expression_or_extra_ann(self):
        config = PhysicalIndexConfig("hnsw", {"m": 8, "ef_construction": 32})
        resource, index = _resource_names(self.scheme, config)
        predicate = "(scheme_identity = '" + self.scheme.identity + "'::text)"
        valid = [True, True, "hnsw", "CREATE INDEX x USING hnsw ((vector::vector(3)) vector_cosine_ops)",
                 ["m=8", "ef_construction=32"], predicate, "(vector)::vector(3)", 1]
        for corruption in (None, "options", "predicate", "expression", "multiple"):
            row = valid.copy()
            if corruption == "options": row[4] = ["m=16", "ef_construction=64"]
            if corruption == "predicate": row[5] += " OR true"
            if corruption == "expression": row[6] = "(-vector)::vector(3)"
            def handler(sql, params):
                if sql.startswith("SELECT to_regclass"): return (resource,)
                if sql.startswith("SELECT count(*) FROM pg_index"): return (2 if corruption == "multiple" else 1,)
                if sql.startswith("SELECT count(*)"): return (0,)
                if sql.startswith("SELECT i.indisvalid"): return row
            self.cursor.handler = handler
            with self.subTest(corruption=corruption):
                self.assertEqual(self.store._physical_health(self.cursor, self.scheme, config, resource, index), corruption is None)

    def test_legacy_read_preserves_old_persisted_identity_and_unknown_provenance(self):
        old_metadata = asdict(replace(self.scheme.metadata, document_role=None, query_role=None))
        normal = self.handler
        def handler(sql, params):
            if sql.startswith("SELECT metadata FROM embedding_schemes"): return (old_metadata,)
            if sql.startswith("WITH "): return [("doc", "v1", "a", "alpha", {}, None, 0, None, None, None)]
            return normal(sql, params)
        self.cursor.handler = handler
        hit = self.store.search_legacy("old:identity", (1, 0, 0))[0]
        self.assertEqual(hit.scheme_identity, "old:identity")
        self.assertIsInstance(hit.chunk, LegacyChunkRecord)
        self.assertIsNone(hit.chunk.chunk_version)
        self.assertIsNone(hit.content_fingerprint)
        self.assertIsNone(hit.generated_at)

    def test_request_payload_fingerprint_and_scheme_binding_are_checked(self):
        payload = {"keys": [identity().key], "fingerprints": ["b" * 64], "scheme_identity": self.scheme.identity}
        with self.assertRaises(FingerprintConflict):
            self.store.reserve_attempt(identity(), "a" * 64, idempotency_key="k", request_payload=payload)
        self.assertEqual(self.cursor.statements, [])

    def test_resolution_cannot_change_persisted_provider_input(self):
        payload = {"keys": [identity().key], "texts": ["alpha"], "fingerprints": ["a" * 64]}
        self.cursor.handler = lambda sql, params: ("unknown", None, payload)
        with self.assertRaisesRegex(EmbeddingContractError, "immutable"):
            self.store.resolve_attempt("attempt", "unknown", request_payload=dict(payload, texts=["different"]))
        self.assertFalse(any(sql.startswith("UPDATE embedding_request_attempts") for sql in self.statements()))

    def test_only_pending_retry_transition_increments_retry_count(self):
        operations = [(lambda: self.store.mark_failure(identity(), "provider", "failure"), "failed", 0),
                      (lambda: self.store.delete(identity()), "deleted", 0),
                      (lambda: self.store.retry(identity()), "pending", 1)]
        for operation, status, increment in operations:
            with self.subTest(status=status):
                self.cursor.statements.clear()
                operation()
                sql, params = self.cursor.statements[-1]
                self.assertIn("retry_count=retry_count+%s", sql)
                self.assertEqual((params[0], params[3]), (status, increment))
                self.assertEqual(params[4:9], ("doc", "v1", "a", "c1", self.scheme.identity))
        self.assertEqual(self.connection.commits, 3)

    def deletion_handler(self, *, active=False, physical_active=False, fail_drop=False):
        configs = [PhysicalIndexConfig(), PhysicalIndexConfig("hnsw"), PhysicalIndexConfig("ivfflat", {"lists": 1})]
        resources = []
        for config in configs:
            resource, index = _resource_names(self.scheme, config)
            resources.append((resource, index if config.algorithm != "exact" else None, physical_active))
        def handler(sql, params):
            if sql.startswith("SELECT is_active FROM index_registry"):
                return (active,)
            if sql.startswith("SELECT resource_table,index_name,is_active"):
                return resources
            if fail_drop and sql.startswith("DROP TABLE"):
                raise RuntimeError("resource drop failed")
            return self.handler(sql, params)
        return handler, resources

    def test_delete_inactive_scheme_cleans_all_resources_after_tombstones_with_activation_lock_order(self):
        self.cursor.handler, resources = self.deletion_handler()
        self.store.delete_scheme(self.scheme)
        statements = self.statements()
        self.assertEqual(statements[:3], ["SELECT pg_advisory_xact_lock(713826004218046210)",
            "SELECT identity FROM embedding_schemes WHERE identity=%s FOR UPDATE", "LOCK TABLE index_registry IN EXCLUSIVE MODE"])
        tombstones = next(position for position, sql in enumerate(statements) if sql.startswith("UPDATE indexed_chunks SET status='deleted'"))
        for resource, index, _ in resources:
            drop = statements.index('DROP TABLE IF EXISTS "' + resource + '"')
            self.assertGreater(drop, tombstones)
            if index is not None:
                self.assertLess(statements.index('DROP INDEX IF EXISTS "' + index + '"'), drop)
        self.assertEqual(self.cursor.statements[-1], ("DELETE FROM physical_index_configs WHERE scheme_identity=%s", (self.scheme.identity,)))
        for table in ("indexed_chunks", "embedding_request_attempts", "index_activation_audit", "embedding_schemes", "index_registry"):
            self.assertFalse(any(sql.startswith("DELETE FROM " + table) or sql.startswith("DROP TABLE " + table) for sql in statements))
        self.assertEqual(self.connection.commits, 1)

    def test_delete_rejects_active_scheme_or_physical_config_before_mutation(self):
        for options in ({"active": True}, {"physical_active": True}):
            with self.subTest(options=options):
                self.cursor.statements.clear()
                self.cursor.handler, _ = self.deletion_handler(**options)
                with self.assertRaisesRegex(ValueError, "active"):
                    self.store.delete_scheme(self.scheme)
                self.assertFalse(any(sql.startswith(("UPDATE ", "DROP ", "DELETE ")) for sql in self.statements()))
        self.assertEqual(self.connection.rollbacks, 2)

    def test_failed_physical_cleanup_rolls_back_scheme_deletion(self):
        self.cursor.handler, _ = self.deletion_handler(fail_drop=True)
        with self.assertRaisesRegex(RuntimeError, "resource drop failed"):
            self.store.delete_scheme(self.scheme)
        self.assertEqual((self.connection.commits, self.connection.rollbacks), (0, 1))
        self.assertFalse(any(sql.startswith("DELETE FROM physical_index_configs") for sql in self.statements()))

    def retry_handler(self, *, canonical=None, locked_status="retryable"):
        def handler(sql, params):
            if sql.startswith("SELECT document_id,document_version,chunk_id,chunk_version,scheme_identity,status"):
                status = locked_status if sql.endswith("FOR UPDATE") else "retryable"
                return ("doc", "v1", "a", "c1", self.scheme.identity, status, "a" * 64)
            if sql.startswith("SELECT content_fingerprint,status FROM indexed_chunks"):
                return canonical
            if sql.startswith("SELECT attempt_id,document_id"):
                return ("attempt", "doc", "v1", "a", "c1", self.scheme.identity, "a" * 64, "retry-key", None, "pending", None, None, None)
            return self.handler(sql, params)
        return handler

    def test_retry_locks_identity_then_canonical_then_request_and_accepts_no_vector(self):
        self.cursor.handler = self.retry_handler()
        retried = self.store.retry_attempt("attempt", idempotency_key="retry-key")
        self.assertEqual(retried.status, "pending")
        statements = self.statements()
        self.assertNotIn("FOR UPDATE", statements[0])
        self.assertIn("pg_advisory_xact_lock(hashtextextended", statements[1])
        self.assertIn("FROM indexed_chunks", statements[2])
        self.assertTrue(statements[2].endswith("FOR UPDATE"))
        self.assertIn("FROM embedding_request_attempts", statements[3])
        self.assertTrue(statements[3].endswith("FOR UPDATE"))
        self.assertTrue(statements[4].startswith("UPDATE embedding_request_attempts SET status='pending'"))

    def test_retry_rejects_canonical_tombstone_or_fingerprint_conflict_without_reactivating(self):
        for canonical, error in ((("a" * 64, "deleted"), ValueError), (("b" * 64, "stored"), FingerprintConflict)):
            with self.subTest(canonical=canonical):
                self.cursor.statements.clear()
                self.cursor.handler = self.retry_handler(canonical=canonical)
                with self.assertRaises(error):
                    self.store.retry_attempt("attempt", idempotency_key="retry-key")
                self.assertFalse(any(sql.startswith("UPDATE embedding_request_attempts") for sql in self.statements()))
                self.assertFalse(any("FROM embedding_request_attempts" in sql and sql.endswith("FOR UPDATE") for sql in self.statements()))
        self.assertEqual(self.connection.rollbacks, 2)

    def test_retry_rechecks_request_status_after_identity_lock(self):
        self.cursor.handler = self.retry_handler(locked_status="unknown")
        with self.assertRaisesRegex(ValueError, "retryable"):
            self.store.retry_attempt("attempt")
        self.assertFalse(any(sql.startswith("UPDATE embedding_request_attempts") for sql in self.statements()))
        self.assertEqual(self.connection.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
