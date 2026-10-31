import importlib
import json
from dataclasses import asdict, dataclass, replace
import unittest

indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")


@dataclass
class Attempt:
    attempt_id: str
    identity: object
    content_fingerprint: str
    idempotency_key: str
    request_id: str
    status: str
    request_payload: dict
    result_payload: dict | None = None
    error: str | None = None


class FakeStore:
    """Contract fake: requests survive rebuilding the application flow."""
    def __init__(self):
        self.rows = {}
        self.attempts = {}
        self.fail_write = False
        self.fail_reserve = False

    def get_attempt_for_identity(self, identity):
        return self.attempts.get(identity.key)

    def reserve_batch_attempts(self, identities, fingerprints, *, request_payload):
        if self.fail_reserve:
            raise RuntimeError("durable reservation unavailable")
        if any(identity.key in self.attempts for identity in identities):
            raise RuntimeError("duplicate request")
        payload = json.loads(json.dumps(request_payload))
        created = []
        for identity, fingerprint in zip(identities, fingerprints):
            attempt = Attempt(identity.key, identity, fingerprint, payload["idempotency_key"],
                              payload["request_id"], "pending", payload)
            self.attempts[identity.key] = attempt
            created.append(attempt)
        return created

    def resolve_attempt(self, attempt_id, status, *, request_id=None, error=None,
                        result_payload=None, request_payload=None):
        attempt = self.attempts[attempt_id]
        if attempt.status in {"succeeded", "failed"} and (
                status != attempt.status or result_payload is not None and result_payload != attempt.result_payload):
            raise ValueError("terminal request resolution is immutable")
        attempt.status = status
        attempt.request_id = request_id or attempt.request_id
        attempt.error = error
        if result_payload is not None:
            attempt.result_payload = json.loads(json.dumps(result_payload))
        if request_payload is not None:
            attempt.request_payload = json.loads(json.dumps(request_payload))

    def retry_attempt(self, attempt_id, *, request_payload=None):
        attempt = self.attempts[attempt_id]
        if attempt.status != "retryable":
            raise ValueError("not retryable")
        attempt.status = "pending"
        attempt.request_payload = json.loads(json.dumps(request_payload))
        attempt.request_id = request_payload["request_id"]
        attempt.idempotency_key = request_payload["idempotency_key"]
        return attempt

    def upsert(self, scheme, chunk, vector, **provenance):
        if self.fail_write:
            raise RuntimeError("write unavailable")
        identity = indexing.LogicalIndexIdentity(chunk.document_id, chunk.document_version,
            chunk.chunk_id, scheme.identity, chunk.chunk_version)
        self.rows[identity.key] = (chunk, tuple(vector), provenance)

    def search(self, scheme, vector, limit=10, **options):
        def score(row):
            return sum(left * right for left, right in zip(row[1], vector))
        rows = sorted((row for key, row in self.rows.items() if json.loads(key)[3] == scheme.identity), key=score, reverse=True)[:limit]
        return [indexing.SearchHit(row[0], score(row), scheme.identity,
            row[2]["content_fingerprint"], row[2]["fingerprint_algorithm"]) for row in rows]


class CountingAdapter(indexing.DeterministicEmbeddingAdapter):
    def __init__(self, dimensions=3):
        super().__init__(dimensions)
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return super().embed(texts)


class UncertainAdapter(CountingAdapter):
    supports_request_metadata = True
    supports_status_query = True

    def embed_request(self, request):
        self.calls += 1
        raise indexing.ProviderError("unknown", "TIMEOUT", "outcome unknown", request_id="provider-request")

    def resolve_request(self, request):
        return indexing.UnknownResolution("embedded", request.request_id, request.idempotency_key,
            request.keys, request.fingerprints, super().embed(request.prepared_texts))


class EmbeddingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.adapter = CountingAdapter()
        self.chunk = indexing.ChunkRecord("c1", "doc", "revision-1", "alpha", {
            "source_ids": ["src"], "structure_path": ["Heading"], "body_span": [0, 5],
        }, "chunk-revision-1")

    def test_chunk_to_embedding_to_same_scheme_search_preserves_revision_and_context(self):
        result = indexing.index_chunks([self.chunk], self.adapter, self.store)
        self.assertEqual(result.items[0].status, "stored")
        hits = indexing.search_chunks("alpha", self.adapter, self.store)
        self.assertEqual(hits[0].chunk, self.chunk)
        self.assertEqual(hits[0].chunk.metadata["structure_path"], ["Heading"])
        self.assertEqual(hits[0].content_fingerprint, result.items[0].content_fingerprint)
        self.assertEqual(len(self.store.attempts), 2)

    def test_repeated_call_does_not_resubmit_and_metadata_update_is_allowed(self):
        indexing.index_chunks([self.chunk], self.adapter, self.store)
        updated = indexing.ChunkRecord("c1", "doc", "revision-1", "alpha", {"updated": True}, "chunk-revision-1")
        result = indexing.index_chunks([updated], self.adapter, self.store)
        self.assertEqual(self.adapter.calls, 1)
        self.assertEqual(result.items[0].status, "stored")
        self.assertEqual(next(iter(self.store.rows.values()))[0].metadata, {"updated": True})
        changed = indexing.ChunkRecord("c1", "doc", "revision-1", "changed", {}, "chunk-revision-1")
        with self.assertRaises(indexing.ContentFingerprintConflict):
            indexing.index_chunks([changed], self.adapter, self.store)
        self.assertEqual(self.adapter.calls, 1)

    def test_successful_vector_survives_index_write_failure(self):
        self.store.fail_write = True
        result = indexing.index_chunks([self.chunk], self.adapter, self.store)
        self.assertEqual(result.items[0].error_code, "INDEX_PERSISTENCE_FAILED")
        self.store.fail_write = False
        result = indexing.index_chunks([self.chunk], self.adapter, self.store)
        self.assertEqual(self.adapter.calls, 1)
        self.assertEqual(result.items[0].status, "stored")

    def test_reservation_failure_prevents_provider_submission(self):
        self.store.fail_reserve = True
        with self.assertRaisesRegex(RuntimeError, "reservation"):
            indexing.index_chunks([self.chunk], self.adapter, self.store)
        self.assertEqual(self.adapter.calls, 0)

    def test_unknown_is_durable_blocks_duplicates_and_explicitly_resolves_after_restart(self):
        adapter = UncertainAdapter()
        first = indexing.index_chunks([self.chunk], adapter, self.store)
        self.assertEqual(first.items[0].status, "unknown")
        again = indexing.index_chunks([self.chunk], adapter, self.store)
        self.assertEqual(again.items[0].status, "unknown")
        self.assertEqual(adapter.calls, 1)
        # Only the repository and a new adapter remain; no in-memory batch result.
        fresh = UncertainAdapter()
        resolved = indexing.resolve_index_requests([self.chunk], fresh, self.store)
        self.assertEqual(resolved.items[0].status, "stored")
        self.assertEqual(fresh.calls, 1)  # resolver locally creates the fixture vector
        self.assertEqual(next(iter(self.store.attempts.values())).status, "succeeded")

    def test_pending_after_crash_requires_explicit_caller_adjudication(self):
        scheme = indexing.IndexSchemeVersion(self.adapter.metadata)
        identity = indexing.LogicalIndexIdentity("doc", "revision-1", "c1", scheme.identity, "chunk-revision-1")
        algorithm, fingerprint = indexing.content_fingerprint("alpha", self.adapter.metadata, "document")
        request = indexing.BatchRequest("request", "idempotent", (identity.key,), ("alpha",), ("alpha",),
                                       "document", (fingerprint,), algorithm, scheme.identity)
        self.store.reserve_batch_attempts([identity], [fingerprint], request_payload=asdict(request))
        result = indexing.index_chunks([self.chunk], self.adapter, self.store)
        self.assertEqual(result.items[0].status, "unknown")
        self.assertEqual(self.adapter.calls, 0)
        indexing.adjudicate_index_request(identity, self.store, state="retryable", actor="operator", reason="provider confirms request not executed")
        result = indexing.index_chunks([self.chunk], self.adapter, self.store, retry_retryable=True)
        self.assertEqual(result.items[0].status, "stored")
        self.assertEqual(self.adapter.calls, 1)

    def test_explicit_rechunk_creates_new_revisions_and_keeps_source_provenance(self):
        policy = indexing.LongInputPolicy("rechunk", "split-v1", lambda text, mode: ["al", "pha"])
        self.adapter.metadata = replace(self.adapter.metadata,
            document_role=replace(self.adapter.metadata.document_role, tokenizer_policy=policy.policy_id))
        result = indexing.index_chunks([self.chunk], self.adapter, self.store,
            max_tokens=3, token_counter=len, long_input_policy=policy)
        self.assertEqual(len(result.items), 2)
        rows = [row[0] for row in self.store.rows.values()]
        self.assertEqual({row.text for row in rows}, {"al", "pha"})
        self.assertTrue(all(row.chunk_version != self.chunk.chunk_version for row in rows))
        self.assertTrue(all(row.metadata["embedding_transform"]["source_chunk_version"] == self.chunk.chunk_version for row in rows))
        self.assertEqual(self.chunk.text, "alpha")

    def test_missing_chunk_revision_is_rejected_before_provider(self):
        class OldChunk:
            chunk_id = "c1"
            document_id = "doc"
            document_version = "v1"
            text = "alpha"
            metadata = {}
        with self.assertRaises(indexing.EmbeddingContractError):
            indexing.index_chunks([OldChunk()], self.adapter, self.store)
        self.assertEqual(self.adapter.calls, 0)

    def test_search_rejects_malformed_query_and_retains_unknown_request(self):
        class Malformed(CountingAdapter):
            def embed(self, texts):
                return [(float("nan"),) * 3]
        with self.assertRaises(indexing.EmbeddingQueryError) as error:
            indexing.search_chunks("query", Malformed(), self.store)
        self.assertEqual(error.exception.result.items[0].status, "failed")
        with self.assertRaises(indexing.EmbeddingQueryError) as error:
            indexing.search_chunks("query", UncertainAdapter(), self.store)
        self.assertEqual(error.exception.result.items[0].status, "unknown")
        self.assertIn("unknown", [attempt.status for attempt in self.store.attempts.values()])


    def test_document_role_override_is_rejected_without_submission(self):
        with self.assertRaisesRegex(indexing.EmbeddingContractError, "document role"):
            indexing.index_chunks([self.chunk], self.adapter, self.store, role="query")
        self.assertEqual(self.adapter.calls, 0)
        self.assertEqual(self.store.attempts, {})

    def test_completed_batch_is_durable_before_later_reservation_failure(self):
        class FailSecondReservation(FakeStore):
            def reserve_batch_attempts(self, identities, fingerprints, *, request_payload):
                if self.attempts:
                    raise RuntimeError("second reservation failed")
                return super().reserve_batch_attempts(identities, fingerprints, request_payload=request_payload)
        store = FailSecondReservation()
        second = replace(self.chunk, chunk_id="c2", text="beta")
        with self.assertRaisesRegex(RuntimeError, "second reservation"):
            indexing.index_chunks([self.chunk, second], self.adapter, store, max_batch_size=1)
        self.assertEqual(self.adapter.calls, 1)
        self.assertEqual(next(iter(store.attempts.values())).status, "succeeded")
        result = indexing.index_chunks([self.chunk], self.adapter, store)
        self.assertEqual(result.items[0].status, "stored")
        self.assertEqual(self.adapter.calls, 1)

    def test_retry_diagnostics_and_generated_time_survive_reload(self):
        class InitiallyRetryable(CountingAdapter):
            broken = True
            def embed(self, texts):
                if self.broken:
                    self.calls += 1
                    raise indexing.ProviderError("retryable", "BUSY", "try later")
                return super().embed(texts)
        adapter = InitiallyRetryable()
        first = indexing.index_chunks([self.chunk], adapter, self.store, max_retries=0)
        reloaded = indexing.index_chunks([self.chunk], adapter, self.store)
        self.assertEqual(first.items[0], reloaded.items[0])
        self.assertEqual(reloaded.items[0].error_code, "BUSY")
        self.assertIsNotNone(reloaded.items[0].next_retry_at)
        adapter.broken = False
        retried = indexing.index_chunks([self.chunk], adapter, self.store, retry_retryable=True)
        self.assertEqual((retried.items[0].attempt_count, retried.items[0].retry_count), (2, 1))
        restored = indexing.index_chunks([self.chunk], adapter, self.store)
        self.assertEqual(retried.items[0], restored.items[0])
        self.assertEqual(adapter.calls, 2)
        self.assertEqual(next(iter(self.store.rows.values()))[2]["generated_at"], restored.items[0].updated_at)

    def test_unknown_query_can_be_reconciled_without_resubmitting(self):
        indexing.index_chunks([self.chunk], self.adapter, self.store)
        adapter = UncertainAdapter()
        with self.assertRaises(indexing.EmbeddingQueryError) as error:
            indexing.search_chunks("alpha", adapter, self.store)
        result = error.exception.result
        hits = indexing.resolve_query_request(result, adapter, self.store)
        self.assertEqual(hits[0].chunk, self.chunk)
        self.assertEqual(adapter.calls, 2)  # original send plus local fixture resolver
        wrong = UncertainAdapter(dimensions=4)
        with self.assertRaisesRegex(indexing.EmbeddingContractError, "different representation"):
            indexing.resolve_query_request(result, wrong, self.store)

    def test_serving_query_captures_binding_once_and_requires_matching_adapter(self):
        indexing.index_chunks([self.chunk], self.adapter, self.store)
        scheme = indexing.IndexSchemeVersion(self.adapter.metadata)
        config = object()
        calls = []
        def active_binding():
            calls.append("binding")
            return scheme, config
        self.store.active_binding = active_binding
        original_search = self.store.search
        def search(selected, vector, **options):
            self.assertIs(options.pop("config"), config)
            return original_search(selected, vector, **options)
        self.store.search = search
        hits = indexing.search_serving_chunks("alpha", lambda selected: self.adapter, self.store)
        self.assertEqual(hits[0].chunk, self.chunk)
        self.assertEqual(calls, ["binding"])
        with self.assertRaises(indexing.EmbeddingContractError):
            indexing.search_serving_chunks("alpha", lambda selected: CountingAdapter(4), self.store)


if __name__ == "__main__":
    unittest.main()
