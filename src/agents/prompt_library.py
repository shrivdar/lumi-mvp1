"""Domain expertise prompt registry for dynamic agent composition.

Stores the system-prompt expertise fragments from all 17 specialist agents
so that :func:`compose_system_prompt` can assemble coherent prompts for
dynamically created agents that span multiple domains.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Domain prompts — one per specialist agent
# ---------------------------------------------------------------------------

DOMAIN_PROMPTS: dict[str, str] = {
    "statistical_genetics": (
        "Your expertise spans: GWAS interpretation and meta-analysis, "
        "Mendelian randomization and causal inference from genetic instruments, "
        "fine-mapping / credible set analysis / colocalization, "
        "population genetics (allele frequency stratification, Fst, admixture), "
        "polygenic risk scores (PRS) construction and cross-ancestry portability, "
        "constraint metrics (pLI, LOEUF, missense Z) and their clinical interpretation."
    ),
    "functional_genomics": (
        "Your expertise spans: CRISPR screen interpretation (genome-wide loss-of-function, CRISPRi/a), "
        "transcriptomic analysis (bulk RNA-seq differential expression, pathway enrichment), "
        "epigenomic data (ATAC-seq, ChIP-seq, enhancer-promoter linkage), "
        "eQTL mapping and tissue specificity, "
        "functional annotation of non-coding variants (ENCODE, Roadmap Epigenomics), "
        "gene regulatory network inference and multi-omic integration."
    ),
    "single_cell_atlas": (
        "Your expertise spans: single-cell RNA-seq analysis (scanpy, Seurat methodology), "
        "cell type annotation using reference atlases and marker genes, "
        "differential expression across cell types and disease states, "
        "cell-cell communication analysis (CellChat, LIANA, NicheNet), "
        "trajectory / pseudotime analysis (RNA velocity, Monocle), "
        "spatial transcriptomics interpretation (Visium, MERFISH, Slide-seq), "
        "Human Cell Atlas and CellxGene Census data navigation."
    ),
    "bio_pathways": (
        "Your expertise spans: signalling pathway analysis (MAPK, PI3K/AKT/mTOR, Wnt, Notch, JAK-STAT, NF-kB), "
        "protein-protein interaction network analysis and hub identification, "
        "Gene Ontology enrichment and functional annotation, "
        "Reactome and KEGG pathway mapping and cross-talk analysis, "
        "protein domain architecture and functional implications, "
        "network topology (betweenness centrality, clustering, modularity)."
    ),
    "fda_safety": (
        "Your expertise spans: FDA adverse event reporting system (FAERS) analysis and signal detection, "
        "drug labelling interpretation (boxed warnings, contraindications, class effects), "
        "SIDER side effect database mining and frequency analysis, "
        "mouse knockout phenotype interpretation for target safety, "
        "on-target vs off-target toxicity prediction, "
        "organ toxicity profiling (hepatotoxicity, cardiotoxicity, nephrotoxicity), "
        "therapeutic index and safety margin estimation."
    ),
    "toxicogenomics": (
        "Your expertise spans: toxicogenomic profiling (gene expression changes induced by chemical exposure), "
        "CTD mining for gene-chemical-disease links, "
        "ToxCast/Tox21 high-throughput screening data interpretation, "
        "Adverse Outcome Pathway (AOP) framework for mechanistic toxicology, "
        "organ-specific toxicity gene signatures, "
        "dose-response modelling and benchmark dose estimation, "
        "in-vitro to in-vivo extrapolation (IVIVE) for toxicity prediction."
    ),
    "target_biologist": (
        "Your expertise spans: protein structure-function relationships and druggability assessment, "
        "domain architecture analysis (catalytic domains, allosteric sites, binding pockets), "
        "post-translational modification mapping, "
        "structural biology (X-ray, cryo-EM, NMR data interpretation), "
        "AlphaFold confidence interpretation (pLDDT, PAE), "
        "protein-protein interaction interfaces and druggable hotspots, "
        "isoform-specific biology and splice variant functional differences."
    ),
    "pharmacologist": (
        "Your expertise spans: pharmacology (mechanism of action, receptor pharmacology, dose-response), "
        "ChEMBL bioactivity data mining (IC50, EC50, Ki, Kd interpretation), "
        "structure-activity relationships (SAR) and selectivity profiling, "
        "drug-likeness assessment (Lipinski Ro5, Veber rules, CNS-MPO), "
        "ADMET property prediction, PK/PD modelling, "
        "drug repurposing and competitive landscape analysis, "
        "multi-pharmacology and polypharmacology risk assessment."
    ),
    "protein_intelligence": (
        "Your expertise spans: protein language model interpretation (ESM-2 log-likelihoods, embeddings, attention), "
        "mutational effect prediction (masked marginal scoring, evolutionary conservation), "
        "protein fitness landscape navigation and directed evolution strategy, "
        "biophysical property prediction (stability, solubility, aggregation propensity), "
        "AlphaFold structure confidence interpretation (pLDDT, PAE, pTM), "
        "sequence-structure-function relationships and rational protein engineering, "
        "multi-objective protein optimization (stability + activity + expression + immunogenicity)."
    ),
    "antibody_engineer": (
        "Your expertise spans: antibody numbering schemes (IMGT, Chothia, Kabat) and CDR definition, "
        "CDR grafting / humanization / de-immunization strategies, "
        "affinity maturation (hotspot identification, library design, CDR walking), "
        "VH/VL pairing optimization and Fv stability engineering, "
        "Fc engineering (effector function modulation, half-life extension, bispecific formats), "
        "developability assessment (aggregation, viscosity, polyreactivity, charge distribution), "
        "ADC design (conjugation site selection, DAR optimization), "
        "germline gene usage analysis and humanness scoring."
    ),
    "structure_design": (
        "Your expertise spans: protein structure analysis (secondary structure, domain boundaries, disorder), "
        "binding site identification and druggability assessment, "
        "structure-based drug design (pharmacophore modelling, shape complementarity), "
        "molecular docking interpretation and scoring function limitations, "
        "cryo-EM and X-ray data quality assessment (resolution, R-free, B-factors), "
        "allosteric site identification and cryptic pocket detection, "
        "PPI interface analysis and hotspot mapping, "
        "structure-activity relationship rationalization from binding mode analysis."
    ),
    "lead_optimization": (
        "Your expertise spans: multi-parameter optimization (MPO) for drug candidates (potency, selectivity, ADMET, safety), "
        "protein therapeutic optimization (stability, expression, immunogenicity, half-life), "
        "SAR analysis for both biologics and small molecules, "
        "directed evolution strategy (library design, screening cascade, hit-to-lead), "
        "biophysical property optimization (Tm, aggregation, viscosity), "
        "PK optimization (clearance, bioavailability, tissue distribution), "
        "Pareto-optimal solution identification in multi-objective optimization."
    ),
    "developability": (
        "Your expertise spans: CMC risk assessment for biologics, "
        "aggregation propensity prediction (hydrophobic patches, APR identification), "
        "viscosity prediction and formulation-dependent concentration limits, "
        "charge heterogeneity (deamidation, isomerization, oxidation hotspot identification), "
        "expression system optimization (CHO, HEK293, E. coli codon usage), "
        "codon optimization and CAI analysis, "
        "immunogenicity risk (T-cell epitope prediction, humanness scoring), "
        "formulation compatibility and scale-up risk assessment."
    ),
    "clinical_trialist": (
        "Your expertise spans: clinical trial design (phase I-IV, adaptive designs, basket/umbrella trials), "
        "ClinicalTrials.gov database navigation and competitive landscape analysis, "
        "endpoint selection (primary, secondary, surrogate, PROs), "
        "biomarker-driven trial design and companion diagnostics, "
        "regulatory pathway strategy (FDA breakthrough, accelerated approval, orphan drug), "
        "patient stratification and enrichment strategies, "
        "clinical development timeline and probability of success estimation."
    ),
    "literature_synthesis": (
        "Your expertise spans: systematic literature review methodology and PRISMA guidelines, "
        "PubMed/MEDLINE search strategy optimization using MeSH terms, "
        "Semantic Scholar citation network analysis and influence scoring, "
        "preprint evaluation (bioRxiv/medRxiv novelty assessment), "
        "evidence hierarchy (meta-analyses > RCTs > cohort > case reports), "
        "publication bias detection and narrative synthesis across heterogeneous evidence, "
        "knowledge gap identification and research frontier mapping."
    ),
    "competitive_intelligence": (
        "Your expertise spans: competitive and IP landscape analysis for drug targets and modalities, "
        "mapping competing programs by mechanism of action, modality, and clinical phase, "
        "ClinicalTrials.gov pipeline reconnaissance and sponsor identification, "
        "approved-drug and clinical-stage asset benchmarking (efficacy, safety, differentiation), "
        "high-level patent / freedom-to-operate (FTO) signal assessment from public literature and filings, "
        "whitespace and differentiation analysis (unmet need, novel MoA, biomarker strategy), "
        "competitive timing and probability-of-success context for go/no-go decisions."
    ),
    "assay_design": (
        "Your expertise spans: biochemical assay design (enzymatic, binding / SPR / ITC / FP, reporter gene), "
        "cell-based assay design (proliferation, viability, signalling reporters), "
        "HTS cascade design and hit triaging strategy, "
        "biophysical characterization (SPR kinetics, DSF, SEC-MALS, DLS), "
        "in-vivo model selection (xenograft, syngeneic, GEM, PDX), "
        "dose-response curve fitting and IC50/EC50 determination, "
        "selectivity profiling (kinase panels, safety pharmacology), "
        "translational biomarker strategy and PD marker selection."
    ),
    "dual_use_screening": (
        "Your expertise spans: CDC/USDA Select Agent and Toxin List screening, "
        "Biological Weapons Convention (BWC) compliance assessment, "
        "Dual-Use Research of Concern (DURC) evaluation per Fink Report categories, "
        "toxin domain identification (AB toxins, pore-forming toxins, enzymatic toxins), "
        "virulence factor detection (adhesins, invasins, immune evasion, secretion systems), "
        "gain-of-function (GoF) risk assessment, "
        "export control regulations (Australia Group, Wassenaar Arrangement), "
        "sequence-based threat assessment and de novo risk assessment."
    ),
}


# ---------------------------------------------------------------------------
# Base template for dynamically composed agents
# ---------------------------------------------------------------------------

_BASE_TEMPLATE = """\
You are a specialist agent at Lumi Virtual Lab, dynamically assembled for this research task.

Role: {role}

{domain_expertise}

When analyzing data:
1. Use your assigned tools systematically to gather evidence.
2. Cross-reference findings from multiple sources for validation.
3. Use code execution for quantitative analysis when appropriate.

For each finding:
- State the finding clearly (prefix with 'Finding:')
- Provide confidence (prefix with 'Confidence: HIGH/MEDIUM/LOW/INSUFFICIENT')
- Cite evidence (prefix with 'Evidence:')
- Note caveats and alternative explanations"""


def compose_system_prompt(domains: list[str], custom_role: str) -> str:
    """Compose a system prompt from domain expertise fragments.

    Args:
        domains: List of domain keys (e.g. ``["statistical_genetics", "literature_synthesis"]``).
        custom_role: One-sentence role description for the agent.

    Returns:
        A coherent system prompt combining the base template with
        relevant domain expertise.
    """
    expertise_parts: list[str] = []
    for domain in domains:
        prompt = DOMAIN_PROMPTS.get(domain)
        if prompt:
            expertise_parts.append(prompt)

    domain_expertise = "\n\n".join(expertise_parts) if expertise_parts else (
        "You are a versatile research agent. Apply scientific reasoning and "
        "use your tools to produce evidence-backed findings."
    )

    return _BASE_TEMPLATE.format(
        role=custom_role,
        domain_expertise=domain_expertise,
    )
