"""Exercise the real module3 batch path with controlled provider/repository ports.

Authored only. The remaining API requires integrated #87, not a monkeypatched
embed_texts result. These tests do not claim a remote model deployment exists.
"""
from dataclasses import dataclass, replace
import importlib

import pytest

embedding = importlib.import_module("app.modules.3_embeddingAndIndexing")
body = importlib.import_module("app.modules.4_retrievalAndFusion.body_embeddings")


class Budget:
    expired = False

    def check(self):
        if self.expired:
            raise TimeoutError("expired")

    def remaining(self):
        self.check()
        return 10.0


@dataclass
class Attempt:
    attempt_id: str
    identity: object
    content_fingerprint: str
    request_id: str
    status: str
    request_payload: dict
    result_payload: dict | None = None


class Repository:
    """RequestRepository test port, retained across encoder instances."""

    def __init__(self):
        self.attempts = {}

    def get_attempt_for_identity(self, identity):
        return self.attempts.get(identity.key)

    def reserve_batch_attempts(self, identities, fingerprints, *, request_payload):
        if any(identity.key in self.attempts for identity in identities):
            raise ValueError("duplicate request")
        created = []
        for identity, fingerprint in zip(identities, fingerprints):
            attempt = Attempt(identity.key, identity, fingerprint, request_payload["request_id"],
                              "pending", request_payload)
            self.attempts[identity.key] = attempt
            created.append(attempt)
        return created

    def resolve_attempt(self, attempt_id, status, *, request_id=None, expected_request_id=None,
                        error=None, result_payload=None, request_payload=None):
        attempt = self.attempts[attempt_id]
        if attempt.request_id != expected_request_id:
            raise ValueError("stale resolution")
        attempt.status = status
        attempt.request_id = request_id or attempt.request_id
        attempt.result_payload = result_payload
        attempt.request_payload = request_payload


class Provider(embedding.DeterministicEmbeddingAdapter):
    supports_deadline = True

    def __init__(self):
        super().__init__(2)
        self.inputs = []
        self.budgets = []

    def embed_role(self, texts, role, *, remaining=None):
        remaining.check()
        self.inputs.append((tuple(texts), role))
        self.budgets.append(remaining)
        return [(1.0, 0.0) if "parent" in text else (0.0, 1.0) for text in texts]


def test_real_batch_encodes_actual_bodies_once_and_durable_results_survive_encoder_recreation():
    provider, repository, budget = Provider(), Repository(), Budget()
    encoder = body.Module3BodyEncoder(provider, repository)
    entries = encoder.encode(("full parent body", "FAQ answer", "full parent body"), remaining=budget)
    assert provider.inputs == [(("full parent body", "FAQ answer"), "document")]
    assert provider.budgets == [budget]
    assert entries[0] == entries[2]
    assert entries[0].vector == (1.0, 0.0)
    assert entries[1].vector == (0.0, 1.0)
    restored = body.Module3BodyEncoder(provider, repository).encode(
        ("FAQ answer", "full parent body"), remaining=budget)
    assert restored == (entries[1], entries[0])
    assert len(provider.inputs) == 1


def test_only_same_full_scheme_and_exact_body_fingerprint_are_reused():
    provider, repository, budget = Provider(), Repository(), Budget()
    scheme = embedding.IndexSchemeVersion(provider.metadata)
    valid = body.BodyVector.for_text("exact answer", scheme, (0, 1))
    wrong_body = body.BodyVector.for_text("FAQ question", scheme, (1, 0))
    wrong_model = replace(valid, scheme_identity=embedding.IndexSchemeVersion(
        replace(provider.metadata, model_revision="v2")).identity)
    encoder = body.Module3BodyEncoder(provider, repository, reusable=(valid, wrong_body, wrong_model))
    entries = encoder.encode(("exact answer", "new answer", "full parent body"), remaining=budget)
    assert entries[0] == valid
    assert provider.inputs == [(("new answer", "full parent body"), "document")]


@pytest.mark.parametrize("change", [{"model_revision": "v2"}, {"chunking_policy": "other"},
                                    {"document_role": embedding.EmbeddingRoleConfig("document", "other") }])
def test_shared_cache_does_not_cross_model_revision_or_configuration(change):
    provider, repository, budget, cache = Provider(), Repository(), Budget(), {}
    first = body.Module3BodyEncoder(provider, repository, cache=cache)
    first.encode(("answer",), remaining=budget)
    other = Provider()
    other.metadata = replace(other.metadata, **change)
    second = body.Module3BodyEncoder(other, repository, cache=cache)
    second.encode(("answer",), remaining=budget)
    assert len(other.inputs) == 1
    assert len(cache) == 2


def test_unknown_provider_outcome_is_durable_and_never_silently_retried():
    class UncertainProvider(Provider):
        def embed_role(self, texts, role, *, remaining=None):
            self.inputs.append((tuple(texts), role))
            raise TimeoutError("private remote endpoint and body")

    provider, repository, budget = UncertainProvider(), Repository(), Budget()
    with pytest.raises(TimeoutError):
        body.Module3BodyEncoder(provider, repository).encode(("answer",), remaining=budget)
    with pytest.raises(body.BodyEncodingError) as caught:
        body.Module3BodyEncoder(provider, repository).encode(("answer",), remaining=budget)
    assert caught.value.code == "mmr_encoding_unresolved"
    assert len(provider.inputs) == 1
    assert next(iter(repository.attempts.values())).status == "unknown"


def test_late_success_is_not_accepted_or_cached():
    class LateProvider(Provider):
        def embed_role(self, texts, role, *, remaining=None):
            vectors = super().embed_role(texts, role, remaining=remaining)
            remaining.expired = True
            return vectors

    provider, repository, budget, cache = LateProvider(), Repository(), Budget(), {}
    with pytest.raises(TimeoutError):
        body.Module3BodyEncoder(provider, repository, cache=cache).encode(("answer",), remaining=budget)
    assert cache == {}


def test_expired_budget_prevents_even_durable_or_cache_reuse():
    provider, repository, budget = Provider(), Repository(), Budget()
    encoder = body.Module3BodyEncoder(provider, repository)
    encoder.encode(("answer",), remaining=budget)
    budget.expired = True
    with pytest.raises(TimeoutError):
        encoder.encode(("answer",), remaining=budget)
    assert len(provider.inputs) == 1


def test_invalid_matching_cached_vector_fails_the_whole_encoding_call():
    provider, repository, budget = Provider(), Repository(), Budget()
    scheme = embedding.IndexSchemeVersion(provider.metadata)
    invalid = body.BodyVector.for_text("answer", scheme, (0, 0))
    encoder = body.Module3BodyEncoder(provider, repository, reusable=(invalid,))
    with pytest.raises(body.BodyEncodingError) as caught:
        encoder.encode(("answer", "full parent body"), remaining=budget)
    assert caught.value.code == "mmr_invalid_vector"
    assert provider.inputs == []
