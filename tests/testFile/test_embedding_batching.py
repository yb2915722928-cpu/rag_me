from dataclasses import replace
import importlib
import unittest


embedding = importlib.import_module("app.modules.3_embeddingAndIndexing")
batching = importlib.import_module("app.modules.3_embeddingAndIndexing.batching")
requests = importlib.import_module("app.modules.3_embeddingAndIndexing.requests")


class FailingAdapter(embedding.DeterministicEmbeddingAdapter):
    def embed(self, texts):
        if "bad" in texts:
            raise requests.ProviderError("retryable", "TEMPORARY_CAPACITY", "temporary failure")
        return super().embed(texts)


class MalformedVectorAdapter(embedding.DeterministicEmbeddingAdapter):
    def embed(self, texts):
        vectors = super().embed(texts)
        vectors[1] = (float("nan"),) * self.metadata.dimensions
        return vectors


class EmbeddingBatchingTests(unittest.TestCase):
    def test_batches_obey_item_and_token_limits_in_input_order(self):
        adapter = embedding.DeterministicEmbeddingAdapter(dimensions=3, token_counter=str.split)
        result = batching.embed_texts(["a b", "c", "d e f", "g"], adapter, max_batch_size=3, max_tokens=3)
        self.assertEqual([item.key for item in result.items], ["0", "1", "2", "3"])
        self.assertEqual([item.status for item in result.items], ["embedded"] * 4)
        self.assertEqual(result.items[0].vector, adapter.embed(["a b"])[0])

    def test_failed_batch_preserves_success_and_retry_is_idempotent_by_identity(self):
        adapter = FailingAdapter(dimensions=3, token_counter=str.split)
        result = batching.embed_texts(["ok", "bad", "fine"], adapter, max_batch_size=1, max_retries=0)
        self.assertEqual([item.status for item in result.items], ["embedded", "retryable", "embedded"])
        retried = batching.retry_failed(result, adapter, keys={"1"}, max_retries=0)
        self.assertEqual([item.status for item in retried.items], ["embedded", "retryable", "embedded"])
        fixed = batching.retry_failed(result, embedding.DeterministicEmbeddingAdapter(3), keys={"1"})
        self.assertEqual([item.status for item in fixed.items], ["embedded"] * 3)
        self.assertEqual(len({item.key for item in fixed.items}), 3)
        self.assertEqual(fixed.items[1].retry_count, 1)
        self.assertEqual(fixed.items[1].attempt_count, 2)
        self.assertEqual(fixed.items[1].idempotency_key, result.items[1].idempotency_key)
        self.assertEqual(fixed.items[1].content_fingerprint, result.items[1].content_fingerprint)

    def test_malformed_vector_fails_only_its_own_item_and_cannot_be_retried(self):
        adapter = MalformedVectorAdapter(3)
        result = batching.embed_texts(["good", "bad", "also good"], adapter)
        self.assertEqual([item.status for item in result.items], ["embedded", "failed", "embedded"])
        self.assertEqual(result.items[1].error_code, "EMBEDDING_CONTRACT")
        self.assertEqual(batching.retry_failed(result, adapter), result)

    def test_empty_input_and_single_oversized_input_are_explicit(self):
        adapter = embedding.DeterministicEmbeddingAdapter(dimensions=3, token_counter=str.split)
        self.assertEqual(batching.embed_texts([], adapter).items, ())
        result = batching.embed_texts(["one two"], adapter, max_tokens=1)
        self.assertEqual(result.items[0].status, "failed")
        self.assertEqual(result.items[0].error_code, "ITEM_EXCEEDS_TOKEN_BUDGET")
        self.assertIsNotNone(result.items[0].content_fingerprint)
        self.assertTrue(result.items[0].diagnostics)
        self.assertEqual(result.items[0].attempt_count, 0)
        self.assertEqual(batching.retry_failed(result, adapter, keys={"0"}, max_tokens=1), result)

    def test_role_instruction_counts_toward_token_limits_for_int_and_sequence_counters(self):
        for counter in (str.split, lambda text: len(text.split())):
            adapter = embedding.DeterministicEmbeddingAdapter(3, token_counter=counter)
            role = embedding.EmbeddingRoleConfig("document", adapter.metadata.document_role.encoder_id, instruction="instruction ")
            adapter.metadata = adapter.metadata.with_changes(document_role=role)
            result = batching.embed_texts(["one two"], adapter, max_tokens=2)
            self.assertEqual(result.items[0].error_code, "ITEM_EXCEEDS_TOKEN_BUDGET")

    def test_truncation_requires_explicit_policy_and_retains_diagnostics(self):
        with self.assertRaises(ValueError):
            batching.LongInputPolicy("truncate")
        adapter = embedding.DeterministicEmbeddingAdapter(3, token_counter=str.split)
        policy = batching.LongInputPolicy("truncate", "first-token-v1", lambda text, mode: [text.split()[0]])
        adapter.metadata = adapter.metadata.with_changes(document_role=replace(adapter.metadata.document_role, tokenizer_policy=policy.policy_id))
        result = batching.embed_texts(["a b c"], adapter, max_tokens=1, long_input_policy=policy)
        item = result.items[0]
        self.assertEqual(item.text, "a")
        self.assertEqual(item.status, "embedded")
        self.assertTrue(item.version_suffix)
        self.assertIn("new chunk revision required", item.diagnostics[-1])
        self.assertEqual(item.vector, adapter.embed_role(["a"], "document")[0])

    def test_rechunk_is_explicit_preparation_with_new_revision_suffixes(self):
        adapter = embedding.DeterministicEmbeddingAdapter(3, token_counter=str.split)
        policy = batching.LongInputPolicy("rechunk", "words-v1", lambda text, mode: text.split())
        adapter.metadata = adapter.metadata.with_changes(document_role=replace(adapter.metadata.document_role, tokenizer_policy=policy.policy_id))
        prepared = batching.prepare_long_inputs(["a b"], adapter, max_tokens=1, policy=policy)
        self.assertEqual([entry.parent_index for entry in prepared], [0, 0])
        self.assertEqual([entry.text for entry in prepared], ["a", "b"])
        self.assertEqual(len({entry.version_suffix for entry in prepared}), 2)
        self.assertEqual(prepared, batching.prepare_long_inputs(["a b"], adapter, max_tokens=1, policy=policy))
        with self.assertRaisesRegex(ValueError, "explicit new Chunk"):
            batching.embed_texts(["a b"], adapter, max_tokens=1, long_input_policy=policy)
        result = batching.embed_texts([entry.text for entry in prepared], adapter, max_tokens=1,
            prepared_inputs=prepared, keys=["new-a", "new-b"])
        self.assertEqual([item.version_suffix for item in result.items], [entry.version_suffix for entry in prepared])

    def test_transform_output_still_over_limit_is_rejected(self):
        adapter = embedding.DeterministicEmbeddingAdapter(3, token_counter=str.split)
        policy = batching.LongInputPolicy("truncate", "bad-handler", lambda text, mode: [text])
        adapter.metadata = adapter.metadata.with_changes(document_role=replace(adapter.metadata.document_role, tokenizer_policy=policy.policy_id))
        with self.assertRaisesRegex(ValueError, "still exceeds"):
            batching.prepare_long_inputs(["a b"], adapter, max_tokens=1, policy=policy)

    def test_plain_failure_auth_failure_and_bad_vector_are_not_retryable(self):
        class AuthAdapter(embedding.DeterministicEmbeddingAdapter):
            def embed_role(self, texts, role):
                raise requests.ProviderError("failed", "AUTHENTICATION_FAILED", "bad credential")
        result = batching.embed_texts(["a"], AuthAdapter(3))
        self.assertEqual(result.items[0].attempt_count, 1)
        self.assertEqual(result.items[0].status, "failed")
        self.assertEqual(batching.retry_failed(result, AuthAdapter(3)), result)

    def test_mixed_roles_are_retried_with_their_original_role(self):
        class RetryAdapter(embedding.DeterministicEmbeddingAdapter):
            def embed_role(self, texts, role):
                raise requests.ProviderError("retryable", "TEMPORARY", "later")
        adapter = RetryAdapter(3)
        document = batching.embed_texts(["a"], adapter, keys=["d"], role="document", max_retries=0)
        query = batching.embed_texts(["b"], adapter, keys=["q"], role="query", max_retries=0)
        result = batching.retry_failed(batching.EmbeddingBatchResult(document.items + query.items), embedding.DeterministicEmbeddingAdapter(3))
        self.assertEqual([item.role for item in result.items], ["document", "query"])
        self.assertEqual([item.status for item in result.items], ["embedded", "embedded"])

    def test_reservation_callback_failure_propagates_without_sending(self):
        class Counting(embedding.DeterministicEmbeddingAdapter):
            calls = 0
            def embed_role(self, texts, role):
                self.calls += 1
                return super().embed_role(texts, role)
        adapter = Counting(3)
        def fail(request, attempt):
            self.assertEqual(attempt, 0)
            raise RuntimeError("reservation conflict")
        with self.assertRaisesRegex(RuntimeError, "reservation conflict"):
            batching.embed_texts(["a"], adapter, before_request=fail)
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(batching.embed_texts(["a"], adapter).items[0].status, "embedded")
    def test_transformation_policy_requires_explicit_matching_role_configuration(self):
        adapter = embedding.DeterministicEmbeddingAdapter(3, token_counter=str.split)
        for policy_id in ("identity", "truncate-first-v1"):
            policy = batching.LongInputPolicy("truncate", policy_id, lambda text, mode: [text.split()[0]])
            with self.assertRaisesRegex(embedding.EmbeddingContractError, "non-identity tokenizer_policy"):
                batching.prepare_long_inputs(["a"], adapter, max_tokens=1, policy=policy)
        adapter.metadata = adapter.metadata.with_changes(document_role=replace(adapter.metadata.document_role, tokenizer_policy="truncate-first-v1"))
        mismatch = batching.LongInputPolicy("truncate", "truncate-first-v2", lambda text, mode: [text.split()[0]])
        with self.assertRaisesRegex(embedding.EmbeddingContractError, "policy_id must match"):
            batching.embed_texts(["a b"], adapter, max_tokens=1, long_input_policy=mismatch)
        matching = batching.LongInputPolicy("truncate", "truncate-first-v1", lambda text, mode: [text.split()[0]])
        with self.assertRaisesRegex(embedding.EmbeddingContractError, "policy_id must match"):
            batching.prepare_long_inputs(["a b"], adapter, max_tokens=1, role="query", policy=matching)
        adapter.metadata = adapter.metadata.with_changes(query_role=replace(adapter.metadata.query_role, tokenizer_policy=matching.policy_id))
        prepared = batching.prepare_long_inputs(["a b"], adapter, max_tokens=1, role="query", policy=matching)
        self.assertEqual(prepared[0].text, "a")

    def test_processing_policy_changes_scheme_and_fingerprint_for_identical_output(self):
        fingerprints, schemes = [], []
        for policy_id in ("truncate-first-v1", "truncate-first-v2"):
            adapter = embedding.DeterministicEmbeddingAdapter(3, token_counter=str.split)
            adapter.metadata = adapter.metadata.with_changes(document_role=replace(adapter.metadata.document_role, tokenizer_policy=policy_id))
            policy = batching.LongInputPolicy("truncate", policy_id, lambda text, mode: [text.split()[0]])
            result = batching.embed_texts(["a b"], adapter, max_tokens=1, long_input_policy=policy)
            self.assertEqual(result.items[0].text, "a")
            fingerprints.append(result.items[0].content_fingerprint)
            schemes.append(result.items[0].request.scheme_identity)
        self.assertNotEqual(fingerprints[0], fingerprints[1])
        self.assertNotEqual(schemes[0], schemes[1])

    def test_after_batch_persists_completed_batch_before_later_reservation_failure(self):
        adapter = embedding.DeterministicEmbeddingAdapter(3)
        events, persisted = [], []
        def reserve(request, attempt):
            events.append(("before", request.keys))
            if request.keys == ("1",):
                raise RuntimeError("second batch reservation failed")
        def persist(result):
            events.append(("after", tuple(item.key for item in result.items)))
            persisted.extend(result.items)
        with self.assertRaisesRegex(RuntimeError, "second batch reservation failed"):
            batching.embed_texts(["first", "second"], adapter, max_batch_size=1, before_request=reserve, after_batch=persist)
        self.assertEqual(events, [("before", ("0",)), ("after", ("0",)), ("before", ("1",))])
        self.assertEqual([(item.key, item.status, item.attempt_count) for item in persisted], [("0", "embedded", 1)])

    def test_after_batch_failure_propagates_and_stops_later_sends(self):
        class Counting(embedding.DeterministicEmbeddingAdapter):
            calls = 0
            def embed_role(self, texts, role):
                self.calls += 1
                return super().embed_role(texts, role)
        adapter = Counting(3)
        def fail(result):
            self.assertEqual([item.status for item in result.items], ["embedded"])
            raise RuntimeError("result persistence failed")
        with self.assertRaisesRegex(RuntimeError, "result persistence failed"):
            batching.embed_texts(["first", "second"], adapter, max_batch_size=1, after_batch=fail)
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(batching.embed_texts(["third"], adapter).items[0].status, "embedded")

    def test_after_batch_receives_finalized_contract_failures_and_retryable_batches(self):
        persisted = []
        result = batching.embed_texts(["good", "bad", "also good"], MalformedVectorAdapter(3), after_batch=persisted.append)
        self.assertEqual(persisted, [result])
        self.assertEqual([item.status for item in persisted[0].items], ["embedded", "failed", "embedded"])
        persisted.clear()
        result = batching.embed_texts(["bad"], FailingAdapter(3), max_retries=0, after_batch=persisted.append)
        self.assertEqual(persisted, [result])
        self.assertEqual(persisted[0].items[0].status, "retryable")


if __name__ == "__main__":
    unittest.main()
