"""
System Factory -- creates and wires the complete Lumi Virtual Lab agent swarm.

This module solves the three integration gaps:

1. **Tool callables**: Agents define tool schemas but have empty
   ``_tool_registry`` dicts.  We use :func:`wire_agent_tools` from
   :mod:`src.mcp_bridge` to populate them with the actual MCP server
   functions.

2. **Specialist assignment**: Division leads are created with
   ``specialist_agents=[]``.  We explicitly create all specialists and
   pass them to the division factories.

3. **Divisions dict**: The CSO pipeline expects a ``divisions`` dict
   mapping division names to :class:`DivisionLead` instances.
   :func:`create_system` builds and returns exactly that.

Usage::

    from src.factory import create_system
    divisions = create_system()
    # Pass to the pipeline:
    report = await run_yohas_pipeline("Evaluate BRCA1 as target", divisions=divisions)
"""

from __future__ import annotations

import logging

from src.agents.base_agent import BaseAgent
from src.divisions.base_lead import DivisionLead
from src.mcp_bridge import wire_agent_tools

# -- All agent factories ------------------------------------------------
from src.agents import (
    # Division 1: Target Identification
    create_statistical_genetics_agent,
    create_functional_genomics_agent,
    create_single_cell_atlas_agent,
    # Division 2: Target Safety
    create_bio_pathways_agent,
    create_fda_safety_agent,
    create_toxicogenomics_agent,
    create_pathology_agent,
    create_physiology_agent,
    # Division 3: Modality Selection
    create_target_biologist_agent,
    create_pharmacologist_agent,
    create_molecular_biology_agent,
    create_cell_biology_agent,
    create_biochemistry_agent,
    # Division 4: Molecular Design
    create_protein_intelligence_agent,
    create_antibody_engineer_agent,
    create_structure_design_agent,
    create_lead_optimization_agent,
    create_developability_agent,
    create_biophysics_agent,
    create_glycoengineering_agent,
    # Division 5: Clinical Intelligence
    create_clinical_trialist_agent,
    # Division 6: Computational Biology
    create_literature_synthesis_agent,
    create_systems_biology_agent,
    create_competitive_intelligence_agent,
    # Division 7: Experimental Design
    create_assay_design_agent,
    create_lab_automation_agent,
    create_protocols_agent,
    # Division 8: Biosecurity
    create_dual_use_screening_agent,
    # Division 9: Immunology & Cancer Biology
    create_cancer_biology_agent,
    create_immunology_agent,
    # Division 10: Microbiology & Synthetic Biology
    create_microbiology_agent,
    create_synthetic_biology_agent,
    create_bioengineering_agent,
    # Division 11: Imaging
    create_bioimaging_agent,
)

# -- All division factories ---------------------------------------------
from src.divisions import (
    create_target_id_lead,
    create_target_safety_lead,
    create_modality_lead,
    create_molecular_design_lead,
    create_clinical_lead,
    create_compbio_lead,
    create_experimental_lead,
    create_biosecurity_lead,
    create_immunology_cancer_lead,
    create_synbio_lead,
    create_imaging_lead,
)

from src.sublabs import (
    Sublab,
    TargetValidationSublab,
    AssayTroubleshootingSublab,
    BiomarkerCurationSublab,
    RegulatorySubmissionsSublab,
    LeadOptimizationSublab,
    ClinicalTranslationSublab,
)

logger = logging.getLogger("lumi.factory")

# Mapping of sublab name -> sublab class
SUBLAB_REGISTRY: dict[str, type[Sublab]] = {
    "Target Validation": TargetValidationSublab,
    "Assay Troubleshooting": AssayTroubleshootingSublab,
    "Biomarker Curation": BiomarkerCurationSublab,
    "Regulatory Submissions": RegulatorySubmissionsSublab,
    "Lead Optimization": LeadOptimizationSublab,
    "Clinical Translation": ClinicalTranslationSublab,
}


def create_sublab(
    name: str,
    divisions: dict[str, DivisionLead] | None = None,
) -> Sublab:
    """Create a sublab instance by name.

    Args:
        name: Sublab name (must match a key in :data:`SUBLAB_REGISTRY`).
        divisions: Optional pre-built divisions dict.  If None, calls
            :func:`create_system` to build the full agent swarm first.

    Returns:
        A fully wired :class:`Sublab` instance.

    Raises:
        ValueError: If *name* is not a registered sublab.
    """
    if name not in SUBLAB_REGISTRY:
        raise ValueError(
            f"Unknown sublab '{name}'. Available: {list(SUBLAB_REGISTRY.keys())}"
        )

    if divisions is None:
        divisions = create_system()

    sublab_cls = SUBLAB_REGISTRY[name]
    sublab = sublab_cls(divisions=divisions)
    logger.info("Created sublab '%s' with %d agents", name, len(sublab.agents))
    return sublab


def create_all_sublabs(
    divisions: dict[str, DivisionLead] | None = None,
) -> dict[str, Sublab]:
    """Create all registered sublabs.

    Args:
        divisions: Optional pre-built divisions dict.  If None, calls
            :func:`create_system` once and shares it across all sublabs.

    Returns:
        A dict mapping sublab names to :class:`Sublab` instances.
    """
    if divisions is None:
        divisions = create_system()

    sublabs = {}
    for name, cls in SUBLAB_REGISTRY.items():
        sublabs[name] = cls(divisions=divisions)
        logger.info("Created sublab '%s' with %d agents", name, len(sublabs[name].agents))

    return sublabs


def create_system() -> dict[str, DivisionLead]:
    """Create the fully wired Lumi Virtual Lab agent swarm.

    This is the single entry-point for bootstrapping the entire system.
    It performs three steps in order:

    1. **Create specialist agents** -- instantiate all 33 specialists via
       their factory functions.
    2. **Wire tool callables** -- for every specialist, match tool schema
       names against the master :data:`~src.mcp_bridge.TOOL_REGISTRY` and
       register the corresponding callables so that LLM-generated
       ``tool_use`` blocks resolve to real function calls.
    3. **Create division leads** -- instantiate each of the 11 division
       leads with their specialist rosters already populated.

    Returns:
        A dict mapping division names to fully populated
        :class:`DivisionLead` instances, keyed exactly as the CSO
        orchestrator expects.
    """
    logger.info("Creating Lumi Virtual Lab agent swarm...")

    # ------------------------------------------------------------------
    # Step 1: Create all specialist agents
    # ------------------------------------------------------------------

    # Division 1 -- Target Identification
    stat_gen = create_statistical_genetics_agent()
    func_gen = create_functional_genomics_agent()
    sc_atlas = create_single_cell_atlas_agent()

    # Division 2 -- Target Safety
    bio_path = create_bio_pathways_agent()
    fda_safe = create_fda_safety_agent()
    toxicog = create_toxicogenomics_agent()
    pathol = create_pathology_agent()
    physiol = create_physiology_agent()

    # Division 3 -- Modality Selection
    tgt_bio = create_target_biologist_agent()
    pharma = create_pharmacologist_agent()
    mol_bio = create_molecular_biology_agent()
    cell_bio = create_cell_biology_agent()
    biochem = create_biochemistry_agent()

    # Division 4 -- Molecular Design
    prot_intel = create_protein_intelligence_agent()
    ab_eng = create_antibody_engineer_agent()
    struct_des = create_structure_design_agent()
    lead_opt = create_lead_optimization_agent()
    develop = create_developability_agent()
    biophys = create_biophysics_agent()
    glyco = create_glycoengineering_agent()

    # Division 5 -- Clinical Intelligence
    clin_trial = create_clinical_trialist_agent()

    # Division 6 -- Computational Biology
    lit_synth = create_literature_synthesis_agent()
    sys_bio = create_systems_biology_agent()
    comp_intel = create_competitive_intelligence_agent()

    # Division 7 -- Experimental Design
    assay_des = create_assay_design_agent()
    lab_auto = create_lab_automation_agent()
    protocols = create_protocols_agent()

    # Division 8 -- Biosecurity
    dual_use = create_dual_use_screening_agent()

    # Division 9 -- Immunology & Cancer Biology
    cancer_bio = create_cancer_biology_agent()
    immuno = create_immunology_agent()

    # Division 10 -- Microbiology & Synthetic Biology
    micro = create_microbiology_agent()
    synbio = create_synthetic_biology_agent()
    bioeng = create_bioengineering_agent()

    # Division 11 -- Imaging
    bioimag = create_bioimaging_agent()

    all_agents: list[BaseAgent] = [
        stat_gen, func_gen, sc_atlas,
        bio_path, fda_safe, toxicog, pathol, physiol,
        tgt_bio, pharma, mol_bio, cell_bio, biochem,
        prot_intel, ab_eng, struct_des, lead_opt, develop, biophys, glyco,
        clin_trial,
        lit_synth, sys_bio,
        assay_des, lab_auto, protocols,
        dual_use,
        cancer_bio, immuno,
        micro, synbio, bioeng,
        bioimag,
    ]

    # ------------------------------------------------------------------
    # Step 2: Wire MCP tool implementations into each agent
    # ------------------------------------------------------------------

    for agent in all_agents:
        wire_agent_tools(agent)

    logger.info("All %d specialist agents created and wired", len(all_agents))

    # ------------------------------------------------------------------
    # Step 3: Create division leads with their specialist rosters
    # ------------------------------------------------------------------

    divisions: dict[str, DivisionLead] = {
        "Target Identification": create_target_id_lead(
            specialist_agents=[stat_gen, func_gen, sc_atlas],
        ),
        "Target Safety": create_target_safety_lead(
            specialist_agents=[bio_path, fda_safe, toxicog, pathol, physiol],
        ),
        "Modality Selection": create_modality_lead(
            specialist_agents=[tgt_bio, pharma, mol_bio, cell_bio, biochem],
        ),
        "Molecular Design": create_molecular_design_lead(
            specialist_agents=[prot_intel, ab_eng, struct_des, lead_opt, develop, biophys, glyco],
        ),
        "Clinical Intelligence": create_clinical_lead(
            specialist_agents=[clin_trial],
        ),
        "Computational Biology": create_compbio_lead(
            specialist_agents=[lit_synth, sys_bio, comp_intel],
        ),
        "Experimental Design": create_experimental_lead(
            specialist_agents=[assay_des, lab_auto, protocols],
        ),
        "Biosecurity": create_biosecurity_lead(
            specialist_agents=[dual_use],
        ),
        "Immunology & Cancer Biology": create_immunology_cancer_lead(
            specialist_agents=[cancer_bio, immuno],
        ),
        "Microbiology & Synthetic Biology": create_synbio_lead(
            specialist_agents=[micro, synbio, bioeng],
        ),
        "Imaging": create_imaging_lead(
            specialist_agents=[bioimag],
        ),
    }

    logger.info("All %d divisions created and populated", len(divisions))
    return divisions


def create_minimal_system() -> dict[str, DivisionLead]:
    """Create a minimal system with only the Biosecurity division.

    Used by the dynamic SubLab pipeline, which composes its own agents
    but still needs the biosecurity veto gate (Phase 4).

    Returns:
        A dict with a single ``"Biosecurity"`` division.
    """
    logger.info("Creating minimal system (biosecurity only) for dynamic mode...")

    dual_use = create_dual_use_screening_agent()
    wire_agent_tools(dual_use)

    divisions: dict[str, DivisionLead] = {
        "Biosecurity": create_biosecurity_lead(
            specialist_agents=[dual_use],
        ),
    }

    logger.info("Minimal system created with biosecurity division")
    return divisions
