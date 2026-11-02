"""Real PostgreSQL public lifecycle tests, NOT RUN during implementation.

Set TEST_DATABASE_URL to a disposable PostgreSQL database when the user elects
 to run these tests. No pgvector/pg_search extension is needed for parent bodies.
"""
import importlib
import os
import unittest
import uuid
from dataclasses import replace

r = importlib.import_module("app.modules.4_retrievalAndFusion")


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "requires explicit real PostgreSQL TEST_DATABASE_URL")
class PublishedContentTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.psycopg = psycopg
        self.dsn = os.environ["TEST_DATABASE_URL"]
        self.schema = "retrieval_test_" + uuid.uuid4().hex
        self.store = r.PostgresRetrievalStore(self.dsn, schema=self.schema)
        self.store.migrate()
        self.addCleanup(self.cleanup_schema)
        self.auth = r.AuthorizationScope(("kb",))
        self.parent = self.record("parent", "old parent body")
        self.child = self.record("child", "USB-C AX-100 v2.1", parent=self.parent.identity)

    def cleanup_schema(self):
        from psycopg import sql
        with self.psycopg.connect(self.dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def record(self, chunk, text, *, kb="kb", revision="v1", parent=None, metadata=None):
        return r.ContentRecord(r.EvidenceIdentity(kb, "manual", revision, chunk, "c1"),
                               text, {"uri": "manual.pdf", "page": 3},
                               metadata or {"product": "AX-100"}, parent)

    def publish(self, snapshot, records):
        self.store.ingest(records)
        prepared = self.store.prepare("kb", snapshot, [record.identity for record in records],
                                      field_types={"product": "string"})
        self.store.publish("kb", snapshot)
        return prepared

    def test_public_handoff_publish_and_parent_read_without_vectors(self):
        chunking = importlib.import_module("app.modules.2_documentChunking.models")
        child = r.ContentRecord.from_chunk(
            chunking.Chunk("child", "manual", None, None, "USB-C AX-100 v2.1", 0,
                           source_ids=("page-3",), parent_chunk_id="parent",
                           metadata={"product": "AX-100"}),
            knowledge_base_id="kb", document_version="v1", chunk_version="c1",
            parent=self.parent.identity,
        )
        self.publish("s1", [self.parent, child])
        # Reconstruct the adapter to prove that authoritative data is persisted.
        reader = r.PostgresRetrievalStore(self.dsn, schema=self.schema)
        reader.migrate()  # Re-applying the migration preserves published content.
        scope = reader.pin(["kb"], authorization=self.auth)
        hit = reader.read(child.identity, scope=scope)
        self.assertEqual(hit.parent, self.parent.identity)
        self.assertEqual(hit.source["source_ids"], ["page-3"])
        parent = reader.read(hit.parent, scope=scope)
        self.assertEqual(parent.text, "old parent body")
        self.assertEqual(parent.source, {"uri": "manual.pdf", "page": 3})

    def test_prepare_failure_keeps_old_snapshot_and_unknown_indexes_never_ready(self):
        self.publish("s1", [self.parent, self.child])
        newer = self.record("child", "new", revision="v2", parent=r.EvidenceIdentity("kb", "manual", "v2", "parent", "c1"))
        self.store.ingest([newer])
        with self.assertRaises(r.SnapshotNotReady):
            self.store.prepare("kb", "broken", [newer.identity])
        for required in ("vector", "document_bm25", "faq_bm25"):
            with self.assertRaises(r.SnapshotNotReady):
                self.store.prepare("kb", "unimplemented-" + required, [self.parent.identity], required_indexes=(required,))
            with self.assertRaises(r.SnapshotNotReady):
                self.store.publish("kb", "unimplemented-" + required)
        self.assertEqual(self.store.pin(["kb"], authorization=self.auth).snapshots["kb"], "s1")

    def test_publish_switch_and_explicit_history_leave_pinned_view_unchanged(self):
        self.publish("z-old", [self.parent, self.child])
        pinned = self.store.pin(["kb"], authorization=self.auth)
        newer = self.record("parent", "new parent", revision="v0")
        self.store.ingest([newer])
        self.store.prepare("kb", "a-new", [newer.identity], field_types={"product": "string"})
        with self.assertRaises(r.SnapshotNotReady):
            self.store.pin(["kb"], authorization=self.auth, snapshot_ids={"kb": "a-new"})
        self.store.publish("kb", "a-new")
        current = self.store.pin(["kb"], authorization=self.auth)
        self.assertEqual(current.snapshots["kb"], "a-new")
        self.assertEqual(self.store.read(self.parent.identity, scope=pinned).text, "old parent body")
        self.assertIsNone(self.store.read(newer.identity, scope=pinned))
        self.assertIsNone(self.store.read(self.parent.identity, scope=current))
        history = self.store.pin(["kb"], authorization=self.auth, snapshot_ids={"kb": "z-old"})
        self.assertEqual(self.store.read(self.parent.identity, scope=history).text, "old parent body")

    def test_conflicting_identity_is_atomic_and_repeat_ingest_is_idempotent(self):
        self.publish("s1", [self.parent])
        self.store.ingest([self.parent])
        other = self.record("other", "must roll back")
        with self.assertRaises(r.ContentConflict):
            self.store.ingest([other, replace(self.parent, text="changed under same identity")])
        with self.assertRaises(r.SnapshotNotReady):
            self.store.prepare("kb", "missing", [other.identity])
        self.assertEqual(self.store.read(self.parent.identity, scope=self.store.pin(["kb"], authorization=self.auth)).text, "old parent body")

    def test_authorization_and_business_filters_apply_to_parent_itself(self):
        restricted = replace(self.parent, metadata={"product": "restricted"})
        self.publish("s1", [restricted, self.child])
        scope = self.store.pin(["kb"], authorization=self.auth,
                               conditions=r.Eq("product", "AX-100"))
        self.assertEqual(self.store.read(self.child.identity, scope=scope).text, "USB-C AX-100 v2.1")
        self.assertIsNone(self.store.read(restricted.identity, scope=scope))
        no_documents = r.AuthorizationScope(("kb",), {"kb": ()})
        denied = self.store.pin(["kb"], authorization=no_documents)
        self.assertIsNone(self.store.read(self.child.identity, scope=denied))
        for auth in (None, r.AuthorizationScope(("elsewhere",))):
            with self.assertRaises(r.RetrievalContractError):
                self.store.pin(["kb"], authorization=auth)
        for condition in (r.Eq("unknown", "x"), r.Eq("product", 7), {"product": "AX-100"}):
            with self.assertRaises(r.RetrievalContractError):
                self.store.pin(["kb"], authorization=self.auth, conditions=condition)

    def test_missing_and_null_values_do_not_match_equality(self):
        records = [self.record("missing", "missing"), self.record("null", "null"), self.record("value", "value")]
        records = [replace(records[0], metadata={}), replace(records[1], metadata={"product": None}), records[2]]
        self.publish("s1", records)
        scope = self.store.pin(["kb"], authorization=self.auth,
                               conditions=r.All((r.Eq("product", "AX-100"),)))
        self.assertEqual([self.store.read(record.identity, scope=scope) is not None for record in records], [False, False, True])
        with self.assertRaises(r.RetrievalContractError):
            self.store.pin(["kb"], authorization=self.auth, conditions=r.Eq("product", None))

    def test_independent_knowledge_bases_and_concurrent_publisher(self):
        from concurrent.futures import ThreadPoolExecutor
        from datetime import datetime, timezone
        instant = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
        reader = r.PostgresRetrievalStore(self.dsn, schema=self.schema, clock=lambda: instant)
        self.publish("s1", [self.parent])
        foreign = self.record("parent", "other KB body", kb="other")
        self.store.ingest([foreign])
        self.store.prepare("other", "independent", [foreign.identity])
        self.store.publish("other", "independent")
        authorization = r.AuthorizationScope(("kb", "other"))
        pinned = reader.pin(["kb", "other"], authorization=authorization)
        newer = self.record("parent", "newer body", revision="v2")
        self.store.ingest([newer])
        self.store.prepare("kb", "s2", [newer.identity])
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(self.store.publish, "kb", "s2").result(timeout=10)
        self.assertEqual(pinned.now, instant)
        self.assertEqual(dict(pinned.snapshots), {"kb": "s1", "other": "independent"})
        self.assertEqual(reader.read(self.parent.identity, scope=pinned).text, "old parent body")
        self.assertEqual(reader.read(foreign.identity, scope=pinned).text, "other KB body")
        current = reader.pin(["kb", "other"], authorization=authorization)
        self.assertEqual(dict(current.snapshots), {"kb": "s2", "other": "independent"})
        with self.assertRaises(r.SnapshotNotReady):
            self.store.publish("kb", "does-not-exist")
        self.assertEqual(reader.pin(["kb"], authorization=self.auth).snapshots["kb"], "s2")

    def test_prepare_rejects_cycles_and_invalid_declared_metadata(self):
        cyclic_parent = replace(self.parent, parent=self.child.identity)
        self.store.ingest([cyclic_parent, self.child])
        with self.assertRaises(r.SnapshotNotReady):
            self.store.prepare("kb", "cycle", [cyclic_parent.identity, self.child.identity])
        invalid = self.record("invalid", "wrong metadata", metadata={"product": 3})
        self.store.ingest([invalid])
        with self.assertRaises(r.RetrievalContractError):
            self.store.prepare("kb", "invalid", [invalid.identity], field_types={"product": "string"})
        with self.assertRaises(r.SnapshotNotReady):
            self.store.publish("kb", "invalid")

    def test_same_chunk_id_different_document_and_chunk_revisions_are_distinct(self):
        first = self.parent
        second = replace(first, identity=replace(first.identity, chunk_version="c2"), text="second chunk revision")
        third = replace(first, identity=replace(first.identity, document_id="other-manual"), text="different document")
        self.publish("selected", [first, second, third])
        scope = self.store.pin(["kb"], authorization=self.auth)
        self.assertEqual([self.store.read(item.identity, scope=scope).text for item in (first, second, third)],
                         ["old parent body", "second chunk revision", "different document"])
        restricted = self.store.pin(["kb"], authorization=r.AuthorizationScope(("kb",), {"kb": ("manual",)}))
        self.assertIsNone(self.store.read(third.identity, scope=restricted))

    def test_snapshot_manifest_is_immutable_and_cross_kb_is_rejected(self):
        prepared = self.publish("s1", [self.parent])
        self.assertEqual(prepared.required_indexes, ("content",))
        self.store.prepare("kb", "s1", [self.parent.identity], field_types={"product": "string"})
        with self.assertRaises(r.ContentConflict):
            self.store.prepare("kb", "s1", [])
        foreign = self.record("parent", "foreign", kb="other")
        self.store.ingest([foreign])
        with self.assertRaises(r.RetrievalContractError):
            self.store.prepare("kb", "cross", [foreign.identity])
        self.assertIsNone(self.store.read(foreign.identity, scope=self.store.pin(["kb"], authorization=self.auth)))
