"""Real PostgreSQL parent expansion lifecycle tests. Authored, NOT RUN.

Requires an explicitly selected disposable TEST_DATABASE_URL. Parent bodies do
not need pgvector or a vector index. Public-query coverage uses an injected
retrieval route backed by real scoped PostgreSQL reads.
"""
import importlib
import os
import unittest
import uuid
from dataclasses import replace

r = importlib.import_module("app.modules.4_retrievalAndFusion")
f = importlib.import_module("app.modules.4_retrievalAndFusion.fusion_contracts")
p = importlib.import_module("app.modules.4_retrievalAndFusion.parent_expansion")


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "requires explicit real PostgreSQL TEST_DATABASE_URL")
class ParentPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.psycopg = psycopg
        self.dsn = os.environ["TEST_DATABASE_URL"]
        self.schema = "parent_test_" + uuid.uuid4().hex
        self.store = r.PostgresRetrievalStore(self.dsn, schema=self.schema)
        self.store.migrate()
        self.addCleanup(self.cleanup_schema)
        self.auth = r.AuthorizationScope(("kb",))
        self.grandparent = self.record("grandparent", "A grandparent must not be returned")
        self.parent = self.record("parent", "Complete parent body includes unmatched facts.",
                                  parent=self.grandparent.identity)
        self.child = self.record("child", "Short matching fragment", parent=self.parent.identity)
        self.sibling = self.record("sibling", "Second matching fragment", parent=self.parent.identity)

    def cleanup_schema(self):
        from psycopg import sql
        with self.psycopg.connect(self.dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def record(self, chunk, text, *, parent=None, revision="v1", product="public"):
        return r.ContentRecord(r.EvidenceIdentity("kb", "manual", revision, chunk, "c1"),
                               text, {"uri": "manual.pdf", "chunk": chunk},
                               {"product": product}, parent)

    def publish(self, name, records):
        self.store.ingest(records)
        prepared = self.store.prepare("kb", name, [record.identity for record in records],
                                      field_types={"product": "string"})
        self.store.publish("kb", name)
        return prepared

    def test_ingest_publish_expand_siblings_without_any_vector_index(self):
        chunking = importlib.import_module("app.modules.2_documentChunking.models")
        child = r.ContentRecord.from_chunk(
            chunking.Chunk("child", "manual", None, None, "Short matching fragment", 0,
                           source_ids=("page-3",), parent_chunk_id="parent",
                           metadata={"product": "public"}),
            knowledge_base_id="kb", document_version="v1", chunk_version="c1",
            parent=self.parent.identity,
        )
        snapshot = self.publish("s1", [self.grandparent, self.parent, child, self.sibling])
        self.assertEqual(snapshot.required_indexes, ("content",))
        reader = r.PostgresRetrievalStore(self.dsn, schema=self.schema)
        scope = reader.pin(["kb"], authorization=self.auth)
        hits = (f.FusedCandidate(reader.read(child.identity, scope=scope), .8, ()),
                f.FusedCandidate(reader.read(self.sibling.identity, scope=scope), .5, ()))
        result = p.expand_parents(hits, store=reader, scope=scope, enabled=True)
        self.assertEqual(result.step.status, "complete")
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].content, self.parent)
        self.assertEqual(result.candidates[0].score, .8)
        self.assertEqual(result.candidates[0].matched_children, (child, self.sibling))

    def test_parent_business_condition_independently_filters_full_parent(self):
        restricted = replace(self.parent, metadata={"product": "restricted"})
        self.publish("s1", [self.grandparent, restricted, self.child])
        scope = self.store.pin(["kb"], authorization=self.auth, conditions=r.Eq("product", "public"))
        child = self.store.read(self.child.identity, scope=scope)
        self.assertIsNotNone(child)
        hit = f.FusedCandidate(child, .8, ())
        for strict in (False, True):
            with self.subTest(strict=strict):
                result = p.expand_parents((hit,), store=self.store, scope=scope, enabled=True, strict=strict)
                self.assertEqual(result.candidates, () if strict else (hit,))
                self.assertEqual(result.step.status, "failed" if strict else "partial")
                self.assertEqual(result.step.reason, "parent_unavailable")

    def test_published_switch_preserves_original_parent_revision_and_scope(self):
        self.publish("s1", [self.grandparent, self.parent, self.child])
        scope = self.store.pin(["kb"], authorization=self.auth)
        child = self.store.read(self.child.identity, scope=scope)
        newer = self.record("parent", "New revision must not leak", revision="v2")
        self.publish("s2", [newer])
        result = p.expand_parents((f.FusedCandidate(child, .8, ()),), store=self.store,
                                  scope=scope, enabled=True)
        self.assertEqual(result.candidates[0].content, self.parent)
        current = self.store.pin(["kb"], authorization=self.auth)
        self.assertIsNone(self.store.read(self.parent.identity, scope=current))
        self.assertIsNone(self.store.read(newer.identity, scope=scope))

    def public_service(self, identities):
        # The external route boundary reads actual published records; parent
        # lookup and filter enforcement remain the production PostgreSQL code.
        def search(query, *, scope, top_k, exact_terms, **options):
            records = [self.store.read(identity, scope=scope) for identity in identities]
            hits = tuple(r.RouteHit(item, scope.snapshots["kb"], 1., "fixture_rank")
                         for item in records if item is not None)[:top_k]
            return r.RouteResult("content-route", "kb", "content", "success" if hits else "empty", hits)
        return r.RetrievalService(self.store, routes=(
            r.RetrievalRoute("content-route", "kb", "content", search),))

    def test_public_ingest_publish_query_expands_without_parent_vectors(self):
        other = self.record("other", "Independent backup evidence")
        self.publish("s1", [self.grandparent, self.parent, self.child, self.sibling, other])
        service = self.public_service([self.child.identity, self.sibling.identity, other.identity])
        result = service.query("fragment", knowledge_base_ids=("kb",), authorization=self.auth,
                               config=r.RetrievalConfig(parent_expansion=True, final_top_k=2))
        self.assertEqual(result.status, "complete")
        self.assertEqual([item.content for item in result.candidates], [self.parent, other])
        self.assertEqual(result.candidates[0].matched_children, (self.child, self.sibling))
        self.assertAlmostEqual(result.candidates[0].score, 1 / 61)
        self.assertEqual([trace.identity for trace in result.candidates[0].traces],
                         [self.child.identity, self.sibling.identity])
        self.assertEqual(result.steps[0].status, "complete")

    def test_public_parent_filters_and_historical_snapshot_are_not_widened(self):
        restricted = replace(self.parent, metadata={"product": "restricted"})
        self.publish("s1", [self.grandparent, restricted, self.child])
        newer = self.record("parent", "New document version", revision="v2")
        self.publish("s2", [newer])
        service = self.public_service([self.child.identity])
        for strict in (False, True):
            with self.subTest(strict=strict):
                result = service.query("fragment", knowledge_base_ids=("kb",), authorization=self.auth,
                    snapshot_ids={"kb": "s1"}, conditions=r.Eq("product", "public"),
                    config=r.RetrievalConfig(parent_expansion=True, postprocess_strict=strict))
                self.assertEqual(result.status, "complete")
                self.assertEqual(result.routes[0].status, "success")
                self.assertEqual(result.scope.snapshots["kb"], "s1")
                self.assertEqual(result.steps[0].reason, "parent_unavailable")
                self.assertEqual([item.content for item in result.working_pool], [self.child])
                self.assertEqual([item.content for item in result.candidates], [] if strict else [self.child])
        historical = service.query("fragment", knowledge_base_ids=("kb",), authorization=self.auth,
            snapshot_ids={"kb": "s1"}, config=r.RetrievalConfig(parent_expansion=True))
        self.assertEqual(historical.candidates[0].content, restricted)
