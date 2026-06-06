"""Evidence provenance tracking.

Maintains a registry of all ``Claim`` and ``EvidenceSource`` objects
produced during an analysis, supports contradiction detection, and
exports a full provenance chain for the final report.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .types import Claim, EvidenceSource


class ProvenanceTracker:
    """Collects claims and evidence sources, detects contradictions,
    and exports a complete provenance chain."""

    def __init__(self) -> None:
        self._claims: list[Claim] = []
        self._evidence: list[EvidenceSource] = []

    # -- mutators -----------------------------------------------------------

    def add_claim(self, claim: Claim) -> None:
        """Store a claim and auto-register its evidence sources."""
        self._claims.append(claim)
        for src in claim.supporting_evidence:
            self._evidence.append(src)
        for src in claim.contradicting_evidence:
            self._evidence.append(src)

    def add_evidence(self, source: EvidenceSource) -> None:
        """Store a standalone evidence source."""
        self._evidence.append(source)

    # -- queries ------------------------------------------------------------

    def get_claims(
        self,
        agent_id: Optional[str] = None,
        min_confidence: Optional[float] = None,
    ) -> list[Claim]:
        """Retrieve claims, optionally filtered by agent and/or confidence.

        Args:
            agent_id: If given, only return claims from this agent.
            min_confidence: If given, only return claims with
                ``confidence.score >= min_confidence``.

        Returns:
            List of matching ``Claim`` objects.
        """
        results: list[Claim] = []
        for claim in self._claims:
            if agent_id is not None and claim.agent_id != agent_id:
                continue
            if min_confidence is not None and claim.confidence.score < min_confidence:
                continue
            results.append(claim)
        return results

    def check_contradiction(self, new_claim: Claim) -> list[Claim]:
        """Find existing claims that might contradict *new_claim*.

        Uses a simple keyword-overlap heuristic: two claims are
        potentially contradictory if they share significant keyword
        overlap but contain negation markers indicating opposing
        positions.

        Args:
            new_claim: The claim to check against existing claims.

        Returns:
            List of potentially contradicting ``Claim`` objects.
        """
        new_keywords = _extract_keywords(new_claim.claim_text)
        if not new_keywords:
            return []

        contradictions: list[Claim] = []
        new_has_negation = _has_negation(new_claim.claim_text)

        for existing in self._claims:
            existing_keywords = _extract_keywords(existing.claim_text)
            if not existing_keywords:
                continue

            overlap = new_keywords & existing_keywords
            # Require at least 2 shared keywords to consider a potential match
            if len(overlap) < 2:
                continue

            # If one has a negation and the other does not, flag as contradictory
            existing_has_negation = _has_negation(existing.claim_text)
            if new_has_negation != existing_has_negation:
                contradictions.append(existing)

        return contradictions

    # -- export -------------------------------------------------------------

    def export_provenance_chain(self) -> list[EvidenceSource]:
        """Return all unique evidence sources (deduplicated by source_db + source_id)."""
        seen: set[tuple[str, str]] = set()
        unique: list[EvidenceSource] = []
        for src in self._evidence:
            key = (src.source_db, src.source_id)
            if key not in seen:
                seen.add(key)
                unique.append(src)
        return unique

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entire tracker state to a plain dict."""
        return {
            "claims": [c.model_dump(mode="json") for c in self._claims],
            "evidence_sources": [e.model_dump(mode="json") for e in self._evidence],
            "unique_sources_count": len(self.export_provenance_chain()),
            "total_claims": len(self._claims),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_NEGATION_PATTERNS = re.compile(
    r"\b(not|no|never|neither|nor|cannot|can't|doesn't|don't|won't|isn't|aren't|wasn't|weren't"
    r"|unlikely|improbable|disprove|refute|contradict|fail|absent|lack|without|insufficient"
    r"|negative|negligible|insignificant)\b",
    re.IGNORECASE,
)

_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "of", "in", "to",
    "for", "with", "on", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "and",
    "but", "or", "if", "then", "than", "that", "this", "it", "its",
    "they", "them", "their", "we", "our", "you", "your", "he", "she",
    "him", "her", "his",
})


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful lowercase keywords from text (no stopwords)."""
    tokens = re.findall(r"[a-zA-Z0-9_-]{3,}", text.lower())
    return {t for t in tokens if t not in _STOPWORDS}


def _has_negation(text: str) -> bool:
    """Check whether *text* contains negation markers."""
    return bool(_NEGATION_PATTERNS.search(text))
