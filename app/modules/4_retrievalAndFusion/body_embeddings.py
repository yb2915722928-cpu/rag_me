"""Final-body encoding through module3's public batch and durable request APIs."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib
import math
from typing import Sequence

from app.models.embedding import IndexSchemeVersion, LogicalIndexIdentity, content_fingerprint


class BodyEncodingError(ValueError):
    """Only fixed, non-sensitive codes cross the postprocessing boundary."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class BodyVector:
    scheme_identity: str
    fingerprint_algorithm: str
    body_fingerprint: str
    vector: tuple[float, ...]

    @classmethod
    def for_text(cls, text, scheme, vector):
        algorithm, fingerprint = content_fingerprint(text, scheme.metadata, "document")
        return cls(scheme.identity, algorithm, fingerprint, tuple(vector))

    def matches(self, text, scheme):
        algorithm, fingerprint = content_fingerprint(text, scheme.metadata, "document")
        return (self.scheme_identity, self.fingerprint_algorithm, self.body_fingerprint) == (
            scheme.identity, algorithm, fingerprint)

    def unit_vector(self, scheme):
        if (self.scheme_identity != scheme.identity or len(self.vector) != scheme.metadata.dimensions
                or any(isinstance(value, (bool, str, bytes)) for value in self.vector)):
            raise BodyEncodingError("mmr_invalid_vector")
        try:
            values = tuple(float(value) for value in self.vector)
            if not all(math.isfinite(value) for value in values):
                raise ValueError
            scale = max(abs(value) for value in values)
            if not scale:
                raise ValueError
            scaled = tuple(value / scale for value in values)
            norm = math.sqrt(math.fsum(value * value for value in scaled))
            if scheme.metadata.normalization == "unit" and abs(scale * norm - 1.0) > 1e-6:
                raise ValueError
            return tuple(value / norm for value in scaled)
        except (ValueError, TypeError, OverflowError):
            raise BodyEncodingError("mmr_invalid_vector") from None


class Module3BodyEncoder:
    """Encode document-role bodies; never manufacture successful module3 outcomes.

    A caller-owned cache is optional and keyed by the *full* scheme identity and
    exact document-role fingerprint. A durable RequestRepository is required on
    cache misses. Pending/unknown attempts are never automatically resubmitted.
    The caller owns provider/network configuration and the repository lifecycle.
    """

    def __init__(self, adapter, request_repository, *, cache=None, reusable=(), max_batch_size=64):
        self.adapter = adapter
        self.scheme = IndexSchemeVersion(adapter.metadata)
        adapter.validate_scheme(self.scheme)
        self.repository = request_repository
        self.cache = cache if cache is not None else {}
        self.reusable = tuple(reusable)
        self.max_batch_size = max_batch_size

    def encode(self, texts: Sequence[str], *, remaining) -> tuple[BodyVector, ...]:
        from .deadline import deadline_scope

        # Repository adapters retain their public signatures while reading the
        # same root budget through the #87 context-local deadline boundary.
        with deadline_scope(remaining):
            return self._encode(texts, remaining=remaining)

    def _encode(self, texts, *, remaining):
        api = importlib.import_module("app.modules.3_embeddingAndIndexing")
        remaining.check()
        # Bind the adapter's metadata throughout this call, including durable reuse.
        self.adapter.validate_scheme(self.scheme)
        unique = {}
        requested = []
        for text in texts:
            remaining.check()
            algorithm, fingerprint = content_fingerprint(text, self.scheme.metadata, "document")
            key = (self.scheme.identity, algorithm, fingerprint)
            requested.append(key)
            unique.setdefault(key, text)
        resolved, pending, identities = {}, {}, {}
        for key, text in unique.items():
            remaining.check()
            entry = self.cache.get(key)
            if entry is not None and (not isinstance(entry, BodyVector) or not entry.matches(text, self.scheme)):
                entry = None
            if entry is None:
                entry = next((vector for vector in self.reusable
                              if isinstance(vector, BodyVector) and vector.matches(text, self.scheme)), None)
            if entry is not None:
                entry.unit_vector(self.scheme)
                resolved[key] = entry
                continue
            # These are request identities, not new evidence identities or index rows.
            identity = LogicalIndexIdentity("retrieval-mmr-body", "v1", key[2], self.scheme.identity, "v1")
            identities[identity.key] = identity
            remaining.check()
            attempt = self.repository.get_attempt_for_identity(identity)
            remaining.check()
            if attempt is not None:
                entry = self._restore(attempt, identity, text, api)
                resolved[key] = entry
            else:
                pending[identity.key] = (key, text)

        def reserve(request, attempt_number):
            remaining.check()
            if attempt_number:
                raise BodyEncodingError("mmr_encoding_failed")
            self.repository.reserve_batch_attempts([identities[key] for key in request.keys],
                request.fingerprints, request_payload=asdict(request))
            remaining.check()

        def persist(result):
            # Durable receipts preserve module3's actual outcome, even if the
            # caller's budget has expired. No late result is accepted by MMR.
            for item in result.items:
                attempt = self.repository.get_attempt_for_identity(identities[item.key])
                if attempt is None:
                    continue  # Rejected before submission: no provider request exists.
                state = "succeeded" if item.status == "embedded" else item.status
                if state not in {"succeeded", "failed", "retryable", "unknown"}:
                    raise BodyEncodingError("mmr_encoding_failed")
                self.repository.resolve_attempt(attempt.attempt_id, state,
                    request_id=item.request_id, expected_request_id=attempt.request_id,
                    error=item.reason, request_payload=asdict(item.request) if item.request else None,
                    result_payload={"vector": list(item.vector) if item.vector is not None else None,
                                    "error_code": item.error_code,
                                    "fingerprint_algorithm": item.fingerprint_algorithm})

        if pending:
            remaining.check()
            # The #87 public module3 extension passes this exact object down to
            # the provider. Older implementations fail closed with TypeError.
            result = api.embed_texts([text for _, text in pending.values()], self.adapter,
                scheme=self.scheme, role="document", keys=tuple(pending),
                max_batch_size=self.max_batch_size, max_retries=0,
                before_request=reserve, after_batch=persist, remaining=remaining)
            remaining.check()
            if len(result.items) != len(pending) or {item.key for item in result.items} != set(pending):
                raise BodyEncodingError("mmr_invalid_vector")
            for item in result.items:
                key, text = pending[item.key]
                if item.status != "embedded":
                    if item.error_code in {"EMBEDDING_TIMEOUT", "DEADLINE_EXCEEDED"}:
                        raise TimeoutError
                    raise BodyEncodingError("mmr_encoding_failed")
                if (item.text != text or item.role != "document" or item.vector is None
                        or item.content_fingerprint != key[2] or item.fingerprint_algorithm != key[1]
                        or item.request is None or item.request.scheme_identity != self.scheme.identity):
                    raise BodyEncodingError("mmr_invalid_vector")
                entry = BodyVector(self.scheme.identity, key[1], key[2], tuple(item.vector))
                entry.unit_vector(self.scheme)
                resolved[key] = entry
        remaining.check()
        # Commit cache only after every needed body is validated. Never expose a
        # partly valid pool to MMR; durable receipts independently retain outcomes.
        self.cache.update(resolved)
        return tuple(resolved[key] for key in requested)

    def _restore(self, attempt, identity, text, api):
        if attempt.status != "succeeded":
            raise BodyEncodingError("mmr_encoding_unresolved")
        payload = attempt.request_payload
        if not payload:
            raise BodyEncodingError("mmr_invalid_vector")
        request = api.BatchRequest(**payload)
        algorithm, fingerprint = content_fingerprint(text, self.scheme.metadata, "document")
        if (attempt.identity != identity or attempt.content_fingerprint != fingerprint
                or request.scheme_identity != self.scheme.identity or request.role != "document"
                or identity.key not in request.keys or request.fingerprint_algorithm != algorithm):
            raise BodyEncodingError("mmr_invalid_vector")
        position = request.keys.index(identity.key)
        if (request.texts[position] != text or request.fingerprints[position] != fingerprint
                or request.prepared_texts[position] != self.adapter.prepare_text(text, "document")):
            raise BodyEncodingError("mmr_invalid_vector")
        vector = (attempt.result_payload or {}).get("vector")
        if vector is None:
            raise BodyEncodingError("mmr_invalid_vector")
        entry = BodyVector(self.scheme.identity, algorithm, fingerprint, tuple(vector))
        entry.unit_vector(self.scheme)
        return entry
