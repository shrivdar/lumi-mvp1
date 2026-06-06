"""
ReMap MCP Server — Lumi Virtual Lab

Exposes tools for querying the ReMap regulatory atlas:
  peak search, transcription factor targets, cis-regulatory modules, experiments.

Start with:  python -m src.mcp_servers.remap.server
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

# Relative import when running inside the package; fall back for direct exec.
try:
    from src.mcp_servers.base import async_http_get, handle_error, standard_response
except ImportError:
    from mcp_servers.base import async_http_get, handle_error, standard_response  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REMAP_API = "https://remap2022.univ-amu.fr/api/v1"

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi ReMap",
    instructions="Regulatory genomics queries via the ReMap 2022 atlas: peaks, TF targets, CRMs, experiments",
)


# ---- 1. Search regulatory peaks in a genomic region -----------------------


@mcp.tool()
async def remap_search_peaks(
    chrom: str,
    start: int,
    end: int,
    genome: str = "hg38",
) -> dict[str, Any]:
    """
    Search ReMap regulatory peaks overlapping a genomic region.

    Args:
        chrom: Chromosome name (e.g. 'chr1').
        start: Start position (0-based).
        end: End position.
        genome: Reference genome assembly (default 'hg38').
    """
    try:
        url = f"{REMAP_API}/peaks/findByRegion"
        params = {
            "chrom": chrom,
            "start": start,
            "end": end,
            "genome": genome,
        }
        data = await async_http_get(url, params=params)

        peaks = data if isinstance(data, list) else data.get("peaks", data.get("data", []))
        peak_count = len(peaks) if isinstance(peaks, list) else 0

        summary = (
            f"Found {peak_count} regulatory peaks in {chrom}:{start}-{end} ({genome})."
            if peak_count
            else f"No regulatory peaks found in {chrom}:{start}-{end} ({genome})."
        )

        return standard_response(
            summary=summary,
            raw_data={"peaks": peaks, "count": peak_count, "region": f"{chrom}:{start}-{end}"},
            source="ReMap 2022",
            source_id=f"{chrom}:{start}-{end}",
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("remap_search_peaks", exc)


# ---- 2. Get target genes for a transcription factor -----------------------


@mcp.tool()
async def remap_get_targets(
    tf_name: str,
    genome: str = "hg38",
) -> dict[str, Any]:
    """
    Get target genes regulated by a given transcription factor from ReMap.

    Args:
        tf_name: Transcription factor name (e.g. 'TP53', 'CTCF').
        genome: Reference genome assembly (default 'hg38').
    """
    try:
        url = f"{REMAP_API}/targets/findByTf"
        params = {
            "tf": tf_name,
            "genome": genome,
        }
        data = await async_http_get(url, params=params)

        targets = data if isinstance(data, list) else data.get("targets", data.get("data", []))
        target_count = len(targets) if isinstance(targets, list) else 0

        target_names = []
        if isinstance(targets, list):
            for t in targets[:10]:
                name = t.get("gene", t.get("target", "")) if isinstance(t, dict) else str(t)
                if name:
                    target_names.append(name)

        summary = (
            f"{tf_name} has {target_count} target genes in {genome}. "
            f"Top targets: {', '.join(target_names[:10])}."
            if target_count
            else f"No target genes found for {tf_name} in {genome}."
        )

        return standard_response(
            summary=summary,
            raw_data={"tf": tf_name, "targets": targets, "count": target_count},
            source="ReMap 2022",
            source_id=tf_name,
            confidence=0.8,
        )
    except Exception as exc:
        return handle_error("remap_get_targets", exc)


# ---- 3. Get cis-regulatory modules in a region ----------------------------


@mcp.tool()
async def remap_get_crms(
    chrom: str,
    start: int,
    end: int,
    genome: str = "hg38",
) -> dict[str, Any]:
    """
    Get cis-regulatory modules (CRMs) overlapping a genomic region from ReMap.

    Args:
        chrom: Chromosome name (e.g. 'chr1').
        start: Start position (0-based).
        end: End position.
        genome: Reference genome assembly (default 'hg38').
    """
    try:
        url = f"{REMAP_API}/crms/findByRegion"
        params = {
            "chrom": chrom,
            "start": start,
            "end": end,
            "genome": genome,
        }
        data = await async_http_get(url, params=params)

        crms = data if isinstance(data, list) else data.get("crms", data.get("data", []))
        crm_count = len(crms) if isinstance(crms, list) else 0

        summary = (
            f"Found {crm_count} cis-regulatory modules in {chrom}:{start}-{end} ({genome})."
            if crm_count
            else f"No cis-regulatory modules found in {chrom}:{start}-{end} ({genome})."
        )

        return standard_response(
            summary=summary,
            raw_data={"crms": crms, "count": crm_count, "region": f"{chrom}:{start}-{end}"},
            source="ReMap 2022",
            source_id=f"{chrom}:{start}-{end}",
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("remap_get_crms", exc)


# ---- 4. List available experiments / TFs -----------------------------------


@mcp.tool()
async def remap_list_experiments(
    genome: str = "hg38",
) -> dict[str, Any]:
    """
    List available experiments and transcription factors catalogued in ReMap.

    Args:
        genome: Reference genome assembly (default 'hg38').
    """
    try:
        url = f"{REMAP_API}/experiments"
        params = {"genome": genome}
        data = await async_http_get(url, params=params)

        experiments = data if isinstance(data, list) else data.get("experiments", data.get("data", []))
        exp_count = len(experiments) if isinstance(experiments, list) else 0

        tf_names = set()
        if isinstance(experiments, list):
            for exp in experiments[:200]:
                tf = exp.get("tf", exp.get("transcription_factor", "")) if isinstance(exp, dict) else ""
                if tf:
                    tf_names.add(tf)

        summary = (
            f"ReMap {genome}: {exp_count} experiments covering {len(tf_names)} unique TFs."
            if exp_count
            else f"No experiments found for {genome}."
        )

        return standard_response(
            summary=summary,
            raw_data={"experiments": experiments, "count": exp_count, "unique_tfs": sorted(tf_names)},
            source="ReMap 2022",
            source_id=genome,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("remap_list_experiments", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
