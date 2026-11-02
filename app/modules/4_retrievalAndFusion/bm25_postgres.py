"""One synchronous content/vector/BM25 prepare and publication interface.

No services are started here. Call migrate explicitly on an already provisioned
PostgreSQL instance. SQL/backend compatibility has NOT been integration-tested.
"""
from pathlib import Path
from typing import Iterable, Mapping

from .bm25 import BM25Analyzer, BM25Candidate, BM25QueryResult, text_match
from .bm25_resources import DocumentBM25Resources
from .contracts import (ContentRecord, EvidenceIdentity, ReadScope, RetrievalContractError,
                        SnapshotNotReady, required_strings)
from .vector import PostgresVectorRetrievalStore


class PostgresBM25RetrievalStore(PostgresVectorRetrievalStore):
    """Extends the vector store with a physically isolated document BM25 corpus.

    prepare(..., required_indexes=('content', 'vector', 'bm25'), vector_scheme=...)
    builds both resources in the same snapshot transaction before publication.
    bm25_identities explicitly chooses retrieval units; unindexed parents remain
    readable through the same scope. None indexes all selected content identities.
    """
    supported_indexes = PostgresVectorRetrievalStore.supported_indexes | frozenset({"bm25"})

    def migrate(self) -> None:
        super().migrate()
        migration = Path(__file__).with_name("migrations") / "003_document_bm25.sql"
        with self._transaction() as cursor:
            cursor.execute(migration.read_text(encoding="utf-8").format(schema=self._namespace))
            DocumentBM25Resources.check_runtime(cursor)

    def prepare(self, knowledge_base_id: str, snapshot_id: str,
                identities: Iterable[EvidenceIdentity], *,
                required_indexes: Iterable[str] = ("content", "bm25"),
                field_types: Mapping[str, str] | None = None,
                bm25_analyzer: BM25Analyzer | None = None,
                bm25_identities: Iterable[EvidenceIdentity] | None = None,
                index_options: Mapping | None = None, **vector_options):
        identities = tuple(identities)
        required = tuple(required_indexes)
        options = dict(index_options or {})
        if "bm25" in options:
            raise RetrievalContractError("BM25 index options are derived from explicit analyzer and identities")
        if "bm25" in required:
            analyzer = bm25_analyzer if bm25_analyzer is not None else BM25Analyzer()
            if not isinstance(analyzer, BM25Analyzer):
                raise RetrievalContractError("bm25_analyzer must be BM25Analyzer")
            selected = identities if bm25_identities is None else tuple(bm25_identities)
            if any(not isinstance(identity, EvidenceIdentity) for identity in selected):
                raise RetrievalContractError("bm25_identities requires complete evidence identities")
            if any(not isinstance(identity, EvidenceIdentity) for identity in identities):
                raise RetrievalContractError("snapshot identities require complete evidence identities")
            if set(selected) - set(identities):
                raise RetrievalContractError("BM25 indexed identities must be visible in the snapshot")
            options["bm25"] = {"analyzer": analyzer.definition,
                               "evidence_keys": sorted({identity.key for identity in selected})}
        elif bm25_analyzer is not None or bm25_identities is not None:
            raise RetrievalContractError("BM25 configuration requires the bm25 index")
        return super().prepare(knowledge_base_id, snapshot_id, identities,
                               required_indexes=required, field_types=field_types,
                               index_options=options, **vector_options)

    def _prepare_indexes(self, cursor, snapshot):
        if "bm25" in snapshot.required_indexes:
            DocumentBM25Resources(self._namespace).prepare(cursor, snapshot)
        super()._prepare_indexes(cursor, snapshot)

    def _verify_indexes(self, cursor, snapshot):
        super()._verify_indexes(cursor, snapshot)
        if "bm25" in snapshot.required_indexes:
            DocumentBM25Resources(self._namespace).verify(cursor, snapshot)

    def search_bm25(self, query: str, *, knowledge_base_id: str, scope: ReadScope,
                    top_k: int = 10, exact_terms: tuple[str, ...] = ()) -> BM25QueryResult:
        """Return eligible top-k at one pinned KB snapshot, with original BM25 scores.

        exact_terms means ALL supplied final regex tokens, preserving case and
        punctuation. Ordinary text automatically uses each indexed tokenizer.
        Contract errors are raised; backend/resource errors fail the whole path
        with no candidates, never silently returning a partially filtered list.
        """
        required_strings(knowledge_base_id)
        if not isinstance(scope, ReadScope):
            raise RetrievalContractError("search_bm25 requires a pinned ReadScope")
        if knowledge_base_id not in scope.snapshots or knowledge_base_id not in scope.authorization.knowledge_base_ids:
            raise RetrievalContractError("BM25 knowledge base is outside the pinned authorized scope")
        if type(top_k) is not int or not 1 <= top_k <= 2147483647:
            raise RetrievalContractError("BM25 top_k must be a positive 32-bit integer")
        try:
            match_sql, match_parameters = text_match(query, exact_terms)
        except ValueError as exc:
            raise RetrievalContractError(str(exc)) from exc
        # Shared predicate contains both typed business conditions and document
        # authorization. Missing/invalid filter plans must never become TRUE.
        predicate, parameters = self.scope_predicate(scope, knowledge_base_id)
        try:
            with self._transaction() as cursor:
                snapshot = self._load_snapshot(cursor, knowledge_base_id,
                                               scope.snapshots[knowledge_base_id], published=True)
                if "bm25" not in snapshot.required_indexes:
                    raise SnapshotNotReady("pinned snapshot has no document BM25 index")
                rows, fingerprint = DocumentBM25Resources(self._namespace).search(
                    cursor, snapshot, scope=scope, match_sql=match_sql,
                    match_parameters=match_parameters, filter_sql=predicate,
                    filter_parameters=parameters, top_k=top_k)
                candidates = tuple(BM25Candidate(
                    ContentRecord(EvidenceIdentity.from_key(row[0]), row[1], row[2], row[3],
                                  EvidenceIdentity.from_key(row[4]) if row[4] else None),
                    snapshot.snapshot_id, float(row[5]), fingerprint) for row in rows)
            return BM25QueryResult("success" if candidates else "empty", candidates)
        except Exception as exc:
            # Do not expose database error text, SQL, DSNs or inaccessible values.
            return BM25QueryResult("failed", error=type(exc).__name__)
