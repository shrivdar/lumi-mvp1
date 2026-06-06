"""Sublab and agent metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from api.models import AgentInfo, IntegrationInfo, SublabInfo, ToolInfo

router = APIRouter(prefix="/sublabs", tags=["sublabs"])

SUBLABS: dict[str, SublabInfo] = {
    "target-validation": SublabInfo(
        name="Target Validation",
        description="Evidence dossiers with pathway diagrams and confidence scores",
        agents=["target_biologist", "bio_pathways", "literature_synthesis", "fda_safety", "competitive_intelligence"],
        divisions=["Target Identification", "Target Safety", "Computational Biology"],
        examples=[
            "Evaluate BRCA1 as a therapeutic target for triple-negative breast cancer",
            "Assess PCSK9 inhibition safety profile based on genetic evidence",
            "Validate KRAS G12C as a druggable target in non-small cell lung cancer",
        ],
    ),
    "assay-troubleshooting": SublabInfo(
        name="Assay Troubleshooting",
        description="Root-cause analysis of unexpected experimental results",
        agents=["assay_design", "functional_genomics", "single_cell_atlas"],
        divisions=["Experimental Design", "Target Identification"],
        examples=[
            "Why is my ELISA showing high background in serum samples?",
            "Troubleshoot low transfection efficiency in HEK293 cells",
            "Diagnose inconsistent IC50 values across plate replicates",
        ],
    ),
    "biomarker-curation": SublabInfo(
        name="Biomarker Curation",
        description="Panel candidates with expression heatmaps",
        agents=["statistical_genetics", "single_cell_atlas", "clinical_trialist"],
        divisions=["Target Identification", "Clinical Intelligence"],
        examples=[
            "Identify circulating biomarkers for early pancreatic cancer detection",
            "Curate a pharmacodynamic biomarker panel for JAK inhibitor response",
            "Find predictive biomarkers for immune checkpoint inhibitor response",
        ],
    ),
    "regulatory-submissions": SublabInfo(
        name="Regulatory Submissions",
        description="Tox literature reviews with MoA illustrations",
        agents=["toxicogenomics", "pharmacologist", "fda_safety", "literature_synthesis"],
        divisions=["Target Safety", "Computational Biology", "Clinical Intelligence"],
        examples=[
            "Prepare a nonclinical toxicology summary for an anti-CD20 antibody",
            "Review hepatotoxicity signals for kinase inhibitor class",
            "Compile mechanism-of-action safety assessment for bispecific antibody",
        ],
    ),
    "lead-optimization": SublabInfo(
        name="Lead Optimization",
        description="Multi-parameter optimization of drug candidates",
        agents=["lead_optimization", "antibody_engineer", "developability", "structure_design"],
        divisions=["Molecular Design", "Modality Selection"],
        examples=[
            "Optimize a lead compound for improved oral bioavailability and reduced hERG liability",
            "Improve thermostability of anti-HER2 antibody without losing affinity",
            "Design selective kinase inhibitor with improved metabolic stability",
        ],
    ),
    "clinical-translation": SublabInfo(
        name="Clinical Translation",
        description="Go/no-go evidence packages for IND-enabling studies",
        agents=["clinical_trialist", "pharmacologist", "statistical_genetics", "fda_safety", "competitive_intelligence"],
        divisions=["Clinical Intelligence", "Target Safety", "Computational Biology"],
        examples=[
            "Build go/no-go evidence package for anti-IL-17 antibody IND filing",
            "Assess clinical translatability of preclinical efficacy data for NASH target",
            "Evaluate first-in-human dose selection strategy for bispecific T-cell engager",
        ],
    ),
}

AGENTS_BY_DIVISION: dict[str, list[str]] = {
    "Target Identification": ["statistical_genetics", "functional_genomics", "single_cell_atlas"],
    "Target Safety": ["bio_pathways", "fda_safety", "toxicogenomics"],
    "Modality Selection": ["target_biologist", "pharmacologist"],
    "Molecular Design": ["protein_intelligence", "antibody_engineer", "structure_design", "lead_optimization", "developability"],
    "Clinical Intelligence": ["clinical_trialist"],
    "Computational Biology": ["literature_synthesis", "competitive_intelligence"],
    "Experimental Design": ["assay_design"],
    "Biosecurity": ["dual_use_screening"],
}

MCP_TOOLS: list[ToolInfo] = [
    ToolInfo(name="search_pubmed", server="literature", description="Search PubMed for publications"),
    ToolInfo(name="query_gwas_catalog", server="genomics", description="Query GWAS Catalog for associations"),
    ToolInfo(name="query_depmap", server="genomics", description="Query DepMap for gene dependencies"),
    ToolInfo(name="query_faers", server="safety", description="Query FDA Adverse Event Reporting System"),
    ToolInfo(name="query_uniprot", server="protein", description="Query UniProt for protein data"),
    ToolInfo(name="predict_structure", server="protein_design", description="Predict protein structure (ESM/AF2)"),
    ToolInfo(name="dock_ligand", server="cheminformatics", description="Molecular docking simulation"),
    ToolInfo(name="simulate_expression", server="expression", description="Simulate gene expression changes"),
    ToolInfo(name="run_fba", server="metabolic", description="Flux balance analysis"),
    ToolInfo(name="query_pathways", server="pathways", description="Query pathway databases (KEGG, Reactome)"),
    ToolInfo(name="screen_biosecurity", server="biosecurity", description="Run biosecurity 5-screen pipeline"),
    ToolInfo(name="query_clinical_trials", server="clinical", description="Query ClinicalTrials.gov"),
    ToolInfo(name="execute_code", server="sandbox", description="Execute Python code in sandbox"),
]

INTEGRATIONS: list[IntegrationInfo] = [
    IntegrationInfo(name="Slack", status="available", description="Post findings and alerts to Slack channels"),
    IntegrationInfo(name="BioRender", status="available", description="Generate scientific illustrations"),
    IntegrationInfo(name="Benchling", status="available", description="Sync with Benchling notebook entries"),
    IntegrationInfo(name="Tamarind Bio", status="available", description="Submit compute jobs (folding, docking, MD)"),
]


@router.get("")
async def list_sublabs() -> dict[str, SublabInfo]:
    return SUBLABS


# NOTE: literal "/meta/*" routes must be declared BEFORE the parametrized
# "/{sublab_id}" routes — otherwise "/meta/agents" is captured by
# "/{sublab_id}/agents" (sublab_id="meta") and 500s with KeyError.
@router.get("/meta/agents")
async def list_all_agents() -> list[AgentInfo]:
    agents = []
    for division, agent_ids in AGENTS_BY_DIVISION.items():
        for agent_id in agent_ids:
            memberships = [s.name for s in SUBLABS.values() if agent_id in s.agents]
            agents.append(AgentInfo(id=agent_id, division=division, sublabs=memberships))
    return agents


@router.get("/meta/tools")
async def list_tools() -> list[ToolInfo]:
    return MCP_TOOLS


@router.get("/meta/integrations")
async def list_integrations() -> list[IntegrationInfo]:
    return INTEGRATIONS


@router.get("/{sublab_id}")
async def get_sublab(sublab_id: str) -> SublabInfo:
    return SUBLABS[sublab_id]


@router.get("/{sublab_id}/agents")
async def get_sublab_agents(sublab_id: str) -> list[AgentInfo]:
    sublab = SUBLABS[sublab_id]
    active = set(sublab.agents)
    agents = []
    for division, agent_ids in AGENTS_BY_DIVISION.items():
        for agent_id in agent_ids:
            if agent_id in active:
                memberships = [s.name for s in SUBLABS.values() if agent_id in s.agents]
                agents.append(AgentInfo(id=agent_id, division=division, status="active", sublabs=memberships))
    return agents
