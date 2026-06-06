"""
Lumi Virtual Lab — Specialist Agent Registry.

Factory functions for all specialist agents in the swarm.
"""

# Division 1: Target Identification
from src.agents.statistical_genetics import create_statistical_genetics_agent
from src.agents.functional_genomics import create_functional_genomics_agent
from src.agents.single_cell_atlas import create_single_cell_atlas_agent

# Division 2: Target Safety
from src.agents.bio_pathways import create_bio_pathways_agent
from src.agents.fda_safety import create_fda_safety_agent
from src.agents.toxicogenomics import create_toxicogenomics_agent
from src.agents.pathology import create_pathology_agent
from src.agents.physiology import create_physiology_agent

# Division 3: Modality
from src.agents.target_biologist import create_target_biologist_agent
from src.agents.pharmacologist import create_pharmacologist_agent
from src.agents.molecular_biology import create_molecular_biology_agent
from src.agents.cell_biology import create_cell_biology_agent
from src.agents.biochemistry import create_biochemistry_agent

# Division 4: Molecular Design
from src.agents.protein_intelligence import create_protein_intelligence_agent
from src.agents.antibody_engineer import create_antibody_engineer_agent
from src.agents.structure_design import create_structure_design_agent
from src.agents.lead_optimization import create_lead_optimization_agent
from src.agents.developability import create_developability_agent
from src.agents.biophysics import create_biophysics_agent
from src.agents.glycoengineering import create_glycoengineering_agent

# Division 5: Clinical
from src.agents.clinical_trialist import create_clinical_trialist_agent

# Division 6: CompBio
from src.agents.literature_synthesis import create_literature_synthesis_agent
from src.agents.systems_biology import create_systems_biology_agent
from src.agents.competitive_intelligence import create_competitive_intelligence_agent

# Division 7: Experimental
from src.agents.assay_design import create_assay_design_agent
from src.agents.lab_automation import create_lab_automation_agent
from src.agents.protocols import create_protocols_agent

# Division 8: Biosecurity
from src.agents.dual_use_screening import create_dual_use_screening_agent

# Division 9: Immunology & Cancer Biology
from src.agents.cancer_biology import create_cancer_biology_agent
from src.agents.immunology import create_immunology_agent

# Division 10: Microbiology & Synthetic Biology
from src.agents.microbiology import create_microbiology_agent
from src.agents.synthetic_biology import create_synthetic_biology_agent
from src.agents.bioengineering import create_bioengineering_agent

# Division 11: Imaging
from src.agents.bioimaging import create_bioimaging_agent

__all__ = [
    # Division 1: Target Identification
    "create_statistical_genetics_agent",
    "create_functional_genomics_agent",
    "create_single_cell_atlas_agent",
    # Division 2: Target Safety
    "create_bio_pathways_agent",
    "create_fda_safety_agent",
    "create_toxicogenomics_agent",
    "create_pathology_agent",
    "create_physiology_agent",
    # Division 3: Modality
    "create_target_biologist_agent",
    "create_pharmacologist_agent",
    "create_molecular_biology_agent",
    "create_cell_biology_agent",
    "create_biochemistry_agent",
    # Division 4: Molecular Design
    "create_protein_intelligence_agent",
    "create_antibody_engineer_agent",
    "create_structure_design_agent",
    "create_lead_optimization_agent",
    "create_developability_agent",
    "create_biophysics_agent",
    "create_glycoengineering_agent",
    # Division 5: Clinical
    "create_clinical_trialist_agent",
    # Division 6: CompBio
    "create_literature_synthesis_agent",
    "create_systems_biology_agent",
    "create_competitive_intelligence_agent",
    # Division 7: Experimental
    "create_assay_design_agent",
    "create_lab_automation_agent",
    "create_protocols_agent",
    # Division 8: Biosecurity
    "create_dual_use_screening_agent",
    # Division 9: Immunology & Cancer Biology
    "create_cancer_biology_agent",
    "create_immunology_agent",
    # Division 10: Microbiology & Synthetic Biology
    "create_microbiology_agent",
    "create_synthetic_biology_agent",
    "create_bioengineering_agent",
    # Division 11: Imaging
    "create_bioimaging_agent",
]

# Convenience mapping: agent name -> factory function
AGENT_REGISTRY: dict[str, callable] = {
    "statistical_genetics": create_statistical_genetics_agent,
    "functional_genomics": create_functional_genomics_agent,
    "single_cell_atlas": create_single_cell_atlas_agent,
    "bio_pathways": create_bio_pathways_agent,
    "fda_safety": create_fda_safety_agent,
    "toxicogenomics": create_toxicogenomics_agent,
    "pathology": create_pathology_agent,
    "physiology": create_physiology_agent,
    "target_biologist": create_target_biologist_agent,
    "pharmacologist": create_pharmacologist_agent,
    "molecular_biology": create_molecular_biology_agent,
    "cell_biology": create_cell_biology_agent,
    "biochemistry": create_biochemistry_agent,
    "protein_intelligence": create_protein_intelligence_agent,
    "antibody_engineer": create_antibody_engineer_agent,
    "structure_design": create_structure_design_agent,
    "lead_optimization": create_lead_optimization_agent,
    "developability": create_developability_agent,
    "biophysics": create_biophysics_agent,
    "glycoengineering": create_glycoengineering_agent,
    "clinical_trialist": create_clinical_trialist_agent,
    "literature_synthesis": create_literature_synthesis_agent,
    "systems_biology": create_systems_biology_agent,
    "competitive_intelligence": create_competitive_intelligence_agent,
    "assay_design": create_assay_design_agent,
    "lab_automation": create_lab_automation_agent,
    "protocols": create_protocols_agent,
    "dual_use_screening": create_dual_use_screening_agent,
    "cancer_biology": create_cancer_biology_agent,
    "immunology": create_immunology_agent,
    "microbiology": create_microbiology_agent,
    "synthetic_biology": create_synthetic_biology_agent,
    "bioengineering": create_bioengineering_agent,
    "bioimaging": create_bioimaging_agent,
}
