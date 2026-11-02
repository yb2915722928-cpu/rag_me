"""Unified document/FAQ vector/BM25 store over one publication protocol.

Depends on #88's integrated FAQ authority contract. No caller readiness flags.
"""
from pathlib import Path

from .bm25 import BM25Analyzer, text_match
from .contracts import ReadScope, RetrievalContractError, SnapshotNotReady, required_strings
from .faq_bm25 import FAQBM25Analyzer, FAQBM25Candidate, FAQBM25QueryResult
from .faq_bm25_resources import FAQBM25Resources
from .faq_contracts import FAQIdentity, FAQRecord, MatchedQuestion
from .faq_postgres import PostgresFAQRetrievalStore
from .execution_errors import execution_failure


class PostgresFAQBM25RetrievalStore(PostgresFAQRetrievalStore):
    supported_indexes = PostgresFAQRetrievalStore.supported_indexes | {"faq_bm25"}

    def migrate(self):
        super().migrate()
        migration = Path(__file__).with_name("migrations") / "005_faq_bm25.sql"
        with self._transaction() as cursor:
            cursor.execute(migration.read_text(encoding="utf-8").format(schema=self._namespace))

    def prepare(self, knowledge_base_id, snapshot_id, identities, *, faq_identities=(),
                required_indexes=("content", "faq", "faq_bm25"), faq_bm25_analyzer=None,
                index_options=None, **options):
        required = set(required_indexes)
        manifest = dict(index_options or {})
        if "faq_bm25" in manifest:
            raise RetrievalContractError("FAQ BM25 manifest is derived from the explicit analyzer")
        if "faq_bm25" in required:
            required.add("faq")
            analyzer = faq_bm25_analyzer if faq_bm25_analyzer is not None else FAQBM25Analyzer()
            if not isinstance(analyzer, BM25Analyzer):
                raise RetrievalContractError("faq_bm25_analyzer requires BM25Analyzer")
            # Both routes use the same pinned options, with separate corpus identity.
            analyzer = FAQBM25Analyzer(**analyzer.definition["options"])
            manifest["faq_bm25"] = {"analyzer": analyzer.definition}
        elif faq_bm25_analyzer is not None:
            raise RetrievalContractError("FAQ BM25 analyzer requires faq_bm25 index")
        return super().prepare(knowledge_base_id, snapshot_id, identities, faq_identities=faq_identities,
                               required_indexes=tuple(sorted(required)), index_options=manifest, **options)

    def _prepare_indexes(self, cursor, snapshot):
        super()._prepare_indexes(cursor, snapshot)
        if "faq_bm25" in snapshot.required_indexes:
            FAQBM25Resources(self._namespace).prepare(cursor, snapshot)

    def _verify_indexes(self, cursor, snapshot):
        super()._verify_indexes(cursor, snapshot)
        if "faq_bm25" in snapshot.required_indexes:
            FAQBM25Resources(self._namespace).verify(cursor, snapshot)

    def search_faq_bm25(self, query, *, knowledge_base_id, scope, top_k=10, exact_terms=()):
        required_strings(knowledge_base_id)
        if not isinstance(scope, ReadScope):
            raise RetrievalContractError("FAQ BM25 requires a pinned ReadScope")
        if type(top_k) is not int or not 1 <= top_k <= 2147483647:
            raise RetrievalContractError("FAQ BM25 top_k must be a positive 32-bit integer")
        try:
            match_sql, match_parameters = text_match(query, exact_terms)
        except ValueError as exc:
            raise RetrievalContractError(str(exc)) from exc
        # Invalid/missing plans fail before opening any search transaction.
        predicate, parameters = self.faq_scope_predicate(scope, knowledge_base_id)
        try:
            with self._transaction() as cursor:
                snapshot = self._load_snapshot(cursor, knowledge_base_id, scope.snapshots[knowledge_base_id], published=True)
                if "faq_bm25" not in snapshot.required_indexes:
                    raise SnapshotNotReady("pinned snapshot has no FAQ BM25 resource")
                rows, fingerprint = FAQBM25Resources(self._namespace).search(
                    cursor, snapshot, match_sql=match_sql, match_parameters=match_parameters,
                    filter_sql=predicate, filter_parameters=parameters, top_k=top_k)
                candidates = tuple(FAQBM25Candidate(
                    FAQRecord(FAQIdentity.from_key(row[0]), row[1], tuple(row[2]), row[3], row[4], row[5]),
                    snapshot.snapshot_id, float(row[6]), fingerprint,
                    tuple(MatchedQuestion(q["question"], float(q["raw_score"])) for q in row[7])) for row in rows)
            return FAQBM25QueryResult("success" if candidates else "empty", candidates)
        except Exception as exc:
            status, reason, _ = execution_failure(exc)
            return FAQBM25QueryResult(status, error=reason)
