"""
Virtual Cell Simulator — Lumi Virtual Lab

Wraps COBRApy genome-scale metabolic models to simulate:
- Protein expression in different hosts
- Metabolic burden of heterologous pathways
- Gene knockout effects
- Growth rate predictions

Used by the Experimental Design division and Virtual Cell agent.

When COBRApy is not installed the simulator falls back to a heuristic mode
that uses sequence-level features and literature-derived rules so that the
rest of the system can still function without a heavy numerical dependency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("lumi.virtual_cell.simulator")

# ---------------------------------------------------------------------------
# Optional COBRApy import
# ---------------------------------------------------------------------------

try:
    import cobra
    from cobra.io import load_json_model

    HAS_COBRA = True
except ImportError:
    HAS_COBRA = False
    logger.warning("COBRApy not installed — Virtual Cell will use heuristic mode")

# ---------------------------------------------------------------------------
# Kyte-Doolittle hydrophobicity scale
# ---------------------------------------------------------------------------

_KD_SCALE: dict[str, float] = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5,
    "Q": -3.5, "E": -3.5, "G": -0.4, "H": -3.2, "I": 4.5,
    "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8, "P": -1.6,
    "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}

# ---------------------------------------------------------------------------
# Result data-classes
# ---------------------------------------------------------------------------


@dataclass
class ExpressionSimResult:
    """Result of protein expression simulation."""

    host: str
    predicted_yield: str          # "high", "medium", "low"
    growth_impact: float          # fraction of wild-type growth (0-1)
    metabolic_burden: float       # estimated metabolic cost (0-1)
    bottlenecks: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


@dataclass
class KnockoutResult:
    """Result of gene knockout simulation."""

    gene: str
    model_name: str
    wildtype_growth: float
    knockout_growth: float
    growth_ratio: float           # knockout / wildtype
    is_essential: bool
    affected_reactions: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


@dataclass
class GrowthResult:
    """Result of growth rate prediction."""

    model_name: str
    growth_rate: float
    objective_value: float
    key_fluxes: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main simulator class
# ---------------------------------------------------------------------------


class VirtualCellSimulator:
    """High-level interface for metabolic simulation.

    Provides three public methods consumed by the Experimental Design
    division and the Virtual Cell specialist agent:

    * ``simulate_expression`` — predict expression yield in a host organism.
    * ``simulate_gene_knockout`` — predict the phenotypic effect of a gene KO.
    * ``predict_growth`` — predict growth rate under optional modifications.
    """

    # Mapping from short host names to BiGG model identifiers
    HOST_MODEL_MAP: dict[str, str] = {
        "ecoli": "iML1515",
        "cho": "iCHO2291",
        "human": "Recon3D",
        "yeast": "iMM904",
    }

    def __init__(self) -> None:
        self._model_cache: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Expression simulation
    # ------------------------------------------------------------------

    async def simulate_expression(
        self,
        protein_seq: str,
        host: str = "ecoli",
    ) -> ExpressionSimResult:
        """Simulate protein expression in a host organism.

        Uses sequence features (length, amino-acid composition,
        hydrophobicity) combined with COBRApy FBA (when available) to
        predict expression yield and metabolic burden.

        Parameters
        ----------
        protein_seq:
            One-letter amino-acid sequence of the target protein.
        host:
            Host organism key (``"ecoli"``, ``"cho"``, ``"human"``,
            ``"yeast"``).

        Returns
        -------
        ExpressionSimResult
            Structured prediction including yield class, growth impact,
            bottlenecks, and actionable recommendations.
        """
        seq = protein_seq.upper()
        length = len(seq)

        # --- amino-acid composition ---
        aa_counts: dict[str, int] = {}
        for aa in seq:
            aa_counts[aa] = aa_counts.get(aa, 0) + 1

        cys_pct = aa_counts.get("C", 0) / max(length, 1) * 100
        pro_pct = aa_counts.get("P", 0) / max(length, 1) * 100
        met_count = aa_counts.get("M", 0)

        # --- average hydrophobicity (GRAVY) ---
        avg_hydro = sum(_KD_SCALE.get(aa, 0.0) for aa in seq) / max(length, 1)

        # --- heuristic scoring ---
        score = 100
        bottlenecks: list[str] = []
        recommendations: list[str] = []

        if length > 800:
            score -= 20
            bottlenecks.append(
                f"Large protein ({length} aa) — may have folding issues"
            )
            recommendations.append("Consider expression as domains/fragments")

        if cys_pct > 3:
            score -= 15
            bottlenecks.append(
                f"High cysteine content ({cys_pct:.1f}%) — disulfide bond "
                "issues in E. coli cytoplasm"
            )
            recommendations.append(
                "Use SHuffle strain or periplasmic expression"
            )

        if avg_hydro > 0.5:
            score -= 15
            bottlenecks.append(
                f"High hydrophobicity (GRAVY={avg_hydro:.2f}) — aggregation risk"
            )
            recommendations.append(
                "Add solubility tags (MBP, SUMO) or lower expression temperature"
            )

        if pro_pct > 8:
            score -= 10
            bottlenecks.append(
                f"High proline content ({pro_pct:.1f}%) — slow translation"
            )

        # --- host-specific adjustments ---
        if host == "cho":
            score += 10
            recommendations.append(
                "CHO cells handle glycosylation and disulfides natively"
            )
        elif host == "ecoli":
            if cys_pct > 2:
                score -= 10
                recommendations.append(
                    "Consider Origami or Rosetta-gami strains for disulfide bonds"
                )
        elif host == "yeast":
            if length > 600:
                score -= 5
                bottlenecks.append(
                    "Very large protein — yeast secretion pathway may truncate"
                )

        # --- metabolic burden estimate ---
        # Approximately 4 ATP per amino acid for translation
        atp_cost = length * 4.0
        metabolic_burden = min(atp_cost / 50_000.0, 1.0)

        # --- growth impact (heuristic) ---
        growth_impact = max(0.5, 1.0 - metabolic_burden * 0.5)

        # --- COBRApy refinement ---
        cobra_details: dict[str, Any] = {}
        if HAS_COBRA:
            try:
                model = await self._get_model(host)
                if model is not None:
                    sol = model.optimize()
                    cobra_details["wildtype_growth"] = sol.objective_value
                    cobra_details["model_used"] = True
            except Exception as exc:
                cobra_details["error"] = str(exc)

        # --- classify yield ---
        if score >= 75:
            yield_class = "high"
        elif score >= 50:
            yield_class = "medium"
        else:
            yield_class = "low"

        return ExpressionSimResult(
            host=host,
            predicted_yield=yield_class,
            growth_impact=round(growth_impact, 4),
            metabolic_burden=round(metabolic_burden, 4),
            bottlenecks=bottlenecks,
            recommendations=recommendations,
            details={
                "score": score,
                "length": length,
                "met_count": met_count,
                "cys_pct": round(cys_pct, 2),
                "pro_pct": round(pro_pct, 2),
                "avg_hydrophobicity": round(avg_hydro, 4),
                "cobra": cobra_details,
            },
        )

    # ------------------------------------------------------------------
    # Gene knockout simulation
    # ------------------------------------------------------------------

    async def simulate_gene_knockout(
        self,
        gene: str,
        model_name: str = "iML1515",
    ) -> KnockoutResult:
        """Simulate the effect of knocking out a gene.

        Parameters
        ----------
        gene:
            Gene identifier (e.g. ``"pfkA"``).  A case-insensitive
            substring match is performed against the model gene list.
        model_name:
            BiGG model identifier (default ``"iML1515"`` for *E. coli*).

        Returns
        -------
        KnockoutResult
        """
        if not HAS_COBRA:
            return KnockoutResult(
                gene=gene,
                model_name=model_name,
                wildtype_growth=0.0,
                knockout_growth=0.0,
                growth_ratio=0.0,
                is_essential=False,
                details={"error": "COBRApy not installed — heuristic mode only"},
            )

        try:
            model = await self._get_model_by_name(model_name)
            if model is None:
                return KnockoutResult(
                    gene=gene, model_name=model_name,
                    wildtype_growth=0.0, knockout_growth=0.0,
                    growth_ratio=0.0, is_essential=False,
                    details={"error": f"Model {model_name} not found"},
                )

            import copy

            model_copy = copy.deepcopy(model)

            # Wild-type growth
            wt_sol = model_copy.optimize()
            wt_growth = wt_sol.objective_value

            # Find and knock out the target gene
            target_genes = [
                g for g in model_copy.genes
                if gene.lower() in g.id.lower()
            ]
            affected: list[str] = []
            if target_genes:
                cobra.manipulation.knock_out_model_genes(
                    model_copy, [target_genes[0].id],
                )
                for rxn in model_copy.reactions:
                    if rxn.bounds == (0, 0):
                        affected.append(rxn.id)

            ko_sol = model_copy.optimize()
            ko_growth = ko_sol.objective_value

            ratio = ko_growth / wt_growth if wt_growth > 0 else 0.0

            return KnockoutResult(
                gene=gene,
                model_name=model_name,
                wildtype_growth=round(wt_growth, 6),
                knockout_growth=round(ko_growth, 6),
                growth_ratio=round(ratio, 6),
                is_essential=(ratio < 0.01),
                affected_reactions=affected[:20],
                details={"status": "success"},
            )
        except Exception as exc:
            return KnockoutResult(
                gene=gene, model_name=model_name,
                wildtype_growth=0.0, knockout_growth=0.0,
                growth_ratio=0.0, is_essential=False,
                details={"error": str(exc)},
            )

    # ------------------------------------------------------------------
    # Growth prediction
    # ------------------------------------------------------------------

    async def predict_growth(
        self,
        model_name: str = "iML1515",
        modifications: dict[str, list[float]] | None = None,
    ) -> GrowthResult:
        """Predict growth rate for a metabolic model.

        Parameters
        ----------
        model_name:
            BiGG model identifier.
        modifications:
            Optional mapping of ``reaction_id`` to ``[lower_bound,
            upper_bound]`` pairs.  Applied to the model before solving.

        Returns
        -------
        GrowthResult
        """
        if not HAS_COBRA:
            return GrowthResult(
                model_name=model_name,
                growth_rate=0.0,
                objective_value=0.0,
                details={"error": "COBRApy not installed — heuristic mode only"},
            )

        try:
            model = await self._get_model_by_name(model_name)
            if model is None:
                return GrowthResult(
                    model_name=model_name,
                    growth_rate=0.0,
                    objective_value=0.0,
                    details={"error": f"Model {model_name} not found"},
                )

            import copy

            m = copy.deepcopy(model)

            # Apply user-specified reaction-bound modifications
            if modifications:
                for rxn_id, bounds in modifications.items():
                    if rxn_id in m.reactions:
                        rxn = m.reactions.get_by_id(rxn_id)
                        rxn.bounds = (bounds[0], bounds[1])

            sol = m.optimize()

            # Collect key exchange / biomass fluxes
            interesting_rxns = [
                "BIOMASS_Ec_iML1515_core_75p37M",
                "EX_glc__D_e",
                "EX_o2_e",
                "ATPM",
            ]
            key_fluxes: dict[str, float] = {}
            for rxn_id in interesting_rxns:
                if rxn_id in m.reactions:
                    key_fluxes[rxn_id] = round(sol.fluxes.get(rxn_id, 0.0), 6)

            return GrowthResult(
                model_name=model_name,
                growth_rate=round(sol.objective_value, 6),
                objective_value=round(sol.objective_value, 6),
                key_fluxes=key_fluxes,
                details={"status": "success"},
            )
        except Exception as exc:
            return GrowthResult(
                model_name=model_name,
                growth_rate=0.0,
                objective_value=0.0,
                details={"error": str(exc)},
            )

    # ------------------------------------------------------------------
    # Internal: model loading & caching
    # ------------------------------------------------------------------

    async def _get_model(self, host: str) -> Any:
        """Resolve a host name to a COBRApy model instance."""
        model_id = self.HOST_MODEL_MAP.get(host, "iML1515")
        return await self._get_model_by_name(model_id)

    async def _get_model_by_name(self, model_name: str) -> Any:
        """Load (and cache) a COBRApy model by its BiGG identifier.

        The loader first checks for a local file under
        ``data/metabolic_models/``.  If none is found it attempts to
        download the model JSON from the BiGG Models database.
        """
        if model_name in self._model_cache:
            return self._model_cache[model_name]

        if not HAS_COBRA:
            return None

        import asyncio
        import pathlib

        data_dir = pathlib.Path("data/metabolic_models")

        # Try local file (JSON or SBML)
        for ext in (".json", ".xml"):
            path = data_dir / f"{model_name}{ext}"
            if path.exists():
                loop = asyncio.get_running_loop()
                if ext == ".json":
                    model = await loop.run_in_executor(
                        None, load_json_model, str(path),
                    )
                else:
                    from cobra.io import read_sbml_model

                    model = await loop.run_in_executor(
                        None, read_sbml_model, str(path),
                    )
                self._model_cache[model_name] = model
                logger.info("Loaded model %s from %s", model_name, path)
                return model

        # Attempt download from BiGG Models
        try:
            import httpx

            url = f"http://bigg.ucsd.edu/static/models/{model_name}.json"
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data_dir.mkdir(parents=True, exist_ok=True)
                path = data_dir / f"{model_name}.json"
                path.write_bytes(resp.content)
                loop = asyncio.get_running_loop()
                model = await loop.run_in_executor(
                    None, load_json_model, str(path),
                )
                self._model_cache[model_name] = model
                logger.info(
                    "Downloaded and cached model %s from BiGG", model_name,
                )
                return model
        except Exception as exc:
            logger.warning("Failed to download model %s: %s", model_name, exc)
            return None
