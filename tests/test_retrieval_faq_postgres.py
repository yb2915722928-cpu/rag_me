"""Real PostgreSQL/pgvector/pg_search FAQ lifecycle tests. NOT RUN by the author.

Requires TEST_DATABASE_URL with the project's supported extensions provisioned.
EmbeddingAdapter is deterministic at the external encoder seam; all persistence,
vector operators, snapshots and public fusion use the real PostgreSQL adapters.
"""
import importlib
import os
import unittest
import uuid
from dataclasses import replace

r = importlib.import_module("app.modules.4_retrievalAndFusion")
f = importlib.import_module("app.modules.4_retrievalAndFusion.faq_contracts")
fs = importlib.import_module("app.modules.4_retrievalAndFusion.faq_postgres")


indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")


class FAQEncoder(indexing.DeterministicEmbeddingAdapter):
    def __init__(self):
        super().__init__(3)
        self.inputs = []

    def embed(self, texts):
        self.inputs.extend(texts)
        # Known vectors: questions about reset outrank a different FAQ.
        return [(1.0, 0.0, 0.0) if "reset" in text.lower() or "restart" in text.lower()
                else (0.0, 1.0, 0.0) for text in texts]


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "requires provisioned real PostgreSQL")
class FAQPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.psycopg = psycopg
        self.dsn = os.environ["TEST_DATABASE_URL"]
        self.schema = "faq_test_" + uuid.uuid4().hex
        self.store = fs.PostgresFAQRetrievalStore(self.dsn, schema=self.schema)
        self.addCleanup(self.cleanup)
        self.store.migrate()
        self.auth = r.AuthorizationScope(("kb",))

    def cleanup(self):
        from psycopg import sql
        with self.psycopg.connect(self.dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def faq(self, item="reset", version="v1", conditions=None):
        return f.FAQRecord(f.FAQIdentity("kb", item, version), "How to reset?",
                           ("Reset steps?", "Restart device?"), "Hold reset for 5 seconds.",
                           {"product": "AX-100"} if conditions is None else conditions,
                           {"uri": "faq/reset"})

    def publish(self, name, records):
        self.store.ingest_faq(records)
        self.store.prepare("kb", name, (), faq_identities=[x.identity for x in records],
                           required_indexes=("content", "faq"), field_types={"product": "string"})
        self.store.publish("kb", name)

    def test_authority_is_persisted_and_explicit_versions_share_the_doc_snapshot(self):
        old = self.faq()
        self.publish("old", [old])
        pinned = self.store.pin(["kb"], authorization=self.auth)
        newer = replace(self.faq(version="v2"), answer="Use the console.")
        self.publish("new", [newer])
        reader = fs.PostgresFAQRetrievalStore(self.dsn, schema=self.schema)
        self.assertEqual(reader.read(old.identity, scope=pinned), old)
        current = reader.pin(["kb"], authorization=self.auth)
        self.assertIsNone(reader.read(old.identity, scope=current))
        self.assertEqual(reader.read(newer.identity, scope=current).text, "Use the console.")
        with self.assertRaises(r.ContentConflict):
            reader.ingest_faq([replace(old, answer="silent mutation")])

    def test_faq_grants_and_typed_conditions_are_enforced_independently(self):
        a, b, c = self.faq(), self.faq("missing", conditions={}), self.faq("null", conditions={"product": None})
        self.publish("s", [a, b, c])
        selected = self.store.pin(["kb"], authorization=self.auth, conditions=r.Eq("product", "AX-100"))
        self.assertEqual([self.store.read(x.identity, scope=selected) is not None for x in (a, b, c)],
                         [True, False, False])
        denied = self.store.pin(["kb"], authorization=r.AuthorizationScope(("kb",), faq_item_ids={"kb": ()}))
        self.assertIsNone(self.store.read(a.identity, scope=denied))
        documents_only = self.store.pin(["kb"], authorization=r.AuthorizationScope(("kb",), {"kb": ("reset",)}))
        self.assertIsNone(self.store.read(a.identity, scope=documents_only))

    def test_question_vectors_group_before_top_k_and_return_answer_evidence(self):
        from app.models.embedding import IndexSchemeVersion
        encoder = FAQEncoder()
        self.store.adapter_for_scheme = lambda scheme: encoder
        first = self.faq()
        second = replace(self.faq("charging"), standard_question="Charging?", similar_questions=(), answer="Use USB-C.")
        self.store.index_faq([first, second], encoder)
        self.assertNotIn(first.answer, encoder.inputs)
        self.assertNotIn(second.answer, encoder.inputs)
        self.store.prepare("kb", "vectors", (), faq_identities=[first.identity, second.identity],
                           field_types={"product": "string"}, faq_vector_scheme=IndexSchemeVersion(encoder.metadata))
        self.store.publish("kb", "vectors")
        scope = self.store.pin(["kb"], authorization=self.auth)
        result = self.store.search_faq_vector("reset", knowledge_base_id="kb", scope=scope, top_k=2)
        self.assertEqual(result.status, "success")
        self.assertEqual([x.content.identity for x in result.candidates], [first.identity, second.identity])
        self.assertEqual(result.candidates[0].content.text, first.answer)
        self.assertEqual(len(result.candidates[0].matched_questions), 3)
        self.assertAlmostEqual(result.candidates[0].raw_score, 1.0)
        no_match = self.store.pin(["kb"], authorization=self.auth, conditions=r.Eq("product", "OTHER"))
        empty = self.store.search_faq_vector("reset", knowledge_base_id="kb", scope=no_match)
        self.assertEqual(empty.status, "empty")
        self.assertEqual(empty.candidates, ())

    def test_public_query_fuses_document_and_faq_with_one_contribution_per_item(self):
        from app.models.embedding import IndexSchemeVersion
        encoder = FAQEncoder()
        self.store.adapter_for_scheme = lambda scheme: encoder
        faq = self.faq()
        doc = r.ContentRecord(r.EvidenceIdentity("kb", "manual", "v1", "reset", "c1"),
                              "Reset device from the console.", {"uri": "manual.pdf"}, {"product": "AX-100"})
        self.store.index_documents([doc], encoder)
        self.store.index_faq([faq], encoder)
        self.store.prepare("kb", "mixed", [doc.identity], faq_identities=[faq.identity],
                           required_indexes=("vector", "bm25", "faq_vector"),
                           vector_scheme=IndexSchemeVersion(encoder.metadata),
                           faq_vector_scheme=IndexSchemeVersion(encoder.metadata), field_types={"product": "string"})
        self.store.publish("kb", "mixed")
        result = r.RetrievalService(self.store).query("reset", knowledge_base_ids=["kb"], authorization=self.auth)
        self.assertEqual(result.status, "complete")
        self.assertEqual({x.content.identity for x in result.candidates}, {faq.identity, doc.identity})
        hit = next(x for x in result.candidates if x.content.identity == faq.identity)
        self.assertEqual(hit.content.text, faq.answer)
        self.assertEqual(len(hit.traces), 1)
        self.assertEqual(hit.traces[0].method, "faq_vector")
        self.assertEqual(len(hit.traces[0].matched_questions), 3)
        self.assertAlmostEqual(hit.score, 1 / 61)
        self.assertEqual({route.method for route in result.routes}, {"vector", "bm25", "faq_vector"})
        limited = r.RetrievalService(self.store).query("reset", knowledge_base_ids=["kb"], authorization=self.auth,
                                                     config=r.RetrievalConfig(final_top_k=1))
        self.assertEqual(len(limited.candidates), 1)
        self.assertEqual(len(limited.working_pool), 2)
        faq_only = r.RetrievalService(self.store).query(
            "reset", knowledge_base_ids=["kb"],
            authorization=r.AuthorizationScope(("kb",), faq_item_ids={"kb": ("reset",)}))
        self.assertEqual([x.content.identity for x in faq_only.candidates], [faq.identity])
        docs_only = r.RetrievalService(self.store).query(
            "reset", knowledge_base_ids=["kb"], authorization=r.AuthorizationScope(("kb",), {"kb": ("manual",)}))
        self.assertEqual([x.content.identity for x in docs_only.candidates], [doc.identity])
        filtered = r.RetrievalService(self.store).query(
            "reset", knowledge_base_ids=["kb"], authorization=self.auth, conditions=r.Eq("product", "OTHER"))
        self.assertEqual(filtered.status, "complete")
        self.assertEqual(filtered.candidates, ())

    def test_missing_required_faq_vectors_cannot_replace_publication(self):
        self.publish("old", [self.faq()])
        from app.models.embedding import IndexSchemeVersion
        adapter = FAQEncoder()
        with self.assertRaises(r.SnapshotNotReady):
            self.store.prepare("kb", "broken", (), faq_identities=[self.faq().identity],
                               required_indexes=("faq", "faq_vector"),
                               field_types={"product": "string"}, faq_vector_scheme=IndexSchemeVersion(adapter.metadata))
        self.assertEqual(self.store.pin(["kb"], authorization=self.auth).snapshots["kb"], "old")
