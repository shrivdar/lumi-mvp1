"""
JASPAR MCP Server — Lumi Virtual Lab

Exposes tools for querying the JASPAR REST API for transcription factor
binding motifs and position frequency matrices.

Start with:  python -m src.mcp_servers.jaspar.server
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

JASPAR_API = "https://jaspar.elixir.no/api/v1"

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi JASPAR",
    instructions="JASPAR transcription factor binding motif queries: motif search, matrix retrieval, PFM data",
)


# ---- 1. Search TF binding motifs -------------------------------------------


@mcp.tool()
async def jaspar_search_motifs(
    query: str,
    collection: str = "CORE",
    tax_group: str = "vertebrates",
) -> dict[str, Any]:
    """
    Search JASPAR for transcription factor binding motifs.

    Args:
        query: Search term (gene name, TF family, etc.).
        collection: JASPAR collection to search (default 'CORE').
        tax_group: Taxonomic group (default 'vertebrates').
    """
    try:
        url = f"{JASPAR_API}/matrix/"
        params = {"search": query, "collection": collection, "tax_group": tax_group}

        data = await async_http_get(url, params=params)

        results = data.get("results", [])
        count = data.get("count", len(results))

        motif_summaries = []
        for motif in results[:10]:
            matrix_id = motif.get("matrix_id", "")
            name = motif.get("name", "")
            tf_class = motif.get("class", [""])[0] if motif.get("class") else ""
            motif_summaries.append(f"{matrix_id} ({name}, class={tf_class})")

        summary = (
            f"JASPAR search for '{query}' in {collection}/{tax_group}: {count} motifs found. "
            f"Top hits: {'; '.join(motif_summaries[:5])}."
            if count
            else f"No JASPAR motifs found for '{query}' in {collection}/{tax_group}."
        )

        return standard_response(
            summary=summary,
            raw_data={"count": count, "results": results},
            source="JASPAR",
            source_id=query,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("jaspar_search_motifs", exc)


# ---- 2. Get a specific motif matrix ----------------------------------------


@mcp.tool()
async def jaspar_get_matrix(matrix_id: str) -> dict[str, Any]:
    """
    Get detailed information for a specific JASPAR motif matrix.

    Args:
        matrix_id: JASPAR matrix ID (e.g. 'MA0004.1').
    """
    try:
        url = f"{JASPAR_API}/matrix/{matrix_id}/"

        data = await async_http_get(url)

        name = data.get("name", matrix_id)
        collection = data.get("collection", "N/A")
        species = data.get("species", [])
        species_names = [s.get("name", "") for s in species] if isinstance(species, list) else []
        tf_class = data.get("class", [])
        pfm = data.get("pfm", {})

        summary = (
            f"JASPAR {matrix_id} ({name}): collection={collection}, "
            f"species={', '.join(species_names) or 'N/A'}, "
            f"class={', '.join(tf_class) if isinstance(tf_class, list) else tf_class or 'N/A'}, "
            f"PFM length={len(pfm.get('A', [])) if isinstance(pfm, dict) else 'N/A'} positions."
        )

        return standard_response(
            summary=summary,
            raw_data=data,
            source="JASPAR",
            source_id=matrix_id,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("jaspar_get_matrix", exc)


# ---- 3. Get position frequency matrix (PFM) --------------------------------


@mcp.tool()
async def jaspar_get_pfm(matrix_id: str) -> dict[str, Any]:
    """
    Get the position frequency matrix (PFM) for a JASPAR motif.

    Args:
        matrix_id: JASPAR matrix ID (e.g. 'MA0004.1').
    """
    try:
        url = f"{JASPAR_API}/matrix/{matrix_id}/"

        data = await async_http_get(url)

        name = data.get("name", matrix_id)
        pfm = data.get("pfm", {})

        if not pfm:
            return standard_response(
                summary=f"No PFM data available for {matrix_id} ({name}).",
                raw_data={"matrix_id": matrix_id, "name": name},
                source="JASPAR",
                source_id=matrix_id,
                confidence=0.5,
            )

        # Calculate motif length and basic statistics
        motif_length = len(pfm.get("A", []))
        total_per_pos = []
        for i in range(motif_length):
            total = sum(pfm.get(base, [0] * motif_length)[i] for base in ["A", "C", "G", "T"])
            total_per_pos.append(total)

        avg_depth = sum(total_per_pos) / len(total_per_pos) if total_per_pos else 0

        summary = (
            f"PFM for {matrix_id} ({name}): {motif_length} positions, "
            f"average depth={avg_depth:.0f} observations per position."
        )

        return standard_response(
            summary=summary,
            raw_data={"matrix_id": matrix_id, "name": name, "pfm": pfm, "motif_length": motif_length},
            source="JASPAR",
            source_id=matrix_id,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("jaspar_get_pfm", exc)


# ---- 4. Search motifs by transcription factor name --------------------------


@mcp.tool()
async def jaspar_search_by_tf(tf_name: str, collection: str = "CORE") -> dict[str, Any]:
    """
    Search JASPAR motifs by transcription factor name.

    Args:
        tf_name: Transcription factor name (e.g. 'CTCF', 'p53', 'GATA1').
        collection: JASPAR collection to search (default 'CORE').
    """
    try:
        url = f"{JASPAR_API}/matrix/"
        params = {"name": tf_name, "collection": collection}

        data = await async_http_get(url, params=params)

        results = data.get("results", [])
        count = data.get("count", len(results))

        motif_details = []
        for motif in results[:10]:
            matrix_id = motif.get("matrix_id", "")
            name = motif.get("name", "")
            species = motif.get("species", [])
            species_names = [s.get("name", "") for s in species] if isinstance(species, list) else []
            motif_details.append({
                "matrix_id": matrix_id,
                "name": name,
                "species": species_names,
            })

        summary = (
            f"JASPAR TF search for '{tf_name}' in {collection}: {count} motifs found. "
            f"IDs: {', '.join(m['matrix_id'] for m in motif_details[:5])}."
            if count
            else f"No JASPAR motifs found for TF '{tf_name}' in {collection}."
        )

        return standard_response(
            summary=summary,
            raw_data={"count": count, "results": results, "motif_details": motif_details},
            source="JASPAR",
            source_id=tf_name,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("jaspar_search_by_tf", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
