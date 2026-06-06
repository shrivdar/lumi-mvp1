"""
cBioPortal Cancer Genomics MCP Server — Lumi Virtual Lab

Exposes tools for querying cBioPortal cancer genomics data:
  mutations, copy number alterations, expression, survival, study search,
  and cross-cancer gene mutation frequency.

Start with:  python -m src.mcp_servers.cbioportal.server
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

CBIOPORTAL_API = "https://www.cbioportal.org/api"

# Pan-cancer studies commonly used for cross-study queries
PAN_CANCER_STUDIES = [
    "msk_impact_2017",
    "tcga_pan_can_atlas_2018",
    "coadread_tcga_pan_can_atlas_2018",
    "brca_tcga_pan_can_atlas_2018",
    "luad_tcga_pan_can_atlas_2018",
    "prad_tcga_pan_can_atlas_2018",
    "ov_tcga_pan_can_atlas_2018",
]

HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi cBioPortal",
    instructions="Cancer genomics queries via cBioPortal: mutations, copy number, expression, survival, study search, gene summaries.",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_molecular_profiles(study_id: str, molecular_type: str) -> list[dict[str, Any]]:
    """Fetch molecular profiles for a study, filtered by type (e.g. MUTATION_EXTENDED, DISCRETE_COPY_NUMBER, MRNA_EXPRESSION)."""
    url = f"{CBIOPORTAL_API}/studies/{study_id}/molecular-profiles"
    profiles = await async_http_get(url, headers=HEADERS)
    if isinstance(profiles, list):
        return [p for p in profiles if p.get("molecularAlterationType") == molecular_type]
    return []


async def _get_sample_list_id(study_id: str, suffix: str = "_all") -> str:
    """Return the sample list ID for a study (e.g. study_id_all)."""
    return f"{study_id}{suffix}"


async def _resolve_entrez_gene_id(gene: str) -> int | None:
    """Resolve a gene symbol to an Entrez gene ID via cBioPortal's gene endpoint."""
    try:
        url = f"{CBIOPORTAL_API}/genes/{gene}"
        data = await async_http_get(url, headers=HEADERS)
        return data.get("entrezGeneId")
    except Exception:
        return None


# ---- 1. Mutations -----------------------------------------------------------


@mcp.tool()
async def query_cbioportal_mutations(gene: str, study_id: str | None = None) -> dict[str, Any]:
    """
    Query cancer mutations for a gene from cBioPortal.

    Searches for somatic mutations in the specified study, or across pan-cancer
    studies if no study is provided.

    Args:
        gene: Gene symbol (e.g. TP53, KRAS, BRAF).
        study_id: Optional cBioPortal study ID (e.g. brca_tcga_pan_can_atlas_2018).
                  If omitted, searches across multiple pan-cancer studies.
    """
    try:
        entrez_id = await _resolve_entrez_gene_id(gene)
        if not entrez_id:
            return handle_error("query_cbioportal_mutations", f"Could not resolve gene symbol '{gene}' to Entrez ID.")

        studies_to_query = [study_id] if study_id else PAN_CANCER_STUDIES
        all_mutations: list[dict[str, Any]] = []
        study_mutation_counts: dict[str, int] = {}

        for sid in studies_to_query:
            try:
                profiles = await _get_molecular_profiles(sid, "MUTATION_EXTENDED")
                if not profiles:
                    continue
                profile_id = profiles[0]["molecularProfileId"]
                sample_list_id = await _get_sample_list_id(sid)

                url = f"{CBIOPORTAL_API}/molecular-profiles/{profile_id}/mutations"
                params = {
                    "sampleListId": sample_list_id,
                    "entrezGeneId": entrez_id,
                }
                mutations = await async_http_get(url, params=params, headers=HEADERS)
                if isinstance(mutations, list):
                    all_mutations.extend(mutations)
                    study_mutation_counts[sid] = len(mutations)
            except Exception:
                continue  # skip failed studies

        # Summarise mutation types
        mutation_types: dict[str, int] = {}
        for m in all_mutations:
            mt = m.get("mutationType", "unknown")
            mutation_types[mt] = mutation_types.get(mt, 0) + 1

        type_str = ", ".join(f"{k}: {v}" for k, v in sorted(mutation_types.items(), key=lambda x: -x[1])[:5])
        scope = study_id if study_id else f"{len(study_mutation_counts)} pan-cancer studies"

        summary = (
            f"Found {len(all_mutations)} mutations in {gene} across {scope}. "
            f"Mutation types: {type_str or 'none'}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "gene": gene,
                "entrez_gene_id": entrez_id,
                "total_mutations": len(all_mutations),
                "study_counts": study_mutation_counts,
                "mutation_types": mutation_types,
                "mutations_sample": all_mutations[:50],
            },
            source="cBioPortal",
            source_id=gene,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("query_cbioportal_mutations", exc)


# ---- 2. Copy Number Alterations ---------------------------------------------


@mcp.tool()
async def get_cbioportal_copy_number(gene: str, study_id: str | None = None) -> dict[str, Any]:
    """
    Get copy number alterations for a gene across cancer studies from cBioPortal.

    Args:
        gene: Gene symbol (e.g. ERBB2, MYC, CDKN2A).
        study_id: Optional cBioPortal study ID. If omitted, queries pan-cancer studies.
    """
    try:
        entrez_id = await _resolve_entrez_gene_id(gene)
        if not entrez_id:
            return handle_error("get_cbioportal_copy_number", f"Could not resolve gene symbol '{gene}' to Entrez ID.")

        studies_to_query = [study_id] if study_id else PAN_CANCER_STUDIES
        all_cna: list[dict[str, Any]] = []
        study_cna_counts: dict[str, int] = {}

        for sid in studies_to_query:
            try:
                profiles = await _get_molecular_profiles(sid, "DISCRETE_COPY_NUMBER")
                if not profiles:
                    continue
                profile_id = profiles[0]["molecularProfileId"]
                sample_list_id = await _get_sample_list_id(sid)

                url = f"{CBIOPORTAL_API}/molecular-profiles/{profile_id}/discrete-copy-number"
                params = {
                    "sampleListId": sample_list_id,
                    "entrezGeneId": entrez_id,
                }
                cna_data = await async_http_get(url, params=params, headers=HEADERS)
                if isinstance(cna_data, list):
                    all_cna.extend(cna_data)
                    study_cna_counts[sid] = len(cna_data)
            except Exception:
                continue

        # Map alteration values: -2=homdel, -1=hetloss, 0=neutral, 1=gain, 2=amp
        alteration_labels = {-2: "homozygous_deletion", -1: "heterozygous_loss", 0: "neutral", 1: "gain", 2: "amplification"}
        alteration_counts: dict[str, int] = {}
        for entry in all_cna:
            alt_val = entry.get("alteration", 0)
            label = alteration_labels.get(alt_val, f"other({alt_val})")
            alteration_counts[label] = alteration_counts.get(label, 0) + 1

        alt_str = ", ".join(f"{k}: {v}" for k, v in sorted(alteration_counts.items(), key=lambda x: -x[1]))
        scope = study_id if study_id else f"{len(study_cna_counts)} pan-cancer studies"

        summary = (
            f"Found {len(all_cna)} copy number alterations in {gene} across {scope}. "
            f"Breakdown: {alt_str or 'none'}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "gene": gene,
                "entrez_gene_id": entrez_id,
                "total_cna_events": len(all_cna),
                "study_counts": study_cna_counts,
                "alteration_counts": alteration_counts,
                "cna_sample": all_cna[:50],
            },
            source="cBioPortal",
            source_id=gene,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_cbioportal_copy_number", exc)


# ---- 3. mRNA Expression -----------------------------------------------------


@mcp.tool()
async def get_cbioportal_expression(gene: str, study_id: str | None = None) -> dict[str, Any]:
    """
    Get mRNA expression data for a gene from cBioPortal.

    Args:
        gene: Gene symbol (e.g. EGFR, TP53).
        study_id: Optional cBioPortal study ID. If omitted, queries pan-cancer studies.
    """
    try:
        entrez_id = await _resolve_entrez_gene_id(gene)
        if not entrez_id:
            return handle_error("get_cbioportal_expression", f"Could not resolve gene symbol '{gene}' to Entrez ID.")

        studies_to_query = [study_id] if study_id else PAN_CANCER_STUDIES
        all_expression: list[dict[str, Any]] = []
        study_expr_counts: dict[str, int] = {}

        for sid in studies_to_query:
            try:
                profiles = await _get_molecular_profiles(sid, "MRNA_EXPRESSION")
                if not profiles:
                    continue
                profile_id = profiles[0]["molecularProfileId"]
                sample_list_id = await _get_sample_list_id(sid)

                url = f"{CBIOPORTAL_API}/molecular-profiles/{profile_id}/molecular-data"
                params = {
                    "sampleListId": sample_list_id,
                    "entrezGeneId": entrez_id,
                }
                expr_data = await async_http_get(url, params=params, headers=HEADERS)
                if isinstance(expr_data, list):
                    all_expression.extend(expr_data)
                    study_expr_counts[sid] = len(expr_data)
            except Exception:
                continue

        # Compute basic statistics
        values = [e.get("value") for e in all_expression if e.get("value") is not None]
        stats: dict[str, Any] = {}
        if values:
            stats = {
                "n_samples": len(values),
                "min": round(min(values), 3),
                "max": round(max(values), 3),
                "mean": round(sum(values) / len(values), 3),
                "median": round(sorted(values)[len(values) // 2], 3),
            }

        scope = study_id if study_id else f"{len(study_expr_counts)} pan-cancer studies"
        stats_str = f"mean={stats.get('mean', 'N/A')}, median={stats.get('median', 'N/A')}, range=[{stats.get('min', 'N/A')}, {stats.get('max', 'N/A')}]" if stats else "no data"

        summary = (
            f"Expression data for {gene} across {scope}: "
            f"{len(values)} samples. Stats: {stats_str}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "gene": gene,
                "entrez_gene_id": entrez_id,
                "total_samples": len(values),
                "study_counts": study_expr_counts,
                "statistics": stats,
                "expression_sample": all_expression[:50],
            },
            source="cBioPortal",
            source_id=gene,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_cbioportal_expression", exc)


# ---- 4. Survival / Clinical Data --------------------------------------------


@mcp.tool()
async def get_cbioportal_survival(study_id: str) -> dict[str, Any]:
    """
    Get survival and clinical data for a cBioPortal study.

    Retrieves clinical attributes including overall survival, disease-free survival,
    and key clinical features.

    Args:
        study_id: cBioPortal study ID (e.g. brca_tcga_pan_can_atlas_2018).
    """
    try:
        url = f"{CBIOPORTAL_API}/studies/{study_id}/clinical-data"
        params = {
            "clinicalDataType": "PATIENT",
            "projection": "DETAILED",
        }
        data = await async_http_get(url, params=params, headers=HEADERS)

        if not isinstance(data, list):
            return standard_response(
                summary=f"No clinical data found for study {study_id}.",
                raw_data={"study_id": study_id},
                source="cBioPortal",
                source_id=study_id,
                confidence=0.5,
            )

        # Aggregate clinical attributes
        attribute_counts: dict[str, int] = {}
        survival_data: list[dict[str, Any]] = []
        patient_ids: set[str] = set()

        for entry in data:
            attr_id = entry.get("clinicalAttributeId", "unknown")
            attribute_counts[attr_id] = attribute_counts.get(attr_id, 0) + 1
            patient_ids.add(entry.get("patientId", ""))

            # Collect survival-related attributes
            if attr_id in ("OS_STATUS", "OS_MONTHS", "DFS_STATUS", "DFS_MONTHS", "PFS_STATUS", "PFS_MONTHS"):
                survival_data.append(entry)

        # Summarise survival attributes
        survival_attrs = [a for a in attribute_counts if "OS_" in a or "DFS_" in a or "PFS_" in a or "SURVIVAL" in a.upper()]
        top_attrs = sorted(attribute_counts.items(), key=lambda x: -x[1])[:10]
        attr_str = ", ".join(f"{k}: {v}" for k, v in top_attrs)

        summary = (
            f"Clinical data for study {study_id}: {len(patient_ids)} patients, "
            f"{len(attribute_counts)} clinical attributes. "
            f"Survival attributes: {', '.join(survival_attrs) or 'none found'}. "
            f"Top attributes: {attr_str}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "study_id": study_id,
                "total_records": len(data),
                "n_patients": len(patient_ids),
                "attribute_counts": attribute_counts,
                "survival_attributes": survival_attrs,
                "survival_data_sample": survival_data[:100],
                "clinical_data_sample": data[:50],
            },
            source="cBioPortal",
            source_id=study_id,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_cbioportal_survival", exc)


# ---- 5. Study Search --------------------------------------------------------


@mcp.tool()
async def search_cbioportal_studies(keyword: str) -> dict[str, Any]:
    """
    Search cBioPortal for cancer studies matching a keyword.

    Args:
        keyword: Search term (e.g. 'breast cancer', 'glioblastoma', 'TCGA').
    """
    try:
        url = f"{CBIOPORTAL_API}/studies"
        params = {"keyword": keyword, "projection": "DETAILED"}
        data = await async_http_get(url, params=params, headers=HEADERS)

        if not isinstance(data, list):
            return standard_response(
                summary=f"No studies found matching '{keyword}'.",
                raw_data={"keyword": keyword},
                source="cBioPortal",
                source_id=keyword,
                confidence=0.5,
            )

        # Filter by keyword presence in name or description
        keyword_lower = keyword.lower()
        matching = [
            s for s in data
            if keyword_lower in s.get("name", "").lower()
            or keyword_lower in s.get("description", "").lower()
            or keyword_lower in s.get("studyId", "").lower()
        ]

        studies_out = []
        for s in matching[:25]:
            studies_out.append({
                "study_id": s.get("studyId", ""),
                "name": s.get("name", ""),
                "description": s.get("description", ""),
                "cancer_type": s.get("cancerType", {}).get("name", "") if isinstance(s.get("cancerType"), dict) else "",
                "sample_count": s.get("allSampleCount", 0),
                "reference": s.get("pmid", ""),
            })

        summary = (
            f"Found {len(matching)} cBioPortal studies matching '{keyword}'. "
            f"Top results: {', '.join(s['name'] for s in studies_out[:5])}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "keyword": keyword,
                "total_matches": len(matching),
                "studies": studies_out,
            },
            source="cBioPortal",
            source_id=keyword,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("search_cbioportal_studies", exc)


# ---- 6. Gene Mutation Frequency Summary --------------------------------------


@mcp.tool()
async def get_cbioportal_gene_summary(gene: str) -> dict[str, Any]:
    """
    Get mutation frequency for a gene across all major cancer types in cBioPortal.

    Queries multiple pan-cancer studies to build a cross-cancer mutation profile.

    Args:
        gene: Gene symbol (e.g. TP53, KRAS, PIK3CA).
    """
    try:
        entrez_id = await _resolve_entrez_gene_id(gene)
        if not entrez_id:
            return handle_error("get_cbioportal_gene_summary", f"Could not resolve gene symbol '{gene}' to Entrez ID.")

        # First, get a broad list of studies to query
        url = f"{CBIOPORTAL_API}/studies"
        params = {"projection": "SUMMARY"}
        all_studies = await async_http_get(url, params=params, headers=HEADERS)

        if not isinstance(all_studies, list):
            all_studies = []

        # Pick TCGA studies for a representative cross-cancer view
        tcga_studies = [s for s in all_studies if "tcga" in s.get("studyId", "").lower() and s.get("allSampleCount", 0) > 50]
        tcga_studies = sorted(tcga_studies, key=lambda s: s.get("allSampleCount", 0), reverse=True)[:20]

        study_frequencies: list[dict[str, Any]] = []

        for study in tcga_studies:
            sid = study["studyId"]
            try:
                profiles = await _get_molecular_profiles(sid, "MUTATION_EXTENDED")
                if not profiles:
                    continue
                profile_id = profiles[0]["molecularProfileId"]
                sample_list_id = await _get_sample_list_id(sid)

                mut_url = f"{CBIOPORTAL_API}/molecular-profiles/{profile_id}/mutations"
                mut_params = {
                    "sampleListId": sample_list_id,
                    "entrezGeneId": entrez_id,
                }
                mutations = await async_http_get(mut_url, params=mut_params, headers=HEADERS)

                n_mutated = len(mutations) if isinstance(mutations, list) else 0
                n_samples = study.get("allSampleCount", 0)
                frequency = round(n_mutated / n_samples, 4) if n_samples > 0 else 0.0

                study_frequencies.append({
                    "study_id": sid,
                    "study_name": study.get("name", sid),
                    "cancer_type": study.get("cancerType", {}).get("name", "") if isinstance(study.get("cancerType"), dict) else "",
                    "n_mutated_samples": n_mutated,
                    "total_samples": n_samples,
                    "mutation_frequency": frequency,
                })
            except Exception:
                continue

        # Sort by mutation frequency
        study_frequencies.sort(key=lambda x: x["mutation_frequency"], reverse=True)

        top_cancers = ", ".join(
            f"{s['cancer_type'] or s['study_id']} ({s['mutation_frequency']:.1%})"
            for s in study_frequencies[:5]
        )

        total_mutated = sum(s["n_mutated_samples"] for s in study_frequencies)
        total_samples = sum(s["total_samples"] for s in study_frequencies)
        overall_freq = round(total_mutated / total_samples, 4) if total_samples > 0 else 0.0

        summary = (
            f"{gene} mutation frequency across {len(study_frequencies)} cancer studies: "
            f"overall {overall_freq:.1%} ({total_mutated}/{total_samples} samples). "
            f"Highest in: {top_cancers or 'N/A'}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "gene": gene,
                "entrez_gene_id": entrez_id,
                "overall_frequency": overall_freq,
                "total_mutated": total_mutated,
                "total_samples": total_samples,
                "studies_queried": len(study_frequencies),
                "study_frequencies": study_frequencies,
            },
            source="cBioPortal",
            source_id=gene,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_cbioportal_gene_summary", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
