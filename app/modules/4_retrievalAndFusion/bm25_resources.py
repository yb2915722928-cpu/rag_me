"""Transactional builders shared by the document BM25 store hooks."""
from __future__ import annotations

from .bm25 import (BM25Analyzer, EXTENSION_VERSIONS, POSTGRES_VERSION_NUM,
                   corpus_names, create_index_sql, quote_identifier)
from .contracts import ContentConflict, SnapshotNotReady
from app.models.embedding import canonical_json


class DocumentBM25Resources:
    def __init__(self, namespace: str):
        self.namespace = namespace

    @staticmethod
    def check_runtime(cursor):
        cursor.execute("SELECT current_setting('server_version_num')::integer")
        if cursor.fetchone()[0] != POSTGRES_VERSION_NUM:
            raise SnapshotNotReady("document BM25 requires PostgreSQL 17.11")
        cursor.execute("SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector', 'pg_search')")
        if dict(cursor.fetchall()) != EXTENSION_VERSIONS:
            raise SnapshotNotReady("document BM25 requires vector 0.8.6 and pg_search 0.26.4")

    def load(self, cursor, snapshot):
        cursor.execute(f"SELECT table_name, index_name, analyzer_fingerprint, analyzer_definition, index_definition, evidence_keys "
                       f"FROM {self.namespace}.bm25_resources WHERE knowledge_base_id=%s AND snapshot_id=%s",
                       (snapshot.knowledge_base_id, snapshot.snapshot_id))
        return cursor.fetchone()

    def prepare(self, cursor, snapshot):
        options = snapshot.index_options["bm25"]
        analyzer = BM25Analyzer(**options["analyzer"]["options"])
        keys = options["evidence_keys"]
        self.check_runtime(cursor)
        existing = self.load(cursor, snapshot)
        if existing is not None:
            if existing[2] != analyzer.fingerprint or existing[3] != analyzer.definition or existing[5] != keys:
                raise ContentConflict("BM25 analyzer is immutable; use a new snapshot_id")
            self.verify(cursor, snapshot)
            return
        cursor.execute(f"SELECT published_at FROM {self.namespace}.snapshots "
                       "WHERE knowledge_base_id=%s AND snapshot_id=%s",
                       (snapshot.knowledge_base_id, snapshot.snapshot_id))
        if cursor.fetchone()[0] is not None:
            raise SnapshotNotReady("cannot rebuild a published BM25 resource in place")
        table, index = corpus_names(snapshot.knowledge_base_id, snapshot.snapshot_id)
        relation = f"{self.namespace}.{quote_identifier(table)}"
        # Separate heap/index per KB x snapshot: no shared-index IDF contamination.
        cursor.execute(f"CREATE TABLE {relation} ("
                       "id bigint PRIMARY KEY, evidence_key text UNIQUE NOT NULL, "
                       "knowledge_base_id text NOT NULL, document_id text NOT NULL, "
                       "document_version text NOT NULL, chunk_id text NOT NULL, chunk_version text NOT NULL, "
                       "body text NOT NULL, body_models text NOT NULL CHECK (body_models=body), "
                       "source jsonb NOT NULL, metadata jsonb NOT NULL, parent_key text)")
        cursor.execute(f"INSERT INTO {relation} SELECT row_number() OVER (ORDER BY evidence_key), "
                       "evidence_key, knowledge_base_id, document_id, document_version, chunk_id, chunk_version, "
                       f"body, body, source, metadata, parent_key FROM {self.namespace}.content "
                       "WHERE knowledge_base_id=%s AND evidence_key=ANY(%s::text[])",
                       (snapshot.knowledge_base_id, keys))
        cursor.execute(create_index_sql(self.namespace, table, index, analyzer))
        cursor.execute(f"CREATE TRIGGER immutable_bm25 BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE "
                       f"ON {relation} FOR EACH STATEMENT EXECUTE FUNCTION {self.namespace}.reject_bm25_mutation()")
        cursor.execute("SELECT pg_get_indexdef(to_regclass(%s))", (f"{self.namespace}.{quote_identifier(index)}",))
        definition = cursor.fetchone()[0]
        cursor.execute(f"INSERT INTO {self.namespace}.bm25_resources "
                       "(knowledge_base_id, snapshot_id, table_name, index_name, analyzer_fingerprint, "
                       "analyzer_definition, index_definition, evidence_keys) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb)",
                       (snapshot.knowledge_base_id, snapshot.snapshot_id, table, index,
                        analyzer.fingerprint, canonical_json(analyzer.definition), definition, canonical_json(keys)))
        self.verify(cursor, snapshot)

    def search(self, cursor, snapshot, *, scope, match_sql, match_parameters,
               filter_sql, filter_parameters, top_k):
        resource = self.verify(cursor, snapshot)
        table, _, fingerprint, _, _, _ = resource
        relation = f"{self.namespace}.{quote_identifier(table)}"
        # Materialization deliberately separates BM25 scoring from eligibility.
        # There is NO internal LIMIT/OFFSET or guessed candidate overfetch budget.
        cursor.execute(
            f"WITH hits AS MATERIALIZED (SELECT t.*, pdb.score(t.id) AS raw_score "
            f"FROM {relation} t WHERE {match_sql}) "
            "SELECT c.evidence_key, c.body, c.source, c.metadata, c.parent_key, c.raw_score "
            "FROM hits c "
            f"JOIN {self.namespace}.snapshot_members m ON m.evidence_key=c.evidence_key "
            "AND m.knowledge_base_id=c.knowledge_base_id "
            "WHERE m.knowledge_base_id=%s AND m.snapshot_id=%s "
            f"AND ({filter_sql}) "
            "ORDER BY c.raw_score DESC, c.evidence_key COLLATE \"C\" ASC LIMIT %s",
            [*match_parameters, snapshot.knowledge_base_id, snapshot.snapshot_id,
             *filter_parameters, top_k])
        return cursor.fetchall(), fingerprint

    def verify(self, cursor, snapshot) -> tuple:
        self.check_runtime(cursor)
        resource = self.load(cursor, snapshot)
        if resource is None:
            raise SnapshotNotReady("required document BM25 resource is missing")
        table, index, fingerprint, definition, ddl, keys = resource
        options = snapshot.index_options.get("bm25", {})
        if (options.get("analyzer") != definition or options.get("evidence_keys") != keys
                or not isinstance(keys, list) or set(keys) - {identity.key for identity in snapshot.identities}):
            raise SnapshotNotReady("BM25 indexed members or analyzer differ from the frozen snapshot")
        if (table, index) != corpus_names(snapshot.knowledge_base_id, snapshot.snapshot_id):
            raise SnapshotNotReady("BM25 resource identity does not match its snapshot")
        try:
            analyzer = BM25Analyzer(**definition["options"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotNotReady("invalid stored BM25 analyzer") from exc
        if analyzer.definition != definition or analyzer.fingerprint != fingerprint:
            raise SnapshotNotReady("stored BM25 analyzer does not match the pinned release")
        relation = f"{self.namespace}.{quote_identifier(table)}"
        verify_physical_index(cursor, relation=relation,
            index=f"{self.namespace}.{quote_identifier(index)}", ddl=ddl,
            trigger="immutable_bm25", subject="document")
        # Compare complete rows before publication; a readiness bit is insufficient.
        columns = "evidence_key,knowledge_base_id,document_id,document_version,chunk_id,chunk_version,body,source,metadata,parent_key"
        cursor.execute(f"WITH expected AS (SELECT {columns} FROM {self.namespace}.content "
                       "WHERE knowledge_base_id=%s AND evidence_key=ANY(%s::text[])), "
                       f"actual AS (SELECT {columns} FROM {relation}) "
                       "SELECT EXISTS((SELECT * FROM expected EXCEPT SELECT * FROM actual) "
                       "UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected))",
                       (snapshot.knowledge_base_id, keys))
        if cursor.fetchone()[0]:
            raise SnapshotNotReady("document BM25 corpus differs from authoritative snapshot content")
        return resource


def verify_physical_index(cursor, *, relation, index, ddl, trigger, subject):
    """Shared readiness checks; each corpus still verifies its own full content."""
    cursor.execute("SELECT i.indisvalid,i.indisready,am.amname,pg_get_indexdef(i.indexrelid) "
                   "FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid "
                   "JOIN pg_am am ON am.oid=idx.relam "
                   "WHERE i.indrelid=to_regclass(%s) AND i.indexrelid=to_regclass(%s)", (relation, index))
    row = cursor.fetchone()
    if row is None or row[:3] != (True, True, "paradedb") or row[3] != ddl:
        raise SnapshotNotReady(f"{subject} BM25 physical index is missing, changed or not ready")
    cursor.execute("SELECT count(*) FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid "
                   "JOIN pg_am am ON am.oid=idx.relam WHERE i.indrelid=to_regclass(%s) "
                   "AND am.amname IN ('paradedb','bm25')", (relation,))
    if cursor.fetchone()[0] != 1:
        raise SnapshotNotReady(f"{subject} corpus must have exactly one ParadeDB index")
    cursor.execute("SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass(%s) "
                   "AND tgname=%s AND tgenabled='O' AND NOT tgisinternal", (relation, trigger))
    if cursor.fetchone() is None:
        raise SnapshotNotReady(f"{subject} BM25 corpus immutability guard is missing")
