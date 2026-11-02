"""Public timeout and explicit query recovery contracts; authored, NOT RUN."""
from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace
from datetime import datetime, timezone
import importlib
import unittest

r = importlib.import_module("app.modules.4_retrievalAndFusion")
e = importlib.import_module("app.modules.3_embeddingAndIndexing")


class PinnedStore:
    def pin(self, knowledge_base_ids, *, authorization, conditions=None, snapshot_ids=None, remaining=None):
        return r.ReadScope({kb: "s1" for kb in knowledge_base_ids}, authorization,
                           conditions, datetime(2026, 1, 1, tzinfo=timezone.utc))


class QueryRecoveryTests(unittest.TestCase):
    def query(self, search):
        route = r.RetrievalRoute("vector", "kb", "vector", search)
        return r.RetrievalService(PinnedStore(), routes=(route,)).query(
            "private query", knowledge_base_ids=("kb",), authorization=r.AuthorizationScope(("kb",)))

    def test_native_timeout_is_timeout_before_root_expires(self):
        def search(query, **options):
            raise TimeoutError("private query and provider transport detail")

        result = self.query(search)
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.routes[0].status, "timeout")
        self.assertEqual(result.routes[0].reason, "route_timeout")
        self.assertIsNone(result.routes[0].query_recovery)
        self.assertNotIn("private", repr(result))

    def test_embedding_timeout_and_other_unknown_or_failed_keep_recovery(self):
        for status, code, expected in (("unknown", "EMBEDDING_TIMEOUT", "timeout"),
                                       ("unknown", "PROVIDER_CONNECTION_LOST", "failed"),
                                       ("failed", "EMBEDDING_FAILED", "failed")):
            with self.subTest(status=status, code=code):
                batch = e.EmbeddingBatchResult((e.EmbeddedItem(
                    "durable-query-key", "private query", status, role="query",
                    error_code=code, reason="private provider detail", request_id="request-1"),))

                def search(query, **options):
                    raise e.EmbeddingQueryError(batch)

                result = self.query(search)
                route = result.routes[0]
                self.assertEqual(route.status, expected)
                self.assertEqual(route.reason, "route_timeout" if expected == "timeout" else "route_execution_failed")
                recovery = route.query_recovery
                self.assertIsInstance(recovery, r.QueryRecovery)
                self.assertEqual(recovery.key, "durable-query-key")
                self.assertEqual(recovery.status, status)
                self.assertEqual(recovery.request_id, "request-1")
                self.assertNotIn("private", repr(result))
                self.assertNotIn("private", repr(recovery))

    def test_backend_result_recovery_survives_default_route_adapter(self):
        batch = e.EmbeddingBatchResult((e.EmbeddedItem(
            "durable-query-key", "private query", "unknown", role="query",
            error_code="EMBEDDING_TIMEOUT", request_id="request-1"),))
        recovery = r.QueryRecovery(batch)
        store = PinnedStore()
        store.search_vector = lambda *args, **kwargs: r.VectorQueryResult(
            "timeout", error="route_timeout", query_recovery=recovery)
        store.search_bm25 = lambda *args, **kwargs: r.BM25QueryResult("empty")
        result = r.RetrievalService(store).query("private query", knowledge_base_ids=("kb",),
            authorization=r.AuthorizationScope(("kb",)))
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.routes[0].status, "timeout")
        self.assertEqual(result.routes[0].reason, "route_timeout")
        self.assertIs(result.routes[0].query_recovery, recovery)

    def test_direct_backends_classify_statement_timeout_without_database(self):
        class StatementTimeout(Exception):
            sqlstate = "57014"
            diag = SimpleNamespace(message_primary="canceling statement due to statement timeout")

        class UserCancellation(Exception):
            sqlstate = "57014"
            diag = SimpleNamespace(message_primary="canceling statement due to user request")

        for error, expected in ((TimeoutError("private transport detail"), "timeout"),
                                (StatementTimeout("private SQL"), "timeout"),
                                (UserCancellation("private SQL"), "failed")):
            with self.subTest(error=type(error).__name__):
                def connect(*args, **kwargs):
                    raise error

                store = r.PostgresFAQBM25RetrievalStore("not-used", connect=connect)
                scope = r.ReadScope({"kb": "s1"}, r.AuthorizationScope(("kb",)), None,
                                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                                    {"kb": r.compile_filter(None, field_types={}, now=datetime(2026, 1, 1, tzinfo=timezone.utc))})
                for method in (store.search_vector, store.search_faq_vector,
                               store.search_bm25, store.search_faq_bm25):
                    with self.subTest(method=method.__name__):
                        result = method("private query", knowledge_base_id="kb", scope=scope)
                        self.assertEqual(result.status, expected)
                        self.assertEqual(result.error, "route_timeout" if expected == "timeout" else "route_execution_failed")
                        self.assertNotIn("private", repr(result))

    def test_direct_vector_backends_preserve_actual_module3_unknown_result(self):
        class TimeoutAdapter(e.DeterministicEmbeddingAdapter):
            def embed_role(self, *args, **kwargs):
                raise TimeoutError("private provider detail")

        adapter = TimeoutAdapter(2)
        scheme = e.IndexSchemeVersion(adapter.metadata)
        attempts, persisted = {}, []

        class Repository:
            def reserve_batch_attempts(self, identities, fingerprints, *, request_payload):
                for identity, fingerprint in zip(identities, fingerprints):
                    attempts[identity.key] = e.RequestAttempt("attempt-" + str(len(attempts)), identity,
                        fingerprint, request_payload["idempotency_key"], request_payload["request_id"],
                        "pending", request_payload=request_payload)

            def get_attempt_for_identity(self, identity):
                return attempts[identity.key]

            def resolve_attempt(self, attempt_id, status, **kwargs):
                persisted.append((attempt_id, status))

        class SnapshotStore(r.PostgresFAQBM25RetrievalStore):
            @contextmanager
            def _transaction(self, **kwargs):
                yield None

            def _load_snapshot(self, *args, **kwargs):
                binding = {"scheme": asdict(scheme.metadata), "algorithm": "exact"}
                return SimpleNamespace(index_options={"vector": binding, "faq_vector": binding})

        store = SnapshotStore("not-used", adapter_for_scheme=lambda _: adapter)
        store.request_repository = Repository()
        scope = r.ReadScope({"kb": "s1"}, r.AuthorizationScope(("kb",)), None,
                            datetime(2026, 1, 1, tzinfo=timezone.utc),
                            {"kb": r.compile_filter(None, field_types={}, now=datetime(2026, 1, 1, tzinfo=timezone.utc))})
        for method in (store.search_vector, store.search_faq_vector):
            with self.subTest(method=method.__name__):
                result = method("private query", knowledge_base_id="kb", scope=scope)
                self.assertEqual(result.status, "timeout")
                self.assertEqual(result.query_recovery.status, "unknown")
                self.assertEqual(result.query_recovery.error_code, "EMBEDDING_TIMEOUT")
                self.assertIn(result.query_recovery.key, attempts)
                self.assertNotIn("private", repr(result))
        self.assertEqual([status for _, status in persisted], ["unknown", "unknown"])

    def test_recovery_explicitly_resolves_original_request_without_resubmission(self):
        adapter = e.DeterministicEmbeddingAdapter(2)
        scheme = e.IndexSchemeVersion(adapter.metadata)
        identity = e.LogicalIndexIdentity("__query__", scheme.identity, "original-id", scheme.identity, "query:v1")
        algorithm, fingerprint = e.content_fingerprint("private query", adapter.metadata, "query")
        request = e.BatchRequest("request-1", "idempotency-1", (identity.key,), ("private query",),
            (adapter.prepare_text("private query", "query"),), "query", (fingerprint,), algorithm, scheme.identity)
        item = e.EmbeddedItem(identity.key, "private query", "unknown", error_code="EMBEDDING_TIMEOUT",
            role="query", request_id=request.request_id, idempotency_key=request.idempotency_key,
            content_fingerprint=fingerprint, fingerprint_algorithm=algorithm, request=request)
        recovery = r.QueryRecovery(e.EmbeddingBatchResult((item,)))
        attempt = e.RequestAttempt("attempt-1", identity, fingerprint, request.idempotency_key,
                                   request.request_id, "unknown", request_payload=asdict(request))
        states, searched, resolved = [], [], []

        class Repository:
            def reserve_batch_attempts(self, *args, **kwargs):
                raise AssertionError("resolution must not submit or reserve a new request")

            def get_attempt_for_identity(self, requested_identity):
                self_identity = requested_identity
                if self_identity != identity:
                    raise AssertionError("resolution must keep the original durable identity")
                return attempt

            def resolve_attempt(self, attempt_id, status, **kwargs):
                states.append((attempt_id, status))

        class ResolvingAdapter(e.DeterministicEmbeddingAdapter):
            supports_status_query = True

            def embed_role(self, *args, **kwargs):
                raise AssertionError("resolution must not resubmit embedding")

            def resolve_request(self, original_request):
                resolved.append(original_request)
                return e.UnknownResolution(e.RequestState.EMBEDDED, original_request.request_id,
                    original_request.idempotency_key, original_request.keys, original_request.fingerprints,
                    vectors=((1.0, 0.0),))

        class SearchStore:
            def search(self, requested_scheme, vector, *, limit):
                searched.append((requested_scheme, vector, limit))
                return ["original-snapshot-hit"]

        self.assertEqual(states, [])
        hits = recovery.resolve(ResolvingAdapter(2), SearchStore(), request_repository=Repository(), limit=3)
        self.assertEqual(hits, ["original-snapshot-hit"])
        self.assertEqual(resolved, [request])
        self.assertEqual(states, [("attempt-1", "succeeded")])
        self.assertEqual(searched, [(scheme, (1.0, 0.0), 3)])
        self.assertEqual(recovery.status, "unknown")
