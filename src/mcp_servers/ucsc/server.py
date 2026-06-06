"""
UCSC Genome Browser MCP Server — Lumi Virtual Lab

Exposes tools for querying the UCSC Genome Browser REST API:
  track data, gene search, DNA sequence retrieval, track listing, chromosome info.

Start with:  python -m src.mcp_servers.ucsc.server
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

UCSC_API = "https://api.genome.ucsc.edu"

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi UCSC Genome Browser",
    instructions="UCSC Genome Browser queries: track data, gene search, DNA sequence, track listing, chromosome info",
)


# ---- 1. Get track data for a genomic region --------------------------------


@mcp.tool()
async def ucsc_get_track_data(
    track: str,
    genome: str = "hg38",
    chrom: str = "",
    start: int = 0,
    end: int = 0,
) -> dict[str, Any]:
    """
    Get track data for a genomic region from the UCSC Genome Browser.

    Args:
        track: Track name (e.g. 'knownGene', 'gc5BaseBw', 'rmsk').
        genome: Genome assembly (default hg38).
        chrom: Chromosome (e.g. 'chr1'). Leave empty for genome-wide.
        start: Start position (0-based).
        end: End position.
    """
    try:
        url = f"{UCSC_API}/getData/track"
        params: dict[str, Any] = {"track": track, "genome": genome}
        if chrom:
            params["chrom"] = chrom
        if start or end:
            params["start"] = start
            params["end"] = end

        data = await async_http_get(url, params=params)

        # Summarise the response
        items = data.get(chrom or track, [])
        if isinstance(items, list):
            count = len(items)
        else:
            count = 1

        region = f"{chrom}:{start}-{end}" if chrom else "genome-wide"
        summary = f"UCSC track '{track}' on {genome} ({region}): {count} data items returned."

        return standard_response(
            summary=summary,
            raw_data=data,
            source="UCSC Genome Browser",
            source_id=f"{genome}/{track}",
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("ucsc_get_track_data", exc)


# ---- 2. Search for genes by name/symbol ------------------------------------


@mcp.tool()
async def ucsc_search_genes(query: str, genome: str = "hg38") -> dict[str, Any]:
    """
    Search for genes by name or symbol in the UCSC Genome Browser.

    Args:
        query: Gene name or symbol to search for (e.g. 'TP53', 'BRCA1').
        genome: Genome assembly (default hg38).
    """
    try:
        url = f"{UCSC_API}/search"
        params = {"search": query, "genome": genome}

        data = await async_http_get(url, params=params)

        matches = data.get("positionMatches", [])
        total = sum(len(m.get("matches", [])) for m in matches)

        match_details = []
        for category in matches:
            for match in category.get("matches", [])[:10]:
                match_details.append({
                    "position": match.get("position", ""),
                    "name": match.get("posName", ""),
                })

        summary = (
            f"UCSC gene search for '{query}' on {genome}: {total} matches found."
            if total
            else f"No matches found for '{query}' on {genome}."
        )

        return standard_response(
            summary=summary,
            raw_data={"matches": match_details, "full_response": data},
            source="UCSC Genome Browser",
            source_id=query,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("ucsc_search_genes", exc)


# ---- 3. Get DNA sequence for a region --------------------------------------


@mcp.tool()
async def ucsc_get_sequence(genome: str, chrom: str, start: int, end: int) -> dict[str, Any]:
    """
    Get DNA sequence for a genomic region from the UCSC Genome Browser.

    Args:
        genome: Genome assembly (e.g. 'hg38', 'mm39').
        chrom: Chromosome (e.g. 'chr1').
        start: Start position (0-based).
        end: End position.
    """
    try:
        url = f"{UCSC_API}/getData/sequence"
        params = {"genome": genome, "chrom": chrom, "start": start, "end": end}

        data = await async_http_get(url, params=params)

        dna = data.get("dna", "")
        seq_len = len(dna) if isinstance(dna, str) else 0

        summary = f"Retrieved {seq_len} bp sequence from {genome} {chrom}:{start}-{end}."

        return standard_response(
            summary=summary,
            raw_data=data,
            source="UCSC Genome Browser",
            source_id=f"{genome}/{chrom}:{start}-{end}",
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("ucsc_get_sequence", exc)


# ---- 4. List available tracks ----------------------------------------------


@mcp.tool()
async def ucsc_list_tracks(genome: str = "hg38") -> dict[str, Any]:
    """
    List available data tracks for a genome assembly in the UCSC Genome Browser.

    Args:
        genome: Genome assembly (default hg38).
    """
    try:
        url = f"{UCSC_API}/list/tracks"
        params = {"genome": genome}

        data = await async_http_get(url, params=params)

        tracks = data.get(genome, {})
        track_names = list(tracks.keys()) if isinstance(tracks, dict) else []

        summary = f"UCSC {genome}: {len(track_names)} tracks available."

        return standard_response(
            summary=summary,
            raw_data={"track_count": len(track_names), "track_names": track_names[:50], "full_response": data},
            source="UCSC Genome Browser",
            source_id=genome,
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("ucsc_list_tracks", exc)


# ---- 5. List chromosomes and sizes -----------------------------------------


@mcp.tool()
async def ucsc_get_chromosomes(genome: str = "hg38") -> dict[str, Any]:
    """
    List chromosomes and their sizes for a genome assembly.

    Args:
        genome: Genome assembly (default hg38).
    """
    try:
        url = f"{UCSC_API}/list/chromosomes"
        params = {"genome": genome}

        data = await async_http_get(url, params=params)

        chromosomes = data.get("chromosomes", {})
        chrom_count = len(chromosomes) if isinstance(chromosomes, dict) else 0

        summary = f"UCSC {genome}: {chrom_count} chromosomes/contigs available."

        return standard_response(
            summary=summary,
            raw_data=data,
            source="UCSC Genome Browser",
            source_id=genome,
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("ucsc_get_chromosomes", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
