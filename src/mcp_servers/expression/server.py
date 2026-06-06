"""
Expression MCP Server — Lumi Virtual Lab

Exposes tools for querying gene/protein expression databases:
  GTEx, Human Protein Atlas, CellxGene, GEO, ENCODE.

Start with:  python -m src.mcp_servers.expression.server
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

try:
    from src.mcp_servers.base import async_http_get, handle_error, standard_response
except ImportError:
    from mcp_servers.base import async_http_get, handle_error, standard_response  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GTEX_API = "https://gtexportal.org/api/v2"
HPA_API = "https://www.proteinatlas.org/api"
ENCODE_API = "https://www.encodeproject.org"
NCBI_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CELLXGENE_API = "https://api.cellxgene.cziscience.com"

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi Expression",
    instructions="Gene & protein expression queries: GTEx, Human Protein Atlas, CellxGene, GEO, ENCODE",
)


# ---- 1. GTEx: gene expression across tissues ------------------------------


@mcp.tool()
async def get_gene_expression(gene: str) -> dict[str, Any]:
    """
    Query the GTEx Portal API for median gene expression (TPM) across ~54 tissues.

    Args:
        gene: Gene symbol (e.g. TP53) or Ensembl gene ID.
    """
    try:
        # Resolve gene to versioned Ensembl ID via GTEx gene search
        gene_id = gene
        if not gene.startswith("ENSG"):
            search_url = f"{GTEX_API}/genes"
            search_params = {"geneId": gene, "page": 0, "itemsPerPage": 5}
            search_data = await async_http_get(search_url, params=search_params)
            genes_found = search_data.get("data", [])
            if genes_found:
                gene_id = genes_found[0].get("gencodeId", gene)
            else:
                gene_id = gene

        url = f"{GTEX_API}/expression/medianGeneExpression"
        params = {
            "gencodeId": gene_id,
            "datasetId": "gtex_v8",
        }
        data = await async_http_get(url, params=params)

        expression = data.get("data", [])
        if not expression:
            # Fallback: try the medianTranscriptExpression endpoint
            return standard_response(
                summary=f"No GTEx expression data found for {gene} ({gene_id}).",
                raw_data={"gene": gene, "gencodeId": gene_id, "data": []},
                source="GTEx Portal",
                source_id=gene_id,
                confidence=0.5,
            )

        # Sort by median TPM descending
        expression_sorted = sorted(expression, key=lambda x: x.get("median", 0), reverse=True)

        top_tissues = []
        for entry in expression_sorted[:10]:
            tissue = entry.get("tissueSiteDetailId", "unknown")
            median_tpm = entry.get("median", 0)
            top_tissues.append(f"{tissue}: {median_tpm:.2f} TPM")

        summary = (
            f"GTEx expression for {gene} across {len(expression)} tissues. "
            f"Top expressed: {'; '.join(top_tissues[:5])}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "gene": gene,
                "gencodeId": gene_id,
                "num_tissues": len(expression),
                "expression": expression_sorted,
            },
            source="GTEx Portal",
            source_id=gene_id,
            version="v8",
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("get_gene_expression", exc)


# ---- 2. Human Protein Atlas: protein expression ----------------------------


@mcp.tool()
async def get_protein_expression(gene: str) -> dict[str, Any]:
    """
    Query the Human Protein Atlas REST API for tissue/cell protein expression
    and subcellular localization.

    Args:
        gene: Gene symbol (e.g. TP53).
    """
    try:
        url = f"{HPA_API}/search_download.php"
        params = {
            "search": gene,
            "format": "json",
            "columns": "g,t,sc,up,rnats,rnacs",
            "compress": "no",
        }
        data = await async_http_get(url, params=params)

        # HPA returns a list of gene entries
        entries = data if isinstance(data, list) else [data] if isinstance(data, dict) and "Gene" in data else []

        if not entries:
            # Try the direct gene endpoint
            alt_url = f"https://www.proteinatlas.org/{gene}.json"
            try:
                data = await async_http_get(alt_url)
                entries = [data] if isinstance(data, dict) else []
            except Exception:
                pass

        if not entries:
            return standard_response(
                summary=f"No Human Protein Atlas data found for {gene}.",
                raw_data={"gene": gene},
                source="Human Protein Atlas",
                source_id=gene,
                confidence=0.4,
            )

        entry = entries[0]

        # Extract tissue expression
        tissue_expression = entry.get("Tissue expression", entry.get("rnaTissue", []))
        subcellular = entry.get("Subcellular location", entry.get("subcellularLocation", []))
        rna_tissue = entry.get("RNA tissue specificity", entry.get("rnaTissueSpecificity", "N/A"))

        # Build summary
        tissue_count = len(tissue_expression) if isinstance(tissue_expression, list) else 0
        subcell_summary = ""
        if isinstance(subcellular, list) and subcellular:
            locs = [s.get("location", s) if isinstance(s, dict) else str(s) for s in subcellular[:5]]
            subcell_summary = f" Subcellular: {', '.join(locs)}."
        elif isinstance(subcellular, str):
            subcell_summary = f" Subcellular: {subcellular}."

        summary = (
            f"HPA protein expression for {gene}: {tissue_count} tissue records. "
            f"RNA tissue specificity: {rna_tissue}.{subcell_summary}"
        )

        return standard_response(
            summary=summary,
            raw_data=entry,
            source="Human Protein Atlas",
            source_id=gene,
            version="23.0",
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_protein_expression", exc)


# ---- 3. HPA: cancer / pathology data --------------------------------------


@mcp.tool()
async def get_pathology_data(gene: str) -> dict[str, Any]:
    """
    Query Human Protein Atlas for cancer pathology expression data.

    Args:
        gene: Gene symbol (e.g. TP53).
    """
    try:
        url = f"{HPA_API}/search_download.php"
        params = {
            "search": gene,
            "format": "json",
            "columns": "g,patd,prca,rnaca",
            "compress": "no",
        }
        data = await async_http_get(url, params=params)

        entries = data if isinstance(data, list) else [data] if isinstance(data, dict) and not data.get("error") else []

        if not entries:
            return standard_response(
                summary=f"No HPA pathology data found for {gene}.",
                raw_data={"gene": gene},
                source="Human Protein Atlas (Pathology)",
                source_id=gene,
                confidence=0.4,
            )

        entry = entries[0]
        entry.get("Pathology data", entry.get("pathology", {}))
        prognostic = entry.get("Prognostic data", entry.get("prognostic", []))
        rna_cancer = entry.get("RNA cancer", entry.get("rnaCancer", []))

        cancer_count = len(rna_cancer) if isinstance(rna_cancer, list) else 0
        prognostic_count = len(prognostic) if isinstance(prognostic, list) else 0

        # Summarise top cancers by expression
        top_cancers = []
        if isinstance(rna_cancer, list):
            for c in rna_cancer[:5]:
                cancer_name = c.get("Cancer", c.get("cancer", "unknown"))
                tpm = c.get("TPM", c.get("value", "N/A"))
                top_cancers.append(f"{cancer_name}: {tpm} TPM")

        summary = (
            f"HPA pathology for {gene}: {cancer_count} cancer types, "
            f"{prognostic_count} prognostic associations. "
            f"Top cancers: {'; '.join(top_cancers) or 'N/A'}."
        )

        return standard_response(
            summary=summary,
            raw_data=entry,
            source="Human Protein Atlas (Pathology)",
            source_id=gene,
            version="23.0",
            confidence=0.8,
        )
    except Exception as exc:
        return handle_error("get_pathology_data", exc)


# ---- 4. CellxGene Census: single-cell expression --------------------------


@mcp.tool()
async def query_gene_expression_single_cell(
    gene: str,
    tissue: str | None = None,
    disease: str | None = None,
) -> dict[str, Any]:
    """
    Query the CellxGene Discover REST API for single-cell gene expression summary.

    Args:
        gene: Gene symbol (e.g. CD8A).
        tissue: Optional tissue filter (e.g. 'lung').
        disease: Optional disease filter (e.g. 'COVID-19').
    """
    try:
        # CellxGene Census API — use the datasets endpoint to find relevant datasets
        # then summarise expression information
        url = f"{CELLXGENE_API}/dp/v1/datasets/index"
        data = await async_http_get(url)

        datasets = data if isinstance(data, list) else data.get("datasets", []) if isinstance(data, dict) else []

        # Filter datasets that mention the gene, tissue, or disease
        relevant = []
        for ds in datasets:
            ds_tissue = ds.get("tissue", []) if isinstance(ds.get("tissue"), list) else [ds.get("tissue", "")]
            ds_disease = ds.get("disease", []) if isinstance(ds.get("disease"), list) else [ds.get("disease", "")]
            ds.get("name", "").lower()

            tissue_labels = [t.get("label", t) if isinstance(t, dict) else str(t) for t in ds_tissue]
            disease_labels = [d.get("label", d) if isinstance(d, dict) else str(d) for d in ds_disease]

            tissue_match = tissue is None or any(tissue.lower() in t.lower() for t in tissue_labels)
            disease_match = disease is None or any(disease.lower() in d.lower() for d in disease_labels)

            if tissue_match and disease_match:
                relevant.append({
                    "dataset_id": ds.get("dataset_id", ds.get("id", "")),
                    "name": ds.get("name", ""),
                    "tissues": tissue_labels,
                    "diseases": disease_labels,
                    "cell_count": ds.get("cell_count", 0),
                    "assay": [a.get("label", a) if isinstance(a, dict) else str(a) for a in (ds.get("assay", []) if isinstance(ds.get("assay"), list) else [])],
                    "organism": [o.get("label", o) if isinstance(o, dict) else str(o) for o in (ds.get("organism", []) if isinstance(ds.get("organism"), list) else [])],
                })

        # Sort by cell count desc
        relevant.sort(key=lambda x: x.get("cell_count", 0), reverse=True)
        relevant = relevant[:20]

        total_cells = sum(d.get("cell_count", 0) for d in relevant)
        tissue_set = set()
        for d in relevant:
            tissue_set.update(d.get("tissues", []))

        filters_applied = []
        if tissue:
            filters_applied.append(f"tissue={tissue}")
        if disease:
            filters_applied.append(f"disease={disease}")
        filter_str = f" (filters: {', '.join(filters_applied)})" if filters_applied else ""

        summary = (
            f"CellxGene: {len(relevant)} datasets relevant to {gene}{filter_str}. "
            f"Total cells: ~{total_cells:,}. "
            f"Tissues represented: {', '.join(sorted(tissue_set)[:10]) or 'N/A'}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "gene": gene,
                "filters": {"tissue": tissue, "disease": disease},
                "matching_datasets": relevant,
                "total_matching_cells": total_cells,
            },
            source="CellxGene Discover",
            source_id=gene,
            confidence=0.7,
        )
    except Exception as exc:
        return handle_error("query_gene_expression_single_cell", exc)


# ---- 5. GEO: dataset search -----------------------------------------------


@mcp.tool()
async def search_geo_datasets(query: str) -> dict[str, Any]:
    """
    Search NCBI GEO for expression datasets matching a query.

    Args:
        query: Free-text search query (e.g. 'TP53 lung cancer RNA-seq').
    """
    try:
        url = f"{NCBI_EUTILS}/esearch.fcgi"
        params = {
            "db": "gds",
            "term": query,
            "retmax": 20,
            "retmode": "json",
        }
        search_data = await async_http_get(url, params=params)

        id_list = search_data.get("esearchresult", {}).get("idlist", [])
        total = int(search_data.get("esearchresult", {}).get("count", 0))

        if not id_list:
            return standard_response(
                summary=f"No GEO datasets found for query: {query}",
                raw_data={"query": query, "count": 0},
                source="NCBI GEO",
                source_id=query,
                confidence=0.5,
            )

        # Fetch summaries
        ids_str = ",".join(id_list[:20])
        summary_url = f"{NCBI_EUTILS}/esummary.fcgi"
        summary_params = {"db": "gds", "id": ids_str, "retmode": "json"}
        summary_data = await async_http_get(summary_url, params=summary_params)

        result = summary_data.get("result", {})
        uids = result.get("uids", [])

        datasets = []
        for uid in uids:
            entry = result.get(uid, {})
            datasets.append({
                "uid": uid,
                "accession": entry.get("accession", ""),
                "title": entry.get("title", ""),
                "summary": entry.get("summary", "")[:300],
                "gpl": entry.get("gpl", ""),
                "gse": entry.get("gse", ""),
                "platform_organism": entry.get("taxon", ""),
                "sample_count": entry.get("n_samples", 0),
                "type": entry.get("gdsType", ""),
            })

        summary = (
            f"GEO search '{query}': {total} total results, retrieved {len(datasets)}. "
            f"Top hits: {'; '.join(d['accession'] + ' - ' + d['title'][:60] for d in datasets[:3])}."
        )

        return standard_response(
            summary=summary,
            raw_data={"query": query, "total_count": total, "datasets": datasets},
            source="NCBI GEO",
            source_id=query,
            confidence=0.8,
        )
    except Exception as exc:
        return handle_error("search_geo_datasets", exc)


# ---- 6. GTEx: eQTLs -------------------------------------------------------


@mcp.tool()
async def get_eqtls(gene: str, tissue: str) -> dict[str, Any]:
    """
    Query the GTEx eQTL API for expression quantitative trait loci.

    Args:
        gene: Gene symbol or Ensembl ID (e.g. TP53).
        tissue: GTEx tissue ID (e.g. 'Lung', 'Liver', 'Whole_Blood').
                Use underscore-separated GTEx tissue names.
    """
    try:
        # Resolve gene ID if needed
        gene_id = gene
        if not gene.startswith("ENSG"):
            search_url = f"{GTEX_API}/genes"
            search_params = {"geneId": gene, "page": 0, "itemsPerPage": 5}
            search_data = await async_http_get(search_url, params=search_params)
            genes_found = search_data.get("data", [])
            if genes_found:
                gene_id = genes_found[0].get("gencodeId", gene)

        url = f"{GTEX_API}/association/singleTissueEqtl"
        params = {
            "gencodeId": gene_id,
            "tissueSiteDetailId": tissue,
            "datasetId": "gtex_v8",
        }
        data = await async_http_get(url, params=params)

        eqtls = data.get("data", data.get("singleTissueEqtl", []))
        if not isinstance(eqtls, list):
            eqtls = []

        # Sort by p-value
        eqtls_sorted = sorted(eqtls, key=lambda x: x.get("pValue", 1.0))

        top_variants = []
        for eq in eqtls_sorted[:10]:
            snp = eq.get("snpId", eq.get("variantId", "?"))
            pval = eq.get("pValue", "N/A")
            nes = eq.get("nes", eq.get("slope", "N/A"))
            top_variants.append(f"{snp} (p={pval}, NES={nes})")

        summary = (
            f"GTEx eQTLs for {gene} in {tissue}: {len(eqtls)} significant associations. "
            f"Top variants: {'; '.join(top_variants[:5]) or 'none'}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "gene": gene,
                "gencodeId": gene_id,
                "tissue": tissue,
                "num_eqtls": len(eqtls),
                "eqtls": eqtls_sorted[:50],
            },
            source="GTEx Portal (eQTL)",
            source_id=f"{gene_id}:{tissue}",
            version="v8",
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_eqtls", exc)


# ---- 7. ENCODE: experiment search ------------------------------------------


@mcp.tool()
async def query_encode_experiments(target: str, assay: str | None = None) -> dict[str, Any]:
    """
    Search the ENCODE portal for experiments targeting a gene/protein.

    Args:
        target: Target gene or protein name (e.g. 'TP53', 'CTCF').
        assay: Optional assay type filter (e.g. 'ChIP-seq', 'RNA-seq', 'ATAC-seq').
    """
    try:
        url = f"{ENCODE_API}/search/"
        params: dict[str, Any] = {
            "type": "Experiment",
            "target.label": target,
            "status": "released",
            "limit": 25,
            "format": "json",
        }
        if assay:
            params["assay_title"] = assay

        headers = {"Accept": "application/json"}
        data = await async_http_get(url, params=params, headers=headers)

        graph = data.get("@graph", [])
        total = data.get("total", len(graph))

        experiments = []
        assay_counts: dict[str, int] = {}
        for exp in graph:
            assay_title = exp.get("assay_title", "unknown")
            assay_counts[assay_title] = assay_counts.get(assay_title, 0) + 1
            experiments.append({
                "accession": exp.get("accession", ""),
                "assay_title": assay_title,
                "biosample_summary": exp.get("biosample_summary", ""),
                "target": exp.get("target", {}).get("label", target) if isinstance(exp.get("target"), dict) else target,
                "lab": exp.get("lab", {}).get("title", "") if isinstance(exp.get("lab"), dict) else "",
                "date_released": exp.get("date_released", ""),
                "status": exp.get("status", ""),
                "files_count": len(exp.get("files", [])),
            })

        assay_str = ", ".join(f"{k}: {v}" for k, v in sorted(assay_counts.items(), key=lambda x: -x[1]))
        filter_str = f" (assay={assay})" if assay else ""

        summary = (
            f"ENCODE: {total} experiments for {target}{filter_str}. "
            f"Assay breakdown: {assay_str or 'N/A'}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "target": target,
                "assay_filter": assay,
                "total": total,
                "assay_counts": assay_counts,
                "experiments": experiments,
            },
            source="ENCODE Project",
            source_id=target,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("query_encode_experiments", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
