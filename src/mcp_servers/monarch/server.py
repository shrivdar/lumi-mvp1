"""
Monarch Initiative MCP Server — Lumi Virtual Lab

Exposes tools for querying the Monarch Initiative knowledge graph:
  entity search, associations, entity details, gene-phenotype lookups.

Start with:  python -m src.mcp_servers.monarch.server
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

MONARCH_API = "https://api.monarchinitiative.org/v3/api"

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi Monarch",
    instructions="Monarch Initiative queries: gene/disease/phenotype entity search, associations, and entity details",
)


# ---- 1. Search entities ----------------------------------------------------


@mcp.tool()
async def monarch_search_entity(
    query: str,
    category: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """
    Search the Monarch Initiative knowledge graph for genes, diseases, or phenotypes.

    Args:
        query: Free-text search term (e.g. 'BRCA1', 'Marfan syndrome').
        category: Optional Biolink category filter (e.g. 'biolink:Gene', 'biolink:Disease', 'biolink:PhenotypicFeature').
        limit: Maximum number of results to return (default 20).
    """
    try:
        url = f"{MONARCH_API}/search"
        params: dict[str, Any] = {"q": query, "limit": limit}
        if category:
            params["category"] = category

        data = await async_http_get(url, params=params)

        items = data.get("items", [])
        total = data.get("total", len(items))

        summaries = []
        for item in items[:10]:
            name = item.get("name", "unnamed")
            cat = item.get("category", "unknown")
            entity_id = item.get("id", "")
            summaries.append(f"{name} ({cat}, {entity_id})")

        summary = (
            f"Monarch search '{query}': {total} results. "
            f"Top hits: {'; '.join(summaries[:5])}"
            if items
            else f"No Monarch results found for '{query}'."
        )

        return standard_response(
            summary=summary,
            raw_data={"total": total, "items": items},
            source="Monarch Initiative",
            source_id=query,
            confidence=0.8,
        )
    except Exception as exc:
        return handle_error("monarch_search_entity", exc)


# ---- 2. Get associations ---------------------------------------------------


@mcp.tool()
async def monarch_get_associations(
    subject: str,
    category: str = "biolink:GeneToPhenotypicFeatureAssociation",
    limit: int = 50,
) -> dict[str, Any]:
    """
    Get associations for a Monarch entity (gene, disease, phenotype).

    Args:
        subject: Entity CURIE (e.g. 'HGNC:1100' for BRCA1, 'MONDO:0007254').
        category: Biolink association category (default: 'biolink:GeneToPhenotypicFeatureAssociation').
        limit: Maximum number of associations to return (default 50).
    """
    try:
        url = f"{MONARCH_API}/association"
        params: dict[str, Any] = {
            "subject": subject,
            "category": category,
            "limit": limit,
        }

        data = await async_http_get(url, params=params)

        items = data.get("items", [])
        total = data.get("total", len(items))

        summaries = []
        for assoc in items[:10]:
            obj = assoc.get("object", {})
            obj_name = obj.get("name", "unknown") if isinstance(obj, dict) else str(obj)
            predicate = assoc.get("predicate", "related_to")
            summaries.append(f"{predicate} -> {obj_name}")

        summary = (
            f"{total} associations for {subject} ({category}). "
            f"Examples: {'; '.join(summaries[:5])}"
            if items
            else f"No associations found for {subject} with category {category}."
        )

        return standard_response(
            summary=summary,
            raw_data={"total": total, "items": items},
            source="Monarch Initiative",
            source_id=subject,
            confidence=0.8,
        )
    except Exception as exc:
        return handle_error("monarch_get_associations", exc)


# ---- 3. Get entity details --------------------------------------------------


@mcp.tool()
async def monarch_get_entity(entity_id: str) -> dict[str, Any]:
    """
    Get detailed information about a specific Monarch entity.

    Args:
        entity_id: Entity CURIE (e.g. 'HGNC:1100', 'MONDO:0007254', 'HP:0001250').
    """
    try:
        url = f"{MONARCH_API}/entity/{entity_id}"

        data = await async_http_get(url, params=None)

        name = data.get("name", entity_id)
        category = data.get("category", "unknown")
        description = data.get("description", "No description available.")
        xrefs = data.get("xrefs", [])

        summary = (
            f"{name} ({entity_id}): category={category}. "
            f"{description[:200]}{'...' if len(description) > 200 else ''} "
            f"Cross-references: {len(xrefs)}."
        )

        return standard_response(
            summary=summary,
            raw_data=data,
            source="Monarch Initiative",
            source_id=entity_id,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("monarch_get_entity", exc)


# ---- 4. Get phenotypes for a gene -------------------------------------------


@mcp.tool()
async def monarch_get_phenotypes(gene_id: str, limit: int = 50) -> dict[str, Any]:
    """
    Get phenotypes associated with a gene via the Monarch Initiative.

    Args:
        gene_id: Gene CURIE (e.g. 'HGNC:1100' for BRCA1).
        limit: Maximum number of phenotype associations to return (default 50).
    """
    try:
        url = f"{MONARCH_API}/association"
        params: dict[str, Any] = {
            "subject": gene_id,
            "category": "biolink:GeneToPhenotypicFeatureAssociation",
            "limit": limit,
        }

        data = await async_http_get(url, params=params)

        items = data.get("items", [])
        total = data.get("total", len(items))

        phenotype_names = []
        for assoc in items[:20]:
            obj = assoc.get("object", {})
            if isinstance(obj, dict):
                phenotype_names.append(obj.get("name", "unknown"))
            else:
                phenotype_names.append(str(obj))

        summary = (
            f"{total} phenotype associations for {gene_id}. "
            f"Phenotypes: {', '.join(phenotype_names[:10])}"
            if items
            else f"No phenotype associations found for {gene_id}."
        )

        return standard_response(
            summary=summary,
            raw_data={"total": total, "items": items},
            source="Monarch Initiative",
            source_id=gene_id,
            confidence=0.8,
        )
    except Exception as exc:
        return handle_error("monarch_get_phenotypes", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
