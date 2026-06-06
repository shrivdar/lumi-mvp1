"""
Metabolic / Virtual Cell MCP Server -- Lumi Virtual Lab

Exposes tools for metabolic modeling (COBRApy FBA/FVA, gene/reaction knockouts,
heterologous pathway insertion), BiGG Models API queries, codon optimization,
and expression-level prediction.

Start with:  python -m src.mcp_servers.metabolic.server
"""

from __future__ import annotations

import json
import logging
import math
import pathlib
from typing import Any

from fastmcp import FastMCP

try:
    from src.mcp_servers.base import async_http_get, handle_error, standard_response
except ImportError:
    from mcp_servers.base import async_http_get, handle_error, standard_response

# ---------------------------------------------------------------------------
# Optional COBRApy import
# ---------------------------------------------------------------------------
try:
    import cobra
    from cobra.io import load_json_model, read_sbml_model
    from cobra.flux_analysis import flux_variability_analysis
    import cobra.manipulation

    HAS_COBRA = True
except ImportError:
    HAS_COBRA = False

logger = logging.getLogger("lumi.mcp.metabolic")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BIGG_API = "http://bigg.ucsd.edu/api/v2"
BIGG_STATIC = "http://bigg.ucsd.edu/static/models"

DATA_DIR = pathlib.Path(__file__).resolve().parents[3] / "data" / "metabolic_models"

# ---------------------------------------------------------------------------
# Model cache
# ---------------------------------------------------------------------------
_model_cache: dict[str, Any] = {}


async def _ensure_data_dir() -> None:
    """Create the local model-cache directory if it does not exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


async def _download_model(model_name: str) -> pathlib.Path:
    """Download a COBRA JSON model from BiGG if not already cached on disk."""
    await _ensure_data_dir()
    local_json = DATA_DIR / f"{model_name}.json"
    if local_json.exists():
        return local_json

    url = f"{BIGG_STATIC}/{model_name}.json"
    logger.info("Downloading model %s from %s ...", model_name, url)
    raw = await async_http_get(url, timeout=120.0)

    # async_http_get returns parsed JSON dict; write it back to disk
    with open(local_json, "w") as fh:
        json.dump(raw, fh)
    logger.info("Model %s saved to %s", model_name, local_json)
    return local_json


async def _load_model(model_name: str) -> Any:
    """Return a COBRApy Model object, using an in-memory cache."""
    if not HAS_COBRA:
        raise RuntimeError(
            "COBRApy is not installed.  Install it with:  pip install cobra"
        )

    if model_name in _model_cache:
        # Return a *copy* so mutations in one tool don't affect the cache
        return _model_cache[model_name].copy()

    # Try local files first (JSON and SBML)
    await _ensure_data_dir()
    local_json = DATA_DIR / f"{model_name}.json"
    local_sbml = DATA_DIR / f"{model_name}.xml"

    model: Any = None
    if local_json.exists():
        model = load_json_model(str(local_json))
    elif local_sbml.exists():
        model = read_sbml_model(str(local_sbml))
    else:
        # Download from BiGG
        path = await _download_model(model_name)
        model = load_json_model(str(path))

    _model_cache[model_name] = model
    return model.copy()


def _top_fluxes(solution: Any, n: int = 20) -> dict[str, float]:
    """Extract the top-N non-zero fluxes by absolute value from an FBA solution."""
    fluxes = solution.fluxes
    nonzero = fluxes[fluxes.abs() > 1e-8]
    top = nonzero.abs().nlargest(n)
    return {rxn_id: round(float(fluxes[rxn_id]), 6) for rxn_id in top.index}


# ---------------------------------------------------------------------------
# Codon usage tables (per-thousand values normalised to probabilities)
# ---------------------------------------------------------------------------
_ECOLI_CODON_TABLE: dict[str, dict[str, float]] = {
    "F": {"TTT": 0.58, "TTC": 0.42},
    "L": {"TTA": 0.11, "TTG": 0.11, "CTT": 0.10, "CTC": 0.10, "CTA": 0.04, "CTG": 0.54},
    "I": {"ATT": 0.49, "ATC": 0.39, "ATA": 0.07},
    "M": {"ATG": 1.0},
    "V": {"GTT": 0.26, "GTC": 0.22, "GTA": 0.15, "GTG": 0.37},
    "S": {"TCT": 0.17, "TCC": 0.15, "TCA": 0.12, "TCG": 0.15, "AGT": 0.15, "AGC": 0.26},
    "P": {"CCT": 0.16, "CCC": 0.12, "CCA": 0.19, "CCG": 0.53},
    "T": {"ACT": 0.17, "ACC": 0.44, "ACA": 0.13, "ACG": 0.26},
    "A": {"GCT": 0.16, "GCC": 0.27, "GCA": 0.21, "GCG": 0.36},
    "Y": {"TAT": 0.43, "TAC": 0.57},
    "*": {"TAA": 0.64, "TAG": 0.07, "TGA": 0.29},
    "H": {"CAT": 0.43, "CAC": 0.57},
    "Q": {"CAA": 0.34, "CAG": 0.66},
    "N": {"AAT": 0.39, "AAC": 0.61},
    "K": {"AAA": 0.76, "AAG": 0.24},
    "D": {"GAT": 0.63, "GAC": 0.37},
    "E": {"GAA": 0.68, "GAG": 0.32},
    "C": {"TGT": 0.44, "TGC": 0.56},
    "W": {"TGG": 1.0},
    "R": {"CGT": 0.38, "CGC": 0.40, "CGA": 0.06, "CGG": 0.10, "AGA": 0.04, "AGG": 0.02},
    "G": {"GGT": 0.35, "GGC": 0.40, "GGA": 0.11, "GGG": 0.14},
}

_CHO_CODON_TABLE: dict[str, dict[str, float]] = {
    "F": {"TTT": 0.43, "TTC": 0.57},
    "L": {"TTA": 0.07, "TTG": 0.13, "CTT": 0.13, "CTC": 0.20, "CTA": 0.07, "CTG": 0.40},
    "I": {"ATT": 0.34, "ATC": 0.52, "ATA": 0.14},
    "M": {"ATG": 1.0},
    "V": {"GTT": 0.17, "GTC": 0.25, "GTA": 0.11, "GTG": 0.47},
    "S": {"TCT": 0.18, "TCC": 0.22, "TCA": 0.14, "TCG": 0.06, "AGT": 0.14, "AGC": 0.26},
    "P": {"CCT": 0.28, "CCC": 0.33, "CCA": 0.27, "CCG": 0.12},
    "T": {"ACT": 0.23, "ACC": 0.37, "ACA": 0.27, "ACG": 0.13},
    "A": {"GCT": 0.26, "GCC": 0.41, "GCA": 0.22, "GCG": 0.11},
    "Y": {"TAT": 0.42, "TAC": 0.58},
    "*": {"TAA": 0.28, "TAG": 0.20, "TGA": 0.52},
    "H": {"CAT": 0.41, "CAC": 0.59},
    "Q": {"CAA": 0.25, "CAG": 0.75},
    "N": {"AAT": 0.44, "AAC": 0.56},
    "K": {"AAA": 0.40, "AAG": 0.60},
    "D": {"GAT": 0.44, "GAC": 0.56},
    "E": {"GAA": 0.41, "GAG": 0.59},
    "C": {"TGT": 0.43, "TGC": 0.57},
    "W": {"TGG": 1.0},
    "R": {"CGT": 0.08, "CGC": 0.19, "CGA": 0.11, "CGG": 0.21, "AGA": 0.20, "AGG": 0.21},
    "G": {"GGT": 0.16, "GGC": 0.34, "GGA": 0.25, "GGG": 0.25},
}

_CODON_TABLES: dict[str, dict[str, dict[str, float]]] = {
    "ecoli": _ECOLI_CODON_TABLE,
    "e_coli": _ECOLI_CODON_TABLE,
    "cho": _CHO_CODON_TABLE,
}

# Reverse genetic code (codon -> amino acid)
_CODON_TO_AA: dict[str, str] = {}
for _aa, _codons in _ECOLI_CODON_TABLE.items():
    for _codon in _codons:
        _CODON_TO_AA[_codon] = _aa


def _best_codon(aa: str, table: dict[str, dict[str, float]]) -> str:
    """Return the most-preferred codon for a given amino acid."""
    codons = table.get(aa, {})
    if not codons:
        raise ValueError(f"Unknown amino acid: {aa}")
    return max(codons, key=lambda c: codons[c])


def _cai_score(dna_seq: str, table: dict[str, dict[str, float]]) -> float:
    """Compute a simplified Codon Adaptation Index for a DNA sequence."""
    codons_in_seq = [dna_seq[i : i + 3] for i in range(0, len(dna_seq) - 2, 3)]
    log_weights: list[float] = []
    for codon in codons_in_seq:
        aa = _CODON_TO_AA.get(codon.upper())
        if aa is None:
            continue
        freqs = table.get(aa, {})
        if not freqs:
            continue
        max_freq = max(freqs.values())
        codon_freq = freqs.get(codon.upper(), 0.01)
        if max_freq > 0 and codon_freq > 0:
            log_weights.append(math.log(codon_freq / max_freq))
    if not log_weights:
        return 0.0
    return round(math.exp(sum(log_weights) / len(log_weights)), 4)


# ---------------------------------------------------------------------------
# Hydrophobicity scale (Kyte-Doolittle)
# ---------------------------------------------------------------------------
_KD_HYDROPHOBICITY: dict[str, float] = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5,
    "Q": -3.5, "E": -3.5, "G": -0.4, "H": -3.2, "I": 4.5,
    "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8, "P": -1.6,
    "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "Lumi Metabolic",
    instructions=(
        "Metabolic modeling, COBRApy FBA/FVA simulations, BiGG Models queries, "
        "codon optimization, and expression-level prediction tools for the "
        "Lumi Virtual Lab."
    ),
)


# ===== COBRApy FBA/FVA tools ================================================


@mcp.tool()
async def run_fba(
    model_name: str = "iML1515",
    objective: str | None = None,
) -> dict[str, Any]:
    """Run Flux Balance Analysis on a genome-scale metabolic model.

    Args:
        model_name: BiGG model identifier (e.g. iML1515 for E. coli,
                    iCHO2291 for CHO, Recon3D for human).
        objective: Optional reaction ID to use as the objective function.
                   Defaults to the model's built-in objective.

    Returns:
        Growth rate, objective value, solver status, and top flux values.
    """
    try:
        model = await _load_model(model_name)

        if objective:
            model.objective = objective

        solution = model.optimize()
        status = solution.status
        obj_value = round(float(solution.objective_value), 6) if status == "optimal" else None
        top = _top_fluxes(solution) if status == "optimal" else {}

        summary = (
            f"FBA on {model_name}: status={status}, "
            f"objective_value={obj_value}, "
            f"top_fluxes_count={len(top)}"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "model_name": model_name,
                "objective": str(model.objective),
                "status": status,
                "objective_value": obj_value,
                "top_fluxes": top,
                "num_reactions": len(model.reactions),
                "num_metabolites": len(model.metabolites),
                "num_genes": len(model.genes),
            },
            source="COBRApy/BiGG",
            source_id=model_name,
            confidence=0.90,
        )
    except Exception as exc:
        return handle_error("run_fba", exc)


@mcp.tool()
async def run_fva(
    model_name: str = "iML1515",
    fraction_of_optimum: float = 0.9,
) -> dict[str, Any]:
    """Run Flux Variability Analysis on a genome-scale metabolic model.

    Args:
        model_name: BiGG model identifier.
        fraction_of_optimum: Minimum fraction of optimal growth to maintain
                             while computing flux ranges (0.0-1.0).

    Returns:
        Flux ranges (minimum, maximum) for reactions in the model.
    """
    try:
        model = await _load_model(model_name)

        # Run FBA first to get the optimal growth rate
        fba_sol = model.optimize()
        wt_growth = round(float(fba_sol.objective_value), 6) if fba_sol.status == "optimal" else None

        fva_result = flux_variability_analysis(
            model,
            fraction_of_optimum=fraction_of_optimum,
        )

        # Convert to a serialisable dict: {reaction_id: {minimum, maximum}}
        fva_dict: dict[str, dict[str, float]] = {}
        for rxn_id in fva_result.index:
            mn = round(float(fva_result.loc[rxn_id, "minimum"]), 6)
            mx = round(float(fva_result.loc[rxn_id, "maximum"]), 6)
            # Only include reactions with non-trivial range
            if abs(mx - mn) > 1e-8:
                fva_dict[rxn_id] = {"minimum": mn, "maximum": mx}

        # Sort by range width descending, take top 50 for readability
        sorted_fva = dict(
            sorted(fva_dict.items(), key=lambda kv: kv[1]["maximum"] - kv[1]["minimum"], reverse=True)[:50]
        )

        summary = (
            f"FVA on {model_name} (fraction_of_optimum={fraction_of_optimum}): "
            f"wt_growth={wt_growth}, variable_reactions={len(fva_dict)}, "
            f"showing top 50 by range width"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "model_name": model_name,
                "fraction_of_optimum": fraction_of_optimum,
                "wild_type_growth": wt_growth,
                "total_variable_reactions": len(fva_dict),
                "flux_ranges": sorted_fva,
            },
            source="COBRApy/BiGG",
            source_id=model_name,
            confidence=0.88,
        )
    except Exception as exc:
        return handle_error("run_fva", exc)


@mcp.tool()
async def simulate_gene_knockout(
    model_name: str,
    gene: str,
) -> dict[str, Any]:
    """Simulate a single-gene knockout and measure growth impact.

    Args:
        model_name: BiGG model identifier (e.g. iML1515).
        gene: Gene identifier to knock out (e.g. 'b0726' for E. coli sucA).

    Returns:
        Wild-type growth rate, knockout growth rate, percentage of wild-type
        growth retained, and whether the gene is essential.
    """
    try:
        model = await _load_model(model_name)

        # Wild-type FBA
        wt_sol = model.optimize()
        wt_growth = float(wt_sol.objective_value) if wt_sol.status == "optimal" else 0.0

        # Perform knockout
        gene_obj = model.genes.get_by_id(gene)
        cobra.manipulation.knock_out_model_genes(model, [gene_obj])

        ko_sol = model.optimize()
        ko_growth = float(ko_sol.objective_value) if ko_sol.status == "optimal" else 0.0

        pct_of_wt = round((ko_growth / wt_growth) * 100, 2) if wt_growth > 1e-10 else 0.0
        is_essential = ko_growth < 1e-6

        summary = (
            f"Gene knockout {gene} in {model_name}: "
            f"growth {round(ko_growth, 6)} ({pct_of_wt}% of WT {round(wt_growth, 6)}). "
            f"Essential: {is_essential}"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "model_name": model_name,
                "gene": gene,
                "wild_type_growth": round(wt_growth, 6),
                "knockout_growth": round(ko_growth, 6),
                "percent_of_wild_type": pct_of_wt,
                "is_essential": is_essential,
                "knockout_status": ko_sol.status,
            },
            source="COBRApy/BiGG",
            source_id=f"{model_name}/{gene}",
            confidence=0.88,
        )
    except Exception as exc:
        return handle_error("simulate_gene_knockout", exc)


@mcp.tool()
async def simulate_reaction_knockout(
    model_name: str,
    reaction: str,
) -> dict[str, Any]:
    """Simulate a reaction knockout by setting its flux bounds to zero.

    Args:
        model_name: BiGG model identifier.
        reaction: Reaction ID to knock out (e.g. 'PFK' for phosphofructokinase).

    Returns:
        Wild-type vs knockout growth rates, percentage retained, essentiality.
    """
    try:
        model = await _load_model(model_name)

        # Wild-type
        wt_sol = model.optimize()
        wt_growth = float(wt_sol.objective_value) if wt_sol.status == "optimal" else 0.0

        # Knock out reaction
        rxn = model.reactions.get_by_id(reaction)
        original_bounds = (rxn.lower_bound, rxn.upper_bound)
        rxn.lower_bound = 0.0
        rxn.upper_bound = 0.0

        ko_sol = model.optimize()
        ko_growth = float(ko_sol.objective_value) if ko_sol.status == "optimal" else 0.0

        pct_of_wt = round((ko_growth / wt_growth) * 100, 2) if wt_growth > 1e-10 else 0.0
        is_essential = ko_growth < 1e-6

        summary = (
            f"Reaction knockout {reaction} in {model_name}: "
            f"growth {round(ko_growth, 6)} ({pct_of_wt}% of WT {round(wt_growth, 6)}). "
            f"Essential: {is_essential}"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "model_name": model_name,
                "reaction": reaction,
                "reaction_name": rxn.name,
                "original_bounds": list(original_bounds),
                "wild_type_growth": round(wt_growth, 6),
                "knockout_growth": round(ko_growth, 6),
                "percent_of_wild_type": pct_of_wt,
                "is_essential": is_essential,
                "knockout_status": ko_sol.status,
            },
            source="COBRApy/BiGG",
            source_id=f"{model_name}/{reaction}",
            confidence=0.88,
        )
    except Exception as exc:
        return handle_error("simulate_reaction_knockout", exc)


@mcp.tool()
async def add_heterologous_pathway(
    model_name: str,
    reactions_json: str,
) -> dict[str, Any]:
    """Add heterologous reactions to a model and run FBA.

    Useful for simulating the metabolic impact of inserting a biosynthetic
    pathway from another organism.

    Args:
        model_name: BiGG model identifier.
        reactions_json: JSON string describing reactions to add. Format:
            [
              {
                "id": "RXN_NEW",
                "name": "New reaction",
                "metabolites": {"met_a_c": -1, "met_b_c": 1},
                "lower_bound": 0,
                "upper_bound": 1000
              }
            ]
            Metabolite IDs must use existing model metabolites or include a
            compartment suffix (e.g. _c for cytoplasm, _e for extracellular).

    Returns:
        Growth rate with the pathway, flux through added reactions, and
        comparison with wild-type.
    """
    try:
        model = await _load_model(model_name)

        # Wild-type growth
        wt_sol = model.optimize()
        wt_growth = float(wt_sol.objective_value) if wt_sol.status == "optimal" else 0.0

        # Parse reactions
        rxn_specs = json.loads(reactions_json)
        added_ids: list[str] = []
        for spec in rxn_specs:
            rxn = cobra.Reaction(spec["id"])
            rxn.name = spec.get("name", spec["id"])
            rxn.lower_bound = spec.get("lower_bound", 0.0)
            rxn.upper_bound = spec.get("upper_bound", 1000.0)

            # Build metabolite dict
            met_dict: dict[Any, float] = {}
            for met_id, coeff in spec["metabolites"].items():
                try:
                    met_obj = model.metabolites.get_by_id(met_id)
                except KeyError:
                    # Create a new metabolite if it does not exist
                    met_obj = cobra.Metabolite(
                        met_id,
                        name=met_id,
                        compartment=met_id.rsplit("_", 1)[-1] if "_" in met_id else "c",
                    )
                met_dict[met_obj] = float(coeff)
            rxn.add_metabolites(met_dict)
            model.add_reactions([rxn])
            added_ids.append(spec["id"])

        # FBA with new pathway
        new_sol = model.optimize()
        new_growth = float(new_sol.objective_value) if new_sol.status == "optimal" else 0.0

        # Fluxes through added reactions
        added_fluxes: dict[str, float] = {}
        if new_sol.status == "optimal":
            for rid in added_ids:
                added_fluxes[rid] = round(float(new_sol.fluxes.get(rid, 0.0)), 6)

        pct_of_wt = round((new_growth / wt_growth) * 100, 2) if wt_growth > 1e-10 else 0.0

        summary = (
            f"Added {len(added_ids)} reactions to {model_name}: "
            f"new growth={round(new_growth, 6)} ({pct_of_wt}% of WT {round(wt_growth, 6)})"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "model_name": model_name,
                "added_reactions": added_ids,
                "wild_type_growth": round(wt_growth, 6),
                "new_growth": round(new_growth, 6),
                "percent_of_wild_type": pct_of_wt,
                "added_reaction_fluxes": added_fluxes,
                "status": new_sol.status,
            },
            source="COBRApy/BiGG",
            source_id=model_name,
            confidence=0.82,
        )
    except Exception as exc:
        return handle_error("add_heterologous_pathway", exc)


# ===== BiGG Models API tools ================================================


@mcp.tool()
async def list_available_models() -> dict[str, Any]:
    """List all genome-scale metabolic models available in the BiGG database.

    Returns:
        List of models with their identifiers, organism, reaction/metabolite
        counts, and genome name.
    """
    try:
        url = f"{BIGG_API}/models"
        data = await async_http_get(url)
        results = data.get("results", [])

        models_summary = []
        for m in results:
            models_summary.append({
                "bigg_id": m.get("bigg_id"),
                "organism": m.get("organism"),
                "metabolite_count": m.get("metabolite_count"),
                "reaction_count": m.get("reaction_count"),
                "gene_count": m.get("gene_count"),
            })

        summary = f"BiGG database contains {len(models_summary)} genome-scale metabolic models"
        return standard_response(
            summary=summary,
            raw_data={"models": models_summary, "results_count": len(models_summary)},
            source="BiGG Models",
            source_id="models_list",
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("list_available_models", exc)


@mcp.tool()
async def get_model_info(model_id: str) -> dict[str, Any]:
    """Get detailed information about a specific BiGG metabolic model.

    Args:
        model_id: BiGG model identifier (e.g. 'iML1515', 'iJO1366').

    Returns:
        Model metadata including organism, reaction/metabolite/gene counts,
        genome name, and reference information.
    """
    try:
        url = f"{BIGG_API}/models/{model_id}"
        data = await async_http_get(url)

        summary = (
            f"Model {model_id}: organism={data.get('organism', 'N/A')}, "
            f"reactions={data.get('reaction_count', 'N/A')}, "
            f"metabolites={data.get('metabolite_count', 'N/A')}, "
            f"genes={data.get('gene_count', 'N/A')}"
        )
        return standard_response(
            summary=summary,
            raw_data=data,
            source="BiGG Models",
            source_id=model_id,
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("get_model_info", exc)


@mcp.tool()
async def get_model_reactions(
    model_id: str,
    search: str | None = None,
) -> dict[str, Any]:
    """Get reactions from a BiGG metabolic model, optionally filtered by search term.

    Args:
        model_id: BiGG model identifier.
        search: Optional search string to filter reactions by name or ID.

    Returns:
        List of reactions with IDs, names, and subsystems.
    """
    try:
        url = f"{BIGG_API}/models/{model_id}/reactions"
        params: dict[str, str] = {}
        if search:
            params["query"] = search
        data = await async_http_get(url, params=params if params else None)

        results = data.get("results", [])
        reactions = []
        for r in results[:200]:  # Cap at 200 for readability
            reactions.append({
                "bigg_id": r.get("bigg_id"),
                "name": r.get("name"),
                "model_bigg_id": r.get("model_bigg_id"),
            })

        summary = (
            f"Model {model_id}: {len(results)} reactions found"
            + (f" matching '{search}'" if search else "")
            + f" (showing {len(reactions)})"
        )
        return standard_response(
            summary=summary,
            raw_data={"reactions": reactions, "total_count": len(results)},
            source="BiGG Models",
            source_id=f"{model_id}/reactions",
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("get_model_reactions", exc)


# ===== Expression optimisation tools ========================================


@mcp.tool()
async def optimize_codons(
    protein_seq: str,
    host: str = "ecoli",
) -> dict[str, Any]:
    """Optimize codons for a protein sequence for expression in a target host.

    Uses host-specific codon usage frequency tables to replace each codon with
    the most-preferred synonym, maximising the Codon Adaptation Index (CAI).

    Args:
        protein_seq: Amino acid sequence (single-letter code, no gaps).
        host: Target host organism. Supported: 'ecoli', 'cho'.

    Returns:
        Optimized DNA sequence, CAI score, GC content, and per-residue codons.
    """
    try:
        host_key = host.lower().replace(" ", "_").replace("-", "_")
        table = _CODON_TABLES.get(host_key)
        if table is None:
            return handle_error(
                "optimize_codons",
                f"Unsupported host '{host}'. Supported hosts: {list(_CODON_TABLES.keys())}",
            )

        seq = protein_seq.upper().replace(" ", "").replace("\n", "")
        # Remove trailing stop if present
        if seq.endswith("*"):
            seq = seq[:-1]

        codons_used: list[str] = []
        for aa in seq:
            codon = _best_codon(aa, table)
            codons_used.append(codon)

        # Add stop codon
        stop = _best_codon("*", table)
        codons_used.append(stop)

        dna_seq = "".join(codons_used)
        cai = _cai_score(dna_seq, table)
        gc_count = dna_seq.count("G") + dna_seq.count("C")
        gc_content = round(gc_count / len(dna_seq), 4) if dna_seq else 0.0

        summary = (
            f"Codon-optimized {len(seq)}-aa sequence for {host}: "
            f"CAI={cai}, GC={gc_content*100:.1f}%, DNA length={len(dna_seq)} bp"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "protein_length": len(seq),
                "host": host,
                "optimized_dna": dna_seq,
                "dna_length": len(dna_seq),
                "cai_score": cai,
                "gc_content": gc_content,
                "codons": codons_used,
            },
            source="Lumi codon optimizer",
            source_id=f"codon_opt/{host}",
            confidence=0.80,
        )
    except Exception as exc:
        return handle_error("optimize_codons", exc)


@mcp.tool()
async def predict_expression_level(
    protein_seq: str,
    host: str = "ecoli",
) -> dict[str, Any]:
    """Predict recombinant protein expression level using sequence heuristics.

    Evaluates protein length, rare-codon frequency, average hydrophobicity,
    cysteine content, and other features to categorise expected expression as
    high / medium / low.

    Args:
        protein_seq: Amino acid sequence (single-letter code).
        host: Target host organism ('ecoli' or 'cho').

    Returns:
        Predicted expression category, individual feature scores, and
        explanatory reasoning.
    """
    try:
        seq = protein_seq.upper().replace(" ", "").replace("\n", "")
        if seq.endswith("*"):
            seq = seq[:-1]

        length = len(seq)
        reasons: list[str] = []
        score = 0  # Higher = better expression

        # 1. Length penalty
        if length < 100:
            score += 2
            reasons.append(f"Short protein ({length} aa) -- generally easier to express")
        elif length < 500:
            score += 1
            reasons.append(f"Moderate length ({length} aa)")
        else:
            score -= 1
            reasons.append(f"Large protein ({length} aa) -- may have folding/solubility challenges")

        # 2. Cysteine content (disulfide bonds are problematic in E. coli cytoplasm)
        cys_count = seq.count("C")
        cys_pct = round(cys_count / length * 100, 2) if length else 0
        if host.lower() in ("ecoli", "e_coli"):
            if cys_pct > 3:
                score -= 2
                reasons.append(
                    f"High cysteine content ({cys_pct}%) -- disulfide bond formation "
                    f"is problematic in E. coli cytoplasm"
                )
            elif cys_pct > 1.5:
                score -= 1
                reasons.append(f"Moderate cysteine content ({cys_pct}%)")
            else:
                score += 1
                reasons.append(f"Low cysteine content ({cys_pct}%) -- favourable for E. coli")

        # 3. Hydrophobicity (very hydrophobic proteins aggregate)
        hydro_values = [_KD_HYDROPHOBICITY.get(aa, 0.0) for aa in seq]
        avg_hydro = round(sum(hydro_values) / len(hydro_values), 3) if hydro_values else 0.0
        if avg_hydro > 0.5:
            score -= 1
            reasons.append(f"High average hydrophobicity ({avg_hydro}) -- aggregation risk")
        elif avg_hydro < -0.5:
            score += 1
            reasons.append(f"Hydrophilic protein ({avg_hydro}) -- good solubility expected")
        else:
            reasons.append(f"Moderate hydrophobicity ({avg_hydro})")

        # 4. Rare-codon proxy: count of Pro/Arg/Ile clusters (simplified)
        rare_residues = seq.count("P") + seq.count("R")
        rare_pct = round(rare_residues / length * 100, 2) if length else 0
        if rare_pct > 15:
            score -= 1
            reasons.append(
                f"High Pro+Arg content ({rare_pct}%) -- potential rare-codon / "
                f"translational pausing issues"
            )
        else:
            score += 1
            reasons.append(f"Pro+Arg content ({rare_pct}%) within normal range")

        # 5. Transmembrane proxy: long stretches of hydrophobic residues
        hydro_stretch = 0
        max_stretch = 0
        for aa in seq:
            if _KD_HYDROPHOBICITY.get(aa, 0) > 1.5:
                hydro_stretch += 1
                max_stretch = max(max_stretch, hydro_stretch)
            else:
                hydro_stretch = 0
        if max_stretch >= 20:
            score -= 2
            reasons.append(
                f"Long hydrophobic stretch ({max_stretch} residues) -- likely transmembrane; "
                f"soluble expression will be very difficult"
            )
        elif max_stretch >= 12:
            score -= 1
            reasons.append(f"Moderate hydrophobic stretch ({max_stretch} residues)")

        # Categorise
        if score >= 3:
            category = "high"
        elif score >= 0:
            category = "medium"
        else:
            category = "low"

        summary = (
            f"Predicted expression in {host}: {category.upper()} "
            f"(score={score}, length={length} aa, Cys={cys_pct}%, "
            f"hydro={avg_hydro})"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "host": host,
                "protein_length": length,
                "predicted_category": category,
                "composite_score": score,
                "features": {
                    "cysteine_percent": cys_pct,
                    "cysteine_count": cys_count,
                    "average_hydrophobicity": avg_hydro,
                    "pro_arg_percent": rare_pct,
                    "max_hydrophobic_stretch": max_stretch,
                },
                "reasoning": reasons,
            },
            source="Lumi expression predictor",
            source_id=f"expr_pred/{host}",
            confidence=0.60,
        )
    except Exception as exc:
        return handle_error("predict_expression_level", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
