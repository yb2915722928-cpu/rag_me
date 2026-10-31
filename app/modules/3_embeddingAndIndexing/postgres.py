"""PostgreSQL + pgvector persistence for versioned Chunk indexes."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Sequence

from .contracts import EmbeddingContractError, IndexSchemeVersion


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    document_version: str
    text: str
    metadata: dict[str, Any]

    @property
    def version(self) -> str:
        return self.document_version


@dataclass(frozen=True)
class SearchHit:
    chunk: ChunkRecord
    score: float
    scheme_identity: str


class PostgresVectorStore:
    """Persist schemes and chunks atomically and search an explicitly selected scheme.

    Pass a DB-API connection factory to test without a server. Production uses
    psycopg v3, imported only when the default factory is needed.
    """

    def __init__(self, dsn: str, *, connect: Callable[[str], Any] | None = None) -> None:
        self.dsn = dsn
        self._connect = connect

    def _connection(self):
        if self._connect is not None:
            return self._connect(self.dsn)
        try:
            import psycopg
        except ImportError as error:
            raise RuntimeError("PostgresVectorStore requires psycopg[binary]>=3.2") from error
        return psycopg.connect(self.dsn)

    def migrate(self, *, dimensions: int) -> None:
        if not isinstance(dimensions, int) or isinstance(dimensions, bool) or dimensions <= 0:
            raise ValueError("dimensions must be a positive integer")
        connection = self._connection()
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS embedding_schemes (
                            identity text PRIMARY KEY,
                            metadata jsonb NOT NULL,
                            dimensions integer NOT NULL CHECK (dimensions > 0)
                        )
                    """)
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS index_registry (
                            identity text PRIMARY KEY REFERENCES embedding_schemes(identity),
                            is_active boolean NOT NULL DEFAULT false,
                            validated_at timestamptz,
                            expected_item_count bigint,
                            CHECK (expected_item_count IS NULL OR expected_item_count >= 0)
                        )
                    """)
                    cursor.execute("""
                        CREATE UNIQUE INDEX IF NOT EXISTS one_active_index_scheme
                        ON index_registry (is_active) WHERE is_active
                    """)
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS indexed_chunks (
                            document_id text NOT NULL,
                            document_version text NOT NULL,
                            chunk_id text NOT NULL,
                            scheme_identity text NOT NULL REFERENCES embedding_schemes(identity),
                            body text NOT NULL,
                            metadata jsonb NOT NULL,
                            vector vector NOT NULL,
                            status text NOT NULL DEFAULT 'stored'
                                CHECK (status IN ('pending','embedded','stored','failed','deleted')),
                            error_code text,
                            error_reason text,
                            retry_count integer NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
                            updated_at timestamptz NOT NULL DEFAULT now(),
                            PRIMARY KEY (document_id, document_version, chunk_id, scheme_identity),
                            CHECK (vector_dims(vector) > 0)
                        )
                    """)
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS indexed_chunks_scheme_idx
                        ON indexed_chunks (scheme_identity) WHERE status = 'stored'
                    """)
                    cursor.execute("""
                        CREATE OR REPLACE FUNCTION check_indexed_chunk_dimensions()
                        RETURNS trigger LANGUAGE plpgsql AS $$
                        DECLARE expected integer;
                        BEGIN
                            SELECT dimensions INTO expected FROM embedding_schemes
                            WHERE identity = NEW.scheme_identity;
                            IF expected IS NULL OR vector_dims(NEW.vector) <> expected THEN
                                RAISE EXCEPTION 'vector dimension does not match index scheme';
                            END IF;
                            RETURN NEW;
                        END $$
                    """)
                    cursor.execute("DROP TRIGGER IF EXISTS indexed_chunk_dimensions ON indexed_chunks")
                    cursor.execute("""
                        CREATE TRIGGER indexed_chunk_dimensions
                        BEFORE INSERT OR UPDATE OF vector, scheme_identity ON indexed_chunks
                        FOR EACH ROW EXECUTE FUNCTION check_indexed_chunk_dimensions()
                    """)
                    cursor.execute("""
                        CREATE OR REPLACE FUNCTION check_embedding_scheme_dimensions()
                        RETURNS trigger LANGUAGE plpgsql AS $$
                        BEGIN
                            IF EXISTS (
                                SELECT 1 FROM indexed_chunks
                                WHERE scheme_identity = NEW.identity
                                  AND vector_dims(vector) <> NEW.dimensions
                            ) THEN
                                RAISE EXCEPTION 'scheme dimension conflicts with stored vectors';
                            END IF;
                            RETURN NEW;
                        END $$
                    """)
                    cursor.execute("DROP TRIGGER IF EXISTS embedding_scheme_dimensions ON embedding_schemes")
                    cursor.execute("""
                        CREATE TRIGGER embedding_scheme_dimensions
                        BEFORE UPDATE OF dimensions ON embedding_schemes
                        FOR EACH ROW EXECUTE FUNCTION check_embedding_scheme_dimensions()
                    """)
                    cursor.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                    if cursor.fetchone() is None:
                        raise RuntimeError("pgvector extension is unavailable")
        finally:
            connection.close()

    def upsert(self, scheme: IndexSchemeVersion, chunk: ChunkRecord, vector: Sequence[float]) -> None:
        values = tuple(float(value) for value in vector)
        expected = scheme.metadata.dimensions
        if len(values) != expected:
            raise EmbeddingContractError(f"vector dimension {len(values)} does not match scheme dimension {expected}")
        import math
        if not all(math.isfinite(value) for value in values):
            raise EmbeddingContractError("vector values must be finite")
        magnitude = math.sqrt(sum(value * value for value in values))
        if scheme.metadata.normalization == "unit" and abs(magnitude - 1.0) > 1e-6:
            raise EmbeddingContractError("vector does not satisfy unit normalization policy")
        connection = self._connection()
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO embedding_schemes(identity, metadata, dimensions) VALUES (%s, %s::jsonb, %s) "
                        "ON CONFLICT (identity) DO NOTHING",
                        (scheme.identity, json.dumps(scheme.metadata.__dict__), expected),
                    )
                    cursor.execute(
                        "INSERT INTO index_registry(identity) VALUES (%s) ON CONFLICT (identity) DO NOTHING",
                        (scheme.identity,),
                    )
                    cursor.execute(
                        "INSERT INTO indexed_chunks(document_id, document_version, chunk_id, scheme_identity, body, metadata, vector) "
                        "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::vector) "
                        "ON CONFLICT (document_id, document_version, chunk_id, scheme_identity) DO UPDATE SET "
                        "body=EXCLUDED.body, metadata=EXCLUDED.metadata, vector=EXCLUDED.vector, "
                        "status='stored', error_code=NULL, error_reason=NULL, updated_at=now() "
                        "WHERE indexed_chunks.status <> 'deleted'",
                        (chunk.document_id, chunk.document_version, chunk.chunk_id, scheme.identity,
                         chunk.text, json.dumps(chunk.metadata), _vector_literal(values)),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError("deleted index identity cannot be upserted")
        finally:
            connection.close()

    def validate_and_activate(self, scheme: IndexSchemeVersion, *, expected_count: int, representative_vector: Sequence[float]) -> dict:
        values = tuple(float(value) for value in representative_vector)
        if len(values) != scheme.metadata.dimensions:
            raise EmbeddingContractError("representative vector dimension does not match scheme")
        connection = self._connection()
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT dimensions FROM embedding_schemes WHERE identity=%s FOR UPDATE", (scheme.identity,))
                    row = cursor.fetchone()
                    if row is None or row[0] != scheme.metadata.dimensions:
                        raise EmbeddingContractError("index scheme is not registered with matching dimensions")
                    cursor.execute(
                        "SELECT count(*), count(*) FILTER (WHERE status <> 'stored'), "
                        "count(*) FILTER (WHERE vector_dims(vector) <> %s) "
                        "FROM indexed_chunks WHERE scheme_identity=%s",
                        (scheme.metadata.dimensions, scheme.identity),
                    )
                    count, incomplete, malformed = cursor.fetchone()
                    cursor.execute(
                        "SELECT count(*) FROM (SELECT 1 FROM indexed_chunks WHERE scheme_identity=%s "
                        "AND status='stored' ORDER BY vector <=> %s::vector LIMIT 1) representative",
                        (scheme.identity, _vector_literal(values)),
                    )
                    has_representative = cursor.fetchone()[0] == 1
                    report = {"expected_count": expected_count, "actual_count": count,
                              "incomplete_count": incomplete, "dimension_errors": malformed,
                              "representative_retrieval": has_representative}
                    if count != expected_count or incomplete or malformed or not has_representative:
                        raise ValueError(f"index validation failed: {report}")
                    cursor.execute("UPDATE index_registry SET is_active=false WHERE is_active")
                    cursor.execute(
                        "UPDATE index_registry SET is_active=true, validated_at=now(), expected_item_count=%s "
                        "WHERE identity=%s",
                        (expected_count, scheme.identity),
                    )
                    if cursor.rowcount != 1:
                        raise KeyError("index scheme is not registered")
                    return report
        finally:
            connection.close()

    def active_scheme(self) -> IndexSchemeVersion:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT s.metadata FROM index_registry r JOIN embedding_schemes s USING(identity) "
                    "WHERE r.is_active"
                )
                row = cursor.fetchone()
                if row is None:
                    raise KeyError("no active index scheme")
                from .contracts import EmbeddingMetadata
                metadata = EmbeddingMetadata(**row[0])
                return IndexSchemeVersion(metadata)
        finally:
            connection.close()

    def delete_scheme(self, scheme: IndexSchemeVersion) -> None:
        connection = self._connection()
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT is_active FROM index_registry WHERE identity=%s FOR UPDATE", (scheme.identity,))
                    row = cursor.fetchone()
                    if row is None:
                        raise KeyError("index scheme is not registered")
                    if row[0]:
                        raise ValueError("active index scheme must be switched before deletion")
                    cursor.execute("DELETE FROM indexed_chunks WHERE scheme_identity=%s", (scheme.identity,))
                    cursor.execute("DELETE FROM index_registry WHERE identity=%s", (scheme.identity,))
                    cursor.execute("DELETE FROM embedding_schemes WHERE identity=%s", (scheme.identity,))
        finally:
            connection.close()

    def mark_failure(self, identity, error_code: str, reason: str) -> None:
        connection = self._connection()
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE indexed_chunks SET status='failed', error_code=%s, error_reason=%s, "
                        "retry_count=retry_count + 1, updated_at=now() WHERE document_id=%s AND document_version=%s "
                        "AND chunk_id=%s AND scheme_identity=%s AND status <> 'deleted'",
                        (error_code, reason, identity.document_id, identity.document_version,
                         identity.chunk_id, identity.scheme_identity),
                    )
                    if cursor.rowcount != 1:
                        raise KeyError("index item identity was not found")
        finally:
            connection.close()

    def retry(self, identity) -> None:
        connection = self._connection()
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE indexed_chunks SET status='pending', error_code=NULL, error_reason=NULL, "
                        "retry_count=retry_count + 1, updated_at=now() "
                        "WHERE document_id=%s AND document_version=%s AND chunk_id=%s "
                        "AND scheme_identity=%s AND status='failed'",
                        (identity.document_id, identity.document_version, identity.chunk_id, identity.scheme_identity),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError("only an existing failed index item can be retried")
        finally:
            connection.close()

    def delete(self, identity) -> None:
        connection = self._connection()
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE indexed_chunks SET status='deleted', updated_at=now() "
                        "WHERE document_id=%s AND document_version=%s AND chunk_id=%s "
                        "AND scheme_identity=%s AND status <> 'deleted'",
                        (identity.document_id, identity.document_version, identity.chunk_id, identity.scheme_identity),
                    )
                    if cursor.rowcount != 1:
                        raise KeyError("index item identity was not found or already deleted")
        finally:
            connection.close()

    def search(self, scheme: IndexSchemeVersion, vector: Sequence[float], *, limit: int = 10) -> list[SearchHit]:
        values = tuple(float(value) for value in vector)
        if len(values) != scheme.metadata.dimensions:
            raise EmbeddingContractError("query vector dimension does not match scheme")
        if limit <= 0:
            raise ValueError("limit must be positive")
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT document_id, document_version, chunk_id, body, metadata, "
                    "1 - (vector <=> %s::vector) AS score FROM indexed_chunks "
                    "WHERE scheme_identity = %s AND status = 'stored' "
                    "ORDER BY vector <=> %s::vector LIMIT %s",
                    (_vector_literal(values), scheme.identity, _vector_literal(values), limit),
                )
                rows = cursor.fetchall()
            return [SearchHit(ChunkRecord(row[2], row[0], row[1], row[3], row[4]), float(row[5]), scheme.identity) for row in rows]
        finally:
            connection.close()


def _vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(format(value, ".17g") for value in values) + "]"
