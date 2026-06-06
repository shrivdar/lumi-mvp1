"""
Yami Simulator Interface

Wraps calls to Protein Design MCP tools + LLM interpretation to simulate
a custom protein language model. For MVP, calls underlying tool functions
directly rather than via MCP protocol.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("lumi.yami.interface")

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ScoringResult:
    fitness_score: float
    stability_estimate: str
    fold_confidence: float
    expression_prediction: str
    solubility_class: str
    confidence: float


@dataclass
class MutantEffectResult:
    ddG_proxy: float  # negative = stabilizing
    effect_on_binding: str
    effect_on_expression: str
    effect_on_immunogenicity: str
    confidence: float
    rationale: str
    per_mutation_effects: list[dict] = field(default_factory=list)


@dataclass
class DesignCandidate:
    sequence: str
    predicted_fitness: float
    constraint_satisfaction: dict
    novelty_score: float
    closest_natural_sequence: str


@dataclass
class ParetoFront:
    candidates: list[DesignCandidate]
    objective_tradeoffs: str
    recommended_candidates: list[DesignCandidate]
    optimization_trajectory: list[dict]


# ---------------------------------------------------------------------------
# Yami Interface
# ---------------------------------------------------------------------------


class YamiInterface:
    """
    High-level protein intelligence interface.

    Aggregates results from ESM-2, AlphaFold DB, Biopython, and LLM
    interpretation to provide composite protein analysis capabilities.
    """

    def __init__(self):
        # Lazy import of MCP tool functions to avoid circular deps
        self._tools_imported = False

    def _ensure_tools(self):
        """Import tool functions on first use."""
        if self._tools_imported:
            return
        try:
            from src.mcp_servers.protein_design.server import (
                esm2_score_sequence,
                esm2_mutant_effect,
                esm2_embed,
                calculate_protein_properties,
                predict_solubility,
                predict_structure_alphafold,
                blast_sequence,
                calculate_cai,
                number_antibody,
                predict_developability,
            )
            self._esm2_score_sequence = esm2_score_sequence
            self._esm2_mutant_effect = esm2_mutant_effect
            self._esm2_embed = esm2_embed
            self._calculate_protein_properties = calculate_protein_properties
            self._predict_solubility = predict_solubility
            self._predict_structure_alphafold = predict_structure_alphafold
            self._blast_sequence = blast_sequence
            self._calculate_cai = calculate_cai
            self._number_antibody = number_antibody
            self._predict_developability = predict_developability
            self._tools_imported = True
        except ImportError as exc:
            logger.error("Failed to import protein design tools: %s", exc)
            self._tools_imported = False

    # ------------------------------------------------------------------
    # score
    # ------------------------------------------------------------------

    async def score(self, sequence: str) -> ScoringResult:
        """
        Composite protein fitness scoring.

        Aggregates ESM-2 pseudo-perplexity, physicochemical properties,
        and solubility prediction into a single ScoringResult.
        """
        self._ensure_tools()

        # Run tools concurrently where possible
        esm_result, props_result, sol_result = await asyncio.gather(
            asyncio.to_thread(self._safe_esm2_score, sequence),
            asyncio.to_thread(self._safe_protein_properties, sequence),
            asyncio.to_thread(self._safe_predict_solubility, sequence),
        )

        # Extract fitness score
        fitness = esm_result.get("fitness_score", 0.5)
        esm_confidence = esm_result.get("overall_confidence", 0.1)

        # Stability estimate from instability index
        instability_idx = props_result.get("instability_index", 40.0)
        if instability_idx < 30:
            stability_estimate = "highly_stable"
        elif instability_idx < 40:
            stability_estimate = "stable"
        elif instability_idx < 50:
            stability_estimate = "marginally_stable"
        else:
            stability_estimate = "unstable"

        # Fold confidence from ESM-2 (proxy)
        perplexity = esm_result.get("pseudo_perplexity")
        if perplexity is not None:
            fold_confidence = max(0.0, min(1.0, 1.0 - (perplexity - 3.0) / 20.0))
        else:
            fold_confidence = 0.3  # low confidence fallback

        # Expression prediction from properties
        props_result.get("gravy", 0.0)
        sol_class = sol_result.get("solubility_class", "unknown")

        if sol_class == "soluble" and instability_idx < 40:
            expression_prediction = "likely_high"
        elif sol_class == "soluble":
            expression_prediction = "moderate"
        elif instability_idx < 40:
            expression_prediction = "moderate"
        else:
            expression_prediction = "likely_low"

        # Composite confidence
        confidence = esm_confidence * 0.6 + (0.4 if props_result.get("molecular_weight") else 0.0)

        return ScoringResult(
            fitness_score=round(fitness, 4),
            stability_estimate=stability_estimate,
            fold_confidence=round(fold_confidence, 4),
            expression_prediction=expression_prediction,
            solubility_class=sol_class,
            confidence=round(confidence, 4),
        )

    # ------------------------------------------------------------------
    # mutant_effect
    # ------------------------------------------------------------------

    async def mutant_effect(self, wildtype: str, mutations: list[str]) -> MutantEffectResult:
        """
        Predict the effect of mutations on protein function.

        Uses ESM-2 masked marginal scoring to compute log-likelihood ratios
        and interprets results for binding, expression, and immunogenicity.
        """
        self._ensure_tools()

        mutations_str = ",".join(mutations)
        esm_result = await asyncio.to_thread(
            self._safe_esm2_mutant_effect, wildtype, mutations_str
        )

        per_mut = esm_result.get("per_mutation_effects", [])
        overall_delta = esm_result.get("overall_delta_ll", 0.0)
        confidence = esm_result.get("confidence", 0.0)

        # Interpret ddG proxy (negative delta_ll ~ destabilizing)
        ddG_proxy = -overall_delta  # flip sign: negative ddG = stabilizing

        # Binding effect interpretation
        if overall_delta > 0.5:
            effect_on_binding = "likely_improved"
        elif overall_delta < -1.0:
            effect_on_binding = "likely_reduced"
        else:
            effect_on_binding = "likely_neutral"

        # Expression effect
        if overall_delta > 0.3:
            effect_on_expression = "likely_improved"
        elif overall_delta < -0.5:
            effect_on_expression = "likely_reduced"
        else:
            effect_on_expression = "likely_neutral"

        # Immunogenicity (mutations away from germline tend to increase)
        destabilizing_count = sum(
            1 for m in per_mut if m.get("predicted_impact") == "destabilizing"
        )
        if destabilizing_count > len(mutations) // 2:
            effect_on_immunogenicity = "potentially_increased"
        else:
            effect_on_immunogenicity = "likely_unchanged"

        # Build rationale
        impacts = [m.get("predicted_impact", "unknown") for m in per_mut if "predicted_impact" in m]
        rationale = (
            f"Analysis of {len(mutations)} mutation(s) using ESM-2 masked marginal scoring. "
            f"Overall delta log-likelihood: {overall_delta:.3f}. "
            f"Individual impacts: {', '.join(f'{m}: {i}' for m, i in zip(mutations, impacts))}."
        )

        return MutantEffectResult(
            ddG_proxy=round(ddG_proxy, 4),
            effect_on_binding=effect_on_binding,
            effect_on_expression=effect_on_expression,
            effect_on_immunogenicity=effect_on_immunogenicity,
            confidence=round(confidence, 4),
            rationale=rationale,
            per_mutation_effects=per_mut,
        )

    # ------------------------------------------------------------------
    # stability
    # ------------------------------------------------------------------

    async def stability(self, sequence: str) -> dict[str, Any]:
        """
        Assess protein stability using ESM-2 perplexity + property analysis.
        """
        self._ensure_tools()

        esm_result, props_result = await asyncio.gather(
            asyncio.to_thread(self._safe_esm2_score, sequence),
            asyncio.to_thread(self._safe_protein_properties, sequence),
        )

        perplexity = esm_result.get("pseudo_perplexity")
        instability_idx = props_result.get("instability_index", None)
        gravy = props_result.get("gravy", None)

        # Thermal stability proxy
        if perplexity is not None and instability_idx is not None:
            # Heuristic: low perplexity + low instability = more stable
            stability_score = max(0.0, min(1.0,
                (1.0 - (perplexity - 3.0) / 20.0) * 0.6 +
                (1.0 - instability_idx / 100.0) * 0.4
            ))
            confidence = 0.7
        elif instability_idx is not None:
            stability_score = max(0.0, min(1.0, 1.0 - instability_idx / 100.0))
            confidence = 0.4
        else:
            stability_score = 0.5
            confidence = 0.1

        return {
            "stability_score": round(stability_score, 4),
            "esm2_perplexity": perplexity,
            "instability_index": instability_idx,
            "gravy": gravy,
            "is_stable": instability_idx < 40 if instability_idx is not None else None,
            "predicted_relative_stability": (
                "high" if stability_score > 0.7 else
                "medium" if stability_score > 0.4 else
                "low"
            ),
            "confidence": round(confidence, 4),
        }

    # ------------------------------------------------------------------
    # fold_confidence
    # ------------------------------------------------------------------

    async def fold_confidence(self, sequence: str, uniprot_id: Optional[str] = None) -> dict[str, Any]:
        """
        Assess folding confidence.

        If a UniProt ID is available, fetches AlphaFold pLDDT.
        Otherwise falls back to ESM-2 confidence proxy.
        """
        self._ensure_tools()

        if uniprot_id:
            try:
                af_result = await self._predict_structure_alphafold(uniprot_id)
                if "error" not in af_result:
                    plddt = af_result.get("pLDDT_mean", 0)
                    return {
                        "source": "alphafold_db",
                        "pLDDT_mean": plddt,
                        "fold_confidence": round(plddt / 100.0, 4) if plddt else 0.5,
                        "model_confidence": af_result.get("model_confidence", "unknown"),
                        "structure_url": af_result.get("structure_url", ""),
                        "per_residue_pLDDT": af_result.get("pLDDT_per_residue", []),
                        "confidence": 0.9,
                    }
            except Exception as exc:
                logger.warning("AlphaFold lookup failed for %s: %s", uniprot_id, exc)

        # Fallback: ESM-2 confidence proxy
        esm_result = await asyncio.to_thread(self._safe_esm2_score, sequence)
        perplexity = esm_result.get("pseudo_perplexity")

        if perplexity is not None:
            fold_conf = max(0.0, min(1.0, 1.0 - (perplexity - 3.0) / 20.0))
            confidence = 0.5  # lower confidence than AlphaFold
        else:
            fold_conf = 0.3
            confidence = 0.1

        return {
            "source": "esm2_proxy",
            "fold_confidence": round(fold_conf, 4),
            "esm2_perplexity": perplexity,
            "esm2_fitness": esm_result.get("fitness_score"),
            "note": "Fold confidence estimated from ESM-2 perplexity; use UniProt ID for AlphaFold pLDDT",
            "confidence": round(confidence, 4),
        }

    # ------------------------------------------------------------------
    # embed
    # ------------------------------------------------------------------

    async def embed(self, sequence: str) -> list[float]:
        """
        Extract ESM-2 mean-pooled embedding (1280-dim).
        """
        self._ensure_tools()

        result = await asyncio.to_thread(self._safe_esm2_embed, sequence)
        return result.get("embedding", [0.0] * 1280)

    # ------------------------------------------------------------------
    # explain
    # ------------------------------------------------------------------

    async def explain(self, sequence: str, property_name: str) -> str:
        """
        Generate a natural language explanation of a protein property.

        Gathers all available data, then uses an LLM to generate an
        interpretable explanation.
        """
        self._ensure_tools()

        # Gather data concurrently
        esm_result, props_result, sol_result, dev_result = await asyncio.gather(
            asyncio.to_thread(self._safe_esm2_score, sequence),
            asyncio.to_thread(self._safe_protein_properties, sequence),
            asyncio.to_thread(self._safe_predict_solubility, sequence),
            asyncio.to_thread(self._safe_predict_developability, sequence),
        )

        # Build context for LLM
        context = (
            f"Protein sequence ({len(sequence)} residues):\n"
            f"First 50 residues: {sequence[:50]}...\n\n"
            f"ESM-2 Analysis:\n"
            f"  Fitness score: {esm_result.get('fitness_score', 'N/A')}\n"
            f"  Pseudo-perplexity: {esm_result.get('pseudo_perplexity', 'N/A')}\n\n"
            f"Physicochemical Properties:\n"
            f"  MW: {props_result.get('molecular_weight', 'N/A')} Da\n"
            f"  pI: {props_result.get('isoelectric_point', 'N/A')}\n"
            f"  Instability index: {props_result.get('instability_index', 'N/A')}\n"
            f"  GRAVY: {props_result.get('gravy', 'N/A')}\n"
            f"  Aromaticity: {props_result.get('aromaticity', 'N/A')}\n\n"
            f"Solubility Prediction:\n"
            f"  Class: {sol_result.get('solubility_class', 'N/A')}\n"
            f"  Score: {sol_result.get('score', 'N/A')}\n\n"
            f"Developability Assessment:\n"
            f"  Overall risk: {dev_result.get('overall_risk', 'N/A')}\n"
            f"  Flags: {dev_result.get('total_flags', 'N/A')}\n"
        )

        prompt = (
            f"You are a protein biochemist. Based on the following analysis data, "
            f"explain the '{property_name}' of this protein in 2-3 paragraphs. "
            f"Be specific about which features drive your assessment and what the "
            f"numbers mean in practical terms.\n\n{context}"
        )

        try:
            from src.utils.llm import call_llm
            explanation = await call_llm(
                prompt=prompt,
                system="You are an expert protein biochemist providing clear, accurate explanations.",
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
            )
            return explanation
        except Exception as exc:
            logger.error("LLM explain failed: %s", exc)
            # Fallback: structured summary without LLM
            return (
                f"Property: {property_name}\n"
                f"ESM-2 fitness: {esm_result.get('fitness_score', 'N/A')}\n"
                f"Stability: {'stable' if props_result.get('instability_index', 50) < 40 else 'unstable'}\n"
                f"Solubility: {sol_result.get('solubility_class', 'N/A')}\n"
                f"Developability risk: {dev_result.get('overall_risk', 'N/A')}\n"
                f"(LLM explanation unavailable: {exc})"
            )

    # ------------------------------------------------------------------
    # compare
    # ------------------------------------------------------------------

    async def compare(self, sequences: list[str], criteria: list[str]) -> dict[str, Any]:
        """
        Compare multiple sequences across specified criteria.

        Scores all sequences, builds a comparison matrix, and uses an LLM
        to generate a ranked analysis.
        """
        self._ensure_tools()

        # Score all sequences concurrently
        scoring_tasks = [self.score(seq) for seq in sequences]
        scoring_results = await asyncio.gather(*scoring_tasks, return_exceptions=True)

        # Build comparison matrix
        matrix: list[dict[str, Any]] = []
        for i, (seq, result) in enumerate(zip(sequences, scoring_results)):
            if isinstance(result, Exception):
                entry = {
                    "index": i,
                    "sequence_preview": seq[:30] + "..." if len(seq) > 30 else seq,
                    "error": str(result),
                }
            else:
                entry = {
                    "index": i,
                    "sequence_preview": seq[:30] + "..." if len(seq) > 30 else seq,
                    "sequence_length": len(seq),
                    "fitness_score": result.fitness_score,
                    "stability_estimate": result.stability_estimate,
                    "fold_confidence": result.fold_confidence,
                    "expression_prediction": result.expression_prediction,
                    "solubility_class": result.solubility_class,
                    "confidence": result.confidence,
                }
            matrix.append(entry)

        # Rank by fitness score
        valid_entries = [e for e in matrix if "fitness_score" in e]
        ranked = sorted(valid_entries, key=lambda x: x["fitness_score"], reverse=True)

        # LLM-generated analysis
        analysis = ""
        try:
            from src.utils.llm import call_llm

            matrix_str = "\n".join(
                f"  Seq {e['index']}: fitness={e.get('fitness_score', '?')}, "
                f"stability={e.get('stability_estimate', '?')}, "
                f"solubility={e.get('solubility_class', '?')}, "
                f"expression={e.get('expression_prediction', '?')}"
                for e in matrix
            )
            criteria_str = ", ".join(criteria) if criteria else "overall fitness"

            prompt = (
                f"Compare these {len(sequences)} protein sequences based on criteria: {criteria_str}.\n\n"
                f"Scoring results:\n{matrix_str}\n\n"
                f"Provide a concise ranking with rationale (2-3 sentences per sequence)."
            )

            analysis = await call_llm(
                prompt=prompt,
                system="You are a protein engineer comparing candidate sequences.",
                model="claude-haiku-4-5-20251001",
            )
        except Exception as exc:
            logger.error("LLM compare analysis failed: %s", exc)
            analysis = f"(LLM analysis unavailable: {exc})"

        return {
            "comparison_matrix": matrix,
            "ranking": [e["index"] for e in ranked],
            "best_candidate": ranked[0] if ranked else None,
            "criteria": criteria,
            "analysis": analysis,
        }

    # ------------------------------------------------------------------
    # Safe wrappers (handle missing tools gracefully)
    # ------------------------------------------------------------------

    def _safe_esm2_score(self, sequence: str) -> dict[str, Any]:
        try:
            self._ensure_tools()
            if self._tools_imported:
                return self._esm2_score_sequence(sequence)
        except Exception as exc:
            logger.warning("esm2_score_sequence failed: %s", exc)
        return {
            "fitness_score": 0.5,
            "pseudo_perplexity": None,
            "overall_confidence": 0.1,
            "warning": "ESM-2 unavailable",
        }

    def _safe_esm2_mutant_effect(self, wildtype: str, mutations: str) -> dict[str, Any]:
        try:
            self._ensure_tools()
            if self._tools_imported:
                return self._esm2_mutant_effect(wildtype, mutations)
        except Exception as exc:
            logger.warning("esm2_mutant_effect failed: %s", exc)
        return {
            "per_mutation_effects": [],
            "overall_delta_ll": 0.0,
            "overall_effect": "unknown",
            "confidence": 0.1,
            "warning": "ESM-2 unavailable",
        }

    def _safe_esm2_embed(self, sequence: str) -> dict[str, Any]:
        try:
            self._ensure_tools()
            if self._tools_imported:
                return self._esm2_embed(sequence)
        except Exception as exc:
            logger.warning("esm2_embed failed: %s", exc)
        return {
            "embedding": [0.0] * 1280,
            "dimensions": 1280,
            "warning": "ESM-2 unavailable; returning zero vector",
        }

    def _safe_protein_properties(self, sequence: str) -> dict[str, Any]:
        err = "protein property tools unavailable"
        try:
            self._ensure_tools()
            if self._tools_imported:
                return self._calculate_protein_properties(sequence)
        except Exception as exc:
            err = str(exc)
            logger.warning("calculate_protein_properties failed: %s", exc)
        return {"error": err, "instability_index": 40.0, "gravy": 0.0}

    def _safe_predict_solubility(self, sequence: str) -> dict[str, Any]:
        try:
            self._ensure_tools()
            if self._tools_imported:
                return self._predict_solubility(sequence)
        except Exception as exc:
            logger.warning("predict_solubility failed: %s", exc)
        return {"solubility_class": "unknown", "score": 0.5}

    def _safe_predict_developability(self, sequence: str) -> dict[str, Any]:
        try:
            self._ensure_tools()
            if self._tools_imported:
                return self._predict_developability(sequence)
        except Exception as exc:
            logger.warning("predict_developability failed: %s", exc)
        return {"overall_risk": "unknown", "risk_flags": [], "total_flags": 0}
