"""模块 3 向模块 4（检索与融合）交接的检索契约。

模块 4 只通过模块 3 的公开导出消费检索能力。本文件把交接面的调用形态、命中字段、
分数语义、身份格式和错误语义固化为可执行断言，使交接面在模块 4 实现期间不能被无声
改变；如需变更，必须同时更新 ADR-0003 与本文件。
"""
import importlib
import inspect
import json
import unittest
from dataclasses import dataclass, fields

indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")


HANDOFF_EXPORTS = (
    "search_serving_chunks",
    "search_chunks",
    "resolve_query_request",
    "SearchHit",
    "ChunkRecord",
    "IndexSchemeVersion",
    "LogicalIndexIdentity",
    "EmbeddingContractError",
    "EmbeddingQueryError",
    "VectorStore",
    "PostgresVectorStore",
    "PhysicalIndexConfig",
)


@dataclass
class Attempt:
    attempt_id: str
    identity: object
    content_fingerprint: str
    request_payload: dict
    status: str = "pending"
    request_id: str | None = None
    idempotency_key: str | None = None
    error: str | None = None
    result_payload: dict | None = None


class ContractStore:
    """满足模块 3 存储协议的最小测试替身，记录检索入口实际收到的参数。"""

    def __init__(self, scheme, config):
        self.scheme = scheme
        self.config = config
        self.attempts = {}
        self.binding_reads = 0
        self.search_calls = []

    # 服务查询使用的活动绑定。
    def active_binding(self):
        self.binding_reads += 1
        return self.scheme, self.config

    # 持久化请求仓库。
    def get_attempt_for_identity(self, identity):
        return self.attempts.get(identity.key)

    def reserve_batch_attempts(self, identities, fingerprints, *, request_payload):
        created = []
        for identity, fingerprint in zip(identities, fingerprints):
            attempt = Attempt(identity.key, identity, fingerprint, request_payload,
                              request_id=request_payload.get("request_id"),
                              idempotency_key=request_payload.get("idempotency_key"))
            self.attempts[identity.key] = attempt
            created.append(attempt)
        return created

    def resolve_attempt(self, attempt_id, status, **options):
        for attempt in self.attempts.values():
            if attempt.attempt_id != attempt_id:
                continue
            expected = options.get("expected_request_id")
            if expected is not None and attempt.request_id is not None and expected != attempt.request_id:
                raise AssertionError("stale response cannot overwrite a newer request")
            attempt.status = status
            attempt.request_id = options.get("request_id", attempt.request_id)
            attempt.error = options.get("error")
            if options.get("result_payload") is not None:
                attempt.result_payload = dict(options["result_payload"])
            return
        raise KeyError(attempt_id)

    # 向量检索。
    def search(self, scheme, vector, limit=10, **options):
        self.search_calls.append({"scheme": scheme, "vector": vector,
                                   "limit": limit, "options": options})
        return []


class UncertainAdapter(indexing.DeterministicEmbeddingAdapter):
    """查询结果无法确认时进入未知状态的提供方替身。"""

    supports_request_metadata = True
    supports_status_query = True

    def embed_request(self, request):
        raise indexing.ProviderError("unknown", "TIMEOUT", "outcome unknown",
                                     request_id="provider-request")

    def resolve_request(self, request):
        return indexing.UnknownResolution("embedded", request.request_id, request.idempotency_key,
                                          request.keys, request.fingerprints,
                                          super().embed(request.prepared_texts))


class RetrievalHandoffContractTests(unittest.TestCase):
    def setUp(self):
        self.adapter = indexing.DeterministicEmbeddingAdapter(3)
        self.scheme = indexing.IndexSchemeVersion(self.adapter.metadata)
        self.config = object()
        self.store = ContractStore(self.scheme, self.config)

    def test_handoff_exports_remain_available(self):
        for name in HANDOFF_EXPORTS:
            with self.subTest(name=name):
                self.assertIn(name, indexing.__all__)
                self.assertIsNotNone(getattr(indexing, name, None))

    def test_search_entry_points_keep_their_call_shape(self):
        serving = inspect.signature(indexing.search_serving_chunks).parameters
        self.assertEqual([parameter.name for parameter in serving.values()],
                         ["query", "adapter_for_scheme", "store", "options"])
        self.assertIs(serving["options"].kind, inspect.Parameter.VAR_KEYWORD)

        search = inspect.signature(indexing.search_chunks).parameters
        self.assertEqual([parameter.name for parameter in search.values()],
                         ["query", "adapter", "store", "limit", "request_repository",
                          "batch_options", "search_options"])
        self.assertIs(search["limit"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(search["limit"].default, 10)
        self.assertIsNone(search["request_repository"].default)
        self.assertIsNone(search["batch_options"].default)
        self.assertIs(search["search_options"].kind, inspect.Parameter.VAR_KEYWORD)

        resolve = inspect.signature(indexing.resolve_query_request).parameters
        self.assertEqual([parameter.name for parameter in resolve.values()],
                         ["result", "adapter", "store", "request_repository", "limit", "search_options"])
        self.assertIs(resolve["limit"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(resolve["limit"].default, 10)
        self.assertIsNone(resolve["request_repository"].default)
        self.assertIs(resolve["search_options"].kind, inspect.Parameter.VAR_KEYWORD)

    def test_hit_and_chunk_records_keep_their_fields(self):
        self.assertEqual([field.name for field in fields(indexing.SearchHit)],
                         ["chunk", "score", "scheme_identity", "content_fingerprint",
                          "fingerprint_algorithm", "generated_at"])
        self.assertEqual([field.name for field in fields(indexing.ChunkRecord)],
                         ["chunk_id", "document_id", "document_version", "text",
                          "metadata", "chunk_version"])
        chunk = indexing.ChunkRecord("c1", "doc", "revision-1", "alpha",
                                      {"source_ids": ["src"]}, "chunk-revision-1")
        self.assertEqual(chunk.version, "revision-1")

    def test_scheme_identity_format_is_stable(self):
        identity = self.scheme.identity
        self.assertTrue(identity.startswith("scheme:v2:"))
        digest = identity.split(":", 2)[2]
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(character in "0123456789abcdef" for character in digest))
        legacy = indexing.EmbeddingMetadata("test", "legacy", "v1", 3)
        self.assertFalse(legacy.verifiable)
        self.assertTrue(indexing.IndexSchemeVersion(legacy).identity.startswith("legacy:"))

    def test_logical_identity_key_is_the_deduplication_key(self):
        identity = indexing.LogicalIndexIdentity("doc", "revision-1", "c1",
                                                 self.scheme.identity, "chunk-revision-1")
        self.assertEqual(identity.key, json.dumps(
            ["doc", "revision-1", "c1", self.scheme.identity, "chunk-revision-1"],
            ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        self.assertNotEqual(identity.key, indexing.LogicalIndexIdentity(
            "doc", "revision-1", "c1", self.scheme.identity, "chunk-revision-2").key)

    def test_serving_query_reads_the_active_binding_once_and_uses_its_configuration(self):
        selected = []

        def adapter_for_scheme(scheme):
            selected.append(scheme)
            return self.adapter

        hits = indexing.search_serving_chunks("alpha", adapter_for_scheme, self.store)
        self.assertEqual(hits, [])
        self.assertEqual(self.store.binding_reads, 1)
        self.assertIs(selected[0], self.scheme)
        call = self.store.search_calls[0]
        self.assertEqual(call["scheme"], self.scheme)
        self.assertEqual(call["scheme"].identity, self.scheme.identity)
        self.assertIs(call["options"]["config"], self.config)

    def test_serving_query_rejects_an_externally_supplied_configuration(self):
        with self.assertRaisesRegex(indexing.EmbeddingContractError,
                                    "active physical configuration"):
            indexing.search_serving_chunks("alpha", lambda scheme: self.adapter,
                                           self.store, config=object())
        self.assertEqual(self.store.binding_reads, 0)
        self.assertEqual(self.store.search_calls, [])

    def test_query_failure_surfaces_as_query_error_with_its_result(self):
        class Malformed(indexing.DeterministicEmbeddingAdapter):
            def embed_role(self, texts, role):
                return [(float("nan"),) * 3]

        with self.assertRaises(indexing.EmbeddingQueryError) as error:
            indexing.search_chunks("alpha", Malformed(3), self.store)
        self.assertEqual(error.exception.result.items[0].status, "failed")

    def test_unknown_query_is_reported_and_can_be_reconciled(self):
        adapter = UncertainAdapter(3)
        with self.assertRaises(indexing.EmbeddingQueryError) as error:
            indexing.search_chunks("alpha", adapter, self.store)
        result = error.exception.result
        self.assertEqual(result.items[0].status, "unknown")
        hits = indexing.resolve_query_request(result, adapter, self.store)
        self.assertEqual(hits, [])
        self.assertEqual(len(self.store.search_calls), 1)

    def test_vector_store_protocol_declares_the_retrieval_surface(self):
        members = {name for name, _ in inspect.getmembers(indexing.VectorStore, inspect.isfunction)}
        self.assertIn("upsert", members)
        self.assertIn("search", members)


if __name__ == "__main__":
    unittest.main()
