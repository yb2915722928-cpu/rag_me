"""Real pg_search FAQ question resources, isolated per knowledge-base snapshot.

SQL authored against #85's fixed 0.26.4 APIs; execution remains unverified.
"""
from app.models.embedding import canonical_json
from .bm25 import create_index_sql, quote_identifier
from .bm25_resources import DocumentBM25Resources
from .contracts import ContentConflict, SnapshotNotReady
from .faq_bm25 import FAQBM25Analyzer, faq_corpus_names


class FAQBM25Resources:
    def __init__(self, namespace):
        self.namespace = namespace

    def load(self, cursor, snapshot):
        cursor.execute(f"SELECT table_name,index_name,analyzer_fingerprint,analyzer_definition,index_definition,item_keys "
                       f"FROM {self.namespace}.faq_bm25_resources WHERE knowledge_base_id=%s AND snapshot_id=%s",
                       (snapshot.knowledge_base_id, snapshot.snapshot_id))
        return cursor.fetchone()

    def prepare(self, cursor, snapshot):
        options = snapshot.index_options["faq_bm25"]
        analyzer = FAQBM25Analyzer(**options["analyzer"]["options"])
        keys = snapshot.index_options["faq"]["identities"]
        DocumentBM25Resources.check_runtime(cursor)
        existing = self.load(cursor, snapshot)
        if existing is not None:
            if existing[2] != analyzer.fingerprint or existing[3] != analyzer.definition or existing[5] != keys:
                raise ContentConflict("FAQ BM25 corpus is immutable; use a new snapshot_id")
            self.verify(cursor, snapshot)
            return
        cursor.execute(f"SELECT published_at FROM {self.namespace}.snapshots "
                       "WHERE knowledge_base_id=%s AND snapshot_id=%s",
                       (snapshot.knowledge_base_id, snapshot.snapshot_id))
        if cursor.fetchone()[0] is not None:
            raise SnapshotNotReady("cannot rebuild a published FAQ BM25 corpus")
        table, index = faq_corpus_names(snapshot.knowledge_base_id, snapshot.snapshot_id)
        relation = f"{self.namespace}.{quote_identifier(table)}"
        cursor.execute(f"CREATE TABLE {relation} (id bigint PRIMARY KEY, question_key text UNIQUE NOT NULL, "
                       "evidence_key text NOT NULL, knowledge_base_id text NOT NULL, question_ordinal integer NOT NULL, "
                       "body text NOT NULL, body_models text NOT NULL CHECK (body_models=body))")
        cursor.execute(f"INSERT INTO {relation} SELECT row_number() OVER (ORDER BY question_key), "
                       f"question_key,evidence_key,knowledge_base_id,question_ordinal,question,question FROM {self.namespace}.faq_questions "
                       "WHERE knowledge_base_id=%s AND evidence_key=ANY(%s::text[])",
                       (snapshot.knowledge_base_id, keys))
        cursor.execute(create_index_sql(self.namespace, table, index, analyzer))
        cursor.execute(f"CREATE TRIGGER immutable_faq_bm25 BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE "
                       f"ON {relation} FOR EACH STATEMENT EXECUTE FUNCTION {self.namespace}.reject_bm25_mutation()")
        cursor.execute("SELECT pg_get_indexdef(to_regclass(%s))", (f"{self.namespace}.{quote_identifier(index)}",))
        ddl = cursor.fetchone()[0]
        cursor.execute(f"INSERT INTO {self.namespace}.faq_bm25_resources "
                       "(knowledge_base_id,snapshot_id,table_name,index_name,analyzer_fingerprint,analyzer_definition,index_definition,item_keys) "
                       "VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb)",
                       (snapshot.knowledge_base_id, snapshot.snapshot_id, table, index, analyzer.fingerprint,
                        canonical_json(analyzer.definition), ddl, canonical_json(keys)))
        self.verify(cursor, snapshot)

    def verify(self, cursor, snapshot):
        DocumentBM25Resources.check_runtime(cursor)
        resource = self.load(cursor, snapshot)
        if resource is None:
            raise SnapshotNotReady("required FAQ BM25 resource is missing")
        table, index, fingerprint, definition, ddl, keys = resource
        if (snapshot.index_options.get("faq_bm25", {}).get("analyzer") != definition
                or snapshot.index_options.get("faq", {}).get("identities") != keys):
            raise SnapshotNotReady("FAQ BM25 analyzer or membership differs from the frozen snapshot")
        if (table, index) != faq_corpus_names(snapshot.knowledge_base_id, snapshot.snapshot_id):
            raise SnapshotNotReady("FAQ BM25 resource identity differs from snapshot")
        try:
            analyzer = FAQBM25Analyzer(**definition["options"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotNotReady("invalid FAQ BM25 analyzer") from exc
        if analyzer.definition != definition or analyzer.fingerprint != fingerprint:
            raise SnapshotNotReady("FAQ BM25 analyzer differs from the pinned release")
        relation = f"{self.namespace}.{quote_identifier(table)}"
        cursor.execute("SELECT i.indisvalid,i.indisready,am.amname,pg_get_indexdef(i.indexrelid) "
                       "FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid JOIN pg_am am ON am.oid=idx.relam "
                       "WHERE i.indrelid=to_regclass(%s) AND i.indexrelid=to_regclass(%s)",
                       (relation, f"{self.namespace}.{quote_identifier(index)}"))
        row = cursor.fetchone()
        if row is None or row[:3] != (True, True, "paradedb") or row[3] != ddl:
            raise SnapshotNotReady("FAQ BM25 physical index is missing, changed or not ready")
        cursor.execute("SELECT count(*) FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid "
                       "JOIN pg_am am ON am.oid=idx.relam WHERE i.indrelid=to_regclass(%s) "
                       "AND am.amname IN ('paradedb','bm25')", (relation,))
        if cursor.fetchone()[0] != 1:
            raise SnapshotNotReady("FAQ corpus must have exactly one ParadeDB index")
        cursor.execute("SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass(%s) "
                       "AND tgname='immutable_faq_bm25' AND tgenabled='O' AND NOT tgisinternal", (relation,))
        if cursor.fetchone() is None:
            raise SnapshotNotReady("FAQ BM25 corpus immutability guard is missing")
        cursor.execute(f"WITH expected AS (SELECT question_key,evidence_key,knowledge_base_id,question_ordinal,question "
                       f"FROM {self.namespace}.faq_questions WHERE knowledge_base_id=%s AND evidence_key=ANY(%s::text[])), "
                       f"actual AS (SELECT question_key,evidence_key,knowledge_base_id,question_ordinal,body FROM {relation}) "
                       "SELECT EXISTS((SELECT * FROM expected EXCEPT SELECT * FROM actual) "
                       "UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected))",
                       (snapshot.knowledge_base_id, keys))
        if cursor.fetchone()[0]:
            raise SnapshotNotReady("FAQ BM25 questions differ from authoritative snapshot questions")
        return resource

    def search(self, cursor, snapshot, *, match_sql, match_parameters, filter_sql, filter_parameters, top_k):
        table, _, fingerprint, _, _, _ = self.verify(cursor, snapshot)
        relation = f"{self.namespace}.{quote_identifier(table)}"
        # Unlimited physical corpus hits, then complete eligibility, then MAX per
        # item before LIMIT: extra paraphrases never consume additional item ranks.
        cursor.execute(
            f"WITH hits AS MATERIALIZED (SELECT t.*,pdb.score(t.id) AS raw_score FROM {relation} t WHERE {match_sql}), "
            "qualified AS MATERIALIZED (SELECT h.* FROM hits h "
            f"JOIN {self.namespace}.faq_items f ON f.evidence_key=h.evidence_key AND f.knowledge_base_id=h.knowledge_base_id "
            f"JOIN {self.namespace}.faq_snapshot_members m ON m.evidence_key=f.evidence_key AND m.knowledge_base_id=f.knowledge_base_id "
            f"WHERE m.knowledge_base_id=%s AND m.snapshot_id=%s AND ({filter_sql})), "
            "items AS (SELECT evidence_key,max(raw_score) AS best_score,"
            "jsonb_agg(jsonb_build_object('question',body,'raw_score',raw_score) "
            "ORDER BY raw_score DESC,question_ordinal) AS matched_questions FROM qualified GROUP BY evidence_key), "
            'ranked AS (SELECT * FROM items ORDER BY best_score DESC,evidence_key COLLATE "C" LIMIT %s) '
            "SELECT f.evidence_key,f.standard_question,f.similar_questions,f.answer,f.conditions,f.source,"
            f"r.best_score,r.matched_questions FROM ranked r JOIN {self.namespace}.faq_items f ON f.evidence_key=r.evidence_key "
            'ORDER BY r.best_score DESC,r.evidence_key COLLATE "C"',
            [*match_parameters, snapshot.knowledge_base_id, snapshot.snapshot_id, *filter_parameters, top_k])
        return cursor.fetchall(), fingerprint
