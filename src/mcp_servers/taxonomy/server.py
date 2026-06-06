"""
Taxonomy MCP Server — Lumi Virtual Lab

Exposes tools for querying taxonomic databases:
  WoRMS (marine species), PaleobiologyDB (fossil taxa), IUCN Red List (conservation status).

Start with:  python -m src.mcp_servers.taxonomy.server
"""

from __future__ import annotations

import os
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

WORMS_API = "https://www.marinespecies.org/rest"
PALEOBIODB_API = "https://paleobiodb.org/data1.2"
IUCN_API = "https://apiv3.iucnredlist.org/api/v3"

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi Taxonomy",
    instructions="Taxonomic queries across WoRMS (marine species), PaleobiologyDB (fossil taxa), and IUCN Red List (conservation status)",
)


# ---- 1. WoRMS: search marine taxa by name ---------------------------------


@mcp.tool()
async def worms_search_taxa(query: str) -> dict[str, Any]:
    """
    Search the World Register of Marine Species (WoRMS) for taxa matching a name.

    Args:
        query: Taxon name to search for (e.g. 'Gadus morhua', 'Delphinidae').
    """
    try:
        url = f"{WORMS_API}/AphiaRecordsByName/{query}"
        data = await async_http_get(url)

        records = data if isinstance(data, list) else [data] if isinstance(data, dict) and data else []

        summaries = []
        for rec in records[:10]:
            name = rec.get("scientificname", rec.get("valid_name", "unknown"))
            status = rec.get("status", "unknown")
            aphia_id = rec.get("AphiaID", "N/A")
            summaries.append(f"{name} (AphiaID={aphia_id}, status={status})")

        summary = (
            f"WoRMS: {len(records)} records for '{query}'. Matches: {'; '.join(summaries[:5])}."
            if records
            else f"No WoRMS records found for '{query}'."
        )

        return standard_response(
            summary=summary,
            raw_data={"query": query, "records": records, "count": len(records)},
            source="WoRMS (World Register of Marine Species)",
            source_id=query,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("worms_search_taxa", exc)


# ---- 2. WoRMS: get record by AphiaID --------------------------------------


@mcp.tool()
async def worms_get_record(aphia_id: int) -> dict[str, Any]:
    """
    Get a full taxonomic record from WoRMS by AphiaID.

    Args:
        aphia_id: The WoRMS AphiaID (e.g. 126436 for Gadus morhua).
    """
    try:
        url = f"{WORMS_API}/AphiaRecordByAphiaID/{aphia_id}"
        data = await async_http_get(url)

        if not data or (isinstance(data, dict) and data.get("text", "").startswith("<!DOCTYPE")):
            return standard_response(
                summary=f"No WoRMS record found for AphiaID {aphia_id}.",
                raw_data={"aphia_id": aphia_id},
                source="WoRMS (World Register of Marine Species)",
                source_id=str(aphia_id),
                confidence=0.5,
            )

        name = data.get("scientificname", "unknown")
        authority = data.get("authority", "")
        rank = data.get("rank", "unknown")
        status = data.get("status", "unknown")
        kingdom = data.get("kingdom", "")
        phylum = data.get("phylum", "")
        class_name = data.get("class", "")
        order = data.get("order", "")
        family = data.get("family", "")

        lineage_parts = [p for p in [kingdom, phylum, class_name, order, family] if p]

        summary = (
            f"{name} {authority}: rank={rank}, status={status}. "
            f"Lineage: {' > '.join(lineage_parts)}."
        )

        return standard_response(
            summary=summary,
            raw_data=data,
            source="WoRMS (World Register of Marine Species)",
            source_id=str(aphia_id),
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("worms_get_record", exc)


# ---- 3. PaleobiologyDB: search fossil taxa --------------------------------


@mcp.tool()
async def paleodb_search_taxa(
    query: str,
    rank: str | None = None,
) -> dict[str, Any]:
    """
    Search the Paleobiology Database for fossil taxa.

    Args:
        query: Taxon name to search (e.g. 'Tyrannosaurus', 'Trilobita').
        rank: Optional taxonomic rank filter (e.g. 'genus', 'family', 'order').
    """
    try:
        url = f"{PALEOBIODB_API}/taxa/list.json"
        params: dict[str, Any] = {"name": query}
        if rank:
            params["rank"] = rank

        data = await async_http_get(url, params=params)

        records = data.get("records", []) if isinstance(data, dict) else []
        record_count = len(records)

        summaries = []
        for rec in records[:10]:
            taxon_name = rec.get("nam", rec.get("taxon_name", "unknown"))
            taxon_rank = rec.get("rnk", rec.get("taxon_rank", ""))
            n_occs = rec.get("noc", rec.get("n_occs", 0))
            summaries.append(f"{taxon_name} (rank={taxon_rank}, occurrences={n_occs})")

        summary = (
            f"PaleobioDB: {record_count} fossil taxa matching '{query}'"
            + (f" at rank '{rank}'" if rank else "")
            + f". Top: {'; '.join(summaries[:5])}."
            if record_count
            else f"No fossil taxa found for '{query}'"
            + (f" at rank '{rank}'" if rank else "")
            + "."
        )

        return standard_response(
            summary=summary,
            raw_data={"query": query, "rank": rank, "records": records, "count": record_count},
            source="Paleobiology Database",
            source_id=query,
            confidence=0.8,
        )
    except Exception as exc:
        return handle_error("paleodb_search_taxa", exc)


# ---- 4. PaleobiologyDB: fossil occurrences --------------------------------


@mcp.tool()
async def paleodb_get_occurrences(
    taxon: str,
    interval: str | None = None,
) -> dict[str, Any]:
    """
    Get fossil occurrence records from the Paleobiology Database.

    Args:
        taxon: Taxon name (e.g. 'Tyrannosaurus rex').
        interval: Optional geological time interval (e.g. 'Cretaceous', 'Jurassic').
    """
    try:
        url = f"{PALEOBIODB_API}/occs/list.json"
        params: dict[str, Any] = {"taxon_name": taxon}
        if interval:
            params["interval"] = interval

        data = await async_http_get(url, params=params)

        records = data.get("records", []) if isinstance(data, dict) else []
        record_count = len(records)

        # Gather geographic and temporal info
        countries = set()
        intervals_found = set()
        for rec in records[:100]:
            cc = rec.get("cc2", rec.get("country", ""))
            if cc:
                countries.add(cc)
            ei = rec.get("oei", rec.get("early_interval", ""))
            if ei:
                intervals_found.add(ei)

        summary = (
            f"PaleobioDB: {record_count} occurrences of '{taxon}'"
            + (f" during {interval}" if interval else "")
            + f". Countries: {', '.join(sorted(countries)[:10])}. "
            + f"Time intervals: {', '.join(sorted(intervals_found)[:10])}."
            if record_count
            else f"No fossil occurrences found for '{taxon}'"
            + (f" during {interval}" if interval else "")
            + "."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "taxon": taxon,
                "interval": interval,
                "records": records,
                "count": record_count,
            },
            source="Paleobiology Database",
            source_id=taxon,
            confidence=0.8,
        )
    except Exception as exc:
        return handle_error("paleodb_get_occurrences", exc)


# ---- 5. IUCN Red List: conservation status --------------------------------


@mcp.tool()
async def iucn_get_species_status(species_name: str) -> dict[str, Any]:
    """
    Get the IUCN Red List conservation status for a species.

    Requires the IUCN_API_TOKEN environment variable to be set.

    Args:
        species_name: Species name (e.g. 'Panthera tigris', 'Gadus morhua').
    """
    try:
        token = os.environ.get("IUCN_API_TOKEN")
        if not token:
            return handle_error(
                "iucn_get_species_status",
                "IUCN_API_TOKEN environment variable is not set. "
                "Please set it to your IUCN Red List API token to use this tool. "
                "You can obtain a token at https://apiv3.iucnredlist.org/api/v3/token",
            )

        url = f"{IUCN_API}/species/{species_name}"
        params = {"token": token}
        data = await async_http_get(url, params=params)

        results = data.get("result", []) if isinstance(data, dict) else []

        if not results:
            return standard_response(
                summary=f"No IUCN Red List record found for '{species_name}'.",
                raw_data={"species": species_name},
                source="IUCN Red List",
                source_id=species_name,
                confidence=0.5,
            )

        species = results[0] if isinstance(results, list) else results
        scientific_name = species.get("scientific_name", species_name)
        category = species.get("category", "unknown")
        population_trend = species.get("population_trend", "unknown")
        taxon_id = species.get("taxonid", "N/A")

        # Map IUCN category codes to readable labels
        category_labels = {
            "LC": "Least Concern",
            "NT": "Near Threatened",
            "VU": "Vulnerable",
            "EN": "Endangered",
            "CR": "Critically Endangered",
            "EW": "Extinct in the Wild",
            "EX": "Extinct",
            "DD": "Data Deficient",
            "NE": "Not Evaluated",
        }
        category_label = category_labels.get(category, category)

        summary = (
            f"IUCN Red List: {scientific_name} — {category_label} ({category}). "
            f"Population trend: {population_trend}. Taxon ID: {taxon_id}."
        )

        return standard_response(
            summary=summary,
            raw_data={"species": species, "all_results": results},
            source="IUCN Red List",
            source_id=str(taxon_id),
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("iucn_get_species_status", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
