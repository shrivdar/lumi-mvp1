"""
UniChem MCP Server — Lumi Virtual Lab

Exposes tools for querying the EBI UniChem API:
  compound cross-reference lookup, ID conversion, InChIKey search, source listing.

Start with:  python -m src.mcp_servers.unichem.server
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

UNICHEM_API = "https://www.ebi.ac.uk/unichem/rest"

# Well-known source IDs for reference
SOURCE_NAMES: dict[int, str] = {
    1: "ChEMBL",
    2: "DrugBank",
    3: "PDB",
    4: "IUPHAR",
    5: "PubChem (dotf)",
    6: "KEGG Ligand",
    7: "ChEBI",
    8: "NIH NCC",
    9: "ZINC",
    10: "eMolecules",
    11: "IBM Patent Data",
    12: "Atlas",
    14: "FDA SRS",
    15: "SureChEMBL",
    17: "PharmGKB",
    18: "HMDB",
    20: "Selleck",
    21: "PubChem (tgt)",
    22: "PubChem",
    24: "NMRShiftDB",
    25: "LINCS",
    26: "ACToR",
    27: "Recon",
    28: "MolPort",
    29: "Nikkaji",
    31: "BindingDB",
    32: "EPA CompTox",
    33: "LiPro",
    34: "DrugCentral",
    35: "Carotenoid DB",
    36: "Metabolights",
    37: "Brenda",
    38: "Rhea",
    39: "ChemicalBook",
    41: "SwissLipids",
}

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi UniChem",
    instructions="Compound cross-reference queries via EBI UniChem: lookup, ID conversion, InChIKey search, source listing",
)


# ---- 1. Compound cross-reference lookup -------------------------------------


@mcp.tool()
async def unichem_lookup(
    src_compound_id: str,
    src_id: int = 1,
    target_id: int | None = None,
) -> dict[str, Any]:
    """
    Look up compound cross-references in UniChem.

    Args:
        src_compound_id: Compound ID in the source database (e.g. 'CHEMBL25' for aspirin in ChEMBL).
        src_id: Source database ID (default 1 = ChEMBL). Use unichem_get_sources() to list all.
        target_id: Optional target database ID to filter results. If None, returns all cross-references.
    """
    try:
        if target_id is not None:
            url = f"{UNICHEM_API}/src_compound_id/{src_compound_id}/src_id/{src_id}/to/{target_id}"
        else:
            url = f"{UNICHEM_API}/src_compound_id/{src_compound_id}/src_id/{src_id}"

        headers = {"Accept": "application/json"}
        data = await async_http_get(url, headers=headers)

        # Response is a list of cross-references
        xrefs = data if isinstance(data, list) else [data] if isinstance(data, dict) and "src_compound_id" in data else []

        src_name = SOURCE_NAMES.get(src_id, f"source {src_id}")
        ref_summaries: list[str] = []
        for xref in xrefs[:15]:
            xref_src_id = int(xref.get("src_id", 0))
            xref_name = SOURCE_NAMES.get(xref_src_id, f"source {xref_src_id}")
            xref_cid = xref.get("src_compound_id", "N/A")
            ref_summaries.append(f"{xref_name}: {xref_cid}")

        if target_id is not None:
            target_name = SOURCE_NAMES.get(target_id, f"source {target_id}")
            summary = (
                f"{len(xrefs)} cross-references for {src_compound_id} ({src_name}) -> {target_name}. "
                f"Results: {'; '.join(ref_summaries[:10])}"
                if xrefs
                else f"No cross-references found for {src_compound_id} ({src_name}) in {target_name}."
            )
        else:
            summary = (
                f"{len(xrefs)} cross-references for {src_compound_id} ({src_name}). "
                f"Databases: {'; '.join(ref_summaries[:10])}"
                if xrefs
                else f"No cross-references found for {src_compound_id} ({src_name})."
            )

        return standard_response(
            summary=summary,
            raw_data={"src_compound_id": src_compound_id, "src_id": src_id, "cross_references": xrefs},
            source="EBI UniChem",
            source_id=src_compound_id,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("unichem_lookup", exc)


# ---- 2. Convert compound ID between databases --------------------------------


@mcp.tool()
async def unichem_convert_id(
    src_compound_id: str,
    src_id: int,
    target_id: int,
) -> dict[str, Any]:
    """
    Convert a compound ID from one database to another via UniChem.

    Args:
        src_compound_id: Compound ID in the source database (e.g. 'CHEMBL25').
        src_id: Source database ID (e.g. 1 for ChEMBL).
        target_id: Target database ID (e.g. 2 for DrugBank).
    """
    try:
        url = f"{UNICHEM_API}/src_compound_id/{src_compound_id}/src_id/{src_id}/to/{target_id}"
        headers = {"Accept": "application/json"}
        data = await async_http_get(url, headers=headers)

        results = data if isinstance(data, list) else [data] if isinstance(data, dict) and "src_compound_id" in data else []

        src_name = SOURCE_NAMES.get(src_id, f"source {src_id}")
        target_name = SOURCE_NAMES.get(target_id, f"source {target_id}")

        converted_ids = [r.get("src_compound_id", "N/A") for r in results]

        summary = (
            f"Converted {src_compound_id} from {src_name} to {target_name}: {', '.join(converted_ids[:10])}."
            if results
            else f"No mapping found from {src_compound_id} ({src_name}) to {target_name}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "src_compound_id": src_compound_id,
                "src_id": src_id,
                "target_id": target_id,
                "converted": results,
            },
            source="EBI UniChem",
            source_id=src_compound_id,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("unichem_convert_id", exc)


# ---- 3. Search by InChIKey --------------------------------------------------


@mcp.tool()
async def unichem_search_inchikey(inchikey: str) -> dict[str, Any]:
    """
    Search UniChem by InChIKey to find compound records across all databases.

    Args:
        inchikey: Standard InChIKey (e.g. 'BSYNRYMUTXBXSQ-UHFFFAOYSA-N' for aspirin).
    """
    try:
        url = f"{UNICHEM_API}/inchikey/{inchikey}"
        headers = {"Accept": "application/json"}
        data = await async_http_get(url, headers=headers)

        results = data if isinstance(data, list) else [data] if isinstance(data, dict) and "src_id" in data else []

        ref_summaries: list[str] = []
        for entry in results[:15]:
            entry_src_id = int(entry.get("src_id", 0))
            db_name = SOURCE_NAMES.get(entry_src_id, f"source {entry_src_id}")
            cid = entry.get("src_compound_id", "N/A")
            ref_summaries.append(f"{db_name}: {cid}")

        summary = (
            f"InChIKey {inchikey} found in {len(results)} databases. "
            f"Records: {'; '.join(ref_summaries[:10])}"
            if results
            else f"No records found for InChIKey {inchikey}."
        )

        return standard_response(
            summary=summary,
            raw_data={"inchikey": inchikey, "records": results},
            source="EBI UniChem",
            source_id=inchikey,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("unichem_search_inchikey", exc)


# ---- 4. List all UniChem sources ---------------------------------------------


@mcp.tool()
async def unichem_get_sources() -> dict[str, Any]:
    """
    List all available UniChem data sources with their IDs and names.
    """
    try:
        url = f"{UNICHEM_API}/src_ids/"
        headers = {"Accept": "application/json"}
        data = await async_http_get(url, headers=headers)

        sources = data if isinstance(data, list) else []

        source_ids = [s.get("src_id", "?") for s in sources]

        summary = (
            f"{len(sources)} UniChem data sources available. "
            f"Source IDs: {', '.join(str(sid) for sid in source_ids[:20])}{'...' if len(source_ids) > 20 else ''}."
            if sources
            else "Unable to retrieve UniChem source list."
        )

        return standard_response(
            summary=summary,
            raw_data={"sources": sources},
            source="EBI UniChem",
            source_id="src_ids",
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("unichem_get_sources", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
