"""PostgreSQL 持久化；领域记录定义于 app.models.embedding。

每个 ANN 配置独占一张表，且表上仅有一个 ANN 索引。PostgreSQL
可以选择顺序扫描，但不会选用其他配置的 ANN 索引。
精确查询先将输入物化，再按距离排序。参数边界依据
pgvector v0.8.2 的 src/{hnsw,ivfflat}.h 和 README.md：
https://github.com/pgvector/pgvector/blob/v0.8.2/README.md
https://github.com/pgvector/pgvector/blob/v0.8.2/src/hnsw.h
https://github.com/pgvector/pgvector/blob/v0.8.2/src/ivfflat.h
ANN 后置过滤可能导致候选数不足 candidate_limit，且不保证精确召回。
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence
import uuid

from app.models.embedding import (
    ChunkRecord, SearchHit, EmbeddingContractError, IndexSchemeVersion,
    ContentFingerprintConflict, scheme_from_metadata,
)


def _integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in {minimum}..{maximum}")
    return value


@dataclass(frozen=True)
class PhysicalIndexConfig:
    algorithm: str = "exact"
    build_parameters: Mapping[str, int] = field(default_factory=dict)
    query_parameters: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if self.algorithm not in {"exact", "hnsw", "ivfflat"}:
            raise ValueError("algorithm must be exact, hnsw or ivfflat")
        build = dict(self.build_parameters)
        query = dict(self.query_parameters)
        allowed = {"exact": {}, "hnsw": {"m": (2, 100), "ef_construction": (4, 1000)},
                   "ivfflat": {"lists": (1, 32768)}}[self.algorithm]
        if set(build) - allowed.keys():
            raise ValueError("unsupported build parameter")
        for key, value in build.items():
            _integer(value, key, *allowed[key])
        if self.algorithm == "hnsw" and build.get("ef_construction", 64) < 2 * build.get("m", 16):
            raise ValueError("ef_construction must be at least 2 * m")
        object.__setattr__(self, "build_parameters", MappingProxyType(build))
        object.__setattr__(self, "query_parameters", MappingProxyType(self.validate_query(query)))

    def validate_query(self, values):
        query = dict(values)
        allowed = {"exact": {}, "hnsw": {"ef_search": (1, 1000)},
                   "ivfflat": {"probes": (1, 32768)}}[self.algorithm]
        if set(query) - allowed.keys():
            raise ValueError("unsupported query parameter")
        for key, value in query.items():
            _integer(value, key, *allowed[key])
        if self.algorithm == "ivfflat" and query.get("probes", 1) > self.build_parameters.get("lists", 100):
            raise ValueError("probes cannot exceed the configured lists")
        return query

    @property
    def identity(self):
        payload = json.dumps([self.algorithm, dict(self.build_parameters), dict(self.query_parameters)],
                             sort_keys=True, separators=(",", ":"))
        return self.algorithm + ":" + hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class LegacyChunkRecord:
    chunk_id: str
    document_id: str
    document_version: str
    text: str
    metadata: dict
    chunk_version: None = None

    @property
    def version(self):
        return self.document_version


@dataclass(frozen=True)
class _PersistedScheme:
    metadata: Any
    identity: str


@dataclass(frozen=True)
class RequestAttempt:
    attempt_id: str
    identity: Any
    content_fingerprint: str
    idempotency_key: str
    request_id: str | None
    status: str
    error: str | None = None
    request_payload: dict | None = None
    result_payload: dict | None = None


class DuplicateRequestAttempt(ValueError):
    """已有持久化请求占用该逻辑身份。"""


class FingerprintConflict(ContentFingerprintConflict):
    pass


def _identity_values(identity):
    values = (identity.document_id, identity.document_version, identity.chunk_id,
              identity.chunk_version, identity.scheme_identity)
    if not all(isinstance(value, str) and value for value in values):
        raise EmbeddingContractError("logical identity fields must be non-empty strings")
    return values


def _fingerprint(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise EmbeddingContractError("content_fingerprint must be a lowercase sha256 digest")
    return value


def _validate_request_payload(identity, fingerprint, payload):
    if payload is None:
        return
    if not isinstance(payload, dict):
        raise EmbeddingContractError("request_payload must be a dictionary")
    if payload.get("role", "document") not in {"document", "query"}:
        raise EmbeddingContractError("request payload role must be document or query")
    if payload.get("scheme_identity", identity.scheme_identity) != identity.scheme_identity:
        raise EmbeddingContractError("request payload scheme does not match logical identity")
    if "keys" in payload:
        key = json.dumps([identity.document_id, identity.document_version, identity.chunk_id, identity.scheme_identity, identity.chunk_version],
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        keys = payload["keys"]
        if not isinstance(keys, (list, tuple)) or key not in keys or len(keys) != len(set(keys)):
            raise EmbeddingContractError("request payload does not contain a unique logical identity")
        position = keys.index(key)
        for field in ("texts", "prepared_texts", "fingerprints"):
            if field in payload and len(payload[field]) != len(keys):
                raise EmbeddingContractError("request payload input lengths do not match")
        if "fingerprints" in payload and payload["fingerprints"][position] != fingerprint:
            raise FingerprintConflict("request payload fingerprint does not match reserved identity")
    if payload.get("fingerprint_algorithm", "sha256") != "sha256":
        raise EmbeddingContractError("request payload requires sha256 fingerprints")


def vector_literal(values):
    """Serialize already validated vector components for a bound pgvector parameter."""
    return "[" + ",".join(format(value, ".17g") for value in values) + "]"


def validate_vector(scheme, vector):
    """Validate the shared representation, float32 and cosine storage contract."""
    raw = tuple(vector)
    if any(isinstance(value, (str, bytes, bool)) for value in raw):
        raise EmbeddingContractError("vector components must be numbers")
    try:
        values = tuple(float(value) for value in raw)
    except (TypeError, ValueError, OverflowError) as error:
        raise EmbeddingContractError("vector components must be numbers") from error
    if len(values) != scheme.metadata.dimensions:
        raise EmbeddingContractError("vector dimension does not match scheme")
    # PostgreSQL vector 使用 float4 存储，仅保证 float8 值有限还不够。
    if not all(math.isfinite(value) and abs(value) <= 3.4028234663852886e38 for value in values):
        raise EmbeddingContractError("vector values must be finite float32 values")
    magnitude = math.hypot(*values)
    if magnitude == 0:
        raise EmbeddingContractError("vector must be nonzero for cosine search")
    if scheme.metadata.normalization == "unit" and abs(magnitude - 1) > 1e-6:
        raise EmbeddingContractError("vector does not satisfy unit normalization policy")
    return values


# Preserve module3's internal names while exposing the shared storage boundary.
_vector_literal = vector_literal
_validate_vector = validate_vector


def _scheme_from_metadata(payload):
    return scheme_from_metadata(json.loads(payload) if isinstance(payload, str) else payload)


def _query_parameters(config, overrides=None):
    values = {"exact": {}, "hnsw": {"ef_search": 40}, "ivfflat": {"probes": 1}}[config.algorithm].copy()
    values.update(config.query_parameters)
    if overrides is not None:
        values.update(overrides)
    return config.validate_query(values)


def _resource_names(scheme, config):
    digest = hashlib.sha256((scheme.identity + "\0" + config.identity).encode()).hexdigest()[:40]
    return "pv_resource_" + digest, "pv_index_" + digest


def _relation(value):
    # SQL 标识符位置仅允许使用服务端生成的名称。
    if re.fullmatch(r"pv_(?:resource|index)_[0-9a-f]{40}", value) is None:
        raise ValueError("invalid physical resource identifier")
    return '"' + value + '"'


class PostgresVectorStore:
    def __init__(self, dsn: str, *, connect: Callable | None = None,
                 metadata_fields: Mapping[str, type] | None = None):
        self.dsn = dsn
        self._connect = connect
        self.metadata_fields = dict(metadata_fields or {})
        if any(not isinstance(key, str) or not key or kind not in (str, int, float, bool)
               for key, kind in self.metadata_fields.items()):
            raise ValueError("metadata fields require declared str/int/float/bool types")

    def _connection(self, remaining=None):
        options = {}
        if remaining is not None:
            remaining.check()
            options["connect_timeout"] = max(1, math.ceil(remaining.remaining()))
        if self._connect is not None:
            return self._connect(self.dsn, **options)
        try:
            import psycopg
        except ImportError as error:
            raise RuntimeError("PostgresVectorStore requires psycopg[binary]>=3.2") from error
        return psycopg.connect(self.dsn, **options)

    @contextmanager
    def _transaction(self):
        from app.models.deadline import current_deadline
        from app.models.db.deadline import DeadlineCursor, watch_connection
        remaining = current_deadline()
        connection = self._connection(remaining)
        try:
            if remaining is None:
                with connection:
                    with connection.cursor() as cursor:
                        yield cursor
            else:
                with watch_connection(connection, remaining):
                    with connection:
                        with connection.cursor() as cursor:
                            remaining.check()
                            yield DeadlineCursor(cursor, remaining)
                            remaining.check()
        finally:
            connection.close()

    def migrate(self, *, dimensions: int | None = None):
        if dimensions is not None:
            _integer(dimensions, "dimensions", 1, 16000)
        with self._transaction() as cursor:
            cursor.execute(Path(__file__).with_name("pgvector_schema.sql").read_text(encoding="utf-8"))
            cursor.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
            row = cursor.fetchone()
            if row is None or tuple(int(part) for part in row[0].split('.')[:3]) < (0, 8, 0):
                raise RuntimeError("pgvector >= 0.8.0 is required")

    def _register_scheme(self, cursor, scheme):
        if not scheme.metadata.verifiable:
            raise EmbeddingContractError("legacy/unverifiable schemes cannot accept new writes or activation")
        _integer(scheme.metadata.dimensions, "dimensions", 1, 16000)
        metadata = json.dumps(asdict(scheme.metadata), ensure_ascii=False, sort_keys=True)
        cursor.execute("INSERT INTO embedding_schemes(identity,metadata,dimensions) VALUES (%s,%s::jsonb,%s) "
                       "ON CONFLICT(identity) DO NOTHING", (scheme.identity, metadata, scheme.metadata.dimensions))
        cursor.execute("SELECT metadata,dimensions FROM embedding_schemes WHERE identity=%s FOR UPDATE", (scheme.identity,))
        row = cursor.fetchone()
        if row is None or row[1] != scheme.metadata.dimensions or _scheme_from_metadata(row[0]) != scheme:
            raise EmbeddingContractError("registered scheme metadata does not match")
        cursor.execute("INSERT INTO index_registry(identity) VALUES (%s) ON CONFLICT(identity) DO NOTHING", (scheme.identity,))

    def upsert(self, scheme, chunk, vector, *, content_fingerprint=None,
               fingerprint_algorithm="sha256", generated_at=None):
        from app.models.embedding import content_fingerprint as fingerprint_for
        values = _validate_vector(scheme, vector)
        _identity_values(_ChunkIdentity(chunk, scheme.identity))
        expected_algorithm, expected_fingerprint = fingerprint_for(chunk.text, scheme.metadata, "document")
        digest = expected_fingerprint if content_fingerprint is None else _fingerprint(content_fingerprint)
        if fingerprint_algorithm != expected_algorithm or digest != expected_fingerprint:
            raise FingerprintConflict("fingerprint does not match the actual role input")
        timestamp = generated_at or datetime.now(timezone.utc)
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise EmbeddingContractError("generated_at must be a timezone-aware datetime")
        with self._transaction() as cursor:
            self._register_scheme(cursor, scheme)
            identity_values = _identity_values(_ChunkIdentity(chunk, scheme.identity))
            self._lock_identity(cursor, identity_values)
            cursor.execute("SELECT content_fingerprint FROM embedding_request_attempts WHERE document_id=%s AND document_version=%s "
                           "AND chunk_id=%s AND chunk_version=%s AND scheme_identity=%s", identity_values)
            attempt = cursor.fetchone()
            if attempt is not None and attempt[0] != digest:
                raise FingerprintConflict("reserved request has a different fingerprint for this identity")
            cursor.execute("INSERT INTO indexed_chunks(document_id,document_version,chunk_id,chunk_version,scheme_identity,"
                           "body,metadata,vector,content_fingerprint,fingerprint_algorithm,generated_at,provenance_state) "
                           "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::vector,%s,%s,%s,'verified') "
                           "ON CONFLICT(document_id,document_version,chunk_id,chunk_version,scheme_identity) "
                           "WHERE chunk_version IS NOT NULL DO NOTHING",
                           (*_identity_values(_ChunkIdentity(chunk, scheme.identity)), chunk.text, json.dumps(chunk.metadata),
                            _vector_literal(values), digest, fingerprint_algorithm, timestamp))
            cursor.execute("SELECT content_fingerprint,fingerprint_algorithm,status FROM indexed_chunks "
                           "WHERE document_id=%s AND document_version=%s AND chunk_id=%s AND chunk_version=%s "
                           "AND scheme_identity=%s FOR UPDATE", _identity_values(_ChunkIdentity(chunk, scheme.identity)))
            row = cursor.fetchone()
            if row is None or row[0] != digest or row[1] != fingerprint_algorithm:
                raise FingerprintConflict("logical index identity already has a different fingerprint")
            if row[2] == "deleted":
                raise ValueError("deleted index identity cannot be upserted")
            cursor.execute("UPDATE indexed_chunks SET metadata=%s::jsonb,status='stored',error_code=NULL,error_reason=NULL,updated_at=now() "
                           "WHERE document_id=%s AND document_version=%s AND chunk_id=%s AND chunk_version=%s "
                           "AND scheme_identity=%s",
                           (json.dumps(chunk.metadata, allow_nan=False), *identity_values))

    def register_physical_config(self, scheme, config):
        if not isinstance(config, PhysicalIndexConfig):
            raise TypeError("config must be PhysicalIndexConfig")
        if config.algorithm != "exact" and scheme.metadata.dimensions > 2000:
            raise ValueError("pgvector vector ANN indexes support at most 2000 dimensions")
        resource, index = _resource_names(scheme, config)
        with self._transaction() as cursor:
            self._register_scheme(cursor, scheme)
            cursor.execute("SELECT identity FROM physical_index_configs WHERE scheme_identity=%s AND identity=%s", (scheme.identity, config.identity))
            if cursor.fetchone() is not None:
                return config
            cursor.execute(f"CREATE TABLE {_relation(resource)} (row_id bigint PRIMARY KEY REFERENCES indexed_chunks(row_id) ON DELETE CASCADE, "
                           "scheme_identity text NOT NULL,vector vector NOT NULL,document_id text NOT NULL,document_version text NOT NULL,"
                           "chunk_id text NOT NULL,chunk_version text NOT NULL,metadata jsonb NOT NULL)")
            cursor.execute(f"INSERT INTO {_relation(resource)} SELECT row_id,scheme_identity,vector,document_id,document_version,"
                           "chunk_id,chunk_version,metadata FROM indexed_chunks WHERE scheme_identity=%s "
                           "AND status='stored' AND provenance_state='verified'", (scheme.identity,))
            if config.algorithm == "ivfflat":
                cursor.execute(f"SELECT count(*) FROM {_relation(resource)}")
                if cursor.fetchone()[0] < config.build_parameters.get("lists", 100):
                    raise ValueError("IVFFlat requires at least lists verified rows before building")
            if config.algorithm != "exact":
                options = dict({"hnsw": {"m": 16, "ef_construction": 64}, "ivfflat": {"lists": 100}}[config.algorithm])
                options.update(config.build_parameters)
                settings = ",".join(f"{key}={value}" for key, value in sorted(options.items()))
                # 转义已验证的索引方案字面量，使规划器能识别部分索引谓词。
                predicate = scheme.identity.replace("'", "''")
                cursor.execute(f"CREATE INDEX {_relation(index)} ON {_relation(resource)} USING {config.algorithm} "
                               f"((vector::vector({scheme.metadata.dimensions})) vector_cosine_ops) WITH ({settings}) "
                               f"WHERE scheme_identity='{predicate}'")
            cursor.execute("INSERT INTO physical_index_configs(scheme_identity,identity,algorithm,build_parameters,query_parameters,resource_table,index_name) "
                           "VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)",
                           (scheme.identity, config.identity, config.algorithm, json.dumps(dict(config.build_parameters)),
                            json.dumps(dict(config.query_parameters)), resource, index if config.algorithm != "exact" else None))
        return config

    def _load_config(self, cursor, scheme, config):
        if config is None:
            cursor.execute("SELECT algorithm,build_parameters,query_parameters,resource_table,index_name FROM physical_index_configs "
                           "WHERE scheme_identity=%s AND is_active", (scheme.identity,))
            row = cursor.fetchone()
            if row is None:
                return PhysicalIndexConfig(), None, None
        else:
            cursor.execute("SELECT algorithm,build_parameters,query_parameters,resource_table,index_name FROM physical_index_configs "
                           "WHERE scheme_identity=%s AND identity=%s", (scheme.identity, config.identity))
            row = cursor.fetchone()
            if row is None:
                if config.algorithm == "exact":
                    return config, None, None
                raise KeyError("physical configuration is not registered")
        loaded = PhysicalIndexConfig(row[0], _json(row[1]), _json(row[2]))
        if config is not None and loaded.identity != config.identity:
            raise ValueError("physical configuration identity does not match persisted parameters")
        _relation(row[3])
        if row[4] is not None:
            _relation(row[4])
        return loaded, row[3], row[4]

    def search(self, scheme, vector, *, limit=10, config=None, filters=None,
               score_threshold=None, distance_threshold=None, candidate_limit=None,
               query_parameters=None, legacy=False):
        values = _validate_vector(scheme, vector)
        _integer(limit, "limit", 1, 2147483647)
        budget = limit if candidate_limit is None else _integer(candidate_limit, "candidate_limit", limit, 2147483647)
        if score_threshold is not None and distance_threshold is not None:
            raise ValueError("score_threshold and distance_threshold are mutually exclusive")
        for name, value, lower, upper in (("score_threshold", score_threshold, -1, 1), ("distance_threshold", distance_threshold, 0, 2)):
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper):
                raise ValueError(f"{name} must be a finite number in {lower}..{upper}")
        threshold = distance_threshold if score_threshold is None else 1 - score_threshold
        if threshold is not None and (isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0 <= threshold <= 2):
            raise ValueError("cosine distance threshold must be in 0..2 (score in -1..1)")
        clauses, filter_values = self._filters(filters or {})
        with self._transaction() as cursor:
            selected, resource, _ = self._load_config(cursor, scheme, config)
            parameters = _query_parameters(selected, query_parameters)
            for name, value in parameters.items():
                cursor.execute("SELECT set_config(%s,%s,true)", (selected.algorithm + "." + name, str(value)))
            if legacy and selected.algorithm != "exact":
                raise ValueError("legacy/unverifiable rows are only searchable through exact legacy path")
            sql, params = self._search_sql(scheme, values, selected, resource, clauses, filter_values, budget, limit, threshold, legacy)
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        return [SearchHit((LegacyChunkRecord(row[2], row[0], row[1], row[3], _json(row[4])) if row[5] is None else
                           ChunkRecord(row[2], row[0], row[1], row[3], _json(row[4]), row[5])),
                          1 - float(row[6]), scheme.identity, row[7], row[8], row[9]) for row in rows]

    def search_legacy(self, scheme_identity, vector, **options):
        """读取持久化的旧身份并保持原值；缺失的来源绑定字段明确保留为 None。"""
        if "config" in options or "legacy" in options:
            raise ValueError("legacy search always uses the exact compatibility path")
        with self._transaction() as cursor:
            cursor.execute("SELECT metadata FROM embedding_schemes WHERE identity=%s", (scheme_identity,))
            row = cursor.fetchone()
            if row is None:
                raise KeyError("legacy scheme not found")
        scheme = _PersistedScheme(_scheme_from_metadata(row[0]).metadata, scheme_identity)
        return self.search(scheme, vector, config=PhysicalIndexConfig(), legacy=True, **options)

    def _filters(self, filters):
        clauses, values = [], []
        for key, value in sorted(filters.items()):
            if key in {"document_id", "document_version"}:
                if type(value) is not str:
                    raise ValueError("document filters require strings")
                clauses.append(key + "=%s")
                values.append(value)
            else:
                name = key[9:] if key.startswith("metadata.") else key
                kind = self.metadata_fields.get(name)
                valid = kind is not None and type(value) is kind
                if kind is float and type(value) in (int, float):
                    valid = not isinstance(value, bool) and math.isfinite(value)
                if not valid:
                    raise ValueError("metadata filter must match a declared field type")
                clauses.append("metadata @> %s::jsonb")
                values.append(json.dumps({name: value}, allow_nan=False))
        return clauses, values

    def _search_sql(self, scheme, vector, config, resource, clauses, filters, budget, limit, threshold, legacy):
        literal = _vector_literal(vector)
        predicates = ["scheme_identity=%s", *clauses]
        params = [scheme.identity, *filters]
        if config.algorithm == "exact" or legacy:
            predicates.extend(["status='stored'", "vector IS NOT NULL"])
            if not legacy:
                predicates.append("provenance_state='verified'")
            source = "WITH eligible AS MATERIALIZED (SELECT * FROM indexed_chunks WHERE " + " AND ".join(predicates) + "), "
            relation = "eligible"
        else:
            source = "WITH "
            relation = _relation(resource)
            # 部分索引谓词必须在规划时可见，预备查询也不例外。
            predicates[0] = "scheme_identity='" + scheme.identity.replace("'", "''") + "'"
            params = list(filters)
        distance = f"vector::vector({scheme.metadata.dimensions}) <=> %s::vector"
        where = "" if relation == "eligible" else " WHERE " + " AND ".join(predicates)
        # 仅按距离排序以支持 ANN 索引扫描；候选物化后再为同距结果应用稳定顺序。
        tie_order = ",document_id,document_version,chunk_id,chunk_version,row_id" if relation == "eligible" else ""
        sql = (source + "candidates AS MATERIALIZED (SELECT row_id," + distance + " AS distance FROM " + relation + where +
               " ORDER BY " + distance + tie_order + " LIMIT %s) SELECT c.document_id,c.document_version,c.chunk_id,c.body,c.metadata,"
               "c.chunk_version,n.distance,c.content_fingerprint,c.fingerprint_algorithm,c.generated_at "
               "FROM candidates n JOIN indexed_chunks c ON c.row_id=n.row_id")
        if relation == "eligible":
            params = [*params, literal, literal, budget]
        else:
            params = [literal, *params, literal, budget]
        if threshold is not None:
            sql += " WHERE n.distance <= %s"
            params.append(threshold)
        sql += " ORDER BY n.distance,c.document_id,c.document_version,c.chunk_id,c.chunk_version,c.row_id LIMIT %s"
        params.append(limit)
        return sql, tuple(params)

    def active_binding(self):
        with self._transaction() as cursor:
            cursor.execute("SELECT s.identity,s.metadata,p.algorithm,p.build_parameters,p.query_parameters FROM index_registry r "
                           "JOIN embedding_schemes s ON s.identity=r.identity JOIN physical_index_configs p ON p.scheme_identity=r.identity "
                           "WHERE r.is_active AND p.is_active")
            row = cursor.fetchone()
        if row is None:
            raise KeyError("no active serving binding")
        scheme = _scheme_from_metadata(row[1])
        if not scheme.metadata.verifiable or scheme.identity != row[0]:
            raise EmbeddingContractError("legacy active scheme requires the explicit legacy read path")
        return scheme, PhysicalIndexConfig(row[2], _json(row[3]), _json(row[4]))

    def active_scheme(self):
        with self._transaction() as cursor:
            cursor.execute("SELECT s.metadata FROM index_registry r JOIN embedding_schemes s USING(identity) WHERE r.is_active")
            row = cursor.fetchone()
            if row is None:
                raise KeyError("no active index scheme")
            return _scheme_from_metadata(row[0])

    def active_config(self, scheme):
        with self._transaction() as cursor:
            config, resource, _ = self._load_config(cursor, scheme, None)
            if resource is None:
                raise KeyError("no active physical configuration")
            return config

    def validate_and_activate(self, scheme, *, expected_count, representative_vector, expected_keys,
                              representative_key=None, threshold=0.99, config=None, actor, reason, _action="activate"):
        if not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip():
            raise ValueError("activation requires actor and reason")
        _integer(expected_count, "expected_count", 1, 2147483647)
        values = _validate_vector(scheme, representative_vector)
        if not isinstance(threshold, (float, int)) or isinstance(threshold, bool) or not math.isfinite(threshold) or not -1 <= threshold <= 1:
            raise ValueError("representative threshold must be in -1..1")
        keys = {tuple(key) for key in expected_keys}
        if len(keys) != expected_count or any(len(key) != 4 for key in keys):
            raise ValueError("manifest requires unique (document_id,document_version,chunk_id,chunk_version) keys")
        chosen = tuple(representative_key) if representative_key is not None else sorted(keys)[0]
        if chosen not in keys:
            raise ValueError("representative key must occur in manifest")
        selected = config or PhysicalIndexConfig()
        self.register_physical_config(scheme, selected)
        with self._transaction() as cursor:
            # 全局咨询锁使激活串行执行；先锁定索引方案，与写入顺序一致。
            cursor.execute("SELECT pg_advisory_xact_lock(713826004218046210)")
            cursor.execute("SELECT metadata,dimensions FROM embedding_schemes WHERE identity=%s FOR UPDATE", (scheme.identity,))
            row = cursor.fetchone()
            if row is None or row[1] != scheme.metadata.dimensions or _scheme_from_metadata(row[0]) != scheme:
                raise EmbeddingContractError("scheme metadata does not match persisted registration")
            cursor.execute("LOCK TABLE index_registry IN EXCLUSIVE MODE")
            selected, resource, index = self._load_config(cursor, scheme, selected)
            cursor.execute("SELECT document_id,document_version,chunk_id,chunk_version,status,provenance_state,vector_dims(vector),content_fingerprint,generated_at "
                           "FROM indexed_chunks WHERE scheme_identity=%s AND status <> 'deleted'", (scheme.identity,))
            rows = cursor.fetchall()
            actual = {tuple(row[:4]) for row in rows}
            malformed = sum(row[4] != "stored" or row[5] != "verified" or row[6] != scheme.metadata.dimensions or row[7] is None or row[8] is None for row in rows)
            physical = self._physical_health(cursor, scheme, selected, resource, index)
            parameters = _query_parameters(selected)
            for name, value in parameters.items():
                cursor.execute("SELECT set_config(%s,%s,true)", (selected.algorithm + "." + name, str(value)))
            query, params = self._search_sql(scheme, values, selected, resource, [], [], expected_count, expected_count, None, False)
            cursor.execute(query, params)
            representatives = cursor.fetchall()
            representative_valid = bool(representatives) and 1 - float(representatives[0][6]) >= threshold and tuple(
                (representatives[0][0], representatives[0][1], representatives[0][2], representatives[0][5])) == chosen
            report = {"expected_count": expected_count, "actual_count": len(rows), "dimension_errors": malformed,
                      "identities_valid": actual == keys, "physical_health": physical,
                      "representative_retrieval": representative_valid}
            if len(rows) != expected_count or malformed or actual != keys or not physical or not representative_valid:
                raise ValueError(f"index validation failed: {report}")
            cursor.execute("SELECT scheme_identity,identity FROM physical_index_configs WHERE is_active")
            previous = cursor.fetchone() or (None, None)
            cursor.execute("UPDATE physical_index_configs SET is_active=false WHERE is_active")
            cursor.execute("UPDATE index_registry SET is_active=false WHERE is_active")
            cursor.execute("UPDATE index_registry SET is_active=true,validated_at=now(),expected_item_count=%s WHERE identity=%s", (expected_count, scheme.identity))
            cursor.execute("UPDATE physical_index_configs SET is_active=true,validated_at=now() WHERE scheme_identity=%s AND identity=%s", (scheme.identity, selected.identity))
            cursor.execute("INSERT INTO index_activation_audit(scheme_identity,config_identity,previous_scheme,previous_config,actor,reason,action,validation_report) "
                           "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                           (scheme.identity, selected.identity, *previous, actor, reason, _action, json.dumps(report)))
            return report

    def _physical_health(self, cursor, scheme, config, resource, index):
        cursor.execute("SELECT to_regclass(%s)", (resource,))
        if cursor.fetchone()[0] is None:
            return False
        cursor.execute(f"SELECT count(*) FROM (SELECT row_id FROM {_relation(resource)} EXCEPT SELECT row_id FROM indexed_chunks "
                       "WHERE scheme_identity=%s AND status='stored' AND provenance_state='verified') extra", (scheme.identity,))
        extra = cursor.fetchone()[0]
        cursor.execute(f"SELECT count(*) FROM (SELECT row_id FROM indexed_chunks WHERE scheme_identity=%s AND status='stored' "
                       f"AND provenance_state='verified' EXCEPT SELECT row_id FROM {_relation(resource)}) missing", (scheme.identity,))
        missing = cursor.fetchone()[0]
        if extra or missing:
            return False
        cursor.execute(f"SELECT count(*) FROM {_relation(resource)} r JOIN indexed_chunks c USING(row_id) WHERE "
                       "(r.scheme_identity,r.vector,r.document_id,r.document_version,r.chunk_id,r.chunk_version,r.metadata) IS DISTINCT FROM "
                       "(c.scheme_identity,c.vector,c.document_id,c.document_version,c.chunk_id,c.chunk_version,c.metadata)")
        if cursor.fetchone()[0]:
            return False
        cursor.execute("SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_am a ON a.oid=c.relam "
                       "WHERE i.indrelid=to_regclass(%s) AND a.amname IN ('hnsw','ivfflat')", (resource,))
        if cursor.fetchone()[0] != (0 if config.algorithm == "exact" else 1):
            return False
        if config.algorithm == "exact":
            return True
        cursor.execute("SELECT i.indisvalid,i.indisready,am.amname,pg_get_indexdef(i.indexrelid),c.reloptions,"
                       "pg_get_expr(i.indpred,i.indrelid),pg_get_expr(i.indexprs,i.indrelid),i.indnkeyatts FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
                       "JOIN pg_am am ON am.oid=c.relam WHERE i.indexrelid=to_regclass(%s) AND i.indrelid=to_regclass(%s)", (index, resource))
        row = cursor.fetchone()
        if not (row and row[0] and row[1] and row[2] == config.algorithm and "vector_cosine_ops" in row[3]
                and f"vector({scheme.metadata.dimensions})" in row[3]):
            return False
        expected = {"hnsw": {"m": 16, "ef_construction": 64}, "ivfflat": {"lists": 100}}[config.algorithm].copy()
        expected.update(config.build_parameters)
        actual = dict(option.split("=", 1) for option in (row[4] or []))
        predicate = "(scheme_identity = '" + scheme.identity.replace("'", "''") + "'::text)"
        expression = re.sub(r'[\s()"]', '', row[6] or '')
        actual_predicate = re.sub(r'[\s()]', '', row[5] or '')
        expected_predicate = re.sub(r'[\s()]', '', predicate)
        return (actual == {key: str(value) for key, value in expected.items()} and actual_predicate == expected_predicate
                and expression == f"vector::vector{scheme.metadata.dimensions}" and row[7] == 1)

    def rollback(self, scheme, **validation):
        return self.validate_and_activate(scheme, **validation, _action="rollback")

    def delete_scheme(self, scheme):
        with self._transaction() as cursor:
            # 遵循激活的加锁顺序，避免并发切换激活正在删除的资源。
            cursor.execute("SELECT pg_advisory_xact_lock(713826004218046210)")
            cursor.execute("SELECT identity FROM embedding_schemes WHERE identity=%s FOR UPDATE", (scheme.identity,))
            cursor.execute("LOCK TABLE index_registry IN EXCLUSIVE MODE")
            cursor.execute("SELECT is_active FROM index_registry WHERE identity=%s FOR UPDATE", (scheme.identity,))
            row = cursor.fetchone()
            if row is None:
                raise KeyError("index scheme is not registered")
            if row[0]:
                raise ValueError("active index scheme must be switched before deletion")
            cursor.execute("SELECT resource_table,index_name,is_active FROM physical_index_configs "
                           "WHERE scheme_identity=%s ORDER BY identity FOR UPDATE", (scheme.identity,))
            resources = cursor.fetchall()
            if any(resource[2] for resource in resources):
                raise ValueError("active physical configuration must be switched before deletion")
            # 主记录转为删除标记时，同步触发器仍需访问这些资源。
            cursor.execute("UPDATE indexed_chunks SET status='deleted',updated_at=now() WHERE scheme_identity=%s AND status <> 'deleted'", (scheme.identity,))
            for resource, index, _ in resources:
                if index is not None:
                    cursor.execute(f"DROP INDEX IF EXISTS {_relation(index)}")
                cursor.execute(f"DROP TABLE IF EXISTS {_relation(resource)}")
            cursor.execute("DELETE FROM physical_index_configs WHERE scheme_identity=%s", (scheme.identity,))
            # 完整保留注册信息、主记录的删除标记、请求尝试和激活审计。

    def _transition(self, identity, status, *, previous, error_code=None, reason=None):
        values = _identity_values(identity)
        with self._transaction() as cursor:
            cursor.execute("SELECT identity FROM embedding_schemes WHERE identity=%s FOR UPDATE", (identity.scheme_identity,))
            cursor.execute("UPDATE indexed_chunks SET status=%s,error_code=%s,error_reason=%s,retry_count=retry_count+%s,updated_at=now() "
                           "WHERE document_id=%s AND document_version=%s AND chunk_id=%s AND chunk_version=%s AND scheme_identity=%s "
                           "AND status=ANY(%s)", (status, error_code, reason, 1 if status == "pending" else 0, *values, list(previous)))
            if cursor.rowcount != 1:
                raise ValueError("index item is absent, deleted or cannot make the requested transition")

    def mark_failure(self, identity, error_code, reason):
        self._transition(identity, "failed", previous=("pending", "embedded", "stored", "failed"), error_code=error_code, reason=reason)

    def retry(self, identity):
        self._transition(identity, "pending", previous=("failed",))

    def delete(self, identity):
        self._transition(identity, "deleted", previous=("pending", "embedded", "stored", "failed"))

    def _reserve_attempt(self, cursor, identity, fingerprint, *, idempotency_key, request_id=None, request_payload=None):
        values = _identity_values(identity)
        digest = _fingerprint(fingerprint)
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise ValueError("idempotency_key must be non-empty")
        _validate_request_payload(identity, digest, request_payload)
        payload = json.dumps(request_payload, ensure_ascii=False, allow_nan=False) if request_payload is not None else None
        # 与 upsert 共用锁，确保并发预留与写入的内容身份一致。
        self._lock_identity(cursor, values)
        cursor.execute("SELECT content_fingerprint,status FROM indexed_chunks WHERE document_id=%s AND document_version=%s "
                       "AND chunk_id=%s AND chunk_version=%s AND scheme_identity=%s", values)
        canonical = cursor.fetchone()
        if canonical is not None:
            if canonical[0] != digest:
                raise FingerprintConflict("index logical identity has a different fingerprint")
            if canonical[1] == "deleted":
                raise ValueError("deleted index identity cannot reserve a request")
        attempt_id = str(uuid.uuid4())
        cursor.execute("INSERT INTO embedding_request_attempts(attempt_id,document_id,document_version,chunk_id,chunk_version,scheme_identity,"
                       "content_fingerprint,idempotency_key,request_id,request_payload,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,'pending') "
                       "ON CONFLICT DO NOTHING RETURNING attempt_id", (attempt_id, *values, digest, idempotency_key, request_id, payload))
        if cursor.fetchone() is None:
            cursor.execute("SELECT content_fingerprint,status FROM embedding_request_attempts WHERE document_id=%s AND document_version=%s "
                           "AND chunk_id=%s AND chunk_version=%s AND scheme_identity=%s FOR UPDATE", values)
            row = cursor.fetchone()
            if row and row[0] != digest:
                raise FingerprintConflict("request logical identity has a different fingerprint")
            raise DuplicateRequestAttempt("request already reserved; reconcile the persisted attempt before sending again")
        return RequestAttempt(attempt_id, identity, digest, idempotency_key, request_id, "pending", None, request_payload)

    def _lock_identity(self, cursor, values):
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (json.dumps(values, ensure_ascii=False),))

    def reserve_attempt(self, identity, fingerprint, *, idempotency_key, request_id=None, request_payload=None):
        with self._transaction() as cursor:
            return self._reserve_attempt(cursor, identity, fingerprint, idempotency_key=idempotency_key,
                                         request_id=request_id, request_payload=request_payload)

    def reserve_batch_attempts(self, identities, fingerprints, *, request_payload):
        if len(identities) != len(fingerprints) or not identities:
            raise ValueError("batch identities and fingerprints must have equal nonzero length")
        batch_key = request_payload.get("idempotency_key")
        if not isinstance(batch_key, str) or not batch_key:
            raise ValueError("batch payload requires an idempotency_key")
        if len({_identity_values(identity) for identity in identities}) != len(identities):
            raise ValueError("batch contains duplicate logical identities")
        attempts = {}
        with self._transaction() as cursor:
            # 统一加锁顺序也可避免存在重叠项的批次之间发生死锁。
            for position in sorted(range(len(identities)), key=lambda index: _identity_values(identities[index])):
                identity = identities[position]
                item_key = hashlib.sha256(json.dumps([batch_key, _identity_values(identity)], ensure_ascii=False).encode()).hexdigest()
                attempts[position] = self._reserve_attempt(cursor, identity, fingerprints[position], idempotency_key=item_key,
                    request_id=request_payload.get("request_id"), request_payload=request_payload)
        return [attempts[index] for index in range(len(identities))]

    def get_attempt_for_identity(self, identity):
        with self._transaction() as cursor:
            cursor.execute("SELECT attempt_id FROM embedding_request_attempts WHERE document_id=%s AND document_version=%s "
                           "AND chunk_id=%s AND chunk_version=%s AND scheme_identity=%s", _identity_values(identity))
            row = cursor.fetchone()
        return None if row is None else self.get_attempt(row[0])

    def get_chunk(self, scheme, identity):
        if identity.scheme_identity != scheme.identity:
            raise EmbeddingContractError("chunk identity does not match scheme")
        with self._transaction() as cursor:
            cursor.execute("SELECT document_id,document_version,chunk_id,body,metadata,chunk_version,vector::text FROM indexed_chunks "
                           "WHERE document_id=%s AND document_version=%s AND chunk_id=%s AND chunk_version=%s AND scheme_identity=%s "
                           "AND status='stored' AND provenance_state='verified'", _identity_values(identity))
            row = cursor.fetchone()
        if row is None:
            return None
        return ChunkRecord(row[2], row[0], row[1], row[3], _json(row[4]), row[5]), tuple(json.loads(row[6]))

    def get_attempt(self, attempt_id):
        from app.models.embedding import LogicalIndexIdentity
        with self._transaction() as cursor:
            cursor.execute("SELECT attempt_id,document_id,document_version,chunk_id,chunk_version,scheme_identity,content_fingerprint,"
                           "idempotency_key,request_id,status,error,request_payload,result_payload FROM embedding_request_attempts WHERE attempt_id=%s", (attempt_id,))
            row = cursor.fetchone()
            if row is None:
                raise KeyError("request attempt not found")
            identity = LogicalIndexIdentity(row[1], row[2], row[3], row[5], row[4])
            return RequestAttempt(row[0], identity, row[6], row[7], row[8], row[9], row[10], _json(row[11]), _json(row[12]))

    def resolve_attempt(self, attempt_id, status, *, request_id=None, expected_request_id=None,
                        error=None, result_payload=None, request_payload=None):
        if status not in {"unknown", "succeeded", "failed", "retryable"}:
            raise ValueError("request resolution must be unknown, succeeded, failed or retryable")
        result = json.dumps(result_payload, ensure_ascii=False, allow_nan=False) if result_payload is not None else None
        request = json.dumps(request_payload, ensure_ascii=False, allow_nan=False) if request_payload is not None else None
        with self._transaction() as cursor:
            cursor.execute("SELECT status,result_payload,request_payload,request_id FROM embedding_request_attempts WHERE attempt_id=%s FOR UPDATE", (attempt_id,))
            row = cursor.fetchone()
            if row is None:
                raise KeyError("request attempt not found")
            current_request_id = row[3] if len(row) >= 4 else None
            current_result_payload = row[1] if len(row) >= 2 else None
            current_request_payload = row[2] if len(row) >= 3 else None
            if expected_request_id is not None and current_request_id != expected_request_id:
                raise ValueError("stale request resolution does not match the current provider request")
            if request_payload is not None and current_request_payload is not None:
                original = _json(current_request_payload)
                immutable = ("idempotency_key", "keys", "texts", "prepared_texts", "role", "fingerprints", "fingerprint_algorithm", "scheme_identity")
                if any(json.dumps(original.get(key), sort_keys=True) != json.dumps(request_payload.get(key), sort_keys=True) for key in immutable):
                    raise EmbeddingContractError("request payload identity and encoding input are immutable")
            if row[0] in {"succeeded", "failed"}:
                if row[0] != status or result_payload is not None and _json(current_result_payload) != result_payload:
                    raise ValueError("terminal request resolution is immutable")
            cursor.execute("UPDATE embedding_request_attempts SET status=%s,request_id=COALESCE(%s,request_id),error=%s,"
                           "result_payload=COALESCE(%s::jsonb,result_payload),request_payload=COALESCE(%s::jsonb,request_payload),updated_at=now() "
                           "WHERE attempt_id=%s", (status, request_id, error, result, request, attempt_id))
        return self.get_attempt(attempt_id)

    def retry_attempt(self, attempt_id, *, request_payload=None, idempotency_key=None):
        """仅在结果确认为可重试后显式重试。"""
        with self._transaction() as cursor:
            lookup = ("SELECT document_id,document_version,chunk_id,chunk_version,scheme_identity,status,content_fingerprint "
                      "FROM embedding_request_attempts WHERE attempt_id=%s")
            # 查询身份时不锁定请求行：预留和 upsert 操作均先锁定身份。
            cursor.execute(lookup, (attempt_id,))
            original = cursor.fetchone()
            if original is None:
                raise ValueError("only confirmed retryable attempts may be retried")
            values = tuple(original[:5])
            self._lock_identity(cursor, values)
            cursor.execute("SELECT content_fingerprint,status FROM indexed_chunks WHERE document_id=%s AND document_version=%s "
                           "AND chunk_id=%s AND chunk_version=%s AND scheme_identity=%s FOR UPDATE", values)
            canonical = cursor.fetchone()
            if canonical is not None:
                if canonical[0] != original[6]:
                    raise FingerprintConflict("index logical identity has a different fingerprint")
                if canonical[1] == "deleted":
                    raise ValueError("deleted index identity cannot retry a request")
            cursor.execute(lookup + " FOR UPDATE", (attempt_id,))
            row = cursor.fetchone()
            if row is None or row[5] != "retryable":
                raise ValueError("only confirmed retryable attempts may be retried")
            if tuple(row[:5]) != values or row[6] != original[6]:
                raise EmbeddingContractError("request logical identity and fingerprint are immutable")
            payload = None
            if request_payload is not None:
                from app.models.embedding import LogicalIndexIdentity
                original_identity = LogicalIndexIdentity(row[0], row[1], row[2], row[4], row[3])
                _validate_request_payload(original_identity, row[6], request_payload)
                batch_key = request_payload.get("idempotency_key")
                if not isinstance(batch_key, str) or not batch_key:
                    raise ValueError("retry payload requires an idempotency_key")
                idempotency_key = idempotency_key or hashlib.sha256(json.dumps([batch_key, row[:5]], ensure_ascii=False).encode()).hexdigest()
                payload = json.dumps(request_payload, ensure_ascii=False, allow_nan=False)
            if idempotency_key is not None and (not isinstance(idempotency_key, str) or not idempotency_key):
                raise ValueError("idempotency_key must be non-empty")
            cursor.execute("UPDATE embedding_request_attempts SET status='pending',error=NULL,result_payload=NULL,"
                           "request_payload=COALESCE(%s::jsonb,request_payload),idempotency_key=COALESCE(%s,idempotency_key),"
                           "request_id=%s,updated_at=now() WHERE attempt_id=%s",
                           (payload, idempotency_key, request_payload.get("request_id") if request_payload else None, attempt_id))
        return self.get_attempt(attempt_id)


@dataclass(frozen=True)
class _ChunkIdentity:
    chunk: Any
    scheme_identity: str

    @property
    def document_id(self):
        return self.chunk.document_id

    @property
    def document_version(self):
        return self.chunk.document_version

    @property
    def chunk_id(self):
        return self.chunk.chunk_id

    @property
    def chunk_version(self):
        return self.chunk.chunk_version


def _json(value):
    return json.loads(value) if isinstance(value, str) else value
