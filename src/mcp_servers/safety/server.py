"""
Safety & Toxicology MCP Server -- Lumi Virtual Lab

Exposes tools for querying safety and toxicology databases:
  CTD (Comparative Toxicogenomics Database), EPA CompTox (Tox21/ToxCast),
  OpenFDA (side effects & drug labels), IMPC (knockout phenotypes).

Start with:  python -m src.mcp_servers.safety.server
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

CTD_API = "https://ctdbase.org/tools/batchQuery.go"
COMPTOX_API = "https://comptox.epa.gov/dashboard-api"
OPENFDA_API = "https://api.fda.gov"
IMPC_SOLR = "https://www.ebi.ac.uk/mi/impc/solr"

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi Safety & Toxicology",
    instructions=(
        "Safety and toxicology database queries: "
        "CTD gene-chemical-disease interactions, EPA CompTox/Tox21, "
        "OpenFDA adverse events & drug labels, IMPC knockout phenotypes"
    ),
)


# ===================================================================
# CTD tools
# ===================================================================


@mcp.tool()
async def query_gene_chemical_interactions(gene: str) -> dict[str, Any]:
    """Query CTD for chemical-gene interactions.

    Returns chemicals known to interact with the given gene, including
    interaction types (increases expression, decreases activity, etc.)
    and the organisms in which the interactions were observed.

    Args:
        gene: Gene symbol (e.g. TP53, CYP2D6, BRCA1).
    """
    try:
        params = {
            "inputType": "gene",
            "inputTerms": gene,
            "report": "cgixns",
            "format": "json",
        }
        data = await async_http_get(CTD_API, params=params, timeout=45.0)

        interactions = data if isinstance(data, list) else []

        # Deduplicate and summarize
        chemicals: dict[str, list[str]] = {}
        for ix in interactions:
            chem = ix.get("ChemicalName", "Unknown")
            action = ix.get("InteractionActions", "unknown")
            chemicals.setdefault(chem, []).append(action)

        interaction_list = []
        for chem, actions in list(chemicals.items())[:50]:
            interaction_list.append({
                "chemical": chem,
                "interaction_count": len(actions),
                "actions": list(set(actions))[:5],
            })

        interaction_list.sort(key=lambda x: x["interaction_count"], reverse=True)

        top_chems = [ix["chemical"] for ix in interaction_list[:8]]
        summary = (
            f"CTD: {len(interactions)} chemical-gene interactions for {gene} "
            f"involving {len(chemicals)} unique chemicals. "
            f"Top interactors: {', '.join(top_chems)}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "gene": gene,
                "total_interactions": len(interactions),
                "unique_chemicals": len(chemicals),
                "top_interactions": interaction_list[:20],
                "raw_sample": interactions[:10],
            },
            source="CTD",
            source_id=gene,
            confidence=0.82,
        )
    except Exception as exc:
        return handle_error("query_gene_chemical_interactions", exc)


@mcp.tool()
async def query_gene_disease_associations(gene: str) -> dict[str, Any]:
    """Query CTD for gene-disease associations.

    Returns diseases associated with the gene based on curated and inferred
    relationships from chemical-gene-disease networks.

    Args:
        gene: Gene symbol (e.g. TP53, BRCA1).
    """
    try:
        params = {
            "inputType": "gene",
            "inputTerms": gene,
            "report": "genes_diseases",
            "format": "json",
        }
        data = await async_http_get(CTD_API, params=params, timeout=45.0)

        associations = data if isinstance(data, list) else []

        # Group by disease
        diseases: dict[str, dict] = {}
        for assoc in associations:
            disease = assoc.get("DiseaseName", "Unknown")
            disease_id = assoc.get("DiseaseID", "")
            direct_evidence = assoc.get("DirectEvidence", "")
            inference_score = assoc.get("InferenceScore", 0)

            if disease not in diseases:
                diseases[disease] = {
                    "disease_name": disease,
                    "disease_id": disease_id,
                    "direct_evidence": direct_evidence,
                    "inference_score": inference_score,
                    "reference_count": int(assoc.get("ReferenceCount", 0)),
                }
            else:
                # Keep the entry with higher evidence
                existing = diseases[disease]
                if direct_evidence and not existing["direct_evidence"]:
                    diseases[disease]["direct_evidence"] = direct_evidence

        disease_list = sorted(diseases.values(), key=lambda x: (
            1 if x["direct_evidence"] else 0,
            x.get("inference_score", 0),
        ), reverse=True)

        # Separate direct and inferred
        direct = [d for d in disease_list if d["direct_evidence"]]
        inferred = [d for d in disease_list if not d["direct_evidence"]]

        top_diseases = [d["disease_name"] for d in disease_list[:8]]
        summary = (
            f"CTD: {len(diseases)} disease associations for {gene}. "
            f"{len(direct)} with direct evidence, {len(inferred)} inferred. "
            f"Top diseases: {', '.join(top_diseases)}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "gene": gene,
                "total_diseases": len(diseases),
                "direct_evidence_count": len(direct),
                "inferred_count": len(inferred),
                "diseases": disease_list[:30],
                "raw_sample": associations[:10],
            },
            source="CTD",
            source_id=gene,
            confidence=0.80,
        )
    except Exception as exc:
        return handle_error("query_gene_disease_associations", exc)


@mcp.tool()
async def query_chemical_diseases(chemical: str) -> dict[str, Any]:
    """Query CTD for diseases associated with a chemical compound.

    Args:
        chemical: Chemical name (e.g. 'Benzo(a)pyrene', 'Doxorubicin', 'Aspirin').
    """
    try:
        params = {
            "inputType": "chem",
            "inputTerms": chemical,
            "report": "diseases_curated",
            "format": "json",
        }
        data = await async_http_get(CTD_API, params=params, timeout=45.0)

        associations = data if isinstance(data, list) else []

        disease_entries = []
        for assoc in associations[:50]:
            disease_entries.append({
                "disease_name": assoc.get("DiseaseName", "Unknown"),
                "disease_id": assoc.get("DiseaseID", ""),
                "direct_evidence": assoc.get("DirectEvidence", ""),
                "inference_score": assoc.get("InferenceScore", 0),
                "reference_count": int(assoc.get("ReferenceCount", 0)),
            })

        disease_entries.sort(key=lambda x: x.get("reference_count", 0), reverse=True)

        top_diseases = [d["disease_name"] for d in disease_entries[:8]]
        summary = (
            f"CTD: {len(associations)} disease associations for chemical '{chemical}'. "
            f"Top diseases: {', '.join(top_diseases)}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "chemical": chemical,
                "total_associations": len(associations),
                "diseases": disease_entries[:30],
                "raw_sample": associations[:10],
            },
            source="CTD",
            source_id=chemical,
            confidence=0.80,
        )
    except Exception as exc:
        return handle_error("query_chemical_diseases", exc)


# ===================================================================
# EPA CompTox / Tox21 / ToxCast tools
# ===================================================================


@mcp.tool()
async def query_toxicity_assays(chemical: str) -> dict[str, Any]:
    """Query EPA CompTox Dashboard for toxicity assay data (Tox21/ToxCast).

    Searches for the chemical in the CompTox database, then retrieves
    associated bioactivity/assay results including AC50 values and hit calls.

    Args:
        chemical: Chemical name, CASRN, or DTXSID (e.g. 'Bisphenol A',
            '80-05-7', 'DTXSID7020182').
    """
    try:
        # Step 1: Search for chemical to get DTXSID
        search_url = f"{COMPTOX_API}/ccdapp1/search/chemical/start-with/{chemical}"
        headers = {"Accept": "application/json"}

        try:
            search_data = await async_http_get(search_url, headers=headers, timeout=30.0)
        except Exception:
            # Fallback: try direct DTXSID if the input looks like one
            if chemical.startswith("DTXSID"):
                search_data = [{"dtxsid": chemical}]
            else:
                # Try alternative search endpoint
                alt_url = f"{COMPTOX_API}/ccdapp1/search/chemical/equal/{chemical}"
                search_data = await async_http_get(alt_url, headers=headers, timeout=30.0)

        results = search_data if isinstance(search_data, list) else []
        if not results:
            return standard_response(
                summary=f"No CompTox entry found for '{chemical}'.",
                raw_data={"chemical": chemical, "results": []},
                source="EPA CompTox",
                source_id=chemical,
                confidence=0.3,
            )

        first_hit = results[0] if results else {}
        dtxsid = first_hit.get("dtxsid", "")
        preferred_name = first_hit.get("preferredName", chemical)
        casrn = first_hit.get("casrn", "N/A")

        # Step 2: Get bioactivity data
        assay_results = []
        if dtxsid:
            try:
                bioactivity_url = f"{COMPTOX_API}/ccdapp1/chemical/bioactivity/{dtxsid}"
                bio_data = await async_http_get(bioactivity_url, headers=headers, timeout=30.0)
                raw_assays = bio_data if isinstance(bio_data, list) else []

                for assay in raw_assays[:50]:
                    assay_results.append({
                        "assay_name": assay.get("assayName", "N/A"),
                        "assay_component_endpoint": assay.get("assayComponentEndpointName", "N/A"),
                        "hit_call": assay.get("hitCall", "N/A"),
                        "ac50": assay.get("ac50", None),
                        "top": assay.get("top", None),
                        "intended_target": assay.get("intendedTargetGeneName", "N/A"),
                        "assay_source": assay.get("assaySourceName", "N/A"),
                    })
            except Exception:
                pass  # Bioactivity data may not be available for all chemicals

        # Count active/inactive
        active = sum(1 for a in assay_results if str(a.get("hit_call", "")).lower() in ("1", "active", "true"))
        inactive = sum(1 for a in assay_results if str(a.get("hit_call", "")).lower() in ("0", "inactive", "false"))

        summary = (
            f"CompTox: {preferred_name} (CASRN: {casrn}, {dtxsid}). "
            f"{len(assay_results)} assay results retrieved. "
            f"Active: {active}, Inactive: {inactive}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "chemical": preferred_name,
                "dtxsid": dtxsid,
                "casrn": casrn,
                "total_assays": len(assay_results),
                "active_count": active,
                "inactive_count": inactive,
                "assay_results": assay_results,
            },
            source="EPA CompTox (Tox21/ToxCast)",
            source_id=dtxsid or chemical,
            confidence=0.80,
        )
    except Exception as exc:
        return handle_error("query_toxicity_assays", exc)


# ===================================================================
# OpenFDA tools (proxy for SIDER side effects & drug indications)
# ===================================================================


@mcp.tool()
async def get_side_effects(drug: str) -> dict[str, Any]:
    """Get adverse event reports for a drug from OpenFDA.

    Uses the FDA Adverse Event Reporting System (FAERS) as a proxy for
    side effect data. Returns the most frequently reported adverse reactions.

    Args:
        drug: Drug generic name or brand name (e.g. 'aspirin', 'imatinib',
            'Gleevec').
    """
    try:
        url = f"{OPENFDA_API}/drug/event.json"
        params = {
            "search": f'patient.drug.openfda.generic_name:"{drug.replace(chr(34), "")}" OR patient.drug.openfda.brand_name:"{drug.replace(chr(34), "")}"',
            "count": "patient.reaction.reactionmeddrapt.exact",
            "limit": "30",
        }
        data = await async_http_get(url, params=params, timeout=30.0)

        results = data.get("results", [])

        side_effects = []
        for r in results:
            side_effects.append({
                "reaction": r.get("term", "Unknown"),
                "count": r.get("count", 0),
            })

        # Also get total report count
        meta = data.get("meta", {})
        total_results = meta.get("results", {}).get("total", "N/A")

        top_reactions = [se["reaction"] for se in side_effects[:10]]
        summary = (
            f"OpenFDA adverse events for '{drug}': {total_results} total reports. "
            f"Top reactions: {', '.join(top_reactions)}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "drug": drug,
                "total_reports": total_results,
                "side_effect_count": len(side_effects),
                "side_effects": side_effects,
            },
            source="OpenFDA FAERS",
            source_id=drug,
            confidence=0.75,
        )
    except Exception as exc:
        return handle_error("get_side_effects", exc)


@mcp.tool()
async def get_drug_indications(drug: str) -> dict[str, Any]:
    """Get approved indications and boxed warnings for a drug from OpenFDA drug labels.

    Args:
        drug: Drug generic name or brand name (e.g. 'imatinib', 'Gleevec').
    """
    try:
        url = f"{OPENFDA_API}/drug/label.json"
        params = {
            "search": f'openfda.generic_name:"{drug.replace(chr(34), "")}" OR openfda.brand_name:"{drug.replace(chr(34), "")}"',
            "limit": "3",
        }
        data = await async_http_get(url, params=params, timeout=30.0)

        results = data.get("results", [])
        if not results:
            return standard_response(
                summary=f"No FDA drug label found for '{drug}'.",
                raw_data={"drug": drug, "results": []},
                source="OpenFDA Drug Labels",
                source_id=drug,
                confidence=0.3,
            )

        label = results[0]

        # Extract key label sections
        indications = label.get("indications_and_usage", ["N/A"])
        boxed_warning = label.get("boxed_warning", ["N/A"])
        warnings = label.get("warnings", ["N/A"])
        contraindications = label.get("contraindications", ["N/A"])
        adverse_reactions = label.get("adverse_reactions", ["N/A"])
        drug_interactions = label.get("drug_interactions", ["N/A"])

        # OpenFDA info
        openfda = label.get("openfda", {})
        generic_name = openfda.get("generic_name", ["N/A"])
        brand_name = openfda.get("brand_name", ["N/A"])
        manufacturer = openfda.get("manufacturer_name", ["N/A"])
        route = openfda.get("route", ["N/A"])
        pharm_class = openfda.get("pharm_class_epc", [])

        # Truncate long text fields for the summary
        indication_text = indications[0] if isinstance(indications, list) and indications else str(indications)
        indication_preview = indication_text[:300] + "..." if len(indication_text) > 300 else indication_text

        has_boxed = boxed_warning != ["N/A"] and boxed_warning

        summary = (
            f"FDA Label for {generic_name[0] if isinstance(generic_name, list) else generic_name} "
            f"({brand_name[0] if isinstance(brand_name, list) else brand_name}): "
            f"{'BOXED WARNING present. ' if has_boxed else ''}"
            f"Indication: {indication_preview}"
        )

        return standard_response(
            summary=summary,
            raw_data={
                "drug": drug,
                "generic_name": generic_name,
                "brand_name": brand_name,
                "manufacturer": manufacturer,
                "route": route,
                "pharm_class": pharm_class,
                "indications": indications,
                "boxed_warning": boxed_warning,
                "warnings": warnings,
                "contraindications": contraindications,
                "adverse_reactions_text": adverse_reactions,
                "drug_interactions_text": drug_interactions,
            },
            source="OpenFDA Drug Labels",
            source_id=drug,
            confidence=0.88,
        )
    except Exception as exc:
        return handle_error("get_drug_indications", exc)


# ===================================================================
# IMPC (International Mouse Phenotyping Consortium) tools
# ===================================================================


@mcp.tool()
async def get_knockout_phenotypes(gene: str) -> dict[str, Any]:
    """Query IMPC for phenotypes observed in mouse gene knockouts.

    Returns significant phenotype associations from the International Mouse
    Phenotyping Consortium, useful for understanding gene function and
    predicting potential on-target safety liabilities.

    Args:
        gene: Gene symbol (e.g. TP53, BRCA1). Human gene symbols are
            automatically mapped to mouse orthologs.
    """
    try:
        # IMPC uses mouse gene symbols (typically same as human but lowercase first letter)
        # Try the human symbol directly first, as IMPC often maps them
        url = f"{IMPC_SOLR}/genotype-phenotype/select"
        params = {
            "q": f"marker_symbol:{gene}",
            "rows": "50",
            "wt": "json",
        }
        data = await async_http_get(url, params=params, timeout=30.0)

        response = data.get("response", {})
        num_found = response.get("numFound", 0)
        docs = response.get("docs", [])

        if num_found == 0:
            # Try with capitalized mouse convention (e.g., Tp53 for TP53)
            mouse_symbol = gene[0].upper() + gene[1:].lower() if len(gene) > 1 else gene
            params["q"] = f"marker_symbol:{mouse_symbol}"
            data = await async_http_get(url, params=params, timeout=30.0)
            response = data.get("response", {})
            num_found = response.get("numFound", 0)
            docs = response.get("docs", [])

        phenotypes = []
        phenotype_systems: dict[str, int] = {}
        for doc in docs:
            mp_term = doc.get("mp_term_name", "N/A")
            mp_id = doc.get("mp_term_id", "N/A")
            p_value = doc.get("p_value", None)
            effect_size = doc.get("effect_size", None)
            zygosity = doc.get("zygosity", "N/A")
            top_level = doc.get("top_level_mp_term_name", [])

            phenotypes.append({
                "mp_term": mp_term,
                "mp_id": mp_id,
                "p_value": p_value,
                "effect_size": effect_size,
                "zygosity": zygosity,
                "top_level_system": top_level[0] if top_level else "N/A",
            })

            for system in top_level:
                phenotype_systems[system] = phenotype_systems.get(system, 0) + 1

        # Sort by p-value
        phenotypes.sort(key=lambda x: x.get("p_value", 1.0) or 1.0)

        top_phenotypes = [p["mp_term"] for p in phenotypes[:8]]
        top_systems = sorted(phenotype_systems.items(), key=lambda x: -x[1])[:5]
        systems_str = ", ".join(f"{s[0]} ({s[1]})" for s in top_systems)

        summary = (
            f"IMPC knockout phenotypes for {gene}: {num_found} phenotype associations. "
            f"Top affected systems: {systems_str}. "
            f"Top phenotypes: {', '.join(top_phenotypes)}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "gene": gene,
                "total_phenotypes": num_found,
                "phenotype_systems": phenotype_systems,
                "phenotypes": phenotypes[:30],
            },
            source="IMPC",
            source_id=gene,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_knockout_phenotypes", exc)


# ===================================================================
# Combined safety assessment
# ===================================================================


@mcp.tool()
async def get_safety_summary(gene_or_drug: str) -> dict[str, Any]:
    """Generate a combined safety summary for a gene or drug target.

    Aggregates data from CTD (gene-chemical-disease interactions),
    IMPC (knockout phenotypes), and OpenFDA (adverse events) to provide
    a holistic safety assessment.

    Args:
        gene_or_drug: Gene symbol or drug name (e.g. 'TP53', 'imatinib').
    """
    try:
        safety_data: dict[str, Any] = {
            "query": gene_or_drug,
            "ctd_chemical_interactions": None,
            "ctd_disease_associations": None,
            "knockout_phenotypes": None,
            "adverse_events": None,
        }
        safety_flags: list[str] = []
        warnings: list[str] = []

        # ---- CTD gene-chemical interactions ----
        try:
            ctd_chem = await query_gene_chemical_interactions(gene_or_drug)
            if not ctd_chem.get("error"):
                raw = ctd_chem.get("raw_data", {})
                n_chems = raw.get("unique_chemicals", 0)
                safety_data["ctd_chemical_interactions"] = {
                    "unique_chemicals": n_chems,
                    "total_interactions": raw.get("total_interactions", 0),
                    "top_chemicals": raw.get("top_interactions", [])[:5],
                }
                if n_chems > 50:
                    safety_flags.append(
                        f"Extensive chemical interaction profile ({n_chems} chemicals) "
                        "-- may indicate broad off-target liability"
                    )
        except Exception:
            warnings.append("CTD chemical interaction query failed")

        # ---- CTD gene-disease associations ----
        try:
            ctd_disease = await query_gene_disease_associations(gene_or_drug)
            if not ctd_disease.get("error"):
                raw = ctd_disease.get("raw_data", {})
                n_diseases = raw.get("total_diseases", 0)
                direct = raw.get("direct_evidence_count", 0)
                safety_data["ctd_disease_associations"] = {
                    "total_diseases": n_diseases,
                    "direct_evidence": direct,
                    "top_diseases": [d["disease_name"] for d in raw.get("diseases", [])[:5]],
                }
                if direct > 10:
                    safety_flags.append(
                        f"Strong disease associations ({direct} with direct evidence) "
                        "-- essential gene with pleiotropic disease links"
                    )
        except Exception:
            warnings.append("CTD disease association query failed")

        # ---- IMPC knockout phenotypes ----
        try:
            ko = await get_knockout_phenotypes(gene_or_drug)
            if not ko.get("error"):
                raw = ko.get("raw_data", {})
                n_pheno = raw.get("total_phenotypes", 0)
                systems = raw.get("phenotype_systems", {})
                safety_data["knockout_phenotypes"] = {
                    "total_phenotypes": n_pheno,
                    "affected_systems": systems,
                    "top_phenotypes": [p["mp_term"] for p in raw.get("phenotypes", [])[:5]],
                }

                # Flag concerning phenotype systems
                concerning_systems = [
                    "cardiovascular system phenotype",
                    "nervous system phenotype",
                    "mortality/aging",
                    "embryo phenotype",
                    "immune system phenotype",
                    "hematopoietic system phenotype",
                    "liver/biliary system phenotype",
                    "renal/urinary system phenotype",
                ]
                flagged_systems = [
                    s for s in concerning_systems
                    if any(s.lower() in k.lower() for k in systems)
                ]
                if flagged_systems:
                    safety_flags.append(
                        f"Knockout phenotypes in safety-relevant systems: "
                        f"{', '.join(flagged_systems)}"
                    )
                if any("mortality" in k.lower() or "lethality" in k.lower() for k in systems):
                    safety_flags.append(
                        "CRITICAL: Knockout is lethal or associated with mortality"
                    )
        except Exception:
            warnings.append("IMPC knockout phenotype query failed")

        # ---- OpenFDA adverse events ----
        try:
            fda = await get_side_effects(gene_or_drug)
            if not fda.get("error"):
                raw = fda.get("raw_data", {})
                n_reports = raw.get("total_reports", 0)
                side_effects_list = raw.get("side_effects", [])
                safety_data["adverse_events"] = {
                    "total_reports": n_reports,
                    "top_side_effects": side_effects_list[:10],
                }
                # Check for serious adverse events
                serious_terms = [
                    "death", "cardiac", "hepat", "renal failure",
                    "anaphyla", "seizure", "stroke", "hemorrhage",
                ]
                serious_found = [
                    se["reaction"] for se in side_effects_list[:20]
                    if any(t in se["reaction"].lower() for t in serious_terms)
                ]
                if serious_found:
                    safety_flags.append(
                        f"Serious adverse events reported: {', '.join(serious_found[:5])}"
                    )
        except Exception:
            warnings.append("OpenFDA adverse event query failed")

        # ---- Build risk assessment ----
        risk_level = "LOW"
        if len(safety_flags) >= 3:
            risk_level = "HIGH"
        elif len(safety_flags) >= 1:
            risk_level = "MODERATE"

        summary = (
            f"Safety summary for '{gene_or_drug}': Risk level = {risk_level}. "
            f"{len(safety_flags)} safety flags identified. "
            f"{'Flags: ' + '; '.join(safety_flags[:3]) + '.' if safety_flags else 'No major safety concerns identified.'}"
            f"{' Warnings: ' + '; '.join(warnings) + '.' if warnings else ''}"
        )

        return standard_response(
            summary=summary,
            raw_data={
                "query": gene_or_drug,
                "risk_level": risk_level,
                "safety_flags": safety_flags,
                "warnings": warnings,
                "data": safety_data,
            },
            source="Lumi Safety (CTD + IMPC + OpenFDA)",
            source_id=gene_or_drug,
            confidence=0.75,
        )
    except Exception as exc:
        return handle_error("get_safety_summary", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
