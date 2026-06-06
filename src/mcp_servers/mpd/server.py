"""
Mouse Phenome Database (MPD) MCP Server — Lumi Virtual Lab

Exposes tools for querying the MPD at JAX:
  measurement search, strain data, ontology term search.

Start with:  python -m src.mcp_servers.mpd.server
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

MPD_API = "https://phenome.jax.org/api"

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi MPD",
    instructions="Mouse Phenome Database queries: phenotype measurement search, strain data, and ontology term lookup",
)


# ---- 1. Search measurements ------------------------------------------------


@mcp.tool()
async def mpd_search_measurements(query: str) -> dict[str, Any]:
    """
    Search the Mouse Phenome Database for phenotype measurements.

    Args:
        query: Search term (e.g. 'body weight', 'glucose', 'blood pressure').
    """
    try:
        url = f"{MPD_API}/measurements/search"
        params: dict[str, Any] = {"q": query}

        data = await async_http_get(url, params=params)

        # Response may be a list or dict with results
        measurements = []
        if isinstance(data, list):
            measurements = data
        elif isinstance(data, dict):
            measurements = data.get("measurements", data.get("results", data.get("data", [])))

        summaries = []
        for meas in measurements[:10]:
            if isinstance(meas, dict):
                measnum = meas.get("measnum", "N/A")
                desc = meas.get("description", meas.get("measname", "unnamed"))
                projsym = meas.get("projsym", "")
                summaries.append(f"#{measnum}: {desc} ({projsym})")

        summary = (
            f"MPD measurement search '{query}': {len(measurements)} results. "
            f"Top hits: {'; '.join(summaries[:5])}"
            if measurements
            else f"No MPD measurements found for '{query}'."
        )

        return standard_response(
            summary=summary,
            raw_data={"count": len(measurements), "measurements": measurements},
            source="Mouse Phenome Database (JAX)",
            source_id=query,
            confidence=0.8,
        )
    except Exception as exc:
        return handle_error("mpd_search_measurements", exc)


# ---- 2. Get strain data -----------------------------------------------------


@mcp.tool()
async def mpd_get_strain_data(strain_id: str, measurement_id: str) -> dict[str, Any]:
    """
    Get measurement data for a specific mouse strain from MPD.

    Args:
        strain_id: MPD strain identifier (e.g. '7' for C57BL/6J).
        measurement_id: MPD measurement number (e.g. '10001').
    """
    try:
        url = f"{MPD_API}/strainmeans"
        params: dict[str, Any] = {
            "measnum": measurement_id,
            "strain": strain_id,
        }

        data = await async_http_get(url, params=params)

        # Response may be a list of strain means or a dict
        strain_data = []
        if isinstance(data, list):
            strain_data = data
        elif isinstance(data, dict):
            strain_data = data.get("strainmeans", data.get("results", data.get("data", [])))

        summaries = []
        for entry in strain_data[:10]:
            if isinstance(entry, dict):
                strain_name = entry.get("strainname", entry.get("strain", "unknown"))
                mean_val = entry.get("mean", entry.get("value", "N/A"))
                n_animals = entry.get("n", entry.get("animal_count", "N/A"))
                sex = entry.get("sex", "N/A")
                summaries.append(f"{strain_name}: mean={mean_val}, n={n_animals}, sex={sex}")

        summary = (
            f"MPD strain data for strain={strain_id}, measurement={measurement_id}: "
            f"{len(strain_data)} records. {'; '.join(summaries[:5])}"
            if strain_data
            else f"No MPD data found for strain={strain_id}, measurement={measurement_id}."
        )

        return standard_response(
            summary=summary,
            raw_data={"count": len(strain_data), "strainmeans": strain_data},
            source="Mouse Phenome Database (JAX)",
            source_id=f"strain:{strain_id}/meas:{measurement_id}",
            confidence=0.8,
        )
    except Exception as exc:
        return handle_error("mpd_get_strain_data", exc)


# ---- 3. Search ontology terms -----------------------------------------------


@mcp.tool()
async def mpd_get_ontology_terms(query: str) -> dict[str, Any]:
    """
    Search MPD ontology terms for phenotype categories.

    Args:
        query: Search term (e.g. 'metabolism', 'cardiovascular', 'behavior').
    """
    try:
        url = f"{MPD_API}/ontologies/search"
        params: dict[str, Any] = {"q": query}

        data = await async_http_get(url, params=params)

        # Response may be a list or dict with results
        terms = []
        if isinstance(data, list):
            terms = data
        elif isinstance(data, dict):
            terms = data.get("terms", data.get("results", data.get("data", [])))

        summaries = []
        for term in terms[:10]:
            if isinstance(term, dict):
                term_id = term.get("id", term.get("ontid", "N/A"))
                term_name = term.get("name", term.get("term", "unnamed"))
                ontology = term.get("ontology", term.get("ont", ""))
                summaries.append(f"{term_id}: {term_name} ({ontology})")

        summary = (
            f"MPD ontology search '{query}': {len(terms)} terms found. "
            f"Top hits: {'; '.join(summaries[:5])}"
            if terms
            else f"No MPD ontology terms found for '{query}'."
        )

        return standard_response(
            summary=summary,
            raw_data={"count": len(terms), "terms": terms},
            source="Mouse Phenome Database (JAX)",
            source_id=query,
            confidence=0.75,
        )
    except Exception as exc:
        return handle_error("mpd_get_ontology_terms", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
