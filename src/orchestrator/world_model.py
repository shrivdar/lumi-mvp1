"""World Model — SQLite-backed persistent knowledge store.

Accumulates knowledge across analysis sessions: entities, relationships,
claims, analysis history, and open questions. This gives Lumi a persistent
memory that improves with each query.

Tables:
- entities: biological entities (genes, proteins, diseases, drugs)
- relationships: pairwise relationships between entities
- claims: scientific claims with provenance and confidence
- analysis_history: record of completed analyses
- open_questions: unresolved questions for future investigation
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

from src.utils.types import Claim, FinalReport

logger = logging.getLogger("lumi.orchestrator.world_model")

# Default database path
DEFAULT_DB_PATH = os.path.join("data", "world_model.db")

# ---------------------------------------------------------------------------
# SQL schema
# ---------------------------------------------------------------------------

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS entities (
    entity_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    entity_type     TEXT NOT NULL,  -- gene, protein, disease, drug, pathway, cell_type
    aliases         TEXT DEFAULT '[]',  -- JSON array of alias strings
    description     TEXT DEFAULT '',
    metadata        TEXT DEFAULT '{}',  -- JSON object with arbitrary metadata
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);

CREATE TABLE IF NOT EXISTS relationships (
    rel_id          TEXT PRIMARY KEY,
    source_entity   TEXT NOT NULL,
    target_entity   TEXT NOT NULL,
    relationship    TEXT NOT NULL,  -- inhibits, activates, binds, associated_with, etc.
    evidence_count  INTEGER DEFAULT 0,
    confidence      REAL DEFAULT 0.0,
    metadata        TEXT DEFAULT '{}',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (source_entity) REFERENCES entities(entity_id),
    FOREIGN KEY (target_entity) REFERENCES entities(entity_id)
);

CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_entity);
CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_entity);
CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(relationship);

CREATE TABLE IF NOT EXISTS claims (
    claim_id        TEXT PRIMARY KEY,
    claim_text      TEXT NOT NULL,
    agent_id        TEXT DEFAULT '',
    confidence_level TEXT DEFAULT 'MEDIUM',
    confidence_score REAL DEFAULT 0.5,
    evidence_json   TEXT DEFAULT '[]',  -- JSON array of evidence source dicts
    methodology     TEXT DEFAULT '',
    entity_refs     TEXT DEFAULT '[]',  -- JSON array of entity_ids this claim references
    query_id        TEXT DEFAULT '',
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claims_agent ON claims(agent_id);
CREATE INDEX IF NOT EXISTS idx_claims_query ON claims(query_id);

CREATE TABLE IF NOT EXISTS analysis_history (
    analysis_id     TEXT PRIMARY KEY,
    query_id        TEXT NOT NULL,
    user_query      TEXT NOT NULL,
    executive_summary TEXT DEFAULT '',
    total_cost      REAL DEFAULT 0.0,
    total_duration  REAL DEFAULT 0.0,
    verdict         TEXT DEFAULT '',
    entity_refs     TEXT DEFAULT '[]',  -- JSON array of entity names involved
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_history_query ON analysis_history(query_id);

CREATE TABLE IF NOT EXISTS open_questions (
    question_id     TEXT PRIMARY KEY,
    question_text   TEXT NOT NULL,
    context         TEXT DEFAULT '',
    priority        TEXT DEFAULT 'MEDIUM',
    source_query_id TEXT DEFAULT '',
    resolved        INTEGER DEFAULT 0,
    resolution      TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    resolved_at     TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_questions_resolved ON open_questions(resolved);
"""


class WorldModel:
    """SQLite-backed persistent knowledge store.

    Accumulates entities, relationships, claims, and analysis history
    across sessions.  All methods are async using ``aiosqlite``.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the database and tables if they don't exist."""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("[WorldModel] Initialized at %s", self.db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def _ensure_db(self) -> aiosqlite.Connection:
        """Return the active connection, initializing if needed."""
        if self._db is None:
            await self.initialize()
        assert self._db is not None
        return self._db

    # ------------------------------------------------------------------
    # Entity operations
    # ------------------------------------------------------------------

    async def store_entity(
        self,
        entity_id: str,
        name: str,
        entity_type: str,
        aliases: list[str] | None = None,
        description: str = "",
        metadata: dict | None = None,
    ) -> None:
        """Insert or update a biological entity."""
        db = await self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """\
            INSERT INTO entities (entity_id, name, entity_type, aliases,
                                  description, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
                name = excluded.name,
                entity_type = excluded.entity_type,
                aliases = excluded.aliases,
                description = excluded.description,
                metadata = excluded.metadata,
                updated_at = excluded.updated_at
            """,
            (
                entity_id,
                name,
                entity_type,
                json.dumps(aliases or []),
                description,
                json.dumps(metadata or {}),
                now,
                now,
            ),
        )
        await db.commit()

    async def query_entity(self, entity_name: str) -> dict:
        """Look up an entity by name (case-insensitive).

        Returns a dict with entity fields plus related claims and
        relationships, or an empty dict if not found.
        """
        db = await self._ensure_db()

        cursor = await db.execute(
            "SELECT * FROM entities WHERE LOWER(name) = LOWER(?)",
            (entity_name,),
        )
        row = await cursor.fetchone()
        if row is None:
            return {}

        entity = dict(row)
        entity["aliases"] = json.loads(entity.get("aliases", "[]"))
        entity["metadata"] = json.loads(entity.get("metadata", "{}"))

        # Fetch related claims
        cursor = await db.execute(
            """\
            SELECT * FROM claims
            WHERE entity_refs LIKE ?
            ORDER BY created_at DESC LIMIT 50
            """,
            (f'%"{entity["entity_id"]}"%',),
        )
        claims = [dict(r) for r in await cursor.fetchall()]
        entity["related_claims"] = claims

        # Fetch relationships
        cursor = await db.execute(
            """\
            SELECT * FROM relationships
            WHERE source_entity = ? OR target_entity = ?
            ORDER BY confidence DESC LIMIT 50
            """,
            (entity["entity_id"], entity["entity_id"]),
        )
        rels = [dict(r) for r in await cursor.fetchall()]
        entity["relationships"] = rels

        return entity

    # ------------------------------------------------------------------
    # Claim operations
    # ------------------------------------------------------------------

    async def store_claim(self, claim: Claim, query_id: str = "") -> None:
        """Store a scientific claim with its provenance."""
        db = await self._ensure_db()
        import uuid as _uuid

        claim_id = f"claim_{_uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        evidence_json = json.dumps(
            [
                {
                    "source_db": e.source_db,
                    "source_id": e.source_id,
                    "access_date": e.access_date.isoformat(),
                    "data_version": e.data_version,
                }
                for e in claim.supporting_evidence
            ]
        )

        await db.execute(
            """\
            INSERT INTO claims (claim_id, claim_text, agent_id,
                                confidence_level, confidence_score,
                                evidence_json, methodology, entity_refs,
                                query_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim_id,
                claim.claim_text,
                claim.agent_id,
                claim.confidence.level.value,
                claim.confidence.score,
                evidence_json,
                claim.methodology or "",
                json.dumps([]),  # entity_refs to be linked later
                query_id,
                now,
            ),
        )
        await db.commit()

    # ------------------------------------------------------------------
    # Relationship operations
    # ------------------------------------------------------------------

    async def store_relationship(
        self,
        source_entity: str,
        target_entity: str,
        relationship: str,
        confidence: float = 0.5,
        metadata: dict | None = None,
    ) -> None:
        """Store a relationship between two entities."""
        db = await self._ensure_db()
        import uuid as _uuid

        rel_id = f"rel_{_uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        await db.execute(
            """\
            INSERT INTO relationships (rel_id, source_entity, target_entity,
                                       relationship, evidence_count,
                                       confidence, metadata,
                                       created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rel_id) DO UPDATE SET
                evidence_count = evidence_count + 1,
                confidence = MAX(confidence, excluded.confidence),
                updated_at = excluded.updated_at
            """,
            (
                rel_id,
                source_entity,
                target_entity,
                relationship,
                1,
                confidence,
                json.dumps(metadata or {}),
                now,
                now,
            ),
        )
        await db.commit()

    # ------------------------------------------------------------------
    # Analysis history
    # ------------------------------------------------------------------

    async def record_analysis(self, report: FinalReport) -> None:
        """Record a completed analysis in the history."""
        db = await self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()

        # Extract entity names from key findings
        entity_refs: list[str] = []
        for claim in report.key_findings:
            # Simple heuristic: look for capitalised multi-word tokens
            words = claim.claim_text.split()
            for w in words:
                if w[0:1].isupper() and len(w) > 2:
                    entity_refs.append(w)

        await db.execute(
            """\
            INSERT OR REPLACE INTO analysis_history
                (analysis_id, query_id, user_query, executive_summary,
                 total_cost, total_duration, verdict, entity_refs, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"analysis_{report.query_id}",
                report.query_id,
                report.user_query,
                report.executive_summary[:2000],
                report.total_cost,
                report.total_duration_seconds,
                "",  # verdict — can be enriched later
                json.dumps(list(set(entity_refs))[:50]),
                now,
            ),
        )
        await db.commit()

    async def get_analysis_history(self, entity_name: str) -> list[dict]:
        """Retrieve past analyses involving a given entity.

        Args:
            entity_name: Name of the entity to search for.

        Returns:
            List of analysis history dicts, most recent first.
        """
        db = await self._ensure_db()
        cursor = await db.execute(
            """\
            SELECT * FROM analysis_history
            WHERE entity_refs LIKE ?
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (f"%{entity_name}%",),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Update from report
    # ------------------------------------------------------------------

    async def update_from_report(self, report: FinalReport) -> None:
        """Ingest all knowledge from a completed report.

        Stores claims, records the analysis, and extracts entities.
        """
        logger.info(
            "[WorldModel] Ingesting report for query_id=%s", report.query_id
        )

        # Store all claims
        for claim in report.key_findings:
            try:
                await self.store_claim(claim, query_id=report.query_id)
            except Exception as exc:
                logger.warning("[WorldModel] Failed to store claim: %s", exc)

        # Record analysis history
        try:
            await self.record_analysis(report)
        except Exception as exc:
            logger.warning("[WorldModel] Failed to record analysis: %s", exc)

        logger.info(
            "[WorldModel] Ingested %d claims from query_id=%s",
            len(report.key_findings),
            report.query_id,
        )

    # ------------------------------------------------------------------
    # Open questions
    # ------------------------------------------------------------------

    async def add_open_question(
        self,
        question_text: str,
        context: str = "",
        priority: str = "MEDIUM",
        source_query_id: str = "",
    ) -> str:
        """Add an unresolved question for future investigation.

        Returns the question_id.
        """
        db = await self._ensure_db()
        import uuid as _uuid

        question_id = f"q_{_uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        await db.execute(
            """\
            INSERT INTO open_questions
                (question_id, question_text, context, priority,
                 source_query_id, resolved, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (question_id, question_text, context, priority, source_query_id, now),
        )
        await db.commit()
        return question_id

    async def resolve_question(
        self, question_id: str, resolution: str
    ) -> None:
        """Mark an open question as resolved."""
        db = await self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """\
            UPDATE open_questions
            SET resolved = 1, resolution = ?, resolved_at = ?
            WHERE question_id = ?
            """,
            (resolution, now, question_id),
        )
        await db.commit()

    async def get_open_questions(self, limit: int = 20) -> list[dict]:
        """Retrieve unresolved questions, ordered by priority."""
        db = await self._ensure_db()
        priority_order = "CASE priority WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 WHEN 'LOW' THEN 3 ELSE 4 END"
        cursor = await db.execute(
            f"""\
            SELECT * FROM open_questions
            WHERE resolved = 0
            ORDER BY {priority_order}, created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    async def get_stats(self) -> dict:
        """Return summary statistics about the world model contents."""
        db = await self._ensure_db()
        stats: dict[str, Any] = {}

        for table in ["entities", "relationships", "claims", "analysis_history", "open_questions"]:
            cursor = await db.execute(f"SELECT COUNT(*) as cnt FROM {table}")
            row = await cursor.fetchone()
            stats[f"{table}_count"] = row["cnt"] if row else 0

        return stats
