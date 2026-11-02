"""Snapshot-scoped pgvector retrieval, reusing module3 encoding and request persistence.

Exact search materializes the fully authorized/filtered relation before ranking.
ANN uses a snapshot-local index and can underfill after filtering; it never claims
complete recall. pgvector 0.8.x parameter bounds are shared with module3.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import importlib
from pathlib import Path

from app.models.embedding import (IndexSchemeVersion, canonical_json,
                                  scheme_from_metadata)
from app.models.db.pgvector import (PhysicalIndexConfig, PostgresVectorStore,
                                    validate_vector, vector_literal)
from .contracts import (ContentConflict, ContentRecord, EvidenceIdentity,
                        RetrievalContractError, SnapshotNotReady)
from .postgres import PostgresRetrievalStore


@dataclass(frozen=True)
class VectorCandidate:
    content: ContentRecord
    snapshot_id: str
    scheme_identity: str
    raw_score: float
    metric: str = "cosine_similarity"


@dataclass(frozen=True)
class VectorQueryResult:
    status: str
    candidates: tuple[VectorCandidate, ...] = ()
    algorithm: str = "exact"
    candidate_limit: int = 10
    exhaustive: bool = True
    shortfall: int = 0
    limitations: tuple[str, ...] = ()
    error: str | None = None


def _resource(schema, kb, snapshot):
    return "rv_" + hashlib.sha256(canonical_json([schema, kb, snapshot]).encode()).hexdigest()[:40]


def _namespace_document(schema, identity):
    return canonical_json(["retrieval", schema, identity.knowledge_base_id, identity.document_id])


class PostgresVectorRetrievalStore(PostgresRetrievalStore):
    supported_indexes = PostgresRetrievalStore.supported_indexes | {"vector"}

    def __init__(self, dsn, *, adapter_for_scheme=None, **options):
        super().__init__(dsn, **options)
        self.adapter_for_scheme = adapter_for_scheme
        self.request_repository = PostgresVectorStore(dsn, connect=self._connect)

    def migrate(self):
        super().migrate()
        self.request_repository.migrate()
        migration = Path(__file__).with_name("migrations") / "002_vector_snapshots.sql"
        with self._transaction() as cursor:
            cursor.execute(migration.read_text(encoding="utf-8").format(schema=self._namespace))

    def index_documents(self, records, adapter, **batch_options):
        """Encode through module3, with durable KB-qualified request identities.

        Parent-only content can be omitted here and from vector_identities during
        prepare. Long-input transformations are rejected: changed chunk revisions
        must first be explicitly handed back as new authoritative ContentRecords.
        """
        records = tuple(records)
        if any(not isinstance(record, ContentRecord) for record in records):
            raise RetrievalContractError("index_documents requires ContentRecord values")
        if "long_input_policy" in batch_options:
            raise RetrievalContractError("retrieval indexing requires explicit untransformed evidence revisions")
        self.ingest(records)
        chunks = [replace(row.to_chunk_record(), document_id=_namespace_document(self.schema, row.identity))
                  for row in records]
        indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")
        return indexing.index_chunks(chunks, adapter, self.request_repository,
                                     request_repository=self.request_repository, **batch_options)

    def prepare(self, knowledge_base_id, snapshot_id, identities, *, required_indexes=("content",),
                field_types=None, vector_scheme=None, vector_config=None, vector_identities=None,
                index_options=None):
        identities = tuple(identities)
        required_indexes = tuple(required_indexes)
        options = dict(index_options or {})
        if "vector" in required_indexes:
            if not isinstance(vector_scheme, IndexSchemeVersion) or not vector_scheme.metadata.verifiable:
                raise RetrievalContractError("vector snapshot requires an explicit verifiable scheme")
            config = vector_config or PhysicalIndexConfig()
            if not isinstance(config, PhysicalIndexConfig):
                raise RetrievalContractError("vector_config must be PhysicalIndexConfig")
            if config.algorithm != "exact" and vector_scheme.metadata.dimensions > 2000:
                raise RetrievalContractError("vector ANN supports at most 2000 dimensions")
            selected = tuple(identities if vector_identities is None else vector_identities)
            if set(selected) - set(identities):
                raise RetrievalContractError("vector identities must be snapshot members")
            binding = {"scheme": asdict(vector_scheme.metadata),
                       "algorithm": config.algorithm, "build_parameters": dict(config.build_parameters),
                       "query_parameters": dict(config.query_parameters),
                       "identities": sorted({identity.key for identity in selected})}
            if "vector" in options and options["vector"] != binding:
                raise RetrievalContractError("conflicting vector index options")
            options["vector"] = binding
        elif vector_scheme is not None or vector_config is not None or vector_identities is not None:
            raise RetrievalContractError("vector options require the vector index")
        return super().prepare(knowledge_base_id, snapshot_id, identities, required_indexes=required_indexes,
                               field_types=field_types, index_options=options)

    def _prepare_indexes(self, cursor, snapshot):
        if "vector" in snapshot.required_indexes:
            self._build_vector(cursor, snapshot)
        super()._prepare_indexes(cursor, snapshot)
        # Only verify this concrete builder; sibling resources may still be building.
        if "vector" in snapshot.required_indexes:
            self._verify_vector(cursor, snapshot)

    def _verify_indexes(self, cursor, snapshot):
        super()._verify_indexes(cursor, snapshot)
        if "vector" in snapshot.required_indexes:
            self._verify_vector(cursor, snapshot)

    def _build_vector(self, cursor, snapshot):
        binding = snapshot.index_options["vector"]
        scheme = scheme_from_metadata(binding["scheme"])
        config = PhysicalIndexConfig(binding["algorithm"], binding["build_parameters"], binding["query_parameters"])
        resource = _resource(self.schema, snapshot.knowledge_base_id, snapshot.snapshot_id)
        table = f'{self._namespace}."{resource}"'
        cursor.execute(f"SELECT binding FROM {self._namespace}.vector_snapshots WHERE knowledge_base_id=%s AND snapshot_id=%s",
                       (snapshot.knowledge_base_id, snapshot.snapshot_id))
        existing = cursor.fetchone()
        if existing:
            if existing[0] != binding:
                raise ContentConflict("vector snapshot binding is immutable")
            return
        cursor.execute(f"CREATE TABLE {table} (evidence_key text PRIMARY KEY REFERENCES {self._namespace}.content(evidence_key), "
                       f"vector vector({scheme.metadata.dimensions}) NOT NULL)")
        for key in binding["identities"]:
            identity = EvidenceIdentity.from_key(key)
            cursor.execute(f"INSERT INTO {table} (evidence_key, vector) "
                           "SELECT %s, i.vector FROM indexed_chunks i "
                           f"JOIN {self._namespace}.content c ON c.evidence_key=%s "
                           "WHERE i.document_id=%s AND i.document_version=%s AND i.chunk_id=%s AND i.chunk_version=%s "
                           "AND i.scheme_identity=%s AND i.status='stored' AND i.provenance_state='verified' "
                           "AND i.body=c.body AND i.vector IS NOT NULL",
                           (key, key, _namespace_document(self.schema, identity), identity.document_version,
                            identity.chunk_id, identity.chunk_version, scheme.identity))
        if config.algorithm == "ivfflat" and len(binding["identities"]) < config.build_parameters.get("lists", 100):
            raise SnapshotNotReady("IVFFlat requires at least lists vectors")
        if config.algorithm != "exact":
            defaults = {"hnsw": {"m": 16, "ef_construction": 64}, "ivfflat": {"lists": 100}}[config.algorithm]
            defaults.update(config.build_parameters)
            settings = ",".join(f"{key}={value}" for key, value in sorted(defaults.items()))
            cursor.execute(f'CREATE INDEX "{resource}_ann" ON {table} USING {config.algorithm} '
                           f"(vector vector_cosine_ops) WITH ({settings})")
        cursor.execute(f"INSERT INTO {self._namespace}.vector_snapshots (knowledge_base_id,snapshot_id,binding,resource_table) "
                       "VALUES (%s,%s,%s::jsonb,%s)",
                       (snapshot.knowledge_base_id, snapshot.snapshot_id, canonical_json(binding), resource))

    def _verify_vector(self, cursor, snapshot):
        binding = snapshot.index_options.get("vector")
        cursor.execute(f"SELECT binding,resource_table FROM {self._namespace}.vector_snapshots "
                       "WHERE knowledge_base_id=%s AND snapshot_id=%s", (snapshot.knowledge_base_id, snapshot.snapshot_id))
        row = cursor.fetchone()
        resource = _resource(self.schema, snapshot.knowledge_base_id, snapshot.snapshot_id)
        if row is None or row[0] != binding or row[1] != resource:
            raise SnapshotNotReady("vector snapshot resource or binding is missing")
        cursor.execute(f'SELECT evidence_key FROM {self._namespace}."{resource}"')
        if {item[0] for item in cursor.fetchall()} != set(binding["identities"]):
            raise SnapshotNotReady("required vectors are incomplete")
        if binding["algorithm"] != "exact":
            cursor.execute("SELECT i.indisvalid, i.indisready, am.amname FROM pg_index i "
                           "JOIN pg_class idx ON idx.oid=i.indexrelid JOIN pg_am am ON am.oid=idx.relam "
                           "WHERE i.indexrelid=to_regclass(%s) AND i.indrelid=to_regclass(%s)",
                           (f'{self._namespace}."{resource}_ann"', f'{self._namespace}."{resource}"'))
            if cursor.fetchone() != (True, True, binding["algorithm"]):
                raise SnapshotNotReady("required ANN index is not ready")

    def search_vector(self, query, *, knowledge_base_id, scope, top_k=10, candidate_limit=None):
        """Fan-out route boundary using the constructor's pinned-scheme adapter resolver."""
        return self.query(query, knowledge_base_id=knowledge_base_id, scope=scope,
                          limit=top_k, candidate_limit=candidate_limit)

    def query(self, query, adapter=None, *, knowledge_base_id, scope, limit=10, candidate_limit=None,
              batch_options=None):
        """Synchronous route result; validation raises, execution failures are explicit."""
        if not isinstance(query, str) or not query.strip():
            raise RetrievalContractError("query must be nonempty text")
        if type(limit) is not int or not 1 <= limit <= 2147483647:
            raise RetrievalContractError("limit must be a positive integer")
        budget = limit if candidate_limit is None else candidate_limit
        if type(budget) is not int or not limit <= budget <= 2147483647:
            raise RetrievalContractError("candidate_limit must be an integer >= limit")
        predicate, params = self.scope_predicate(scope, knowledge_base_id)
        algorithm = "unknown"
        try:
            with self._transaction() as cursor:
                snapshot = self._load_snapshot(cursor, knowledge_base_id, scope.snapshots[knowledge_base_id], published=True)
            binding = snapshot.index_options.get("vector")
            if binding is None:
                raise SnapshotNotReady("snapshot has no vector resource")
            scheme = scheme_from_metadata(binding["scheme"])
            algorithm = binding["algorithm"]
            if adapter is None:
                if self.adapter_for_scheme is None:
                    raise RetrievalContractError("configure adapter_for_scheme or supply an adapter")
                adapter = self.adapter_for_scheme(scheme)
            if IndexSchemeVersion(adapter.metadata).identity != scheme.identity:
                raise RetrievalContractError("query encoder does not match pinned vector scheme")
            scoped_store = _SnapshotSearch(self, snapshot, predicate, params, budget)
            indexing = importlib.import_module("app.modules.3_embeddingAndIndexing")
            from app.models.deadline import current_deadline
            remaining = current_deadline()
            batch_options = dict(batch_options or {})
            if remaining is not None:
                remaining.check()
                batch_options["remaining"] = remaining
            candidates = indexing.search_chunks(query, adapter, scoped_store, limit=limit,
                                                request_repository=self.request_repository,
                                                batch_options=batch_options)
        except Exception as exc:
            return VectorQueryResult("failed", algorithm=algorithm, candidate_limit=budget, exhaustive=False,
                                     shortfall=limit, error=f"{type(exc).__name__}: {exc}")
        ann = algorithm != "exact"
        limitations = (("ANN is approximate; post-index filtering can underfill the candidate budget and does not guarantee complete qualified top-K.",)
                       if ann else ())
        return VectorQueryResult("success" if candidates else "empty", tuple(candidates), algorithm, budget,
                                 not ann, max(0, limit - len(candidates)), limitations)


class _SnapshotSearch:
    """Module3 VectorStore.search boundary bound to one immutable snapshot."""
    def __init__(self, owner, snapshot, predicate, params, budget):
        self.owner, self.snapshot = owner, snapshot
        self.predicate, self.params, self.budget = predicate, params, budget

    def search(self, scheme, vector, *, limit):
        binding = self.snapshot.index_options["vector"]
        expected = scheme_from_metadata(binding["scheme"])
        if scheme.identity != expected.identity:
            raise RetrievalContractError("search scheme differs from snapshot")
        literal = vector_literal(validate_vector(scheme, vector))
        config = PhysicalIndexConfig(binding["algorithm"], binding["build_parameters"], binding["query_parameters"])
        resource = _resource(self.owner.schema, self.snapshot.knowledge_base_id, self.snapshot.snapshot_id)
        table = f'{self.owner._namespace}."{resource}"'
        columns = "c.evidence_key,c.body,c.source,c.metadata,c.parent_key"
        source = (f"FROM {table} v JOIN {self.owner._namespace}.content c ON c.evidence_key=v.evidence_key "
                  f"JOIN {self.owner._namespace}.snapshot_members m ON m.evidence_key=c.evidence_key "
                  "AND m.knowledge_base_id=c.knowledge_base_id "
                  "WHERE m.knowledge_base_id=%s AND m.snapshot_id=%s AND (" + self.predicate + ")")
        common = [self.snapshot.knowledge_base_id, self.snapshot.snapshot_id, *self.params]
        with self.owner._transaction() as cursor:
            if config.algorithm == "exact":
                # MATERIALIZED prevents an ANN scan or pre-filter LIMIT from
                # substituting a limited unqualified pool for the complete set.
                sql = (f"WITH qualified AS MATERIALIZED (SELECT {columns},v.vector {source}) "
                       "SELECT evidence_key,body,source,metadata,parent_key,vector <=> %s::vector AS distance "
                       "FROM qualified ORDER BY distance,evidence_key LIMIT %s")
                parameters = [*common, literal, limit]
            else:
                settings = {"hnsw": {"ef_search": 40}, "ivfflat": {"probes": 1}}[config.algorithm]
                settings.update(config.query_parameters)
                for name, value in settings.items():
                    cursor.execute("SELECT set_config(%s,%s,true)", (config.algorithm + "." + name, str(value)))
                sql = (f"WITH candidates AS MATERIALIZED (SELECT {columns},v.vector <=> %s::vector AS distance "
                       f"{source} ORDER BY v.vector <=> %s::vector LIMIT %s) "
                       "SELECT evidence_key,body,source,metadata,parent_key,distance FROM candidates "
                       "ORDER BY distance,evidence_key LIMIT %s")
                parameters = [literal, *common, literal, self.budget, limit]
            cursor.execute(sql, parameters)
            rows = cursor.fetchall()
        return [VectorCandidate(ContentRecord(EvidenceIdentity.from_key(row[0]), row[1], row[2], row[3],
                                               EvidenceIdentity.from_key(row[4]) if row[4] else None),
                                self.snapshot.snapshot_id, scheme.identity, 1 - float(row[5])) for row in rows]
