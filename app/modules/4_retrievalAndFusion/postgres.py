"""PostgreSQL authoritative content and immutable per-KB publication snapshots.

Connections follow module3's injected psycopg connection convention. Index
builders belong here behind prepare/publish, not in caller-provided readiness
flags. This revision implements only the authoritative content resource.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Callable, Iterable, Mapping

from app.models.embedding import canonical_json
from .contracts import (
    AuthorizationScope, ContentConflict, ContentRecord, EvidenceIdentity,
    ReadScope, RetrievalContractError, Snapshot, SnapshotNotReady, required_strings,
)
from .filters import compile_condition, validate_condition, validate_field_types, validate_metadata


class PostgresRetrievalStore:
    def __init__(self, dsn: str, *, connect: Callable | None = None,
                 schema: str = "retrieval", clock: Callable | None = None):
        if not isinstance(schema, str) or re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema) is None:
            raise RetrievalContractError("schema must be a lowercase PostgreSQL identifier")
        self.dsn = dsn
        self.schema = schema
        self._connect = connect
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._namespace = '"' + schema + '"'

    @contextmanager
    def _transaction(self):
        if self._connect is None:
            import psycopg
            connection = psycopg.connect(self.dsn)
        else:
            connection = self._connect(self.dsn)
        try:
            with connection:
                with connection.cursor() as cursor:
                    yield cursor
        finally:
            connection.close()

    def migrate(self) -> None:
        """Apply the transactional, additive authority schema; creates no extensions."""
        migration = Path(__file__).with_name("migrations") / "001_authoritative_content.sql"
        with self._transaction() as cursor:
            cursor.execute(migration.read_text(encoding="utf-8").format(schema=self._namespace))

    def ingest(self, records: Iterable[ContentRecord]) -> None:
        """Persist a batch atomically; equal identities are idempotent, never updated."""
        records = tuple(records)
        if any(not isinstance(record, ContentRecord) for record in records):
            raise RetrievalContractError("ingest requires ContentRecord values")
        with self._transaction() as cursor:
            for record in records:
                self._insert_content(cursor, record)

    def prepare(self, knowledge_base_id: str, snapshot_id: str,
                identities: Iterable[EvidenceIdentity], *,
                required_indexes: Iterable[str] = ("content",),
                field_types: Mapping[str, str] | None = None) -> Snapshot:
        """Freeze the explicitly selected revisions and build required resources.

        No ordering or version-name heuristic selects a document revision.
        A failed preparation leaves no partially prepared snapshot behind.
        """
        required_strings(knowledge_base_id, snapshot_id)
        identities = tuple(identities)
        if any(not isinstance(item, EvidenceIdentity) or item.knowledge_base_id != knowledge_base_id
               for item in identities):
            raise RetrievalContractError("snapshot identities must belong to its knowledge base")
        identities = tuple(sorted(set(identities)))
        indexes = tuple(sorted(set(required_indexes) | {"content"}))
        fields = validate_field_types(field_types or {})
        snapshot = Snapshot(knowledge_base_id, snapshot_id, identities, indexes, fields)
        manifest = {"identities": [item.key for item in identities],
                    "required_indexes": list(indexes), "field_types": fields}
        with self._transaction() as cursor:
            cursor.execute(f"INSERT INTO {self._namespace}.snapshots (knowledge_base_id, snapshot_id, manifest) "
                           "VALUES (%s, %s, %s::jsonb) ON CONFLICT DO NOTHING",
                           (knowledge_base_id, snapshot_id, canonical_json(manifest)))
            cursor.execute(f"SELECT manifest FROM {self._namespace}.snapshots "
                           "WHERE knowledge_base_id=%s AND snapshot_id=%s FOR UPDATE",
                           (knowledge_base_id, snapshot_id))
            if cursor.fetchone()[0] != manifest:
                raise ContentConflict("snapshot manifest is immutable; use a new snapshot_id")
            self._verify_content(cursor, snapshot)
            self._prepare_indexes(cursor, snapshot)
            for identity in identities:
                cursor.execute(f"INSERT INTO {self._namespace}.snapshot_members "
                               "(knowledge_base_id, snapshot_id, evidence_key) VALUES (%s, %s, %s) "
                               "ON CONFLICT DO NOTHING", (knowledge_base_id, snapshot_id, identity.key))
        return snapshot

    def publish(self, knowledge_base_id: str, snapshot_id: str) -> None:
        """Verify all required resources, then atomically switch this KB's pointer."""
        required_strings(knowledge_base_id, snapshot_id)
        with self._transaction() as cursor:
            snapshot = self._load_snapshot(cursor, knowledge_base_id, snapshot_id, lock=True)
            self._verify_content(cursor, snapshot)
            self._verify_indexes(cursor, snapshot)
            cursor.execute(f"SELECT evidence_key FROM {self._namespace}.snapshot_members "
                           "WHERE knowledge_base_id=%s AND snapshot_id=%s", (knowledge_base_id, snapshot_id))
            if {row[0] for row in cursor.fetchall()} != {item.key for item in snapshot.identities}:
                raise SnapshotNotReady("snapshot membership is incomplete")
            cursor.execute(f"UPDATE {self._namespace}.snapshots SET published_at=COALESCE(published_at, now()) "
                           "WHERE knowledge_base_id=%s AND snapshot_id=%s", (knowledge_base_id, snapshot_id))
            cursor.execute(f"INSERT INTO {self._namespace}.publications (knowledge_base_id, snapshot_id) "
                           "VALUES (%s, %s) ON CONFLICT (knowledge_base_id) "
                           "DO UPDATE SET snapshot_id=EXCLUDED.snapshot_id", (knowledge_base_id, snapshot_id))

    def pin(self, knowledge_base_ids: Iterable[str], *, authorization: AuthorizationScope,
            conditions=None, snapshot_ids: Mapping[str, str] | None = None) -> ReadScope:
        """Fix all KB snapshots in one repeatable-read transaction plus one clock instant.

        Only previously published snapshots can be explicitly selected as history.
        Authorization is caller-confirmed, never inferred from query text.
        """
        knowledge_base_ids = tuple(dict.fromkeys(knowledge_base_ids))
        required_strings(*knowledge_base_ids)
        if not knowledge_base_ids:
            raise RetrievalContractError("at least one knowledge base is required")
        if not isinstance(authorization, AuthorizationScope):
            raise RetrievalContractError("authorization is required")
        if set(knowledge_base_ids) - set(authorization.knowledge_base_ids):
            raise RetrievalContractError("requested knowledge base is outside authorization")
        selected = dict(snapshot_ids or {})
        if set(selected) - set(knowledge_base_ids):
            raise RetrievalContractError("history selection contains an unrequested knowledge base")
        required_strings(*selected.values())
        now = self._clock()
        with self._transaction() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            for kb in knowledge_base_ids:
                if kb not in selected:
                    cursor.execute(f"SELECT snapshot_id FROM {self._namespace}.publications WHERE knowledge_base_id=%s", (kb,))
                    row = cursor.fetchone()
                    if row is None:
                        raise SnapshotNotReady("knowledge base has no published snapshot")
                    selected[kb] = row[0]
                snapshot = self._load_snapshot(cursor, kb, selected[kb], published=True)
                validate_condition(conditions, snapshot.field_types)
        return ReadScope(selected, authorization, conditions, now)

    def read(self, identity: EvidenceIdentity, *, scope: ReadScope) -> ContentRecord | None:
        """Read exact evidence within the pinned snapshot, authorization and conditions.

        Missing, invisible and denied content all return None; the parent must be
        read through this same method with its own full identity and same scope.
        """
        if not isinstance(identity, EvidenceIdentity) or not isinstance(scope, ReadScope):
            raise RetrievalContractError("read requires a complete identity and pinned scope")
        kb = identity.knowledge_base_id
        if kb not in scope.snapshots or kb not in scope.authorization.knowledge_base_ids:
            return None
        documents = scope.authorization.document_ids.get(kb)
        if documents is not None and identity.document_id not in documents:
            return None
        with self._transaction() as cursor:
            snapshot = self._load_snapshot(cursor, kb, scope.snapshots[kb], published=True)
            validate_condition(scope.conditions, snapshot.field_types)
            predicate, parameters = compile_condition(scope.conditions)
            cursor.execute(f"SELECT c.body, c.source, c.metadata, c.parent_key "
                           f"FROM {self._namespace}.content c JOIN {self._namespace}.snapshot_members m "
                           "ON m.evidence_key=c.evidence_key AND m.knowledge_base_id=c.knowledge_base_id "
                           "WHERE m.knowledge_base_id=%s AND m.snapshot_id=%s AND c.evidence_key=%s AND "
                           + predicate, [kb, snapshot.snapshot_id, identity.key, *parameters])
            row = cursor.fetchone()
        if row is None:
            return None
        return ContentRecord(identity, row[0], row[1], row[2],
                             EvidenceIdentity.from_key(row[3]) if row[3] else None)

    def _insert_content(self, cursor, record):
        parent_key = record.parent.key if record.parent else None
        cursor.execute(f"INSERT INTO {self._namespace}.content "
                       "(evidence_key, knowledge_base_id, document_id, document_version, chunk_id, chunk_version, "
                       "body, source, metadata, parent_key) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s) "
                       "ON CONFLICT DO NOTHING", (record.identity.key, *record.identity.parts, record.text,
                                                  canonical_json(record.source), canonical_json(record.metadata), parent_key))
        cursor.execute(f"SELECT body, source, metadata, parent_key FROM {self._namespace}.content WHERE evidence_key=%s",
                       (record.identity.key,))
        if cursor.fetchone() != (record.text, record.source, record.metadata, parent_key):
            raise ContentConflict("evidence identity already stores different content, source, metadata or parent")

    def _load_snapshot(self, cursor, kb, snapshot_id, *, lock=False, published=False):
        cursor.execute(f"SELECT manifest, published_at FROM {self._namespace}.snapshots "
                       "WHERE knowledge_base_id=%s AND snapshot_id=%s" + (" FOR UPDATE" if lock else ""),
                       (kb, snapshot_id))
        row = cursor.fetchone()
        if row is None or (published and row[1] is None):
            raise SnapshotNotReady("snapshot is missing or has never been published")
        manifest = row[0]
        return Snapshot(kb, snapshot_id, tuple(EvidenceIdentity.from_key(key) for key in manifest["identities"]),
                        tuple(manifest["required_indexes"]), manifest["field_types"])

    def _verify_content(self, cursor, snapshot):
        keys = [identity.key for identity in snapshot.identities]
        cursor.execute(f"SELECT evidence_key, parent_key, metadata FROM {self._namespace}.content "
                       "WHERE knowledge_base_id=%s AND evidence_key=ANY(%s::text[])",
                       (snapshot.knowledge_base_id, keys))
        rows = cursor.fetchall()
        if {row[0] for row in rows} != set(keys):
            raise SnapshotNotReady("snapshot contains missing authoritative content")
        parents = {key: parent for key, parent, _ in rows}
        for key, parent, metadata in rows:
            if parent is not None and parent not in parents:
                raise SnapshotNotReady("parent must be visible in the same snapshot")
            validate_metadata(metadata, snapshot.field_types)
            visited = {key}
            while parent is not None:
                if parent in visited:
                    raise SnapshotNotReady("snapshot contains a cyclic parent relation")
                visited.add(parent)
                parent = parents.get(parent)

    def _prepare_indexes(self, cursor, snapshot):
        # Concrete builders are added here as each index path is implemented.
        # An injected boolean/mark-ready hook would let an absent index publish.
        self._verify_indexes(cursor, snapshot)

    def _verify_indexes(self, cursor, snapshot):
        unsupported = set(snapshot.required_indexes) - {"content"}
        if unsupported:
            raise SnapshotNotReady("required indexes are not implemented: " + ", ".join(sorted(unsupported)))
