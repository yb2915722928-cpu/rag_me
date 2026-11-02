from dataclasses import asdict, replace
import importlib
import json
import threading
import unittest


embedding = importlib.import_module("app.modules.3_embeddingAndIndexing")
batching = importlib.import_module("app.modules.3_embeddingAndIndexing.batching")
scheduling = importlib.import_module("app.modules.3_embeddingAndIndexing.scheduling")
requests = importlib.import_module("app.modules.3_embeddingAndIndexing.requests")


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.delays = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.delays.append(seconds)
        self.now += seconds


class RecordingAdapter(embedding.DeterministicEmbeddingAdapter):
    def __init__(self, failures=0):
        super().__init__(3, token_counter=str.split)
        self.calls = []
        self.failures = failures

    def embed_role(self, texts, role):
        self.calls.append((tuple(texts), role))
        if self.failures:
            self.failures -= 1
            raise requests.ProviderError("retryable", "RATE_LIMITED", "retry later")
        return super().embed_role(texts, role)


class EmbeddingSchedulingTests(unittest.TestCase):
    def test_request_and_token_quotas_expire_each_charge_in_a_sliding_window(self):
        for options in ({"request_budget": 2}, {"token_budget": 2}):
            with self.subTest(options=options):
                clock = FakeClock()
                limiter = scheduling.LocalRateLimiter(window_seconds=10, clock=clock, sleeper=clock.sleep, **options)
                limiter.acquire(1)
                limiter.release()
                clock.now = 9
                limiter.acquire(1)
                limiter.release()
                clock.now = 10
                limiter.acquire(1)
                limiter.release()
                limiter.acquire(1)
                limiter.release()
                self.assertEqual(clock.delays, [9])
                self.assertEqual(clock.now, 19)

    def test_quota_persists_across_calls_and_uses_configured_window(self):
        clock = FakeClock()
        adapter = RecordingAdapter()
        options = dict(request_budget=1, rate_window_seconds=10, clock=clock, sleeper=clock.sleep)
        batching.embed_texts(["a"], adapter, **options)
        result = batching.embed_texts(["b"], adapter, **options)
        self.assertEqual(result.items[0].status, "embedded")
        self.assertEqual(clock.delays, [10])

    def test_each_retry_is_charged_request_and_prepared_token_quota(self):
        clock = FakeClock()
        adapter = RecordingAdapter(failures=1)
        config = embedding.EmbeddingRoleConfig("document", adapter.metadata.document_role.encoder_id, instruction="prefix ")
        adapter.metadata = adapter.metadata.with_changes(document_role=config)
        result = batching.embed_texts(["a"], adapter, request_budget=1, token_budget=2,
            rate_window_seconds=10, clock=clock, sleeper=clock.sleep, jitter=lambda: 0)
        self.assertEqual(result.items[0].status, "embedded")
        self.assertEqual(result.items[0].attempt_count, 2)
        self.assertEqual(result.items[0].retry_count, 1)
        self.assertEqual(clock.delays, [10])
        self.assertEqual(result.items[0].request.prepared_texts, ("prefix a",))

    def test_final_retry_count_and_identity_are_retained_after_success(self):
        clock = FakeClock()
        adapter = RecordingAdapter(failures=2)
        reservations = []
        result = batching.embed_texts(["a"], adapter, max_retries=2, clock=clock,
            sleeper=clock.sleep, jitter=lambda: 1, before_request=lambda request, attempt: reservations.append((request, attempt)))
        self.assertEqual(result.items[0].attempt_count, 3)
        self.assertEqual(result.items[0].retry_count, 2)
        self.assertEqual([attempt for _, attempt in reservations], [0, 1, 2])
        self.assertEqual(len({request.idempotency_key for request, _ in reservations}), 1)
        self.assertEqual(len({request.request_id for request, _ in reservations}), 1)
        self.assertEqual(clock.delays, [0.25, 0.5])

    def test_max_wait_bounds_quota_plus_retry_after_waits(self):
        class RetryAfter(RecordingAdapter):
            def embed_role(self, texts, role):
                self.calls.append((tuple(texts), role))
                raise requests.ProviderError("retryable", "RATE_LIMITED", "later", retry_after_seconds=20)
        clock = FakeClock()
        adapter = RetryAfter()
        result = batching.embed_texts(["a"], adapter, max_wait_seconds=2, max_retries=10,
            clock=clock, sleeper=clock.sleep)
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(result.items[0].status, "retryable")
        self.assertEqual(result.items[0].attempt_count, 1)
        self.assertEqual(clock.delays, [])

    def test_exhausted_shared_quota_returns_without_sending(self):
        clock = FakeClock()
        adapter = RecordingAdapter()
        options = dict(request_budget=1, rate_window_seconds=10, max_wait_seconds=0, clock=clock, sleeper=clock.sleep)
        batching.embed_texts(["a"], adapter, **options)
        result = batching.embed_texts(["b"], adapter, **options)
        self.assertEqual(result.items[0].status, "retryable")
        self.assertEqual(result.items[0].attempt_count, 0)
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(clock.delays, [])

    def test_batch_larger_than_token_window_is_split_and_oversize_item_rejected(self):
        clock = FakeClock()
        adapter = RecordingAdapter()
        result = batching.embed_texts(["a b", "c d", "e f g"], adapter, token_budget=2,
            clock=clock, sleeper=clock.sleep, rate_window_seconds=5)
        self.assertEqual([item.status for item in result.items], ["embedded", "embedded", "failed"])
        self.assertEqual(len(adapter.calls), 2)
        self.assertEqual(clock.delays, [5])
        limiter = scheduling.LocalRateLimiter(token_budget=2, clock=clock, sleeper=clock.sleep)
        with self.assertRaises(scheduling.QuotaCapacityExceeded):
            limiter.acquire(3)

    def test_nonadvancing_injected_clock_cannot_loop_forever(self):
        limiter = scheduling.LocalRateLimiter(request_budget=1, clock=lambda: 0, sleeper=lambda seconds: None)
        limiter.acquire(0)
        limiter.release()
        with self.assertRaises(scheduling.QuotaWaitExceeded):
            limiter.acquire(0, max_wait_seconds=2)

    def test_shared_limiter_enforces_cross_thread_concurrency(self):
        limiter = scheduling.LocalRateLimiter(max_concurrency=1)
        entered = threading.Event()
        release = threading.Event()
        results = []
        class Blocking(RecordingAdapter):
            def embed_role(self, texts, role):
                entered.set()
                release.wait(3)
                return super().embed_role(texts, role)
        adapter = Blocking()
        thread = threading.Thread(target=lambda: results.append(batching.embed_texts(["a"], adapter, limiter=limiter)))
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            blocked = batching.embed_texts(["b"], adapter, limiter=limiter, max_wait_seconds=0)
            self.assertEqual(blocked.items[0].status, "retryable")
            self.assertEqual(blocked.items[0].attempt_count, 0)
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].items[0].status, "embedded")

    def test_timeout_is_unknown_with_reloadable_identity_and_never_retried(self):
        class Timeout(RecordingAdapter):
            def embed_role(self, texts, role):
                self.calls.append((tuple(texts), role))
                error = TimeoutError("response lost")
                error.request_id = "remote-123"
                raise error
        adapter = Timeout()
        result = batching.embed_texts(["a", "b"], adapter, keys=["chunk-a", "chunk-b"], max_retries=10)
        self.assertEqual([item.status for item in result.items], ["unknown", "unknown"])
        self.assertEqual(len(adapter.calls), 1)
        item = result.items[0]
        self.assertEqual(item.request_id, "remote-123")
        self.assertEqual(item.attempt_count, 1)
        self.assertTrue(item.content_fingerprint)
        payload = json.loads(json.dumps(asdict(item.request)))
        self.assertEqual(requests.BatchRequest(**payload), item.request)
        self.assertEqual(batching.retry_failed(result, adapter), result)

    def test_resolution_requires_explicit_capability_and_validates_success_identity(self):
        class Resolver(RecordingAdapter):
            supports_status_query = True
            mismatch = False
            def embed_role(self, texts, role):
                raise TimeoutError("lost")
            def resolve_request(self, request):
                vectors = super().embed_role(request.texts, request.role)
                return requests.UnknownResolution(requests.RequestState.EMBEDDED, request.request_id,
                    "wrong" if self.mismatch else request.idempotency_key, request.keys, request.fingerprints, vectors)
        adapter = Resolver()
        unknown = batching.embed_texts(["a", "b"], adapter)
        with self.assertRaises(embedding.EmbeddingContractError):
            batching.resolve_unknown(unknown, RecordingAdapter())
        adapter.mismatch = True
        with self.assertRaisesRegex(embedding.EmbeddingContractError, "identity"):
            batching.resolve_unknown(unknown, adapter)
        adapter.mismatch = False
        recovered = batching.resolve_unknown(unknown, adapter)
        self.assertEqual([item.status for item in recovered.items], ["embedded", "embedded"])
        self.assertEqual([item.attempt_count for item in recovered.items], [1, 1])

    def test_resolution_rejects_bad_count_vector_and_tampered_request_content(self):
        class Resolver(RecordingAdapter):
            supports_status_query = True
            vectors = []
            def embed_role(self, texts, role):
                raise TimeoutError("lost")
            def resolve_request(self, request):
                return requests.UnknownResolution("embedded", request.request_id, request.idempotency_key,
                    request.keys, request.fingerprints, self.vectors)
        adapter = Resolver()
        unknown = batching.embed_texts(["a"], adapter)
        with self.assertRaisesRegex(embedding.EmbeddingContractError, "number"):
            batching.resolve_unknown(unknown, adapter)
        adapter.vectors = [(1.0,)]
        with self.assertRaisesRegex(embedding.EmbeddingContractError, "dimension"):
            batching.resolve_unknown(unknown, adapter)
        item = unknown.items[0]
        tampered = replace(item, request=replace(item.request, texts=("tampered",)))
        with self.assertRaisesRegex(embedding.EmbeddingContractError, "persisted request content"):
            batching.resolve_unknown(batching.EmbeddingBatchResult((tampered,)), adapter)

    def test_reused_provider_request_id_does_not_mix_distinct_batch_results(self):
        class ReusedProviderId(RecordingAdapter):
            supports_status_query = True
            resolutions = 0
            def embed_role(self, texts, role):
                raise requests.ProviderError("unknown", "LOST", "response lost", request_id="same-provider-id")
            def resolve_request(self, request):
                self.resolutions += 1
                vectors = embedding.DeterministicEmbeddingAdapter.embed_role(self, request.texts, request.role)
                return requests.UnknownResolution(requests.RequestState.EMBEDDED, request.request_id,
                    request.idempotency_key, request.keys, request.fingerprints, vectors)
        adapter = ReusedProviderId()
        pending = batching.embed_texts(["alpha", "beta"], adapter, max_batch_size=1)
        resolved = batching.resolve_unknown(pending, adapter)
        expected = embedding.DeterministicEmbeddingAdapter.embed_role(adapter, ["alpha", "beta"], "document")
        self.assertEqual(adapter.resolutions, 2)
        self.assertEqual([item.vector for item in resolved.items], expected)
        self.assertNotEqual(resolved.items[0].vector, resolved.items[1].vector)

    def test_undeclared_preparation_is_rejected_before_sending(self):
        class HiddenTransform(RecordingAdapter):
            def prepare_text(self, text, role):
                return super().prepare_text(text, role).lower()
        adapter = HiddenTransform()
        with self.assertRaisesRegex(embedding.EmbeddingContractError, "declared role input"):
            batching.embed_texts(["Alpha"], adapter)
        self.assertEqual(adapter.calls, [])

    def test_request_metadata_capability_is_explicit_and_receives_prepared_identity(self):
        class Metadata(RecordingAdapter):
            supports_request_metadata = True
            def embed_request(self, request):
                self.last = request
                return super().embed_role(request.texts, request.role)
        adapter = Metadata()
        result = batching.embed_texts(["a"], adapter, keys=["stable-key"])
        self.assertEqual(adapter.last.keys, ("stable-key",))
        self.assertEqual(result.items[0].request, adapter.last)

    def test_default_retry_limit_is_finite_and_exhaustion_retains_all_attempts(self):
        clock = FakeClock()
        adapter = RecordingAdapter(failures=100)
        result = batching.embed_texts(["a"], adapter, clock=clock, sleeper=clock.sleep, jitter=lambda: 0)
        self.assertEqual(len(adapter.calls), 3)
        self.assertEqual(result.items[0].status, "retryable")
        self.assertEqual(result.items[0].attempt_count, 3)
        self.assertEqual(result.items[0].retry_count, 2)
        self.assertIsNotNone(result.items[0].next_retry_at)

    def test_timeout_after_retry_retains_history_and_does_not_send_again(self):
        class LaterTimeout(RecordingAdapter):
            def embed_role(self, texts, role):
                self.calls.append((tuple(texts), role))
                if len(self.calls) == 1:
                    raise requests.ProviderError("retryable", "TEMPORARY", "later")
                raise TimeoutError("response lost")
        clock = FakeClock()
        adapter = LaterTimeout()
        result = batching.embed_texts(["a"], adapter, clock=clock, sleeper=clock.sleep, jitter=lambda: 0)
        self.assertEqual(result.items[0].status, "unknown")
        self.assertEqual(result.items[0].attempt_count, 2)
        self.assertEqual(result.items[0].retry_count, 1)
        self.assertEqual(len(adapter.calls), 2)

    def test_only_token_quota_charges_role_instruction_on_every_request(self):
        clock = FakeClock()
        adapter = RecordingAdapter()
        config = embedding.EmbeddingRoleConfig("query", adapter.metadata.query_role.encoder_id, instruction="two prefixes ")
        adapter.metadata = adapter.metadata.with_changes(query_role=config)
        result = batching.embed_texts(["a", "b"], adapter, role="query", token_budget=3,
            clock=clock, sleeper=clock.sleep, rate_window_seconds=7)
        self.assertEqual([item.status for item in result.items], ["embedded", "embedded"])
        self.assertEqual(clock.delays, [7])
        self.assertEqual([entry[1] for entry in adapter.calls], ["query", "query"])

    def test_failed_provider_calls_still_consume_shared_quota(self):
        clock = FakeClock()
        adapter = RecordingAdapter(failures=1)
        options = dict(request_budget=1, rate_window_seconds=9, clock=clock, sleeper=clock.sleep, max_retries=0)
        failed = batching.embed_texts(["a"], adapter, **options)
        self.assertEqual(failed.items[0].status, "retryable")
        recovered = batching.retry_failed(failed, adapter, **options)
        self.assertEqual(recovered.items[0].status, "embedded")
        self.assertEqual(recovered.items[0].attempt_count, 2)
        self.assertEqual(clock.delays, [9])

    def test_generic_errors_require_explicit_mapping_to_be_retryable(self):
        class Generic(RecordingAdapter):
            def embed_role(self, texts, role):
                self.calls.append((tuple(texts), role))
                raise RuntimeError("429")
            def map_error(self, error):
                return requests.ProviderError("retryable", "RATE_LIMITED", str(error))
        adapter = Generic()
        result = batching.embed_texts(["a"], adapter, max_retries=0)
        self.assertEqual(result.items[0].status, "failed")
        adapter.supports_error_mapping = True
        result = batching.embed_texts(["a"], adapter, max_retries=0)
        self.assertEqual(result.items[0].status, "retryable")


if __name__ == "__main__":
    unittest.main()
