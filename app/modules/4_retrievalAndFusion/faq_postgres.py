"""FAQ authority shares the document store's prepare/publication transaction.

FAQ identity is never converted into document evidence. Module3's legacy input
shape is used only inside the encoder adapter with a disjoint FAQ namespace.
"""
from dataclasses import asdict
import importlib
from pathlib import Path

from app.models.embedding import ChunkRecord, IndexSchemeVersion, canonical_json
from .bm25_postgres import PostgresBM25RetrievalStore
from .contracts import ContentConflict, RetrievalContractError, SnapshotNotReady
from .faq_contracts import FAQIdentity, FAQRecord
from .filters import validate_metadata


def question_key(identity, ordinal):
    return canonical_json([*identity.parts, "question", ordinal])


def encoding_namespace(schema, identity):
    return canonical_json(["retrieval-faq", schema, identity.knowledge_base_id, identity.item_id])


class PostgresFAQRetrievalStore(PostgresBM25RetrievalStore):
    supported_indexes = PostgresBM25RetrievalStore.supported_indexes | {"faq", "faq_vector"}

    def migrate(self):
        super().migrate()
        migration = Path(__file__).with_name("migrations") / "004_faq_authority.sql"
        with self._transaction() as cursor:
            cursor.execute(migration.read_text(encoding="utf-8").format(schema=self._namespace))

    def ingest_faq(self, records):
        records = tuple(records)
        if any(not isinstance(row, FAQRecord) for row in records):
            raise RetrievalContractError("ingest_faq requires FAQRecord values")
        with self._transaction() as cursor:
            for row in records:
                identity = row.identity
                cursor.execute(f"INSERT INTO {self._namespace}.faq_items "
                               "(evidence_key,knowledge_base_id,item_id,version,standard_question,similar_questions,answer,conditions,source) "
                               "VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb) ON CONFLICT DO NOTHING",
                               (identity.key, identity.knowledge_base_id, identity.item_id, identity.version,
                                row.standard_question, canonical_json(row.similar_questions), row.answer,
                                canonical_json(row.conditions), canonical_json(row.source)))
                cursor.execute(f"SELECT standard_question,similar_questions,answer,conditions,source "
                               f"FROM {self._namespace}.faq_items WHERE evidence_key=%s", (identity.key,))
                if cursor.fetchone() != (row.standard_question, list(row.similar_questions), row.answer, row.conditions, row.source):
                    raise ContentConflict("FAQ identity already stores different content")
                for ordinal, question in enumerate(row.questions):
                    cursor.execute(f"INSERT INTO {self._namespace}.faq_questions "
                                   "(question_key,knowledge_base_id,evidence_key,question_ordinal,question) "
                                   "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                   (question_key(identity, ordinal), identity.knowledge_base_id, identity.key, ordinal, question))

    def index_faq(self, records, adapter, **batch_options):
        """Only questions enter module3 embedding/request persistence; never answers."""
        records = tuple(records)
        if "long_input_policy" in batch_options:
            raise RetrievalContractError("FAQ questions must be indexed without implicit text transformations")
        self.ingest_faq(records)
        chunks = [ChunkRecord(question_key(row.identity, ordinal), encoding_namespace(self.schema, row.identity),
                              row.identity.version, question, {"faq_identity": row.identity.key}, row.identity.version)
                  for row in records for ordinal, question in enumerate(row.questions)]
        indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")
        return indexing.index_chunks(chunks, adapter, self.request_repository,
                                     request_repository=self.request_repository, **batch_options)

    def prepare(self, knowledge_base_id, snapshot_id, identities, *, faq_identities=(),
                required_indexes=("content", "faq", "faq_vector"), faq_vector_scheme=None,
                index_options=None, **options):
        selected = tuple(faq_identities)
        if any(not isinstance(i, FAQIdentity) or i.knowledge_base_id != knowledge_base_id for i in selected):
            raise RetrievalContractError("FAQ snapshot identities must belong to its knowledge base")
        required = set(required_indexes)
        manifest = dict(index_options or {})
        if "faq" in manifest or "faq_vector" in manifest:
            raise RetrievalContractError("FAQ manifests are derived from explicit identities and scheme")
        if selected or "faq_vector" in required:
            required.add("faq")
        if "faq" in required:
            manifest["faq"] = {"identities": sorted({i.key for i in selected})}
        if "faq_vector" in required:
            if not isinstance(faq_vector_scheme, IndexSchemeVersion) or not faq_vector_scheme.metadata.verifiable:
                raise RetrievalContractError("FAQ vector indexing requires an explicit verifiable scheme")
            # Exact qualified ranking ensures all matching questions are grouped
            # into items before any top-K. ANN question budgets would bias items.
            manifest["faq_vector"] = {"scheme": asdict(faq_vector_scheme.metadata), "algorithm": "exact"}
        elif faq_vector_scheme is not None:
            raise RetrievalContractError("FAQ scheme requires faq_vector index")
        return super().prepare(knowledge_base_id, snapshot_id, identities, required_indexes=tuple(sorted(required)),
                               index_options=manifest, **options)

    def _verify_content(self, cursor, snapshot):
        super()._verify_content(cursor, snapshot)
        if "faq" not in snapshot.required_indexes:
            return
        keys = snapshot.index_options["faq"]["identities"]
        cursor.execute(f"SELECT evidence_key,standard_question,similar_questions,answer,conditions,source "
                       f"FROM {self._namespace}.faq_items WHERE knowledge_base_id=%s AND evidence_key=ANY(%s::text[])",
                       (snapshot.knowledge_base_id, keys))
        rows = cursor.fetchall()
        if {row[0] for row in rows} != set(keys):
            raise SnapshotNotReady("snapshot contains missing authoritative FAQ")
        expected = {}
        for row in rows:
            record = FAQRecord(FAQIdentity.from_key(row[0]), row[1], tuple(row[2]), row[3], row[4], row[5])
            validate_metadata(record.conditions, snapshot.field_types)
            for ordinal, question in enumerate(record.questions):
                expected[question_key(record.identity, ordinal)] = (record.identity.key, ordinal, question)
        cursor.execute(f"SELECT question_key,evidence_key,question_ordinal,question FROM {self._namespace}.faq_questions "
                       "WHERE evidence_key=ANY(%s::text[])", (keys,))
        if {row[0]: tuple(row[1:]) for row in cursor.fetchall()} != expected:
            raise SnapshotNotReady("FAQ questions differ from authoritative items")

    def _prepare_indexes(self, cursor, snapshot):
        super()._prepare_indexes(cursor, snapshot)
        if "faq" in snapshot.required_indexes:
            for key in snapshot.index_options["faq"]["identities"]:
                cursor.execute(f"INSERT INTO {self._namespace}.faq_snapshot_members "
                               "(knowledge_base_id,snapshot_id,evidence_key) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                               (snapshot.knowledge_base_id, snapshot.snapshot_id, key))
        if "faq_vector" in snapshot.required_indexes:
            from .faq_vector import FAQVectorResources
            FAQVectorResources(self).prepare(cursor, snapshot)

    def _verify_indexes(self, cursor, snapshot):
        super()._verify_indexes(cursor, snapshot)
        if "faq" in snapshot.required_indexes:
            cursor.execute(f"SELECT evidence_key FROM {self._namespace}.faq_snapshot_members "
                           "WHERE knowledge_base_id=%s AND snapshot_id=%s", (snapshot.knowledge_base_id, snapshot.snapshot_id))
            if {row[0] for row in cursor.fetchall()} != set(snapshot.index_options["faq"]["identities"]):
                raise SnapshotNotReady("FAQ snapshot membership is incomplete")
        if "faq_vector" in snapshot.required_indexes:
            from .faq_vector import FAQVectorResources
            FAQVectorResources(self).verify(cursor, snapshot)

    def faq_scope_predicate(self, scope, knowledge_base_id):
        if knowledge_base_id not in scope.snapshots or knowledge_base_id not in scope.authorization.knowledge_base_ids:
            raise RetrievalContractError("FAQ knowledge base is outside pinned authorization")
        plan = scope.filter_plans.get(knowledge_base_id)
        if plan is None:
            raise RetrievalContractError("FAQ scope must have pinned validated filters")
        predicate, params = plan.sql(column="f.conditions")
        items = scope.authorization.faq_item_ids.get(knowledge_base_id)
        # A document-only grant never implicitly grants FAQ items.
        if items is None and knowledge_base_id in scope.authorization.document_ids:
            items = ()
        if items is not None:
            predicate = "(" + predicate + ") AND f.item_id=ANY(%s::text[])"
            params.append(list(items))
        return predicate, params

    def read(self, identity, *, scope):
        if not isinstance(identity, FAQIdentity):
            return super().read(identity, scope=scope)
        kb = identity.knowledge_base_id
        if kb not in scope.snapshots or kb not in scope.authorization.knowledge_base_ids:
            return None
        predicate, params = self.faq_scope_predicate(scope, kb)
        with self._transaction() as cursor:
            self._load_snapshot(cursor, kb, scope.snapshots[kb], published=True)
            cursor.execute(f"SELECT f.standard_question,f.similar_questions,f.answer,f.conditions,f.source "
                           f"FROM {self._namespace}.faq_items f JOIN {self._namespace}.faq_snapshot_members m "
                           "ON m.knowledge_base_id=f.knowledge_base_id AND m.evidence_key=f.evidence_key "
                           "WHERE m.knowledge_base_id=%s AND m.snapshot_id=%s AND f.evidence_key=%s AND (" + predicate + ")",
                           [kb, scope.snapshots[kb], identity.key, *params])
            row = cursor.fetchone()
        return None if row is None else FAQRecord(identity, row[0], tuple(row[1]), row[2], row[3], row[4])

    def search_faq_vector(self, query, *, knowledge_base_id, scope, top_k=10, **options):
        from .faq_vector import search_faq_vector
        return search_faq_vector(self, query, knowledge_base_id=knowledge_base_id, scope=scope, top_k=top_k, **options)
