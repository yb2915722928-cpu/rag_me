"""Exact pgvector question retrieval; item aggregation precedes rank and LIMIT."""
from dataclasses import dataclass
import hashlib
import importlib

from app.models.embedding import IndexSchemeVersion, canonical_json, scheme_from_metadata
from app.models.db.pgvector import validate_vector, vector_literal
from .contracts import ContentConflict, RetrievalContractError, SnapshotNotReady
from .faq_contracts import FAQIdentity, FAQRecord, MatchedQuestion
from .faq_postgres import encoding_namespace
from .vector import VectorQueryResult


@dataclass(frozen=True)
class FAQVectorCandidate:
    content: FAQRecord
    snapshot_id: str
    scheme_identity: str
    raw_score: float
    metric: str = "cosine_similarity"
    matched_questions: tuple[MatchedQuestion, ...] = ()


def resource_name(schema, kb, snapshot_id):
    return "rfv_" + hashlib.sha256(canonical_json([schema, kb, snapshot_id]).encode()).hexdigest()[:40]


class FAQVectorResources:
    def __init__(self, owner):
        self.owner = owner
        self.namespace = owner._namespace

    def prepare(self, cursor, snapshot):
        binding = snapshot.index_options["faq_vector"]
        scheme = scheme_from_metadata(binding["scheme"])
        resource = resource_name(self.owner.schema, snapshot.knowledge_base_id, snapshot.snapshot_id)
        table = f'{self.namespace}."{resource}"'
        cursor.execute(f"SELECT binding,resource_table FROM {self.namespace}.faq_vector_snapshots "
                       "WHERE knowledge_base_id=%s AND snapshot_id=%s", (snapshot.knowledge_base_id, snapshot.snapshot_id))
        existing = cursor.fetchone()
        if existing:
            if existing != (binding, resource):
                raise ContentConflict("FAQ vector binding is immutable")
            self.verify(cursor, snapshot)
            return
        cursor.execute(f"CREATE TABLE {table} (question_key text PRIMARY KEY REFERENCES "
                       f"{self.namespace}.faq_questions(question_key), vector vector({scheme.metadata.dimensions}) NOT NULL)")
        for key in snapshot.index_options["faq"]["identities"]:
            identity = FAQIdentity.from_key(key)
            cursor.execute(f"INSERT INTO {table} (question_key,vector) "
                           f"SELECT q.question_key,i.vector FROM {self.namespace}.faq_questions q "
                           "JOIN indexed_chunks i ON i.chunk_id=q.question_key "
                           "WHERE q.evidence_key=%s AND i.document_id=%s AND i.document_version=%s "
                           "AND i.chunk_version=%s AND i.scheme_identity=%s AND i.status='stored' "
                           "AND i.provenance_state='verified' AND i.body=q.question AND i.vector IS NOT NULL",
                           (key, encoding_namespace(self.owner.schema, identity), identity.version, identity.version, scheme.identity))
        cursor.execute(f"INSERT INTO {self.namespace}.faq_vector_snapshots "
                       "(knowledge_base_id,snapshot_id,binding,resource_table) VALUES (%s,%s,%s::jsonb,%s)",
                       (snapshot.knowledge_base_id, snapshot.snapshot_id, canonical_json(binding), resource))
        self.verify(cursor, snapshot)

    def verify(self, cursor, snapshot):
        resource = resource_name(self.owner.schema, snapshot.knowledge_base_id, snapshot.snapshot_id)
        cursor.execute(f"SELECT binding,resource_table FROM {self.namespace}.faq_vector_snapshots "
                       "WHERE knowledge_base_id=%s AND snapshot_id=%s", (snapshot.knowledge_base_id, snapshot.snapshot_id))
        if cursor.fetchone() != (snapshot.index_options["faq_vector"], resource):
            raise SnapshotNotReady("FAQ vector resource binding is missing")
        cursor.execute(f"SELECT question_key FROM {self.namespace}.faq_questions WHERE evidence_key=ANY(%s::text[])",
                       (snapshot.index_options["faq"]["identities"],))
        expected = {row[0] for row in cursor.fetchall()}
        cursor.execute(f'SELECT question_key FROM {self.namespace}."{resource}"')
        if {row[0] for row in cursor.fetchall()} != expected:
            raise SnapshotNotReady("required FAQ question vectors are incomplete")


def search_faq_vector(owner, query, *, knowledge_base_id, scope, top_k=10, adapter=None,
                      batch_options=None, remaining=None):
    if not isinstance(query, str) or not query.strip():
        raise RetrievalContractError("FAQ query must be nonempty text")
    if type(top_k) is not int or not 1 <= top_k <= 2147483647:
        raise RetrievalContractError("FAQ top_k must be a positive integer")
    predicate, params = owner.faq_scope_predicate(scope, knowledge_base_id)
    try:
        with owner._transaction() as cursor:
            snapshot = owner._load_snapshot(cursor, knowledge_base_id, scope.snapshots[knowledge_base_id], published=True)
        binding = snapshot.index_options.get("faq_vector")
        if binding is None:
            raise SnapshotNotReady("snapshot has no FAQ vector resource")
        scheme = scheme_from_metadata(binding["scheme"])
        if adapter is None:
            if owner.adapter_for_scheme is None:
                raise RetrievalContractError("FAQ query requires adapter_for_scheme")
            adapter = owner.adapter_for_scheme(scheme)
        if IndexSchemeVersion(adapter.metadata).identity != scheme.identity:
            raise RetrievalContractError("FAQ query encoder differs from pinned scheme")
        indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")
        encoding_options = dict(batch_options or {})
        if remaining is not None:
            encoding_options["remaining"] = remaining
        candidates = indexing.search_chunks(query, adapter, _FAQSearch(owner, snapshot, predicate, params),
                                            limit=top_k, request_repository=owner.request_repository,
                                            batch_options=encoding_options)
        return VectorQueryResult("success" if candidates else "empty", tuple(candidates), "exact", top_k,
                                 True, max(0, top_k - len(candidates)))
    except Exception as exc:
        return VectorQueryResult("failed", algorithm="exact", candidate_limit=top_k, exhaustive=False,
                                 shortfall=top_k, error=type(exc).__name__)


class _FAQSearch:
    def __init__(self, owner, snapshot, predicate, params):
        self.owner, self.snapshot, self.predicate, self.params = owner, snapshot, predicate, params

    def search(self, scheme, vector, *, limit):
        expected = scheme_from_metadata(self.snapshot.index_options["faq_vector"]["scheme"])
        if scheme.identity != expected.identity:
            raise RetrievalContractError("FAQ search scheme differs from snapshot")
        literal = vector_literal(validate_vector(scheme, vector))
        namespace = self.owner._namespace
        resource = resource_name(self.owner.schema, self.snapshot.knowledge_base_id, self.snapshot.snapshot_id)
        # Every qualified question is scored. Grouping happens before ranking and
        # LIMIT, so three similar questions can never crowd out another item.
        sql = ("WITH qualified AS MATERIALIZED ("
               "SELECT f.evidence_key,q.question_key,q.question,q.question_ordinal,v.vector "
               f'FROM {namespace}."{resource}" v JOIN {namespace}.faq_questions q ON q.question_key=v.question_key '
               f"JOIN {namespace}.faq_items f ON f.evidence_key=q.evidence_key "
               f"JOIN {namespace}.faq_snapshot_members m ON m.evidence_key=f.evidence_key "
               "AND m.knowledge_base_id=f.knowledge_base_id "
               "WHERE m.knowledge_base_id=%s AND m.snapshot_id=%s AND (" + self.predicate + ")), "
               "scored AS MATERIALIZED (SELECT evidence_key,question,question_ordinal,1-(vector <=> %s::vector) AS score "
               "FROM qualified), items AS (SELECT evidence_key,max(score) AS best_score,"
               "jsonb_agg(jsonb_build_object('question',question,'raw_score',score) "
               "ORDER BY score DESC,question_ordinal) AS matched_questions FROM scored GROUP BY evidence_key), "
               "ranked AS (SELECT * FROM items ORDER BY best_score DESC,evidence_key LIMIT %s) "
               "SELECT f.evidence_key,f.standard_question,f.similar_questions,f.answer,f.conditions,f.source,"
               f"r.best_score,r.matched_questions FROM ranked r JOIN {namespace}.faq_items f ON f.evidence_key=r.evidence_key "
               "ORDER BY r.best_score DESC,r.evidence_key")
        with self.owner._transaction() as cursor:
            cursor.execute(sql, [self.snapshot.knowledge_base_id, self.snapshot.snapshot_id, *self.params, literal, limit])
            rows = cursor.fetchall()
        return [FAQVectorCandidate(FAQRecord(FAQIdentity.from_key(row[0]), row[1], tuple(row[2]), row[3], row[4], row[5]),
                                   self.snapshot.snapshot_id, scheme.identity, float(row[6]),
                                   matched_questions=tuple(MatchedQuestion(x["question"], float(x["raw_score"])) for x in row[7]))
                for row in rows]
