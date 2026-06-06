"""
Genomics MCP Server — Lumi Virtual Lab

Exposes tools for querying genomic databases:
  Open Targets, GWAS Catalog, gnomAD, ClinVar, Ensembl, dbSNP, PharmGKB.

Start with:  python -m src.mcp_servers.genomics.server
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

# Relative import when running inside the package; fall back for direct exec.
try:
    from src.mcp_servers.base import async_http_get, async_http_post, handle_error, standard_response
except ImportError:
    from mcp_servers.base import async_http_get, async_http_post, handle_error, standard_response  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPEN_TARGETS_GRAPHQL = "https://api.platform.opentargets.org/api/v4/graphql"
GWAS_CATALOG_API = "https://www.ebi.ac.uk/gwas/rest/api"
ENSEMBL_REST = "https://rest.ensembl.org"
NCBI_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
GNOMAD_GRAPHQL = "https://gnomad.broadinstitute.org/api"
PHARMGKB_API = "https://api.pharmgkb.org/v1/data"

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi Genomics",
    instructions="Genomic database queries: Open Targets, GWAS Catalog, gnomAD, ClinVar, Ensembl, dbSNP, PharmGKB",
)


# ---- 1. Open Targets: target–disease associations -------------------------


@mcp.tool()
async def query_target_disease(target_gene: str, disease_efo_id: str | None = None) -> dict[str, Any]:
    """
    Query Open Targets for target–disease associations.

    Args:
        target_gene: Ensembl gene ID (e.g. ENSG00000141510) or gene symbol.
        disease_efo_id: Optional EFO disease ID to narrow results (e.g. EFO_0000311).
    """
    try:
        # If a symbol was passed, resolve via Ensembl first
        ensembl_id = target_gene
        if not target_gene.startswith("ENSG"):
            info = await _resolve_gene_symbol(target_gene)
            if info:
                ensembl_id = info

        query = """
        query TargetDiseaseAssoc($ensemblId: String!, $size: Int!) {
          target(ensemblId: $ensemblId) {
            id
            approvedSymbol
            approvedName
            associatedDiseases(page: {size: $size, index: 0}) {
              count
              rows {
                disease { id name }
                score
                datasourceScores { componentId score }
              }
            }
          }
        }
        """
        variables: dict[str, Any] = {"ensemblId": ensembl_id, "size": 25}
        if disease_efo_id:
            # Use the disease-specific association query instead
            query = """
            query TargetDiseaseDetail($ensemblId: String!, $efoId: String!) {
              disease(efoId: $efoId) {
                id name
                associatedTargets(page: {size: 5, index: 0}) {
                  rows {
                    target { id approvedSymbol }
                    score
                    datasourceScores { componentId score }
                  }
                }
              }
              target(ensemblId: $ensemblId) {
                id approvedSymbol approvedName
              }
            }
            """
            variables = {"ensemblId": ensembl_id, "efoId": disease_efo_id}

        payload = {"query": query, "variables": variables}
        headers = {"Content-Type": "application/json"}
        data = await async_http_post(OPEN_TARGETS_GRAPHQL, data=payload, headers=headers)

        target_data = data.get("data", {})
        summary_parts = []
        if "target" in target_data and target_data["target"]:
            t = target_data["target"]
            summary_parts.append(f"Target: {t.get('approvedSymbol', ensembl_id)} ({t.get('approvedName', 'N/A')})")
        if "disease" in target_data and target_data["disease"]:
            d = target_data["disease"]
            summary_parts.append(f"Disease: {d.get('name', disease_efo_id)}")

        assoc = target_data.get("target", {}).get("associatedDiseases", {})
        if assoc:
            summary_parts.append(f"{assoc.get('count', 0)} associated diseases found")

        summary = "; ".join(summary_parts) if summary_parts else "No associations found."
        return standard_response(
            summary=summary,
            raw_data=target_data,
            source="Open Targets Platform",
            source_id=ensembl_id,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("query_target_disease", exc)


# ---- 2. Open Targets: target profile --------------------------------------


@mcp.tool()
async def get_target_info(ensembl_gene_id: str) -> dict[str, Any]:
    """
    Retrieve the Open Targets target profile for a given Ensembl gene ID.

    Args:
        ensembl_gene_id: Ensembl gene ID (e.g. ENSG00000141510).
    """
    try:
        query = """
        query TargetProfile($ensemblId: String!) {
          target(ensemblId: $ensemblId) {
            id
            approvedSymbol
            approvedName
            biotype
            functionDescriptions
            subcellularLocations
            tractability {
              label
              modality
              value
            }
            safetyLiabilities {
              event
              effects {
                direction
                dosing
              }
            }
            knownDrugs {
              uniqueDrugs
              uniqueTargets
              count
              rows {
                drug {
                  name
                  mechanismsOfAction {
                    rows {
                      mechanismOfAction
                    }
                  }
                }
                phase
                status
              }
            }
          }
        }
        """
        payload = {"query": query, "variables": {"ensemblId": ensembl_gene_id}}
        headers = {"Content-Type": "application/json"}
        data = await async_http_post(OPEN_TARGETS_GRAPHQL, data=payload, headers=headers)

        target = data.get("data", {}).get("target", {})
        symbol = target.get("approvedSymbol", ensembl_gene_id)
        name = target.get("approvedName", "")
        biotype = target.get("biotype", "unknown")
        drugs_count = target.get("knownDrugs", {}).get("uniqueDrugs", 0)

        summary = (
            f"{symbol} ({name}): biotype={biotype}, "
            f"{drugs_count} known drugs, "
            f"{len(target.get('tractability', []))} tractability assessments"
        )

        return standard_response(
            summary=summary,
            raw_data=target,
            source="Open Targets Platform",
            source_id=ensembl_gene_id,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("get_target_info", exc)


# ---- 3. GWAS Catalog: associations ----------------------------------------


@mcp.tool()
async def query_gwas_associations(gene: str) -> dict[str, Any]:
    """
    Query the GWAS Catalog REST API for associations linked to a gene.

    Args:
        gene: Gene symbol (e.g. TP53, BRCA1).
    """
    try:
        # Query studies associated with the gene via the GWAS Catalog REST API
        url = f"{GWAS_CATALOG_API}/singleNucleotidePolymorphisms/search/findByGene"
        params = {"geneName": gene}
        headers = {"Accept": "application/json"}
        data = await async_http_get(url, params=params, headers=headers)

        snps = data.get("_embedded", {}).get("singleNucleotidePolymorphisms", [])

        # Extract associations from the SNP records
        associations = []
        for snp in snps:
            rsid = snp.get("rsId", "N/A")
            for study in snp.get("studies", []):
                trait = study.get("diseaseTrait", {}).get("trait", "unknown trait") if study.get("diseaseTrait") else "unknown trait"
                associations.append({
                    "rsId": rsid,
                    "trait": trait,
                    "study_accession": study.get("accessionId", "N/A"),
                })

        summaries = []
        seen_traits = set()
        for assoc in associations[:20]:
            trait = assoc.get("trait", "unknown trait")
            if trait not in seen_traits:
                seen_traits.add(trait)
                summaries.append(f"{trait} ({assoc.get('rsId', 'N/A')})")
            if len(summaries) >= 5:
                break

        summary = (
            f"{len(snps)} SNPs with {len(associations)} GWAS associations for {gene}. "
            f"Top traits: {'; '.join(summaries[:5])}"
            if snps
            else f"No GWAS associations found for {gene}."
        )

        return standard_response(
            summary=summary,
            raw_data={"snps": snps, "associations": associations},
            source="NHGRI-EBI GWAS Catalog",
            source_id=gene,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("query_gwas_associations", exc)


# ---- 4. gnomAD: gene constraint metrics ------------------------------------


@mcp.tool()
async def query_gene_variants(gene: str) -> dict[str, Any]:
    """
    Query gnomAD GraphQL API for gene constraint metrics (pLI, LOEUF, missense Z).

    Args:
        gene: Gene symbol (e.g. BRCA1).
    """
    try:
        query = """
        query GeneConstraint($geneSymbol: String!) {
          gene(gene_symbol: $geneSymbol, reference_genome: GRCh38) {
            gene_id
            symbol
            name
            gnomad_constraint {
              pLI
              oe_lof
              oe_lof_upper
              oe_mis
              oe_mis_upper
              mis_z
              syn_z
            }
          }
        }
        """
        payload = {"query": query, "variables": {"geneSymbol": gene}}
        headers = {"Content-Type": "application/json"}
        data = await async_http_post(GNOMAD_GRAPHQL, data=payload, headers=headers)

        gene_data = data.get("data", {}).get("gene", {})
        constraint = gene_data.get("gnomad_constraint", {}) or {}

        pli = constraint.get("pLI", "N/A")
        loeuf = constraint.get("oe_lof_upper", "N/A")
        mis_z = constraint.get("mis_z", "N/A")

        summary = (
            f"{gene}: pLI={pli}, LOEUF={loeuf}, missense Z={mis_z}. "
            f"{'Loss-of-function intolerant' if isinstance(pli, (int, float)) and pli > 0.9 else 'Tolerant or unknown'}."
        )

        return standard_response(
            summary=summary,
            raw_data=gene_data,
            source="gnomAD",
            source_id=gene,
            version="v4",
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("query_gene_variants", exc)


# ---- 5. ClinVar: pathogenic/benign variants --------------------------------


@mcp.tool()
async def query_clinvar_gene(gene: str) -> dict[str, Any]:
    """
    Query NCBI E-utilities for ClinVar variants associated with a gene.

    Returns counts of pathogenic, likely pathogenic, benign, and VUS variants.

    Args:
        gene: Gene symbol (e.g. BRCA1).
    """
    try:
        # Step 1: esearch to get IDs
        search_url = f"{NCBI_EUTILS}/esearch.fcgi"
        search_params = {
            "db": "clinvar",
            "term": f"{gene}[gene] AND single_gene[prop]",
            "retmax": 500,
            "retmode": "json",
        }
        search_data = await async_http_get(search_url, params=search_params)

        id_list = search_data.get("esearchresult", {}).get("idlist", [])
        total_count = int(search_data.get("esearchresult", {}).get("count", 0))

        if not id_list:
            return standard_response(
                summary=f"No ClinVar entries found for gene {gene}.",
                raw_data={"count": 0, "variants": []},
                source="ClinVar (NCBI)",
                source_id=gene,
                confidence=0.7,
            )

        # Step 2: esummary for variant details
        ids_str = ",".join(id_list[:100])  # limit to first 100
        summary_url = f"{NCBI_EUTILS}/esummary.fcgi"
        summary_params = {
            "db": "clinvar",
            "id": ids_str,
            "retmode": "json",
        }
        summary_data = await async_http_get(summary_url, params=summary_params)

        result = summary_data.get("result", {})
        uid_list = result.get("uids", [])

        categories: dict[str, int] = {}
        variants_out = []
        for uid in uid_list:
            entry = result.get(uid, {})
            clin_sig = entry.get("clinical_significance", {}).get("description", "unknown")
            categories[clin_sig] = categories.get(clin_sig, 0) + 1
            variants_out.append({
                "uid": uid,
                "title": entry.get("title", ""),
                "clinical_significance": clin_sig,
                "variant_type": entry.get("variant_type", ""),
            })

        cat_str = ", ".join(f"{k}: {v}" for k, v in sorted(categories.items(), key=lambda x: -x[1]))
        summary = f"ClinVar: {total_count} total entries for {gene}. Significance breakdown (sampled {len(uid_list)}): {cat_str}."

        return standard_response(
            summary=summary,
            raw_data={"total_count": total_count, "sampled": len(uid_list), "categories": categories, "variants": variants_out},
            source="ClinVar (NCBI)",
            source_id=gene,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("query_clinvar_gene", exc)


# ---- 6. Ensembl: gene metadata ---------------------------------------------


@mcp.tool()
async def get_gene_info(gene_symbol: str) -> dict[str, Any]:
    """
    Retrieve gene metadata from the Ensembl REST API.

    Args:
        gene_symbol: HGNC gene symbol (e.g. TP53).
    """
    try:
        url = f"{ENSEMBL_REST}/lookup/symbol/homo_sapiens/{gene_symbol}"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        data = await async_http_get(url, headers=headers)

        display = data.get("display_name", gene_symbol)
        description = data.get("description", "N/A")
        biotype = data.get("biotype", "N/A")
        chrom = data.get("seq_region_name", "?")
        start = data.get("start", "?")
        end = data.get("end", "?")
        strand = "+" if data.get("strand", 1) == 1 else "-"
        ensembl_id = data.get("id", "N/A")

        summary = (
            f"{display} ({ensembl_id}): {description}. "
            f"Biotype: {biotype}. Location: chr{chrom}:{start}-{end} ({strand})."
        )

        return standard_response(
            summary=summary,
            raw_data=data,
            source="Ensembl REST API",
            source_id=ensembl_id,
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("get_gene_info", exc)


# ---- 7. Ensembl VEP: variant consequences ---------------------------------


@mcp.tool()
async def get_variant_consequences(variant: str) -> dict[str, Any]:
    """
    Predict functional consequences of a variant using Ensembl VEP REST API.

    Args:
        variant: Variant in HGVS notation (e.g. 'rs699' or '9:g.22125504G>C')
                 or as 'chr:pos:ref:alt' (e.g. '7:140753336:A:T').
    """
    try:
        # Determine which VEP endpoint to use
        if variant.startswith("rs"):
            url = f"{ENSEMBL_REST}/vep/human/id/{variant}"
        elif ":g." in variant:
            url = f"{ENSEMBL_REST}/vep/human/hgvs/{variant}"
        else:
            # Assume chr:pos:ref:alt format — convert to region format
            parts = variant.split(":")
            if len(parts) == 4:
                chrom, pos, ref, alt = parts
                url = f"{ENSEMBL_REST}/vep/human/region/{chrom}:{pos}:{pos}/{alt}"
            else:
                url = f"{ENSEMBL_REST}/vep/human/id/{variant}"

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        data = await async_http_get(url, headers=headers)

        # VEP returns a list
        if isinstance(data, list) and data:
            entry = data[0]
            consequences = []
            for tc in entry.get("transcript_consequences", []):
                consequences.append({
                    "gene_symbol": tc.get("gene_symbol", ""),
                    "consequence": ",".join(tc.get("consequence_terms", [])),
                    "impact": tc.get("impact", ""),
                    "biotype": tc.get("biotype", ""),
                    "sift": tc.get("sift_prediction", ""),
                    "polyphen": tc.get("polyphen_prediction", ""),
                })
            most_severe = entry.get("most_severe_consequence", "unknown")
            summary = f"Variant {variant}: most severe consequence = {most_severe}. {len(consequences)} transcript consequences."
            raw = {"input": variant, "most_severe_consequence": most_severe, "transcript_consequences": consequences, "full": entry}
        else:
            summary = f"No VEP results for {variant}."
            raw = {"input": variant, "response": data}

        return standard_response(
            summary=summary,
            raw_data=raw,
            source="Ensembl VEP",
            source_id=variant,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("get_variant_consequences", exc)


# ---- 8. dbSNP: rsID lookup ------------------------------------------------


@mcp.tool()
async def query_rsid(rsid: str) -> dict[str, Any]:
    """
    Query NCBI E-utilities for dbSNP information on a given rsID.

    Args:
        rsid: RefSNP ID (e.g. rs699).
    """
    try:
        # Strip leading 'rs' for the numeric ID
        numeric_id = rsid.lstrip("rs")

        # esummary for SNP
        url = f"{NCBI_EUTILS}/esummary.fcgi"
        params = {
            "db": "snp",
            "id": numeric_id,
            "retmode": "json",
        }
        data = await async_http_get(url, params=params)

        result = data.get("result", {})
        snp = result.get(numeric_id, {})

        if not snp or "error" in snp:
            return standard_response(
                summary=f"No dbSNP record found for {rsid}.",
                raw_data={"rsid": rsid, "response": result},
                source="dbSNP (NCBI)",
                source_id=rsid,
                confidence=0.5,
            )

        # Extract key fields
        snp_class = snp.get("snp_class", "unknown")
        genes_list = snp.get("genes", [])
        gene_names = [g.get("name", "") for g in genes_list] if isinstance(genes_list, list) else []
        clinical = snp.get("clinical_significance", "not reported")
        maf_info = snp.get("global_mafs", [])
        maf_str = ""
        if maf_info and isinstance(maf_info, list):
            first = maf_info[0] if maf_info else {}
            maf_str = f", MAF={first.get('freq', 'N/A')} ({first.get('study', '')})"

        summary = (
            f"{rsid}: class={snp_class}, genes={','.join(gene_names) or 'N/A'}, "
            f"clinical_significance={clinical}{maf_str}."
        )

        return standard_response(
            summary=summary,
            raw_data=snp,
            source="dbSNP (NCBI)",
            source_id=rsid,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("query_rsid", exc)


# ---- 9. PharmGKB: drug–gene interactions -----------------------------------


@mcp.tool()
async def query_pharmgkb_gene(gene: str) -> dict[str, Any]:
    """
    Query PharmGKB REST API for pharmacogenomic annotations of a gene.

    Args:
        gene: Gene symbol (e.g. CYP2D6, BRCA1).
    """
    try:
        # Search for the gene
        url = f"{PHARMGKB_API}/gene"
        params = {"symbol": gene}
        headers = {"Accept": "application/json"}
        data = await async_http_get(url, params=params, headers=headers)

        # PharmGKB returns a dict with "data" list
        gene_list = data.get("data", []) if isinstance(data, dict) else data if isinstance(data, list) else []

        if not gene_list:
            return standard_response(
                summary=f"No PharmGKB entry found for {gene}.",
                raw_data={"gene": gene},
                source="PharmGKB",
                source_id=gene,
                confidence=0.5,
            )

        gene_entry = gene_list[0] if isinstance(gene_list, list) else gene_list
        pgkb_id = gene_entry.get("id", "unknown")
        name = gene_entry.get("name", gene)
        has_rx = gene_entry.get("hasRxAnnotation", False)
        has_cpic = gene_entry.get("hasCpicGuideline", False)
        gene_entry.get("crossReferences", [])

        # Fetch clinical annotations if available
        clinical_anns = []
        try:
            ca_url = f"{PHARMGKB_API}/clinicalAnnotation"
            ca_params = {"gene.symbol": gene}
            ca_data = await async_http_get(ca_url, params=ca_params, headers=headers)
            clinical_anns = ca_data.get("data", []) if isinstance(ca_data, dict) else []
        except Exception:
            pass  # non-critical

        drug_names = set()
        for ann in clinical_anns[:20]:
            for rel in ann.get("relatedChemicals", []):
                drug_names.add(rel.get("name", ""))

        summary = (
            f"PharmGKB: {name} ({pgkb_id}). "
            f"Rx annotations: {has_rx}, CPIC guideline: {has_cpic}. "
            f"Related drugs: {', '.join(sorted(drug_names)[:10]) or 'none found'}. "
            f"{len(clinical_anns)} clinical annotations."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "gene": gene_entry,
                "clinical_annotations_count": len(clinical_anns),
                "clinical_annotations_sample": clinical_anns[:10],
                "related_drugs": sorted(drug_names),
            },
            source="PharmGKB",
            source_id=pgkb_id,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("query_pharmgkb_gene", exc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_gene_symbol(symbol: str) -> str | None:
    """Resolve a gene symbol to an Ensembl gene ID via the Ensembl REST API."""
    try:
        url = f"{ENSEMBL_REST}/lookup/symbol/homo_sapiens/{symbol}"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        data = await async_http_get(url, headers=headers)
        return data.get("id")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
