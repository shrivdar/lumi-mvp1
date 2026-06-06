"""
Pathways & Ontology MCP Server -- Lumi Virtual Lab

Exposes tools for biological pathway and ontology queries across Reactome,
Gene Ontology (GO), KEGG, and WikiPathways databases.

Start with:  python -m src.mcp_servers.pathways.server
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

from fastmcp import FastMCP

try:
    from src.mcp_servers.base import async_http_get, async_http_post, handle_error, standard_response
except ImportError:
    from mcp_servers.base import async_http_get, async_http_post, handle_error, standard_response

logger = logging.getLogger("lumi.mcp.pathways")

# ---------------------------------------------------------------------------
# API base URLs
# ---------------------------------------------------------------------------
REACTOME_CONTENT = "https://reactome.org/ContentService"
REACTOME_ANALYSIS = "https://reactome.org/AnalysisService"
GO_API = "https://api.geneontology.org/api"
KEGG_REST = "https://rest.kegg.jp"
WIKIPATHWAYS_API = "https://webservice.wikipathways.org"

# ---------------------------------------------------------------------------
# KEGG text-response helpers
# ---------------------------------------------------------------------------


def _parse_kegg_tsv(text: str) -> list[dict[str, str]]:
    """Parse KEGG tab-separated text into a list of dicts with keys 'col1', 'col2'."""
    rows: list[dict[str, str]] = []
    for line in text.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append({"col1": parts[0].strip(), "col2": parts[1].strip()})
        elif len(parts) == 1:
            rows.append({"col1": parts[0].strip(), "col2": ""})
    return rows


def _parse_kegg_flat(text: str) -> dict[str, Any]:
    """Parse a KEGG flat-file record (from /get/) into a dictionary.

    KEGG flat files use a fixed-width label in the first 12 characters.
    Multi-line values are continued with leading whitespace.
    """
    result: dict[str, Any] = {}
    current_key: str | None = None

    for line in text.splitlines():
        if line.startswith("///"):
            break  # End of record

        # Check if this is a new field (label in columns 0-11)
        if line and not line[0].isspace():
            # Split on first run of whitespace after label
            match = re.match(r"^(\S+)\s+(.*)", line)
            if match:
                current_key = match.group(1)
                value = match.group(2).strip()
                if current_key in result:
                    # Append to existing list
                    if isinstance(result[current_key], list):
                        result[current_key].append(value)
                    else:
                        result[current_key] = [result[current_key], value]
                else:
                    result[current_key] = value
            else:
                current_key = line.strip()
                result[current_key] = ""
        elif current_key:
            # Continuation line
            val = line.strip()
            if isinstance(result[current_key], list):
                result[current_key].append(val)
            elif result[current_key]:
                result[current_key] = [result[current_key], val]
            else:
                result[current_key] = val

    return result


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "Lumi Pathways",
    instructions=(
        "Biological pathway and gene ontology toolkit for the Lumi Virtual Lab.  "
        "Queries Reactome, Gene Ontology, KEGG, and WikiPathways to retrieve "
        "pathway memberships, enrichment results, and functional annotations."
    ),
)


# ===== Reactome tools =======================================================


@mcp.tool()
async def get_pathways_for_gene(gene: str) -> dict[str, Any]:
    """Find Reactome pathways associated with a gene.

    Args:
        gene: Gene symbol (e.g. 'TP53', 'BRCA1', 'EGFR').

    Returns:
        List of Reactome pathways containing the gene, with stable IDs,
        names, and species.
    """
    try:
        url = f"{REACTOME_CONTENT}/search/query"
        params = {
            "query": gene,
            "types": "Pathway",
            "species": "Homo sapiens",
            "cluster": "true",
        }
        data = await async_http_get(url, params=params)

        results: list[dict[str, Any]] = []
        grouped = data.get("results", [])
        for group in grouped:
            entries = group.get("entries", [])
            for entry in entries:
                results.append({
                    "stable_id": entry.get("stId"),
                    "name": entry.get("name"),
                    "species": entry.get("species", []),
                    "exact_type": entry.get("exactType"),
                    "score": entry.get("score"),
                })

        # Deduplicate by stable_id
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for r in results:
            sid = r.get("stable_id", "")
            if sid and sid not in seen:
                seen.add(sid)
                unique.append(r)

        summary = (
            f"Found {len(unique)} Reactome pathways for gene {gene} "
            f"(Homo sapiens)"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "gene": gene,
                "num_pathways": len(unique),
                "pathways": unique[:100],  # Cap for readability
            },
            source="Reactome",
            source_id=gene,
            confidence=0.90,
        )
    except Exception as exc:
        return handle_error("get_pathways_for_gene", exc)


@mcp.tool()
async def get_pathway_details(pathway_id: str) -> dict[str, Any]:
    """Get detailed information about a specific Reactome pathway.

    Args:
        pathway_id: Reactome stable identifier (e.g. 'R-HSA-1640170').

    Returns:
        Pathway name, compartments, literature references, participating
        molecules, and sub-pathways.
    """
    try:
        url = f"{REACTOME_CONTENT}/data/query/{pathway_id}"
        data = await async_http_get(url)

        # Extract key fields
        name = data.get("displayName") or data.get("name", "N/A")
        species_name = ""
        species_list = data.get("species", [])
        if species_list:
            species_name = species_list[0].get("displayName", "") if isinstance(species_list[0], dict) else str(species_list[0])

        compartments = [
            c.get("displayName", str(c))
            for c in data.get("compartment", [])
            if isinstance(c, dict)
        ]

        literature = []
        for lit in data.get("literatureReference", [])[:10]:
            if isinstance(lit, dict):
                literature.append({
                    "title": lit.get("title"),
                    "pubmed_id": lit.get("pubMedIdentifier"),
                    "year": lit.get("year"),
                })

        has_event = data.get("hasEvent", [])
        sub_pathways = []
        for ev in has_event[:50]:
            if isinstance(ev, dict):
                sub_pathways.append({
                    "stable_id": ev.get("stId"),
                    "name": ev.get("displayName"),
                    "schema_class": ev.get("schemaClass"),
                })

        summary = (
            f"Reactome pathway {pathway_id}: '{name}' "
            f"({species_name}), "
            f"{len(sub_pathways)} sub-event(s), "
            f"{len(literature)} reference(s)"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "pathway_id": pathway_id,
                "name": name,
                "species": species_name,
                "compartments": compartments,
                "sub_pathways": sub_pathways,
                "literature": literature,
                "schema_class": data.get("schemaClass"),
                "is_in_disease": data.get("isInDisease", False),
            },
            source="Reactome",
            source_id=pathway_id,
            confidence=0.92,
        )
    except Exception as exc:
        return handle_error("get_pathway_details", exc)


@mcp.tool()
async def pathway_enrichment(gene_list: str) -> dict[str, Any]:
    """Run Reactome pathway over-representation analysis on a gene list.

    Args:
        gene_list: Newline-separated or comma-separated list of gene
                   identifiers (symbols, UniProt IDs, or Ensembl IDs).

    Returns:
        Enriched pathways sorted by p-value, with FDR, gene counts, and
        pathway names.
    """
    try:
        # Normalise separators to newlines
        genes_clean = gene_list.replace(",", "\n").replace(";", "\n").replace(" ", "\n")
        genes_clean = "\n".join(
            g.strip() for g in genes_clean.splitlines() if g.strip()
        )
        gene_count = len(genes_clean.splitlines())

        url = f"{REACTOME_ANALYSIS}/identifiers/projection"
        headers = {"Content-Type": "text/plain"}
        data = await async_http_post(url, data=genes_clean, headers=headers, timeout=90.0)

        pathways_raw = data.get("pathways", [])
        enriched: list[dict[str, Any]] = []
        for pw in pathways_raw[:100]:
            entities = pw.get("entities", {})
            enriched.append({
                "stable_id": pw.get("stId"),
                "name": pw.get("name"),
                "p_value": entities.get("pValue"),
                "fdr": entities.get("fdr"),
                "found": entities.get("found"),
                "total": entities.get("total"),
                "ratio": entities.get("ratio"),
                "species": pw.get("species", {}).get("name", ""),
            })

        # Sort by p-value
        enriched.sort(key=lambda x: x.get("p_value") or 1.0)

        sig_count = sum(1 for e in enriched if (e.get("fdr") or 1.0) < 0.05)
        summary = (
            f"Reactome enrichment for {gene_count} genes: "
            f"{len(enriched)} pathways returned, "
            f"{sig_count} significant (FDR < 0.05)"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "input_gene_count": gene_count,
                "total_pathways": len(pathways_raw),
                "shown": len(enriched),
                "significant_fdr005": sig_count,
                "pathways": enriched,
                "summary_token": data.get("summary", {}).get("token"),
            },
            source="Reactome",
            source_id="enrichment_analysis",
            confidence=0.88,
        )
    except Exception as exc:
        return handle_error("pathway_enrichment", exc)


# ===== Gene Ontology tools ==================================================


@mcp.tool()
async def get_go_annotations(gene: str) -> dict[str, Any]:
    """Retrieve Gene Ontology functional annotations for a gene.

    Queries the GO API for molecular function, biological process, and
    cellular component annotations.

    Args:
        gene: Gene symbol (e.g. 'TP53').  Will be queried via HGNC prefix.

    Returns:
        GO term annotations grouped by aspect (F=function, P=process,
        C=component).
    """
    try:
        encoded = quote(gene, safe="")
        # Use search endpoint — bioentity requires numeric HGNC IDs
        url = f"{GO_API}/search/entity/autocomplete/{encoded}"
        params = {"rows": "1", "category": "gene"}
        search = await async_http_get(url, params=params, timeout=30.0)
        docs = search.get("docs", [])
        entity_id = docs[0].get("id", f"HGNC:{encoded}") if docs else f"HGNC:{encoded}"
        url = f"{GO_API}/bioentity/gene/{quote(entity_id, safe='')}/function"
        params = {"rows": "100"}
        data = await async_http_get(url, params=params, timeout=45.0)

        associations = data.get("associations", [])
        annotations: list[dict[str, Any]] = []
        for assoc in associations:
            obj = assoc.get("object", {})
            annotations.append({
                "go_id": obj.get("id"),
                "go_term": obj.get("label"),
                "aspect": obj.get("category", [None])[0] if obj.get("category") else None,
                "evidence_code": assoc.get("evidence"),
                "qualifier": assoc.get("qualifier"),
            })

        # Group by aspect
        by_aspect: dict[str, list[dict[str, Any]]] = {
            "molecular_function": [],
            "biological_process": [],
            "cellular_component": [],
            "other": [],
        }
        aspect_map = {
            "molecular_activity": "molecular_function",
            "molecular_function": "molecular_function",
            "biological_process": "biological_process",
            "cellular_component": "cellular_component",
        }
        for ann in annotations:
            aspect = ann.get("aspect") or "other"
            bucket = aspect_map.get(aspect, "other")
            by_aspect[bucket].append(ann)

        total = len(annotations)
        summary = (
            f"GO annotations for {gene}: {total} total -- "
            f"MF={len(by_aspect['molecular_function'])}, "
            f"BP={len(by_aspect['biological_process'])}, "
            f"CC={len(by_aspect['cellular_component'])}"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "gene": gene,
                "total_annotations": total,
                "by_aspect": by_aspect,
                "all_annotations": annotations[:100],
            },
            source="Gene Ontology",
            source_id=f"HGNC:{gene}",
            confidence=0.88,
        )
    except Exception as exc:
        return handle_error("get_go_annotations", exc)


@mcp.tool()
async def go_enrichment(gene_list: str) -> dict[str, Any]:
    """Run Gene Ontology enrichment analysis on a gene list.

    Uses the GO enrichment API to find over-represented GO terms in the
    provided gene set.

    Args:
        gene_list: Comma-separated or newline-separated gene symbols.

    Returns:
        Enriched GO terms with p-values, FDR, fold enrichment, and term
        names grouped by ontology aspect.
    """
    try:
        # Normalise to comma-separated list
        genes = [
            g.strip()
            for g in gene_list.replace("\n", ",").replace(";", ",").split(",")
            if g.strip()
        ]

        # Use the PANTHER enrichment endpoint via GO API
        url = "https://pantherdb.org/services/oai/pantherdb/enrich/overrep"
        params = {
            "geneInputList": ",".join(genes),
            "organism": "9606",  # Homo sapiens
            "annotDataSet": "GO:0008150",  # Biological Process by default
            "enrichmentTestType": "FISHER",
            "correction": "FDR",
        }
        data = await async_http_get(url, params=params, timeout=90.0)

        results_raw = data.get("results", {}).get("result", [])
        if isinstance(results_raw, dict):
            results_raw = [results_raw]

        enriched: list[dict[str, Any]] = []
        for item in results_raw[:100]:
            term = item.get("term", {})
            enriched.append({
                "go_id": term.get("id"),
                "go_term": term.get("label"),
                "p_value": item.get("pValue"),
                "fdr": item.get("fdr"),
                "fold_enrichment": item.get("fold_enrichment"),
                "expected": item.get("expected"),
                "number_in_list": item.get("number_in_list"),
                "number_in_reference": item.get("number_in_reference"),
                "plus_minus": item.get("plus_minus"),
            })

        # Sort by p-value
        enriched.sort(key=lambda x: x.get("p_value") or 1.0)
        sig_count = sum(1 for e in enriched if (e.get("fdr") or 1.0) < 0.05)

        summary = (
            f"GO enrichment for {len(genes)} genes: "
            f"{len(enriched)} terms returned, "
            f"{sig_count} significant (FDR < 0.05)"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "input_gene_count": len(genes),
                "genes": genes,
                "total_terms": len(results_raw),
                "shown": len(enriched),
                "significant_fdr005": sig_count,
                "enriched_terms": enriched,
            },
            source="Gene Ontology / PANTHER",
            source_id="go_enrichment",
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("go_enrichment", exc)


# ===== KEGG tools ===========================================================


@mcp.tool()
async def get_kegg_pathways(gene: str) -> dict[str, Any]:
    """Find KEGG pathways associated with a human gene.

    First resolves the gene symbol to a KEGG gene ID, then retrieves linked
    pathways.

    Args:
        gene: Gene symbol (e.g. 'TP53', 'BRCA1').

    Returns:
        List of KEGG pathway IDs and names linked to the gene.
    """
    try:
        # Step 1: Resolve gene symbol to KEGG gene ID
        search_url = f"{KEGG_REST}/find/genes/{quote(gene, safe='')}+homo+sapiens"
        search_data = await async_http_get(search_url, timeout=30.0)
        search_text = search_data.get("text", "")

        if not search_text.strip():
            return handle_error(
                "get_kegg_pathways",
                f"No KEGG gene entries found for '{gene}' in Homo sapiens.",
            )

        # Parse search results to find the hsa: gene ID
        gene_ids: list[str] = []
        for line in search_text.strip().splitlines():
            parts = line.split("\t")
            if parts and parts[0].startswith("hsa:"):
                gene_ids.append(parts[0].strip())

        if not gene_ids:
            return handle_error(
                "get_kegg_pathways",
                f"Could not resolve '{gene}' to a KEGG Homo sapiens gene ID.",
            )

        kegg_gene_id = gene_ids[0]  # Take the first match

        # Step 2: Get linked pathways
        link_url = f"{KEGG_REST}/link/pathway/{kegg_gene_id}"
        link_data = await async_http_get(link_url, timeout=30.0)
        link_text = link_data.get("text", "")

        pathway_ids: list[str] = []
        for line in link_text.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                pid = parts[1].strip()
                if pid.startswith("path:"):
                    pid = pid.replace("path:", "")
                pathway_ids.append(pid)

        # Step 3: Get pathway names in batch
        pathways: list[dict[str, str]] = []
        if pathway_ids:
            ids_str = "+".join(pathway_ids)
            info_url = f"{KEGG_REST}/list/{ids_str}"
            info_data = await async_http_get(info_url, timeout=30.0)
            info_text = info_data.get("text", "")

            for line in info_text.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    pid = parts[0].strip()
                    pname = parts[1].strip()
                    # Remove " - Homo sapiens (human)" suffix if present
                    pname = re.sub(r"\s*-\s*Homo sapiens\s*\(human\)\s*$", "", pname)
                    pathways.append({"pathway_id": pid, "name": pname})

        summary = (
            f"KEGG pathways for {gene} ({kegg_gene_id}): "
            f"{len(pathways)} pathway(s) found"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "gene": gene,
                "kegg_gene_id": kegg_gene_id,
                "all_matched_gene_ids": gene_ids[:5],
                "num_pathways": len(pathways),
                "pathways": pathways,
            },
            source="KEGG",
            source_id=kegg_gene_id,
            confidence=0.88,
        )
    except Exception as exc:
        return handle_error("get_kegg_pathways", exc)


@mcp.tool()
async def get_pathway_genes(pathway_id: str) -> dict[str, Any]:
    """Get all human genes belonging to a KEGG pathway.

    Args:
        pathway_id: KEGG pathway identifier (e.g. 'hsa04110' for cell cycle,
                    'hsa05200' for pathways in cancer).  The 'hsa' prefix is
                    required for human pathways.

    Returns:
        List of KEGG gene IDs linked to the pathway.
    """
    try:
        # Normalise pathway ID
        pid = pathway_id.strip()
        if not pid.startswith("hsa") and not pid.startswith("path:"):
            pid = f"hsa{pid}" if pid.isdigit() or pid.startswith("0") else pid

        url = f"{KEGG_REST}/link/hsa/{pid}"
        data = await async_http_get(url, timeout=30.0)
        text = data.get("text", "")

        gene_ids: list[str] = []
        for line in text.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                gid = parts[1].strip()
                if gid.startswith("hsa:"):
                    gene_ids.append(gid)

        # Optionally resolve gene names
        gene_info: list[dict[str, str]] = []
        if gene_ids:
            # Batch lookup (KEGG allows up to ~100 IDs)
            batch = gene_ids[:100]
            ids_str = "+".join(batch)
            list_url = f"{KEGG_REST}/list/{ids_str}"
            list_data = await async_http_get(list_url, timeout=30.0)
            list_text = list_data.get("text", "")

            for line in list_text.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    gid = parts[0].strip()
                    desc = parts[1].strip()
                    # Extract symbol from description (usually first token before semicolon)
                    symbol = desc.split(";")[0].strip().split(",")[0].strip()
                    gene_info.append({
                        "kegg_id": gid,
                        "symbol": symbol,
                        "description": desc,
                    })

        summary = (
            f"KEGG pathway {pid}: {len(gene_ids)} gene(s) found"
            + (f" (showing details for {len(gene_info)})" if gene_info else "")
        )
        return standard_response(
            summary=summary,
            raw_data={
                "pathway_id": pid,
                "num_genes": len(gene_ids),
                "gene_ids": gene_ids,
                "gene_details": gene_info,
            },
            source="KEGG",
            source_id=pid,
            confidence=0.90,
        )
    except Exception as exc:
        return handle_error("get_pathway_genes", exc)


@mcp.tool()
async def get_pathway_info(pathway_id: str) -> dict[str, Any]:
    """Get detailed information about a KEGG pathway.

    Args:
        pathway_id: KEGG pathway identifier (e.g. 'hsa04110').

    Returns:
        Pathway name, description, associated diseases, related pathways,
        database links, and references.
    """
    try:
        pid = pathway_id.strip()
        if not pid.startswith("hsa") and not pid.startswith("path:") and not pid.startswith("map"):
            pid = f"hsa{pid}" if pid.isdigit() or pid.startswith("0") else pid

        url = f"{KEGG_REST}/get/{pid}"
        data = await async_http_get(url, timeout=30.0)
        text = data.get("text", "")

        if not text.strip():
            return handle_error(
                "get_pathway_info",
                f"No data returned for pathway '{pid}'.",
            )

        parsed = _parse_kegg_flat(text)

        # Extract structured fields
        name = parsed.get("NAME", "N/A")
        if isinstance(name, list):
            name = name[0]
        # Clean trailing " - Homo sapiens (human)"
        name = re.sub(r"\s*-\s*Homo sapiens\s*\(human\)\s*$", "", str(name))

        description = parsed.get("DESCRIPTION", "")
        if isinstance(description, list):
            description = " ".join(description)

        # Disease associations
        diseases_raw = parsed.get("DISEASE", [])
        if isinstance(diseases_raw, str):
            diseases_raw = [diseases_raw]
        diseases: list[dict[str, str]] = []
        for d in diseases_raw:
            match = re.match(r"(H\d+)\s+(.*)", str(d))
            if match:
                diseases.append({"kegg_disease_id": match.group(1), "name": match.group(2)})
            else:
                diseases.append({"kegg_disease_id": "", "name": str(d)})

        # Drug associations
        drugs_raw = parsed.get("DRUG", [])
        if isinstance(drugs_raw, str):
            drugs_raw = [drugs_raw]

        # Module associations
        modules_raw = parsed.get("MODULE", [])
        if isinstance(modules_raw, str):
            modules_raw = [modules_raw]

        # References
        refs_raw = parsed.get("REFERENCE", [])
        if isinstance(refs_raw, str):
            refs_raw = [refs_raw]

        # DB links
        dblinks_raw = parsed.get("DBLINKS", [])
        if isinstance(dblinks_raw, str):
            dblinks_raw = [dblinks_raw]

        summary = (
            f"KEGG pathway {pid}: '{name}'. "
            f"{len(diseases)} disease association(s), "
            f"{len(drugs_raw)} drug(s)"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "pathway_id": pid,
                "name": name,
                "description": str(description),
                "class": parsed.get("CLASS", ""),
                "diseases": diseases,
                "drugs": drugs_raw[:20],
                "modules": modules_raw[:20],
                "db_links": dblinks_raw[:20],
                "references": refs_raw[:10],
                "organism": parsed.get("ORGANISM", ""),
            },
            source="KEGG",
            source_id=pid,
            confidence=0.90,
        )
    except Exception as exc:
        return handle_error("get_pathway_info", exc)


# ===== WikiPathways tool ====================================================


@mcp.tool()
async def search_pathways(
    query: str,
    species: str = "Homo sapiens",
) -> dict[str, Any]:
    """Search WikiPathways for pathways matching a text query.

    Args:
        query: Free-text search term (e.g. 'apoptosis', 'WNT signaling').
        species: Species name (default: 'Homo sapiens').

    Returns:
        List of matching WikiPathways with IDs, names, species, revision
        numbers, and URLs.
    """
    try:
        url = f"{WIKIPATHWAYS_API}/findPathwaysByText"
        params = {
            "query": query,
            "species": species,
            "format": "json",
        }
        data = await async_http_get(url, params=params, timeout=45.0)

        # WikiPathways returns {"result": [...]} or the list directly
        results_raw: list[Any] = []
        if isinstance(data, dict):
            results_raw = data.get("result", data.get("pathways", []))
            if isinstance(results_raw, dict):
                results_raw = [results_raw]
        elif isinstance(data, list):
            results_raw = data

        pathways: list[dict[str, Any]] = []
        for item in results_raw[:100]:
            if isinstance(item, dict):
                wp_id = item.get("id") or item.get("identifier", "")
                name = item.get("name") or item.get("title", "")
                sp = item.get("species") or item.get("organism", "")
                rev = item.get("revision") or item.get("version", "")
                url_link = item.get("url") or f"https://www.wikipathways.org/pathways/{wp_id}"

                pathways.append({
                    "wp_id": wp_id,
                    "name": name,
                    "species": sp,
                    "revision": rev,
                    "url": url_link,
                })

        summary = (
            f"WikiPathways search for '{query}' ({species}): "
            f"{len(pathways)} pathway(s) found"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "query": query,
                "species": species,
                "num_pathways": len(pathways),
                "pathways": pathways,
            },
            source="WikiPathways",
            source_id=f"search:{query}",
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("search_pathways", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
