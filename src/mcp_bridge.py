"""
MCP Tool Bridge -- connects agent tool registries to MCP server functions.

Instead of running MCP servers as separate processes and connecting via the
MCP protocol (which requires stdio/SSE transport), we import the tool
functions directly and register them as callables in agent tool registries.

Each MCP server module defines async (or sync) functions decorated with
``@mcp.tool()``.  These are ordinary Python functions that we can import
and invoke directly -- no protocol overhead needed.

Usage::

    from src.mcp_bridge import wire_agent_tools
    agent = create_statistical_genetics_agent()
    wire_agent_tools(agent)
    # agent._tool_registry is now populated with callable implementations
"""

from __future__ import annotations

import logging
from typing import Callable, TypedDict

from src.agents.base_agent import BaseAgent

logger = logging.getLogger("lumi.mcp_bridge")

# ===================================================================
# Import all MCP server tool functions
# ===================================================================

# -- Genomics ----------------------------------------------------------
from src.mcp_servers.genomics.server import (
    query_target_disease,
    get_target_info,
    query_gwas_associations,
    query_gene_variants,
    query_clinvar_gene,
    get_gene_info,
    get_variant_consequences,
    query_rsid,
    query_pharmgkb_gene,
)

# -- Expression --------------------------------------------------------
from src.mcp_servers.expression.server import (
    get_gene_expression,
    get_protein_expression,
    get_pathology_data,
    query_gene_expression_single_cell,
    search_geo_datasets,
    get_eqtls,
    query_encode_experiments,
)

# -- Protein & Structure -----------------------------------------------
from src.mcp_servers.protein.server import (
    get_protein_info,
    search_proteins,
    get_protein_sequence,
    get_protein_features,
    search_structures,
    get_structure_info,
    get_binding_sites,
    get_predicted_structure,
    get_pae,
    get_protein_domains,
    search_domains_by_name,
    get_interactions,
    get_network,
    get_enrichment,
)

# -- Clinical & Drug ---------------------------------------------------
from src.mcp_servers.clinical.server import (
    search_trials,
    get_trial_details,
    search_trials_by_target,
    search_pubmed,
    get_article_details,
    get_target_compounds,
    get_compound_info,
    get_drug_info,
    search_adverse_events,
    get_drug_label,
    get_drug_label_sections,
)

# -- Literature --------------------------------------------------------
from src.mcp_servers.literature.server import (
    search_papers,
    get_paper_details,
    get_citations,
    get_references,
    get_author_papers,
    search_preprints,
    get_preprint_details,
    search_fulltext,
    get_article_citations,
)

# -- Safety & Toxicology -----------------------------------------------
from src.mcp_servers.safety.server import (
    query_gene_chemical_interactions,
    query_gene_disease_associations,
    query_chemical_diseases,
    query_toxicity_assays,
    get_side_effects,
    get_drug_indications,
    get_knockout_phenotypes,
    get_safety_summary,
)

# -- Protein Design ----------------------------------------------------
from src.mcp_servers.protein_design.server import (
    esm2_score_sequence,
    esm2_mutant_effect,
    esm2_embed,
    calculate_protein_properties,
    predict_solubility,
    predict_structure_alphafold,
    blast_sequence,
    calculate_cai,
    number_antibody,
    predict_developability,
)

# -- Pathways & Ontology -----------------------------------------------
from src.mcp_servers.pathways.server import (
    get_pathways_for_gene,
    get_pathway_details,
    pathway_enrichment,
    get_go_annotations,
    go_enrichment,
    get_kegg_pathways,
    get_pathway_genes,
    get_pathway_info,
    search_pathways,
)

# -- Biosecurity -------------------------------------------------------
from src.mcp_servers.biosecurity.server import (
    screen_against_select_agents,
    blast_protein,
    check_select_agent_list,
    scan_toxin_domains,
    screen_virulence_factors,
    check_bwc_compliance,
)

# -- cBioPortal (Cancer Genomics) --------------------------------------
from src.mcp_servers.cbioportal.server import (
    query_cbioportal_mutations,
    get_cbioportal_copy_number,
    get_cbioportal_expression,
    get_cbioportal_survival,
    search_cbioportal_studies,
    get_cbioportal_gene_summary,
)

# -- QuickGO (Gene Ontology) -------------------------------------------
from src.mcp_servers.quickgo.server import (
    quickgo_annotation_search,
    quickgo_term_info,
    quickgo_term_descendants,
    quickgo_slim_mapping,
)

# -- UniChem (Chemical ID Mapping) -------------------------------------
from src.mcp_servers.unichem.server import (
    unichem_lookup,
    unichem_convert_id,
    unichem_search_inchikey,
    unichem_get_sources,
)

# -- UCSC Genome Browser -----------------------------------------------
from src.mcp_servers.ucsc.server import (
    ucsc_get_track_data,
    ucsc_search_genes,
    ucsc_get_sequence,
    ucsc_list_tracks,
    ucsc_get_chromosomes,
)

# -- JASPAR (Transcription Factor Motifs) ------------------------------
from src.mcp_servers.jaspar.server import (
    jaspar_search_motifs,
    jaspar_get_matrix,
    jaspar_get_pfm,
    jaspar_search_by_tf,
)

# -- Monarch Initiative (Phenotype-Genotype) ---------------------------
from src.mcp_servers.monarch.server import (
    monarch_search_entity,
    monarch_get_associations,
    monarch_get_entity,
    monarch_get_phenotypes,
)

# -- PRIDE (Proteomics) ------------------------------------------------
from src.mcp_servers.pride.server import (
    pride_search_projects,
    pride_get_project,
    pride_get_project_files,
)

# -- MPD (Mouse Phenome Database) --------------------------------------
from src.mcp_servers.mpd.server import (
    mpd_search_measurements,
    mpd_get_strain_data,
    mpd_get_ontology_terms,
)

# -- ReMap (Regulatory Maps) -------------------------------------------
from src.mcp_servers.remap.server import (
    remap_search_peaks,
    remap_get_targets,
    remap_get_crms,
    remap_list_experiments,
)

# -- Taxonomy (WoRMS + PaleobiologyDB + IUCN) -------------------------
from src.mcp_servers.taxonomy.server import (
    worms_search_taxa,
    worms_get_record,
    paleodb_search_taxa,
    paleodb_get_occurrences,
    iucn_get_species_status,
)

# -- Alignment CLI (samtools + BWA -- optional) ------------------------
_HAS_ALIGNMENT = False
try:
    from src.mcp_servers.alignment.server import (
        samtools_view,
        samtools_stats,
        samtools_index,
        samtools_depth,
        bwa_align,
    )
    _HAS_ALIGNMENT = True
except ImportError:
    logger.warning("Alignment MCP server not available (missing samtools/bwa?)")

# -- GWAS CLI (PLINK + GCTA -- optional) ------------------------------
_HAS_GWAS_CLI = False
try:
    from src.mcp_servers.gwas_cli.server import (
        plink_assoc,
        plink_ld,
        plink_pca,
        plink_clump,
        gcta_greml,
        gcta_cojo,
    )
    _HAS_GWAS_CLI = True
except ImportError:
    logger.warning("GWAS CLI MCP server not available (missing plink/gcta?)")

# -- Phylogenetics CLI (MUSCLE + FastTree + IQ-TREE -- optional) -------
_HAS_PHYLO = False
try:
    from src.mcp_servers.phylogenetics.server import (
        muscle_align,
        fasttree_build,
        iqtree_build,
        iqtree_model_test,
    )
    _HAS_PHYLO = True
except ImportError:
    logger.warning("Phylogenetics MCP server not available")

# -- Epigenomics CLI (HOMER + MACS2 -- optional) ----------------------
_HAS_EPIGENOMICS = False
try:
    from src.mcp_servers.epigenomics_cli.server import (
        macs2_callpeak,
        macs2_bdgcmp,
        homer_find_motifs,
        homer_annotate_peaks,
    )
    _HAS_EPIGENOMICS = True
except ImportError:
    logger.warning("Epigenomics CLI MCP server not available (missing macs2/homer?)")

# -- SV Calling CLI (LUMPY -- optional) --------------------------------
_HAS_SV_CALLING = False
try:
    from src.mcp_servers.sv_calling.server import (
        lumpy_call_sv,
        lumpy_filter_sv,
    )
    _HAS_SV_CALLING = True
except ImportError:
    logger.warning("SV Calling MCP server not available (missing lumpy?)")

# -- Metabolic (requires COBRApy -- optional) --------------------------
_HAS_METABOLIC = False
try:
    from src.mcp_servers.metabolic.server import (
        run_fba,
        run_fva,
        simulate_gene_knockout,
        simulate_reaction_knockout,
        add_heterologous_pathway,
        list_available_models,
        get_model_info,
        get_model_reactions,
        optimize_codons,
        predict_expression_level,
    )
    _HAS_METABOLIC = True
except ImportError:
    logger.warning("Metabolic MCP server not available (missing cobra?)")

# -- Tamarind Bio (requires API key -- optional) --------------------------
_HAS_TAMARIND = False
try:
    from src.mcp_servers.tamarind.server import (
        tamarind_list_tools,
        tamarind_submit_job,
        tamarind_submit_batch,
        tamarind_get_jobs,
        tamarind_poll_until_complete,
        tamarind_get_result,
        tamarind_upload_file,
        tamarind_list_files,
        tamarind_submit_pipeline,
        tamarind_run_pipeline,
        tamarind_delete_job,
        tamarind_get_finetuned_models,
    )
    _HAS_TAMARIND = True
except ImportError:
    logger.warning("Tamarind Bio MCP server not available")

# -- Slack (requires LUMI_SLACK_BOT_TOKEN -- optional) -------------------
_HAS_SLACK = False
try:
    from src.mcp_servers.slack.server import (
        slack_post_message,
        slack_post_thread_reply,
        slack_list_channels,
        slack_get_thread_replies,
    )
    _HAS_SLACK = True
except ImportError:
    logger.warning("Slack MCP server not available")

# -- BioRender / Figure Generation (requires mcp + Node.js -- optional) -
_HAS_BIORENDER = False
try:
    from src.mcp_servers.biorender.server import (
        generate_volcano_plot,
        generate_expression_heatmap,
        generate_pathway_diagram,
        generate_target_comparison_radar,
        generate_gene_expression_bar,
        generate_drug_target_sankey,
        generate_pipeline_flow,
        generate_moa_diagram,
        generate_literature_wordcloud,
        generate_confidence_distribution,
        generate_clinical_timeline,
        generate_category_pie,
        generate_venn_diagram,
        search_biorender_icons,
        search_biorender_templates,
        download_figure,
    )
    _HAS_BIORENDER = True
except ImportError:
    logger.warning("BioRender MCP server not available (missing mcp package or Node.js?)")

# -- PyMOL Structure (requires pymol-open-source via conda -- optional) -
_HAS_PYMOL = False
try:
    from src.mcp_servers.pymol_structure.server import (
        render_protein_structure,
        render_protein_surface,
        render_binding_site,
        align_structures,
        render_antibody_complex,
        highlight_residues,
        render_mutation_sites,
        measure_distance,
        generate_structure_movie,
        fetch_pdb_info,
    )
    _HAS_PYMOL = True
except ImportError:
    logger.warning("PyMOL MCP server not available (install pymol-open-source via conda-forge)")

# -- MockFlow / BioRender extras (conditional on BioRender server) -----
_HAS_MOCKFLOW = False
try:
    from src.mcp_servers.biorender.server import (
        generate_bio_diagram,
        generate_signaling_flowchart,
        generate_experiment_mindmap,
        generate_data_table,
        generate_pipeline_gantt,
    )
    _HAS_MOCKFLOW = True
except ImportError:
    logger.warning("MockFlow tools not available (missing mcp package or Node.js?)")

# -- Cheminformatics (requires RDKit -- optional) ----------------------
_HAS_CHEM = False
try:
    from src.mcp_servers.cheminformatics.server import (
        calculate_descriptors,
        check_drug_likeness,
        compute_fingerprint,
        compute_similarity,
        substructure_search,
        search_compound,
        get_compound_bioactivity,
        get_compound_safety,
        search_zinc,
        convert_molecule,
    )
    _HAS_CHEM = True
except ImportError:
    logger.warning("Cheminformatics MCP server not available (missing rdkit?)")


# ===================================================================
# Master tool registry: tool_name -> callable
# ===================================================================

TOOL_REGISTRY: dict[str, Callable] = {
    # --- Genomics ---
    "query_target_disease": query_target_disease,
    "get_target_info": get_target_info,
    "query_gwas_associations": query_gwas_associations,
    "query_gene_variants": query_gene_variants,
    "query_clinvar_gene": query_clinvar_gene,
    "get_gene_info": get_gene_info,
    "get_variant_consequences": get_variant_consequences,
    "query_rsid": query_rsid,
    "query_pharmgkb_gene": query_pharmgkb_gene,
    # --- Expression ---
    "get_gene_expression": get_gene_expression,
    "get_protein_expression": get_protein_expression,
    "get_pathology_data": get_pathology_data,
    "query_gene_expression_single_cell": query_gene_expression_single_cell,
    "search_geo_datasets": search_geo_datasets,
    "get_eqtls": get_eqtls,
    "query_encode_experiments": query_encode_experiments,
    # --- Protein & Structure ---
    "get_protein_info": get_protein_info,
    "search_proteins": search_proteins,
    "get_protein_sequence": get_protein_sequence,
    "get_protein_features": get_protein_features,
    "search_structures": search_structures,
    "get_structure_info": get_structure_info,
    "get_binding_sites": get_binding_sites,
    "get_predicted_structure": get_predicted_structure,
    "get_pae": get_pae,
    "get_protein_domains": get_protein_domains,
    "search_domains_by_name": search_domains_by_name,
    "get_interactions": get_interactions,
    "get_network": get_network,
    "get_enrichment": get_enrichment,
    # --- Clinical & Drug ---
    "search_trials": search_trials,
    "get_trial_details": get_trial_details,
    "search_trials_by_target": search_trials_by_target,
    "search_pubmed": search_pubmed,
    "get_article_details": get_article_details,
    "get_target_compounds": get_target_compounds,
    "get_compound_info": get_compound_info,
    "get_drug_info": get_drug_info,
    "search_adverse_events": search_adverse_events,
    "get_drug_label": get_drug_label,
    "get_drug_label_sections": get_drug_label_sections,
    # --- Literature ---
    "search_papers": search_papers,
    "get_paper_details": get_paper_details,
    "get_citations": get_citations,
    "get_references": get_references,
    "get_author_papers": get_author_papers,
    "search_preprints": search_preprints,
    "get_preprint_details": get_preprint_details,
    "search_fulltext": search_fulltext,
    "get_article_citations": get_article_citations,
    # --- Safety & Toxicology ---
    "query_gene_chemical_interactions": query_gene_chemical_interactions,
    "query_gene_disease_associations": query_gene_disease_associations,
    "query_chemical_diseases": query_chemical_diseases,
    "query_toxicity_assays": query_toxicity_assays,
    "get_side_effects": get_side_effects,
    "get_drug_indications": get_drug_indications,
    "get_knockout_phenotypes": get_knockout_phenotypes,
    "get_safety_summary": get_safety_summary,
    # --- Protein Design ---
    "esm2_score_sequence": esm2_score_sequence,
    "esm2_mutant_effect": esm2_mutant_effect,
    "esm2_embed": esm2_embed,
    "calculate_protein_properties": calculate_protein_properties,
    "predict_solubility": predict_solubility,
    "predict_structure_alphafold": predict_structure_alphafold,
    "blast_sequence": blast_sequence,
    "calculate_cai": calculate_cai,
    "number_antibody": number_antibody,
    "predict_developability": predict_developability,
    # --- Pathways & Ontology ---
    "get_pathways_for_gene": get_pathways_for_gene,
    "get_pathway_details": get_pathway_details,
    "pathway_enrichment": pathway_enrichment,
    "get_go_annotations": get_go_annotations,
    "go_enrichment": go_enrichment,
    "get_kegg_pathways": get_kegg_pathways,
    "get_pathway_genes": get_pathway_genes,
    "get_pathway_info": get_pathway_info,
    "search_pathways": search_pathways,
    # --- Biosecurity ---
    "screen_against_select_agents": screen_against_select_agents,
    "blast_protein": blast_protein,
    "check_select_agent_list": check_select_agent_list,
    "scan_toxin_domains": scan_toxin_domains,
    "screen_virulence_factors": screen_virulence_factors,
    "check_bwc_compliance": check_bwc_compliance,
    # --- cBioPortal (Cancer Genomics) ---
    "query_cbioportal_mutations": query_cbioportal_mutations,
    "get_cbioportal_copy_number": get_cbioportal_copy_number,
    "get_cbioportal_expression": get_cbioportal_expression,
    "get_cbioportal_survival": get_cbioportal_survival,
    "search_cbioportal_studies": search_cbioportal_studies,
    "get_cbioportal_gene_summary": get_cbioportal_gene_summary,
    # --- QuickGO ---
    "quickgo_annotation_search": quickgo_annotation_search,
    "quickgo_term_info": quickgo_term_info,
    "quickgo_term_descendants": quickgo_term_descendants,
    "quickgo_slim_mapping": quickgo_slim_mapping,
    # --- UniChem ---
    "unichem_lookup": unichem_lookup,
    "unichem_convert_id": unichem_convert_id,
    "unichem_search_inchikey": unichem_search_inchikey,
    "unichem_get_sources": unichem_get_sources,
    # --- UCSC Genome Browser ---
    "ucsc_get_track_data": ucsc_get_track_data,
    "ucsc_search_genes": ucsc_search_genes,
    "ucsc_get_sequence": ucsc_get_sequence,
    "ucsc_list_tracks": ucsc_list_tracks,
    "ucsc_get_chromosomes": ucsc_get_chromosomes,
    # --- JASPAR ---
    "jaspar_search_motifs": jaspar_search_motifs,
    "jaspar_get_matrix": jaspar_get_matrix,
    "jaspar_get_pfm": jaspar_get_pfm,
    "jaspar_search_by_tf": jaspar_search_by_tf,
    # --- Monarch Initiative ---
    "monarch_search_entity": monarch_search_entity,
    "monarch_get_associations": monarch_get_associations,
    "monarch_get_entity": monarch_get_entity,
    "monarch_get_phenotypes": monarch_get_phenotypes,
    # --- PRIDE ---
    "pride_search_projects": pride_search_projects,
    "pride_get_project": pride_get_project,
    "pride_get_project_files": pride_get_project_files,
    # --- MPD ---
    "mpd_search_measurements": mpd_search_measurements,
    "mpd_get_strain_data": mpd_get_strain_data,
    "mpd_get_ontology_terms": mpd_get_ontology_terms,
    # --- ReMap ---
    "remap_search_peaks": remap_search_peaks,
    "remap_get_targets": remap_get_targets,
    "remap_get_crms": remap_get_crms,
    "remap_list_experiments": remap_list_experiments,
    # --- Taxonomy ---
    "worms_search_taxa": worms_search_taxa,
    "worms_get_record": worms_get_record,
    "paleodb_search_taxa": paleodb_search_taxa,
    "paleodb_get_occurrences": paleodb_get_occurrences,
    "iucn_get_species_status": iucn_get_species_status,
}

# --- Metabolic (conditional) ---
if _HAS_METABOLIC:
    TOOL_REGISTRY.update({
        "run_fba": run_fba,
        "run_fva": run_fva,
        "simulate_gene_knockout": simulate_gene_knockout,
        "simulate_reaction_knockout": simulate_reaction_knockout,
        "add_heterologous_pathway": add_heterologous_pathway,
        "list_available_models": list_available_models,
        "get_model_info": get_model_info,
        "get_model_reactions": get_model_reactions,
        "optimize_codons": optimize_codons,
        "predict_expression_level": predict_expression_level,
    })

# --- Tamarind Bio (conditional) ---
if _HAS_TAMARIND:
    TOOL_REGISTRY.update({
        "tamarind_list_tools": tamarind_list_tools,
        "tamarind_submit_job": tamarind_submit_job,
        "tamarind_submit_batch": tamarind_submit_batch,
        "tamarind_get_jobs": tamarind_get_jobs,
        "tamarind_poll_until_complete": tamarind_poll_until_complete,
        "tamarind_get_result": tamarind_get_result,
        "tamarind_upload_file": tamarind_upload_file,
        "tamarind_list_files": tamarind_list_files,
        "tamarind_submit_pipeline": tamarind_submit_pipeline,
        "tamarind_run_pipeline": tamarind_run_pipeline,
        "tamarind_delete_job": tamarind_delete_job,
        "tamarind_get_finetuned_models": tamarind_get_finetuned_models,
    })

# --- BioRender / Figure Generation (conditional) ---
if _HAS_BIORENDER:
    TOOL_REGISTRY.update({
        "generate_volcano_plot": generate_volcano_plot,
        "generate_expression_heatmap": generate_expression_heatmap,
        "generate_pathway_diagram": generate_pathway_diagram,
        "generate_target_comparison_radar": generate_target_comparison_radar,
        "generate_gene_expression_bar": generate_gene_expression_bar,
        "generate_drug_target_sankey": generate_drug_target_sankey,
        "generate_pipeline_flow": generate_pipeline_flow,
        "generate_moa_diagram": generate_moa_diagram,
        "generate_literature_wordcloud": generate_literature_wordcloud,
        "generate_confidence_distribution": generate_confidence_distribution,
        "generate_clinical_timeline": generate_clinical_timeline,
        "generate_category_pie": generate_category_pie,
        "generate_venn_diagram": generate_venn_diagram,
        "search_biorender_icons": search_biorender_icons,
        "search_biorender_templates": search_biorender_templates,
        "download_figure": download_figure,
    })

# --- Alignment CLI (conditional) ---
if _HAS_ALIGNMENT:
    TOOL_REGISTRY.update({
        "samtools_view": samtools_view,
        "samtools_stats": samtools_stats,
        "samtools_index": samtools_index,
        "samtools_depth": samtools_depth,
        "bwa_align": bwa_align,
    })

# --- GWAS CLI (conditional) ---
if _HAS_GWAS_CLI:
    TOOL_REGISTRY.update({
        "plink_assoc": plink_assoc,
        "plink_ld": plink_ld,
        "plink_pca": plink_pca,
        "plink_clump": plink_clump,
        "gcta_greml": gcta_greml,
        "gcta_cojo": gcta_cojo,
    })

# --- Phylogenetics CLI (conditional) ---
if _HAS_PHYLO:
    TOOL_REGISTRY.update({
        "muscle_align": muscle_align,
        "fasttree_build": fasttree_build,
        "iqtree_build": iqtree_build,
        "iqtree_model_test": iqtree_model_test,
    })

# --- Epigenomics CLI (conditional) ---
if _HAS_EPIGENOMICS:
    TOOL_REGISTRY.update({
        "macs2_callpeak": macs2_callpeak,
        "macs2_bdgcmp": macs2_bdgcmp,
        "homer_find_motifs": homer_find_motifs,
        "homer_annotate_peaks": homer_annotate_peaks,
    })

# --- SV Calling CLI (conditional) ---
if _HAS_SV_CALLING:
    TOOL_REGISTRY.update({
        "lumpy_call_sv": lumpy_call_sv,
        "lumpy_filter_sv": lumpy_filter_sv,
    })

# --- Slack (conditional) ---
if _HAS_SLACK:
    TOOL_REGISTRY.update({
        "slack_post_message": slack_post_message,
        "slack_post_thread_reply": slack_post_thread_reply,
        "slack_list_channels": slack_list_channels,
        "slack_get_thread_replies": slack_get_thread_replies,
    })

# --- Cheminformatics (conditional) ---
if _HAS_CHEM:
    TOOL_REGISTRY.update({
        "calculate_descriptors": calculate_descriptors,
        "check_drug_likeness": check_drug_likeness,
        "compute_fingerprint": compute_fingerprint,
        "compute_similarity": compute_similarity,
        "substructure_search": substructure_search,
        "search_compound": search_compound,
        "get_compound_bioactivity": get_compound_bioactivity,
        "get_compound_safety": get_compound_safety,
        "search_zinc": search_zinc,
        "convert_molecule": convert_molecule,
    })

# --- PyMOL Structure (conditional) ---
if _HAS_PYMOL:
    TOOL_REGISTRY.update({
        "render_protein_structure": render_protein_structure,
        "render_protein_surface": render_protein_surface,
        "render_binding_site": render_binding_site,
        "align_structures": align_structures,
        "render_antibody_complex": render_antibody_complex,
        "highlight_residues": highlight_residues,
        "render_mutation_sites": render_mutation_sites,
        "measure_distance": measure_distance,
        "generate_structure_movie": generate_structure_movie,
        "fetch_pdb_info": fetch_pdb_info,
    })

# --- MockFlow (conditional) ---
if _HAS_MOCKFLOW:
    TOOL_REGISTRY.update({
        "generate_bio_diagram": generate_bio_diagram,
        "generate_signaling_flowchart": generate_signaling_flowchart,
        "generate_experiment_mindmap": generate_experiment_mindmap,
        "generate_data_table": generate_data_table,
        "generate_pipeline_gantt": generate_pipeline_gantt,
    })


# ===================================================================
# Tool domain tagging
# ===================================================================

_TOOL_DOMAINS: dict[str, str] = {}

def _tag(domain: str, names: list[str]) -> None:
    for n in names:
        _TOOL_DOMAINS[n] = domain

_tag("genomics", [
    "query_target_disease", "get_target_info", "query_gwas_associations",
    "query_gene_variants", "query_clinvar_gene", "get_gene_info",
    "get_variant_consequences", "query_rsid", "query_pharmgkb_gene",
])
_tag("expression", [
    "get_gene_expression", "get_protein_expression", "get_pathology_data",
    "query_gene_expression_single_cell", "search_geo_datasets",
    "get_eqtls", "query_encode_experiments",
])
_tag("protein", [
    "get_protein_info", "search_proteins", "get_protein_sequence",
    "get_protein_features", "search_structures", "get_structure_info",
    "get_binding_sites", "get_predicted_structure", "get_pae",
    "get_protein_domains", "search_domains_by_name",
    "get_interactions", "get_network", "get_enrichment",
])
_tag("clinical", [
    "search_trials", "get_trial_details", "search_trials_by_target",
    "search_pubmed", "get_article_details", "get_target_compounds",
    "get_compound_info", "get_drug_info", "search_adverse_events",
    "get_drug_label", "get_drug_label_sections",
])
_tag("literature", [
    "search_papers", "get_paper_details", "get_citations", "get_references",
    "get_author_papers", "search_preprints", "get_preprint_details",
    "search_fulltext", "get_article_citations",
])
_tag("safety", [
    "query_gene_chemical_interactions", "query_gene_disease_associations",
    "query_chemical_diseases", "query_toxicity_assays", "get_side_effects",
    "get_drug_indications", "get_knockout_phenotypes", "get_safety_summary",
])
_tag("protein_design", [
    "esm2_score_sequence", "esm2_mutant_effect", "esm2_embed",
    "calculate_protein_properties", "predict_solubility",
    "predict_structure_alphafold", "blast_sequence", "calculate_cai",
    "number_antibody", "predict_developability",
])
_tag("pathways", [
    "get_pathways_for_gene", "get_pathway_details", "pathway_enrichment",
    "get_go_annotations", "go_enrichment", "get_kegg_pathways",
    "get_pathway_genes", "get_pathway_info", "search_pathways",
])
_tag("biosecurity", [
    "screen_against_select_agents", "blast_protein", "check_select_agent_list",
    "scan_toxin_domains", "screen_virulence_factors", "check_bwc_compliance",
])
_tag("metabolic", [
    "run_fba", "run_fva", "simulate_gene_knockout", "simulate_reaction_knockout",
    "add_heterologous_pathway", "list_available_models", "get_model_info",
    "get_model_reactions", "optimize_codons", "predict_expression_level",
])
_tag("biorender", [
    "generate_volcano_plot", "generate_expression_heatmap", "generate_pathway_diagram",
    "generate_target_comparison_radar", "generate_gene_expression_bar",
    "generate_drug_target_sankey", "generate_pipeline_flow", "generate_moa_diagram",
    "generate_literature_wordcloud", "generate_confidence_distribution",
    "generate_clinical_timeline", "generate_category_pie", "generate_venn_diagram",
    "search_biorender_icons", "search_biorender_templates", "download_figure",
])
_tag("slack", [
    "slack_post_message", "slack_post_thread_reply",
    "slack_list_channels", "slack_get_thread_replies",
])
_tag("cheminformatics", [
    "calculate_descriptors", "check_drug_likeness", "compute_fingerprint",
    "compute_similarity", "substructure_search", "search_compound",
    "get_compound_bioactivity", "get_compound_safety", "search_zinc",
    "convert_molecule",
])
_tag("pymol", [
    "render_protein_structure", "render_protein_surface", "render_binding_site",
    "align_structures", "render_antibody_complex", "highlight_residues",
    "render_mutation_sites", "measure_distance", "generate_structure_movie",
    "fetch_pdb_info",
])
_tag("mockflow", [
    "generate_bio_diagram", "generate_signaling_flowchart",
    "generate_experiment_mindmap", "generate_data_table",
    "generate_pipeline_gantt",
])


# ===================================================================
# Tool metadata & catalog
# ===================================================================

class ToolDescriptor(TypedDict):
    name: str
    description: str
    domain: str
    parameters: list[str]
    input_schema: dict


def _get_tool_description(func: Callable) -> str:
    """Extract a one-line description from a callable's docstring."""
    doc = getattr(func, "__doc__", None)
    if doc:
        return doc.strip().split("\n")[0]
    return func.__name__.replace("_", " ").title()


def _get_input_schema_from_agents(tool_name: str) -> dict:
    """Look up the input_schema for *tool_name* from agent _TOOLS lists.

    Imports are deferred to avoid circular dependencies at module load time.
    """
    # Lazy import of all agent modules that define _TOOLS
    from src.agents import (  # noqa: F811
        statistical_genetics, functional_genomics, single_cell_atlas,
        bio_pathways, fda_safety, toxicogenomics,
        target_biologist, pharmacologist,
        protein_intelligence, antibody_engineer, structure_design,
        lead_optimization, developability,
        clinical_trialist, literature_synthesis, assay_design,
        dual_use_screening,
    )

    agent_modules = [
        statistical_genetics, functional_genomics, single_cell_atlas,
        bio_pathways, fda_safety, toxicogenomics,
        target_biologist, pharmacologist,
        protein_intelligence, antibody_engineer, structure_design,
        lead_optimization, developability,
        clinical_trialist, literature_synthesis, assay_design,
        dual_use_screening,
    ]

    for mod in agent_modules:
        tools_list = getattr(mod, "_TOOLS", [])
        for tool_def in tools_list:
            if tool_def.get("name") == tool_name:
                return tool_def.get("input_schema", {})
    return {"type": "object", "properties": {}}


# Cache for the built catalog
_catalog_cache: list[ToolDescriptor] | None = None


def build_tool_catalog() -> list[ToolDescriptor]:
    """Build a catalog of all registered tools with metadata.

    Returns:
        List of :class:`ToolDescriptor` dicts with name, description,
        domain, parameter names, and input_schema.
    """
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache

    catalog: list[ToolDescriptor] = []
    for name, func in TOOL_REGISTRY.items():
        schema = _get_input_schema_from_agents(name)
        params = list(schema.get("properties", {}).keys())
        desc = _get_tool_description(func)
        domain = _TOOL_DOMAINS.get(name, "unknown")

        catalog.append(ToolDescriptor(
            name=name,
            description=desc,
            domain=domain,
            parameters=params,
            input_schema=schema,
        ))

    _catalog_cache = catalog

    # Log per-domain breakdown
    domain_counts: dict[str, int] = {}
    for td in catalog:
        domain_counts[td["domain"]] = domain_counts.get(td["domain"], 0) + 1
    logger.info("Built tool catalog: %d tools across %d domains", len(catalog), len(domain_counts))
    for domain, count in sorted(domain_counts.items()):
        logger.info("  %s: %d tools", domain, count)

    return catalog


def get_catalog_prompt_text() -> str:
    """Return a compact text representation of the tool catalog for LLM prompts.

    Format: ``name | domain | description`` per tool, ~3-4K tokens.
    """
    catalog = build_tool_catalog()
    lines = ["Available tools (name | domain | description):"]
    lines.append("-" * 60)
    for td in catalog:
        params_str = ", ".join(td["parameters"]) if td["parameters"] else "none"
        lines.append(f"{td['name']} | {td['domain']} | {td['description']} | params: {params_str}")
    return "\n".join(lines)


def get_tool_schema(tool_name: str) -> dict | None:
    """Look up the full tool-definition dict for a single tool.

    Returns a dict with ``name``, ``description``, and ``input_schema``
    suitable for passing to the Anthropic API, or ``None`` if not found.
    """
    catalog = build_tool_catalog()
    for td in catalog:
        if td["name"] == tool_name:
            return {
                "name": td["name"],
                "description": td["description"],
                "input_schema": td["input_schema"],
            }
    return None


# ===================================================================
# Wiring function
# ===================================================================


def wire_agent_tools(agent: BaseAgent) -> None:
    """Register callable implementations for all tools defined in an agent's tool list.

    Iterates over ``agent.tools`` (the list of tool-definition dicts that
    are sent to the Anthropic API), looks up each tool name in the master
    :data:`TOOL_REGISTRY`, and registers the corresponding callable in
    ``agent._tool_registry`` so that :meth:`BaseAgent._call_tool` can
    invoke it.

    The built-in ``execute_code`` tool is skipped since it is handled
    directly by :class:`BaseAgent`.

    Args:
        agent: A specialist agent whose tools need callable implementations.
    """
    wired = 0
    skipped = 0
    missing: list[str] = []

    for tool_def in agent.tools:
        name = tool_def.get("name", "")
        if name == "execute_code":
            skipped += 1
            continue
        if name in TOOL_REGISTRY:
            agent._tool_registry[name] = TOOL_REGISTRY[name]
            wired += 1
        else:
            missing.append(name)

    tool_count = len(agent.tools) - skipped  # exclude execute_code
    if missing:
        logger.warning(
            "Agent '%s': %d/%d tools wired, %d missing: %s",
            agent.name,
            wired,
            tool_count,
            len(missing),
            ", ".join(missing),
        )
    else:
        logger.info(
            "Agent '%s': all %d tools wired successfully",
            agent.name,
            wired,
        )
