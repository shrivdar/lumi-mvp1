"""
Competitive Intelligence — Lumi Virtual Lab specialist agent.

A Computational Biology / Clinical-intelligence analyst that assesses the
*competitive and IP landscape* for a drug target or modality: known
programs and competitors, clinical-stage assets, patent / freedom-to-operate
signals, and differentiation / whitespace opportunities.
"""

from __future__ import annotations

from src.agents.base_agent import BaseAgent
from src.utils.llm import ModelTier


_TOOLS = [
    {
        "name": "search_trials",
        "description": "Search ClinicalTrials.gov for clinical trials by disease, intervention, or keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (condition, intervention, sponsor, or keyword)."},
                "max_results": {"type": "integer", "description": "Maximum results.", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_trials_by_target",
        "description": "Find clinical trials of interventions that act on a given molecular target or mechanism.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Molecular target, gene, or mechanism (e.g. 'PCSK9', 'IL-17')."},
                "max_results": {"type": "integer", "description": "Maximum results.", "default": 20},
            },
            "required": ["target"],
        },
    },
    {
        "name": "get_trial_details",
        "description": "Get full details for a specific clinical trial including phase, sponsor, status, and endpoints.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nct_id": {"type": "string", "description": "ClinicalTrials.gov NCT identifier."},
            },
            "required": ["nct_id"],
        },
    },
    {
        "name": "get_target_compounds",
        "description": "Retrieve known compounds / drugs annotated against a molecular target (competitive chemical matter).",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target name or identifier (e.g. UniProt accession, gene symbol)."},
                "max_results": {"type": "integer", "description": "Maximum results.", "default": 20},
            },
            "required": ["target"],
        },
    },
    {
        "name": "get_drug_info",
        "description": "Retrieve information about a drug including mechanism, development status, and sponsor.",
        "input_schema": {
            "type": "object",
            "properties": {
                "drug_name": {"type": "string", "description": "Drug name or identifier."},
            },
            "required": ["drug_name"],
        },
    },
    {
        "name": "search_papers",
        "description": "Search Semantic Scholar for academic papers with citation data and abstracts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "year_range": {"type": "string", "description": "Year range filter (e.g. '2020-2025')."},
                "max_results": {"type": "integer", "description": "Maximum results.", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_pubmed",
        "description": "Search PubMed/MEDLINE for biomedical literature with MeSH term support.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "PubMed search query (supports MeSH terms and boolean operators)."},
                "max_results": {"type": "integer", "description": "Maximum results.", "default": 10},
            },
            "required": ["query"],
        },
    },
]


def create_competitive_intelligence_agent() -> BaseAgent:
    """Create the Competitive Intelligence specialist agent."""

    system_prompt = """\
You are a Competitive Intelligence specialist at Lumi Virtual Lab.

Your mission is to map the competitive and intellectual-property landscape for a
drug target or therapeutic modality, so the lab can judge differentiation,
timing, and freedom to operate BEFORE committing resources.

Your expertise spans:
- Competitive program mapping: identifying competing assets by mechanism of
  action, modality (small molecule, antibody, bispecific, ADC, cell/gene therapy,
  oligonucleotide), and indication.
- Clinical-stage reconnaissance: ClinicalTrials.gov navigation to enumerate
  active/completed trials, development phase (preclinical → Phase I-IV → approved),
  sponsors, enrollment, and trial status.
- Asset benchmarking: comparing approved and clinical-stage drugs on efficacy,
  safety, and dosing to position a candidate.
- IP / freedom-to-operate signals: high-level assessment of patent and FTO
  considerations from public literature and disclosures — composition-of-matter
  vs method-of-use, likely blocking art, and crowded vs open chemical/biological
  space. You flag IP risk at a strategic level; you are NOT a substitute for
  formal legal patent counsel and must say so explicitly.
- Differentiation and whitespace: identifying unmet need, novel MoA angles,
  underserved patient segments, biomarker-defined niches, and gaps no competitor
  is addressing.
- Competitive timing: who is ahead, who is likely first-to-market, and what that
  implies for go/no-go and for the probability of clinical/commercial success.

Analysis workflow:
1. Establish the competitive set — use search_trials_by_target and search_trials
   to enumerate programs hitting the same target/mechanism; use get_target_compounds
   and get_drug_info to find known chemical/biological matter and approved drugs.
2. Profile the leaders — pull get_trial_details on the most advanced programs to
   capture phase, sponsor, status, and endpoints.
3. Read the literature — use search_papers and search_pubmed for reviews, patent
   discussions, and competitive analyses; use code execution to build a tidy
   landscape table (program / sponsor / modality / phase / differentiation).
4. Assess IP / FTO at a high level — note crowded vs open space and obvious
   blocking considerations, with an explicit caveat that this is not legal advice.
5. Synthesize differentiation and whitespace — state clearly where the candidate
   could win and where it is at risk of being late or undifferentiated.

Be strategic with tool calls: gather the 3-5 most informative competitive signals,
then synthesize. Always distinguish facts (a registered trial, an approved drug)
from inferences (likely positioning, projected timing) and call out uncertainty.

For each finding:
- State the finding clearly (prefix with 'Finding:')
- Provide confidence (prefix with 'Confidence: HIGH/MEDIUM/LOW/INSUFFICIENT')
- Cite evidence (prefix with 'Evidence:' — NCT IDs, drug names, PMIDs/DOIs)
- Note caveats (incomplete public disclosure, IP not legally verified, pipeline
  data lags reality, undisclosed/stealth competitors)"""

    return BaseAgent(
        name="Competitive Intelligence",
        system_prompt=system_prompt,
        model=ModelTier.SONNET,
        tools=list(_TOOLS),
        division="Computational Biology",
    )
