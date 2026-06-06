"""Chat endpoints — mock pipeline for GLP-1R / semaglutide / Parkinson's Disease.

Dynamic SubLab demo:
  1. CSO scopes query → selects dynamic SubLab mode
  2. Biosecurity pre-screen (GREEN)
  3. SubLab Planner composes team (3 agents, 2 execution groups)
  4. Group 1 (parallel): Pharmacology & Drug Analyst + Neuro-Genomics Analyst
  5. Group 2 (sequential): Pathway Visualization Specialist
  6. Adversarial review panel (3-pass)
  7. HITL flag on low-confidence clinical claim → opens /review tab
  8. Slack posts (if configured)
  9. HITL auto-resolved after review tab conversation plays
  10. Integrations (Slack, BioRender, Benchling)
  11. Final synthesis streamed as markdown
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

log = logging.getLogger("lumi.chat")

from api.models import (
    AgentTrace,
    Chat,
    ClarifyQuestion,
    ClarifyRequest,
    ClarifyResponse,
    CreateChatRequest,
    HitlEvent,
    IntegrationEvent,
    Message,
    ReviewDecisionRequest,
    Role,
    SendMessageRequest,
    ToolCall,
)

router = APIRouter(prefix="/chats", tags=["chats"])

# Seed sidebar with realistic past research chats
_seed_chats: list[tuple[str, str, str]] = [
    ("a1b2c3d4", "BRCA2 synthetic lethality screen — PARP inhibitor candidates", "target-validation"),
    ("e5f6a7b8", "JAK2 V617F myelofibrosis safety assessment", "target-validation"),
    ("c9d0e1f2", "CDK4/6 inhibitor resistance mechanisms in HR+ breast cancer", "dynamic"),
    ("a3b4c5d6", "TREM2 agonist antibody for Alzheimer's microglial phagocytosis", "dynamic"),
    ("e7f8a9b0", "USP1 inhibitor selectivity profiling across DUB family", "dynamic"),
    ("c1d2e3f4", "SHP2 allosteric inhibitor combo with KRAS G12C in NSCLC", "dynamic"),
    ("a5b6c7d8", "PCSK9 siRNA vs mAb cardiovascular outcomes comparison", "target-validation"),
    ("e9f0a1b2", "GLP-1R agonist repurposing for Parkinson's neuroprotection", "dynamic"),
    ("c3d4e5f6", "CFTR modulator triple therapy — ivacaftor/tezacaftor/elexacaftor", "dynamic"),
    ("a7b8c9d0", "BET bromodomain degrader PROTAC design for AML", "dynamic"),
    ("e1f2a3b4", "IL-23 p19 antibody biosimilar developability assessment", "dynamic"),
    ("c5d6e7f8", "APOE4 antisense oligonucleotide BBB penetration modeling", "dynamic"),
]

_chats: dict[str, Chat] = {}
for _id, _title, _sublab in _seed_chats:
    _c = Chat(id=_id, title=_title, sublab=_sublab)
    _c.messages.append(Message(id=f"m_{_id}", role=Role.USER, content=_title))
    _c.messages.append(Message(id=f"r_{_id}", role=Role.ASSISTANT, content=f"Analysis complete for: {_title}"))
    _chats[_id] = _c


# ===========================================================================
# Mock response text — GLP-1R neuroprotection assessment
# ===========================================================================


def _mock_response_text() -> str:
    return (
        "## GLP-1R Agonist Repurposing Assessment — Parkinson's Disease\n\n"
        "### Executive Summary\n\n"
        "GLP-1 receptor agonists, including semaglutide, represent a **scientifically plausible** "
        "neuroprotective strategy for early-stage Parkinson's disease. The GLP-1R → cAMP → PKA → "
        "CREB → BDNF signaling cascade is validated in dopaminergic neurons of the substantia nigra, "
        "with additional anti-inflammatory effects via microglial modulation. However, clinical evidence "
        "remains **preliminary**, resting primarily on a single Phase II exenatide trial (n=62).\n\n"
        "---\n\n"
        "### Dynamic SubLab Execution\n\n"
        "- **Mode**: Dynamic SubLab (cross-domain tool mixing)\n"
        "- **Team**: 3 agents, 2 execution groups, 8 tools across 5 domains\n"
        "- **Biosecurity**: Pre-screen PASSED (GREEN)\n"
        "- **Review**: 3-pass adversarial — 6/7 findings approved, 1 routed to HITL\n"
        "- **HITL**: Clinical efficacy claim reviewed and approved with uncertainty label\n\n"
        "---\n\n"
        "### Key Findings\n\n"
        "| # | Finding | Agent | Confidence |\n"
        "|---|---------|-------|------------|\n"
        "| 1 | GLP1R expressed in SN dopaminergic neurons (TPM: 3.2), co-localized with TH | neuro_genomics_analyst | **HIGH** 88% |\n"
        "| 2 | Validated cascade: GLP-1R → Gαs → cAMP → PKA → CREB → BDNF → neuronal survival | neuro_genomics_analyst | **HIGH** 91% |\n"
        "| 3 | PI3K/Akt anti-apoptotic branch provides additional neuronal protection | neuro_genomics_analyst | **HIGH** 85% |\n"
        "| 4 | Semaglutide: established safety from >10M patient-years in diabetes/obesity | pharmacology_drug_analyst | **HIGH** 95% |\n"
        "| 5 | 4 active clinical trials for GLP-1 agonists in PD (Phase II–III) | pharmacology_drug_analyst | **HIGH** 90% |\n"
        "| 6 | Epidemiological signal: 20-30% lower PD incidence in GLP-1 agonist users | neuro_genomics_analyst | **MED** 62% |\n"
        "| 7 | Disease-modifying efficacy in PD *(HITL-reviewed, Phase II only)* | pharmacology_drug_analyst | **LOW** 38% |\n\n"
        "---\n\n"
        "### GLP-1R Neuroprotective Pathway\n\n"
        "```\n"
        "Semaglutide → GLP-1R → Gαs → cAMP → PKA → CREB → BDNF → Neuronal Survival\n"
        "                                    ↘ PI3K → Akt → Anti-apoptosis\n"
        "                               ↘ Microglial NF-κB ↓ → Reduced Neuroinflammation\n"
        "```\n\n"
        "### Risk Assessment\n\n"
        "- **Biological plausibility**: Strong — GLP1R expression in target neurons, mechanism well-characterized\n"
        "- **Safety**: Low risk — extensive safety data from diabetes/obesity; CNS-specific AEs minimal\n"
        "- **Clinical evidence**: Moderate risk — Phase II positive but underpowered; Phase III pending\n"
        "- **BBB penetration**: Moderate concern — limited but detectable CSF levels; NLY01 (brain-penetrant) in Phase II\n\n"
        "### Recommended Next Steps\n\n"
        "1. Monitor Exenatide-PD3 Phase III trial (NCT04232969) — efficacy readout expected 2025\n"
        "2. Evaluate semaglutide CSF penetration via PET imaging with radiolabeled analog\n"
        "3. Profile GLP-1R expression changes across Braak stages using spatial transcriptomics\n"
        "4. Assess synergy with existing PD therapeutics (levodopa, MAO-B inhibitors) in preclinical models\n\n"
        "### Integrations\n\n"
        "- Findings posted to **#neuro-repurposing** on Slack\n"
        "- GLP-1R pathway diagram generated via **BioRender**\n"
        "- Notebook entry **EXP-2026-0417** created in **Benchling**\n\n"
        "---\n\n"
        "*Overall confidence: **MEDIUM-HIGH** (0.76) · Cost: $3.18 · Duration: 2m 34s · 3 agents · 5 domains · Dynamic SubLab*"
    )


# ===========================================================================
# Mock response text — PARP + PD-L1 combination TNBC
# ===========================================================================


def _mock_response_text_parp() -> str:
    return (
        "## PARP Inhibitor + Anti-PD-L1 Combination Assessment — BRCA1-Mutant TNBC\n\n"
        "### Executive Summary\n\n"
        "The combination of PARP inhibition (olaparib/talazoparib) with anti-PD-L1 checkpoint blockade "
        "(atezolizumab) represents a **mechanistically rational** strategy for BRCA1-mutant triple-negative "
        "breast cancer. Synthetic lethality via PARP trapping in HR-deficient tumor cells is well-validated "
        "(Bryant & Farmer, 2005), and BRCA1-mutant TNBCs exhibit elevated PD-L1 expression (45–60%) and "
        "higher tumor mutational burden, creating a favorable immunogenic context. However, the proposed "
        "PD-L1/PARP-trapping bispecific antibody remains **highly speculative** — no validated format exists "
        "for antibody-conjugated PARP-trapping moieties.\n\n"
        "---\n\n"
        "### Dynamic SubLab Execution\n\n"
        "- **Mode**: Dynamic SubLab (cross-domain tool mixing)\n"
        "- **Team**: 5 agents, 3 execution groups, 14 tools across 6 domains\n"
        "- **Biosecurity**: Pre-screen PASSED (GREEN)\n"
        "- **Review**: 3-pass adversarial — 8/9 findings approved, 1 routed to HITL\n"
        "- **HITL**: Bispecific antibody feasibility reviewed — approved for in silico exploration only\n\n"
        "---\n\n"
        "### Key Findings\n\n"
        "| # | Finding | Agent | Confidence |\n"
        "|---|---------|-------|------------|\n"
        "| 1 | BRCA1 loss-of-function confers synthetic lethality with PARP inhibition via HR-deficiency | synthetic_lethality_analyst | **HIGH** 94% |\n"
        "| 2 | Olaparib/talazoparib trap PARP1 on DNA → replication fork collapse → cell death in BRCA1⁻/⁻ | structural_biology_lead_opt | **HIGH** 92% |\n"
        "| 3 | BRCA1-mutant TNBC shows elevated PD-L1 (45–60%) and TMB (avg 8.2 mut/Mb) | immuno_oncology_analyst | **HIGH** 88% |\n"
        "| 4 | MEDIOLA trial: olaparib + durvalumab showed 63% DCR in BRCA-mutant breast cancer | immuno_oncology_analyst | **HIGH** 85% |\n"
        "| 5 | PARP inhibitors upregulate PD-L1 via cGAS-STING pathway activation | synthetic_lethality_analyst | **HIGH** 82% |\n"
        "| 6 | Combination toxicity manageable: overlapping anemia (12%) and neutropenia (8%) | toxicology_safety_profiler | **HIGH** 79% |\n"
        "| 7 | PARP1 catalytic domain structure (PDB: 7KK5) amenable to trapping-optimized derivatives | structural_biology_lead_opt | **MED** 71% |\n"
        "| 8 | Talazoparib shows 100x stronger PARP trapping vs olaparib in biochemical assays | structural_biology_lead_opt | **MED** 68% |\n"
        "| 9 | PD-L1/PARP-trapping bispecific antibody feasibility *(HITL-reviewed, in silico only)* | bispecific_antibody_engineer | **LOW** 32% |\n\n"
        "---\n\n"
        "### Synthetic Lethality & Combination Mechanism\n\n"
        "```\n"
        "BRCA1 Loss → HR Deficiency → Reliance on PARP-mediated BER\n"
        "                              ↓\n"
        "PARP Inhibitor (Trapping) → PARP1-DNA Complex → Replication Fork Collapse → DSBs → Tumor Cell Death\n"
        "                              ↓\n"
        "cGAS-STING Activation → Type I IFN → PD-L1 Upregulation + Neoantigen Presentation\n"
        "                              ↓\n"
        "Anti-PD-L1 (Atezolizumab) → T-cell Reactivation → Immune-Mediated Killing\n"
        "```\n\n"
        "### PARP1 Structure & Binding\n\n"
        "3D structure rendered via PyMOL (PDB: 7KK5). Olaparib occupies the nicotinamide-binding subsite "
        "of the PARP1 catalytic domain (residues 662–1014). Key trapping contacts: H862 (π-stacking), "
        "Y907 (hydrogen bond), E988 (electrostatic). Druggable pocket volume: 847 Å³.\n\n"
        "### Risk Assessment\n\n"
        "- **Synthetic lethality**: Strong — landmark evidence since 2005, FDA-approved PARP inhibitors in BRCA+ cancers\n"
        "- **Combination rationale**: Strong — PARP inhibition primes immune response via STING pathway\n"
        "- **Safety**: Moderate — manageable overlapping hematologic toxicity, immune-related AEs\n"
        "- **Bispecific antibody**: High risk — no precedent for PARP-trapping antibody conjugate format\n"
        "- **CMC feasibility**: High risk — dual-mechanism payload stability, manufacturing scalability unknown\n\n"
        "### Recommended Next Steps\n\n"
        "1. Prioritize conventional combination (olaparib + atezolizumab) for near-term clinical development\n"
        "2. Initiate in silico modeling of PD-L1/PARP-trapping bispecific format (Rosetta, AlphaFold-Multimer)\n"
        "3. Profile PARP-trapping moiety stability when conjugated to antibody scaffold\n"
        "4. Evaluate talazoparib as preferred PARP component (stronger trapping, lower dose requirement)\n"
        "5. Design Phase Ib dose-escalation for combination in BRCA1-mutant TNBC (biomarker-selected)\n\n"
        "### Integrations\n\n"
        "- Findings posted to **#tnbc-combination-therapy** on Slack\n"
        "- PARP1-olaparib binding structure rendered via **PyMOL**\n"
        "- Bispecific antibody design notebook **EXP-2026-0892** created in **Benchling**\n\n"
        "---\n\n"
        "*Overall confidence: **MEDIUM-HIGH** (0.74) · Cost: $4.87 · Duration: 3m 48s · 5 agents · 6 domains · Dynamic SubLab*"
    )


# ===========================================================================
# Mock streaming — Dynamic SubLab pipeline
# ===========================================================================


async def _try_slack_post(channel: str, text: str, blocks_json: str | None = None, **kwargs) -> str | None:
    """Post to Slack if configured. Returns thread_ts or None."""
    try:
        from src.mcp_servers.slack.server import slack_post_message
        result = await slack_post_message(channel=channel, text=text, blocks_json=blocks_json, **kwargs)
        if not result.get("error"):
            return result.get("raw_data", {}).get("ts")
    except Exception as exc:
        log.debug("Slack post skipped: %s", exc)
    return None


async def _try_slack_reply(channel: str, thread_ts: str, text: str, **kwargs) -> str | None:
    """Reply in Slack thread if configured. Returns ts or None."""
    try:
        from src.mcp_servers.slack.server import slack_post_thread_reply
        result = await slack_post_thread_reply(channel=channel, thread_ts=thread_ts, text=text, **kwargs)
        if not result.get("error"):
            return result.get("raw_data", {}).get("ts")
    except Exception as exc:
        log.debug("Slack reply skipped: %s", exc)
    return None


async def _stream_mock(chat: Chat, msg_id: str):
    """Stream the GLP-1R dynamic SubLab demo with realistic timing."""
    import os
    slack_channel = os.environ.get("LUMI_SLACK_CHANNEL", "")

    all_traces: list[AgentTrace] = []
    all_hitl: list[HitlEvent] = []
    all_integrations: list[IntegrationEvent] = []

    def _sse(event_type: str, data: dict) -> str:
        data["message_id"] = msg_id
        data["type"] = event_type
        return f"data: {json.dumps(data, default=str)}\n\n"

    # ── Phase 1: CSO Scoping ──

    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="cso_orchestrator", division="Orchestration", status="running",
        message="Analyzing research query...",
    ).model_dump()})
    await asyncio.sleep(2.0)

    cso_done = AgentTrace(
        agent_id="cso_orchestrator", division="Orchestration", status="complete",
        message="Query parsed. Drug repurposing assessment across neurology + pharmacology. Selecting Dynamic SubLab mode.",
        tools_called=[
            ToolCall(tool_name="parse_research_query", tool_input={"query": "GLP-1R semaglutide neurodegeneration Parkinson's"}, result="Target: GLP1R | Drug: semaglutide | Indication: PD | Task: repurposing assessment", duration_ms=580),
            ToolCall(tool_name="select_sublab_mode", tool_input={"domains": ["pharmacology", "neurology", "genomics", "clinical"]}, result="Dynamic SubLab — 4 domains require cross-domain tool mixing", duration_ms=290),
        ],
        confidence_score=0.96, confidence_level="HIGH", duration_ms=1820,
    )
    yield _sse("trace_complete", {"trace": cso_done.model_dump()})
    all_traces.append(cso_done)
    await asyncio.sleep(1.0)

    # ── Phase 2: Biosecurity Pre-screen ──

    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="biosecurity_officer", division="Biosecurity", status="running",
        message="Screening for dual-use risk...",
    ).model_dump()})
    await asyncio.sleep(1.0)

    bio_tool = ToolCall(
        tool_name="screen_biosecurity",
        tool_input={"query": "semaglutide GLP-1 agonist Parkinson's neuroprotection"},
        result="5/5 screens passed — GREEN. FDA-approved diabetes drug, no dual-use concern.",
        duration_ms=740,
    )
    yield _sse("tool_call", {"agent_id": "biosecurity_officer", "tool": bio_tool.model_dump()})
    await asyncio.sleep(1.0)

    bio_done = AgentTrace(
        agent_id="biosecurity_officer", division="Biosecurity", status="complete",
        message="Pre-screen PASSED. Category: GREEN. No dual-use, toxin, or GoF risk.",
        tools_called=[bio_tool],
        confidence_score=1.0, confidence_level="HIGH", duration_ms=960,
    )
    yield _sse("trace_complete", {"trace": bio_done.model_dump()})
    all_traces.append(bio_done)
    await asyncio.sleep(0.8)

    # ── Phase 3: SubLab Planning ──

    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="sublab_planner", division="Orchestration", status="running",
        message="Planning dynamic agent team (Opus)...",
    ).model_dump()})
    await asyncio.sleep(2.0)

    plan_done = AgentTrace(
        agent_id="sublab_planner", division="Orchestration", status="complete",
        message=(
            "Team composed: 3 agents in 2 execution groups.\n"
            "Group 1 (parallel): Pharmacology & Drug Analyst, Neuro-Genomics Analyst\n"
            "Group 2 (sequential): Pathway Visualization Specialist"
        ),
        tools_called=[
            ToolCall(
                tool_name="compose_team",
                tool_input={"domains": ["pharmacology", "neurology", "genomics", "clinical", "pathways"], "tools": 119},
                result="3 agents selected, 8 tools assigned across 5 domains",
                duration_ms=1240,
            ),
        ],
        confidence_score=0.98, confidence_level="HIGH", duration_ms=2140,
    )
    yield _sse("trace_complete", {"trace": plan_done.model_dump()})
    all_traces.append(plan_done)
    await asyncio.sleep(1.0)

    # ── Phase 4: Group 1 — Parallel Data Gathering ──

    # Start both agents simultaneously
    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="pharmacology_drug_analyst", division="Dynamic SubLab · Group 1", status="running",
        message="Gathering drug, trial, safety, and literature data...",
    ).model_dump()})
    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="neuro_genomics_analyst", division="Dynamic SubLab · Group 1", status="running",
        message="Gathering gene, expression, pathway, and GWAS data...",
    ).model_dump()})
    await asyncio.sleep(1.5)

    # Tool calls for each agent
    pharma_tools = [
        ToolCall(tool_name="get_drug_info", tool_input={"drug": "semaglutide"}, result="GLP-1 receptor agonist. MW: 4113.6 Da. Half-life: ~7 days. FDA-approved T2DM/obesity. BBB penetration: limited but detectable in CSF.", duration_ms=1180),
        ToolCall(tool_name="search_trials", tool_input={"query": "GLP-1 Parkinson's disease"}, result="4 trials: NCT01971242 (exenatide Phase II, completed), NCT04232969 (exenatide Phase III, recruiting), NCT04154072 (lixisenatide Phase II), NCT05819372 (NLY01 Phase II)", duration_ms=1420),
        ToolCall(tool_name="search_pubmed", tool_input={"query": "GLP1R neuroprotection Parkinson dopaminergic"}, result="187 results. Key: Athauda 2017 (exenatide RCT), Kim 2017 (GLP-1R in DA neurons), Yun 2018 (NLY01 neuroprotection)", duration_ms=1340),
        ToolCall(tool_name="get_side_effects", tool_input={"drug": "semaglutide"}, result="Common: nausea (20%), diarrhea (10%), vomiting (8%). Serious: pancreatitis (0.3%). Established safety >10M patient-years.", duration_ms=980),
    ]
    neuro_tools = [
        ToolCall(tool_name="get_gene_info", tool_input={"gene": "GLP1R"}, result="GLP1R: 6p21.2, 463 aa, class B1 GPCR. Expression: pancreas (high), brain (moderate — substantia nigra, hippocampus, cortex).", duration_ms=1090),
        ToolCall(tool_name="get_gene_expression", tool_input={"gene": "GLP1R", "tissue": "brain"}, result="Substantia nigra TPM: 3.2, hippocampus: 4.8, cortex: 2.1, hypothalamus: 8.7. Co-expressed with TH in DA neurons.", duration_ms=1560),
        ToolCall(tool_name="get_pathways_for_gene", tool_input={"gene": "GLP1R"}, result="KEGG: hsa04024 (cAMP), hsa04151 (PI3K-Akt). Cascade: GLP-1R → Gαs → cAMP → PKA → CREB → BDNF → neuronal survival.", duration_ms=1380),
        ToolCall(tool_name="query_gwas_associations", tool_input={"gene": "GLP1R"}, result="rs10305492 A316T: T2DM protection (OR=0.86). No direct PD GWAS hits. Epidemiological: GLP-1 users show 20-30% lower PD incidence.", duration_ms=1240),
    ]

    # Interleave tool calls — demonstrates parallel execution
    for i in range(4):
        yield _sse("tool_call", {"agent_id": "pharmacology_drug_analyst", "tool": pharma_tools[i].model_dump()})
        await asyncio.sleep(1.0)
        yield _sse("tool_call", {"agent_id": "neuro_genomics_analyst", "tool": neuro_tools[i].model_dump()})
        await asyncio.sleep(1.0)

    await asyncio.sleep(0.8)

    # Complete both agents
    pharma_done = AgentTrace(
        agent_id="pharmacology_drug_analyst", division="Dynamic SubLab · Group 1", status="complete",
        message="Semaglutide: validated GLP-1 agonist with established safety. 4 active PD trials. Phase II exenatide data showed motor improvement (n=62) but limited. Safety well-characterized (>10M patient-years).",
        tools_called=pharma_tools,
        confidence_score=0.82, confidence_level="HIGH", duration_ms=8420,
    )
    yield _sse("trace_complete", {"trace": pharma_done.model_dump()})
    all_traces.append(pharma_done)
    await asyncio.sleep(0.6)

    neuro_done = AgentTrace(
        agent_id="neuro_genomics_analyst", division="Dynamic SubLab · Group 1", status="complete",
        message="GLP1R expressed in SN dopaminergic neurons (TPM: 3.2), co-localized with TH. Validated cascade: GLP-1R → cAMP → PKA → CREB → BDNF. PI3K/Akt provides anti-apoptotic signaling. Epidemiological association with lower PD incidence.",
        tools_called=neuro_tools,
        confidence_score=0.88, confidence_level="HIGH", duration_ms=9270,
    )
    yield _sse("trace_complete", {"trace": neuro_done.model_dump()})
    all_traces.append(neuro_done)
    await asyncio.sleep(1.0)

    # ── Phase 5: Group 2 — Synthesis & Visualization ──

    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="pathway_visualization", division="Dynamic SubLab · Group 2", status="running",
        message="Generating pathway and MOA diagrams from Group 1 findings...",
    ).model_dump()})
    await asyncio.sleep(1.5)

    viz_tools = [
        ToolCall(
            tool_name="generate_pathway_diagram",
            tool_input={"title": "GLP-1R Neuroprotective Signaling in PD", "nodes": ["GLP-1R", "Gαs", "cAMP", "PKA", "CREB", "BDNF", "Neuronal Survival", "PI3K", "Akt", "Anti-apoptosis"]},
            result="Pathway diagram: 10 nodes, 9 edges. Linear cascade with PI3K/Akt branch.",
            duration_ms=2340,
        ),
        ToolCall(
            tool_name="generate_moa_diagram",
            tool_input={"drug": "semaglutide", "target": "GLP-1R", "indication": "Parkinson's disease"},
            result="MOA diagram: semaglutide → GLP-1R → dual neuroprotective mechanism in substantia nigra.",
            duration_ms=1890,
        ),
    ]
    for tool in viz_tools:
        yield _sse("tool_call", {"agent_id": "pathway_visualization", "tool": tool.model_dump()})
        await asyncio.sleep(1.2)

    await asyncio.sleep(0.8)
    viz_done = AgentTrace(
        agent_id="pathway_visualization", division="Dynamic SubLab · Group 2", status="complete",
        message="Generated pathway diagram (GLP-1R → BDNF cascade with PI3K/Akt branch) and MOA diagram for semaglutide in PD.",
        tools_called=viz_tools,
        confidence_score=0.94, confidence_level="HIGH", duration_ms=5840,
    )
    yield _sse("trace_complete", {"trace": viz_done.model_dump()})
    all_traces.append(viz_done)
    await asyncio.sleep(1.0)

    # ── Phase 6: Adversarial Review Panel ──

    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="review_panel", division="Orchestration", status="running",
        message="Running 3-pass adversarial review (methodology → evidence → synthesis)...",
    ).model_dump()})
    await asyncio.sleep(1.5)

    review_tool = ToolCall(
        tool_name="confidence_calibration",
        tool_input={"claims": 7, "method": "3-pass adversarial"},
        result="7 claims scored. Auto-pass (≥0.70): GLP1R expression, cAMP/CREB mechanism, semaglutide safety. Soft-flag: clinical efficacy (0.38). Mean: 0.76.",
        duration_ms=860,
    )
    yield _sse("tool_call", {"agent_id": "review_panel", "tool": review_tool.model_dump()})
    await asyncio.sleep(1.0)

    review_done = AgentTrace(
        agent_id="review_panel", division="Orchestration", status="complete",
        message="3-pass adversarial review complete. 6/7 findings APPROVED (≥0.70). 1 flagged SOFT (0.38) — clinical efficacy routed to HITL.",
        tools_called=[review_tool],
        confidence_score=0.92, confidence_level="HIGH", duration_ms=2180,
    )
    yield _sse("trace_complete", {"trace": review_done.model_dump()})
    all_traces.append(review_done)
    await asyncio.sleep(1.0)

    # ── Phase 7: HITL — Flag low-confidence clinical claim ──

    finding_id = "review_glp1r_clin_001"

    clinical_hitl = {
        "finding": "GLP-1 receptor agonists show disease-modifying potential in Parkinson's disease, with motor score improvement in the exenatide Phase II trial (Athauda et al., 2017, n=62).",
        "agent_id": "pharmacology_drug_analyst",
        "confidence_score": 0.38,
        "reason": "Below 0.50 threshold. Single Phase II RCT (n=62), open-label extension with mixed results. No Phase III data. Exenatide-PD3 (NCT04232969) pending.",
        "finding_id": finding_id,
        "status": "pending",
    }
    yield _sse("hitl_flag", {"hitl": clinical_hitl})

    # Post to Slack (real API call if configured)
    thread_ts = None
    if slack_channel:
        thread_ts = await _try_slack_post(
            channel=slack_channel,
            text=(
                "Lumi HITL Review | Confidence: 38%\n"
                "Finding: GLP-1 receptor agonists show disease-modifying potential in PD "
                "(Athauda et al., 2017, n=62).\n"
                "Agent: pharmacology_drug_analyst"
            ),
            username="Lumi Agent",
            icon_emoji=":microscope:",
        )
        if thread_ts is None:
            yield _sse("warning", {"message": "Slack notification failed — expert may not be alerted. Check LUMI_SLACK_BOT_TOKEN."})

    # Post expert conversation to Slack thread (if configured) — UI handles its own playback
    expert_messages = [
        ("Lumi Agent", "AI Scientist", "agent",
         "I've flagged a clinical finding for your review. The evidence suggests GLP-1R agonists "
         "may be disease-modifying in Parkinson's, but confidence is low (38%). The primary evidence "
         "is a single Phase II trial with 62 participants (Athauda et al., 2017)."),
        ("Dr. Sarah Chen", "Neuropharmacologist", "expert",
         "The Athauda 2017 exenatide trial showed motor improvement at 60 weeks, but it was "
         "open-label initially. What was the effect size in the placebo-controlled phase? "
         "And are there any replication studies underway?"),
        ("Lumi Agent", "AI Scientist", "agent",
         "MDS-UPDRS Part 3 off-medication: exenatide -1.0 pts vs placebo +2.1 pts "
         "(adjusted difference: -3.5, 95% CI: -6.7 to -0.3, p=0.04). No independent "
         "replication yet, but Exenatide-PD3 Phase III (NCT04232969, n=200) is actively recruiting. "
         "Lixisenatide and NLY01 (brain-penetrant GLP-1 agonist) Phase II trials also ongoing."),
        ("Dr. Sarah Chen", "Neuropharmacologist", "expert",
         "Effect size is modest but statistically significant. Given it's a single underpowered "
         "trial, I'll approve this for inclusion with an explicit uncertainty label. The open-label "
         "extension showed benefit persisted at 2 years, which is encouraging. Track the Phase III "
         "for definitive evidence."),
    ]
    if slack_channel and thread_ts:
        for name, title, role, text in expert_messages:
            await _try_slack_reply(
                channel=slack_channel,
                thread_ts=thread_ts,
                text=f"*{name}* ({title})\n{text}",
                username=name,
                icon_emoji=":microscope:" if role == "agent" else ":female-scientist:",
            )

    # Wait for review tab conversation to auto-play (~12s), then resolve
    await asyncio.sleep(12.0)

    clinical_resolved = {
        **clinical_hitl,
        "status": "approved",
        "reason": "Dr. Sarah Chen: Include as promising signal with explicit uncertainty label. Phase II is hypothesis-generating. Track Exenatide-PD3 Phase III for definitive evidence.",
    }
    yield _sse("hitl_resolved", {"hitl": clinical_resolved})
    all_hitl.append(HitlEvent(**clinical_resolved))
    await asyncio.sleep(1.2)

    # ── Phase 8: Integrations ──

    # Post findings summary to Slack (real API call if configured)
    slack_detail = "7 findings, 1 HITL-reviewed. 3 agents across 5 domains. Confidence: 0.76."
    if slack_channel:
        summary_ts = await _try_slack_post(
            channel=slack_channel,
            text=f"Lumi Pipeline Complete | GLP-1R Neuroprotection Assessment\n{slack_detail}",
            username="Lumi",
            icon_emoji=":dna:",
        )
        if summary_ts is None:
            yield _sse("warning", {"message": "Slack summary post failed — findings were not posted to Slack."})

    integrations = [
        IntegrationEvent(integration="Slack", action="Posted findings summary to #neuro-repurposing", status="complete", detail=slack_detail),
        IntegrationEvent(integration="BioRender", action="Generated GLP-1R neuroprotective signaling pathway diagram", status="complete", detail="10-node cascade: GLP-1R → BDNF with PI3K/Akt and anti-inflammatory branches."),
        IntegrationEvent(integration="Benchling", action="Created notebook entry EXP-2026-0417", status="complete", detail="Linked GLP-1R repurposing dossier to PD-Neuroprotection project."),
    ]
    for integ in integrations:
        all_integrations.append(integ)
        yield _sse("integration", {"call": integ.model_dump()})
        await asyncio.sleep(1.2)

    # ── Phase 9: Final synthesis ──

    text = _mock_response_text()
    chunks = [text[i:i + 80] for i in range(0, len(text), 80)]
    accumulated = ""
    for chunk in chunks:
        accumulated += chunk
        yield _sse("text_delta", {"delta": chunk})
        await asyncio.sleep(0.05)

    # Store message
    assistant_msg = Message(
        id=msg_id, role=Role.ASSISTANT, content=accumulated,
        agent_traces=all_traces, hitl_events=all_hitl, integration_events=all_integrations,
    )
    chat.messages.append(assistant_msg)
    chat.updated_at = datetime.now(timezone.utc)

    yield _sse("done", {})


# ===========================================================================
# Mock streaming — PARP + PD-L1 combination (BRCA1-mutant TNBC)
# ===========================================================================


def _mock_response_text_parp() -> str:
    return (
        "## PARP Inhibitor + Anti-PD-L1 Combination Assessment — BRCA1-Mutant TNBC\n\n"
        "### Executive Summary\n\n"
        "The combination of PARP inhibition (olaparib/talazoparib) with anti-PD-L1 checkpoint blockade "
        "(atezolizumab) represents a **mechanistically rational** strategy for BRCA1-mutant triple-negative "
        "breast cancer. Synthetic lethality via PARP trapping in HR-deficient tumor cells is well-validated "
        "(Bryant & Farmer, 2005), and BRCA1-mutant TNBCs exhibit elevated PD-L1 expression (45–60%) and "
        "higher tumor mutational burden, creating a favorable immunogenic context. However, the proposed "
        "PD-L1/PARP-trapping bispecific antibody remains **highly speculative** — no validated format exists "
        "for antibody-conjugated PARP-trapping moieties.\n\n"
        "---\n\n"
        "### Dynamic SubLab Execution\n\n"
        "- **Mode**: Dynamic SubLab (cross-domain tool mixing)\n"
        "- **Team**: 5 agents, 3 execution groups, 14 tools across 6 domains\n"
        "- **Biosecurity**: Pre-screen PASSED (GREEN)\n"
        "- **Review**: 3-pass adversarial — 8/9 findings approved, 1 routed to HITL\n"
        "- **HITL**: Bispecific antibody feasibility reviewed — approved for in silico exploration only\n\n"
        "---\n\n"
        "### Key Findings\n\n"
        "| # | Finding | Agent | Confidence |\n"
        "|---|---------|-------|------------|\n"
        "| 1 | BRCA1 loss-of-function confers synthetic lethality with PARP inhibition via HR-deficiency | synthetic_lethality_analyst | **HIGH** 94% |\n"
        "| 2 | Olaparib/talazoparib trap PARP1 on DNA → replication fork collapse → cell death in BRCA1⁻/⁻ | structural_biology_lead_opt | **HIGH** 92% |\n"
        "| 3 | BRCA1-mutant TNBC shows elevated PD-L1 (45–60%) and TMB (avg 8.2 mut/Mb) | immuno_oncology_analyst | **HIGH** 88% |\n"
        "| 4 | MEDIOLA trial: olaparib + durvalumab showed 63% DCR in BRCA-mutant breast cancer | immuno_oncology_analyst | **HIGH** 85% |\n"
        "| 5 | PARP inhibitors upregulate PD-L1 via cGAS-STING pathway activation | synthetic_lethality_analyst | **HIGH** 82% |\n"
        "| 6 | Combination toxicity manageable: overlapping anemia (12%) and neutropenia (8%) | toxicology_safety_profiler | **HIGH** 79% |\n"
        "| 7 | PARP1 catalytic domain structure (PDB: 7KK5) amenable to trapping-optimized derivatives | structural_biology_lead_opt | **MED** 71% |\n"
        "| 8 | Talazoparib shows 100x stronger PARP trapping vs olaparib in biochemical assays | structural_biology_lead_opt | **MED** 68% |\n"
        "| 9 | PD-L1/PARP-trapping bispecific antibody feasibility *(HITL-reviewed, in silico only)* | bispecific_antibody_engineer | **LOW** 32% |\n\n"
        "---\n\n"
        "### Synthetic Lethality & Combination Mechanism\n\n"
        "```\n"
        "BRCA1 Loss → HR Deficiency → Reliance on PARP-mediated BER\n"
        "                              ↓\n"
        "PARP Inhibitor (Trapping) → PARP1-DNA Complex → Replication Fork Collapse → DSBs → Tumor Cell Death\n"
        "                              ↓\n"
        "cGAS-STING Activation → Type I IFN → PD-L1 Upregulation + Neoantigen Presentation\n"
        "                              ↓\n"
        "Anti-PD-L1 (Atezolizumab) → T-cell Reactivation → Immune-Mediated Killing\n"
        "```\n\n"
        "### PARP1 Structure & Binding\n\n"
        "3D structure rendered via PyMOL (PDB: 7KK5). Olaparib occupies the nicotinamide-binding subsite "
        "of the PARP1 catalytic domain (residues 662–1014). Key trapping contacts: H862 (π-stacking), "
        "Y907 (hydrogen bond), E988 (electrostatic). Druggable pocket volume: 847 Å³.\n\n"
        "### Risk Assessment\n\n"
        "- **Synthetic lethality**: Strong — landmark evidence since 2005, FDA-approved PARP inhibitors in BRCA+ cancers\n"
        "- **Combination rationale**: Strong — PARP inhibition primes immune response via STING pathway\n"
        "- **Safety**: Moderate — manageable overlapping hematologic toxicity, immune-related AEs\n"
        "- **Bispecific antibody**: High risk — no precedent for PARP-trapping antibody conjugate format\n"
        "- **CMC feasibility**: High risk — dual-mechanism payload stability, manufacturing scalability unknown\n\n"
        "### Recommended Next Steps\n\n"
        "1. Prioritize conventional combination (olaparib + atezolizumab) for near-term clinical development\n"
        "2. Initiate in silico modeling of PD-L1/PARP-trapping bispecific format (Rosetta, AlphaFold-Multimer)\n"
        "3. Profile PARP-trapping moiety stability when conjugated to antibody scaffold\n"
        "4. Evaluate talazoparib as preferred PARP component (stronger trapping, lower dose requirement)\n"
        "5. Design Phase Ib dose-escalation for combination in BRCA1-mutant TNBC (biomarker-selected)\n\n"
        "### Integrations\n\n"
        "- Findings posted to **#tnbc-combination-therapy** on Slack\n"
        "- PARP1-olaparib binding structure rendered via **PyMOL**\n"
        "- Bispecific antibody design notebook **EXP-2026-0892** created in **Benchling**\n\n"
        "---\n\n"
        "*Overall confidence: **MEDIUM-HIGH** (0.74) · Cost: $4.87 · Duration: 3m 48s · 5 agents · 6 domains · Dynamic SubLab*"
    )


async def _stream_mock_parp(chat: Chat, msg_id: str):
    """Stream the PARP/PD-L1 bispecific dynamic SubLab demo."""
    slack_channel = os.environ.get("LUMI_SLACK_CHANNEL", "")

    all_traces: list[AgentTrace] = []
    all_hitl: list[HitlEvent] = []
    all_integrations: list[IntegrationEvent] = []

    def _sse(event_type: str, data: dict) -> str:
        data["message_id"] = msg_id
        data["type"] = event_type
        return f"data: {json.dumps(data, default=str)}\n\n"

    # ── Phase 1: CSO Scoping ──

    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="cso_orchestrator", division="Orchestration", status="running",
        message="Parsing combination therapy query across oncology, immunology, and structural biology...",
    ).model_dump()})
    await asyncio.sleep(2.5)

    cso_done = AgentTrace(
        agent_id="cso_orchestrator", division="Orchestration", status="complete",
        message="Query parsed. PARP + anti-PD-L1 combination for BRCA1-mutant TNBC. Covers synthetic lethality, structural optimization, safety, and bispecific antibody developability.",
        tools_called=[
            ToolCall(tool_name="parse_research_query", tool_input={"query": "PARP inhibitor anti-PD-L1 BRCA1 TNBC bispecific"}, result="Target: PARP1 + PD-L1 | Indication: BRCA1-mut TNBC | Task: combination assessment + bispecific feasibility", duration_ms=620),
            ToolCall(tool_name="select_sublab_mode", tool_input={"domains": ["oncology", "immunology", "structural_biology", "toxicology", "antibody_engineering", "clinical"]}, result="Dynamic SubLab — 6 domains require cross-domain tool mixing", duration_ms=310),
        ],
        confidence_score=0.97, confidence_level="HIGH", duration_ms=2180,
    )
    yield _sse("trace_complete", {"trace": cso_done.model_dump()})
    all_traces.append(cso_done)
    await asyncio.sleep(1.0)

    # ── Phase 2: Biosecurity Pre-screen ──

    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="biosecurity_officer", division="Biosecurity", status="running",
        message="Screening PARP inhibitor + checkpoint blockade for dual-use risk...",
    ).model_dump()})
    await asyncio.sleep(1.0)

    bio_tool = ToolCall(
        tool_name="screen_biosecurity",
        tool_input={"query": "PARP inhibitor olaparib anti-PD-L1 atezolizumab BRCA1 TNBC bispecific antibody"},
        result="5/5 screens passed — GREEN. FDA-approved drug classes (PARP inhibitor, anti-PD-L1). Bispecific concept is therapeutic, not dual-use.",
        duration_ms=820,
    )
    yield _sse("tool_call", {"agent_id": "biosecurity_officer", "tool": bio_tool.model_dump()})
    await asyncio.sleep(1.0)

    bio_done = AgentTrace(
        agent_id="biosecurity_officer", division="Biosecurity", status="complete",
        message="Pre-screen PASSED. Category: GREEN. Both drug classes FDA-approved, bispecific antibody is therapeutic.",
        tools_called=[bio_tool],
        confidence_score=1.0, confidence_level="HIGH", duration_ms=1040,
    )
    yield _sse("trace_complete", {"trace": bio_done.model_dump()})
    all_traces.append(bio_done)
    await asyncio.sleep(0.8)

    # ── Phase 3: SubLab Planning ──

    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="sublab_planner", division="Orchestration", status="running",
        message="Composing cross-domain team for combination therapy + bispecific assessment...",
    ).model_dump()})
    await asyncio.sleep(2.5)

    plan_done = AgentTrace(
        agent_id="sublab_planner", division="Orchestration", status="complete",
        message=(
            "Team composed: 5 agents in 3 execution groups.\n"
            "Group 1 (parallel): Synthetic Lethality Analyst, Immuno-Oncology Analyst\n"
            "Group 2 (parallel): Structural Biology & Lead Opt, Toxicology & Safety Profiler\n"
            "Group 3 (sequential): Bispecific Antibody Engineer"
        ),
        tools_called=[
            ToolCall(
                tool_name="compose_team",
                tool_input={"domains": ["oncology", "immunology", "structural_biology", "toxicology", "antibody_engineering", "clinical"], "tools": 119},
                result="5 agents selected, 14 tools assigned across 6 domains",
                duration_ms=1480,
            ),
        ],
        confidence_score=0.97, confidence_level="HIGH", duration_ms=2640,
    )
    yield _sse("trace_complete", {"trace": plan_done.model_dump()})
    all_traces.append(plan_done)
    await asyncio.sleep(1.0)

    # ── Phase 4: Group 1 — Parallel (Synthetic Lethality + Immuno-Oncology) ──

    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="synthetic_lethality_analyst", division="Dynamic SubLab · Group 1", status="running",
        message="Evaluating BRCA1 synthetic lethality with PARP inhibition...",
    ).model_dump()})
    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="immuno_oncology_analyst", division="Dynamic SubLab · Group 1", status="running",
        message="Analyzing PD-L1 checkpoint blockade in TNBC microenvironment...",
    ).model_dump()})
    await asyncio.sleep(1.5)

    synth_tools = [
        ToolCall(tool_name="get_gene_info", tool_input={"gene": "BRCA1"}, result="BRCA1: 17q21.31, 1863 aa, tumor suppressor. Functions: HR repair, DNA damage checkpoint, transcription regulation. Loss → HR deficiency → PARP synthetic lethality.", duration_ms=1120),
        ToolCall(tool_name="get_pathways_for_gene", tool_input={"gene": "BRCA1"}, result="KEGG: hsa03440 (HR repair), hsa04115 (p53 signaling), hsa03460 (Fanconi anemia). BRCA1-PALB2-BRCA2-RAD51 axis essential for HR.", duration_ms=1340),
        ToolCall(tool_name="search_pubmed", tool_input={"query": "BRCA1 PARP synthetic lethality mechanism"}, result="2,340 results. Landmark: Bryant 2005 (Nature), Farmer 2005 (Nature). PARP trapping > catalytic inhibition for cell killing. cGAS-STING upregulates PD-L1 post-PARP inhibition.", duration_ms=1480),
        ToolCall(tool_name="query_gwas_associations", tool_input={"gene": "BRCA1"}, result="5,592 pathogenic variants (ClinVar). BRCA1 185delAG and 5382insC most common. Lifetime breast cancer risk: 57-87%. TNBC enrichment: 70% of BRCA1-mutant breast cancers are TN.", duration_ms=1260),
    ]
    io_tools = [
        ToolCall(tool_name="get_drug_info", tool_input={"drug": "olaparib"}, result="PARP1/2 inhibitor. MW: 434.5 Da. FDA-approved: BRCA+ breast, ovarian, pancreatic, prostate. IC₅₀: 5 nM (PARP1). Trapping potency: moderate (vs talazoparib 100x stronger).", duration_ms=1180),
        ToolCall(tool_name="get_drug_info", tool_input={"drug": "atezolizumab"}, result="Anti-PD-L1 mAb (IgG1, Fc-engineered). FDA-approved: TNBC (IMpassion130, with nab-paclitaxel), NSCLC, urothelial. Binds PD-L1 on tumor cells and tumor-infiltrating immune cells.", duration_ms=1090),
        ToolCall(tool_name="search_trials", tool_input={"query": "TNBC PARP PD-L1 combination breast cancer"}, result="12 trials: MEDIOLA (olaparib+durvalumab, Phase II), KEYLYNK-009 (olaparib+pembrolizumab, Phase III), TOPACIO (niraparib+pembrolizumab, Phase II), JAVELIN PARP Medley (talazoparib+avelumab, Phase Ib/II).", duration_ms=1420),
        ToolCall(tool_name="search_pubmed", tool_input={"query": "PD-L1 expression BRCA1 mutant triple negative breast cancer TMB"}, result="482 results. Key: Nolan 2017 (BRCA1-mut TNBC: PD-L1+ 45-60%), Samstein 2019 (TMB correlates with ICB response), Jiao 2017 (PARP inhibition activates cGAS-STING → IFN → PD-L1 upregulation).", duration_ms=1380),
    ]

    for i in range(4):
        yield _sse("tool_call", {"agent_id": "synthetic_lethality_analyst", "tool": synth_tools[i].model_dump()})
        await asyncio.sleep(0.9)
        yield _sse("tool_call", {"agent_id": "immuno_oncology_analyst", "tool": io_tools[i].model_dump()})
        await asyncio.sleep(0.9)

    await asyncio.sleep(0.8)

    synth_done = AgentTrace(
        agent_id="synthetic_lethality_analyst", division="Dynamic SubLab · Group 1", status="complete",
        message="BRCA1 loss confers synthetic lethality with PARP inhibition via HR deficiency. cGAS-STING pathway activation post-PARP inhibition upregulates PD-L1, creating immune synergy rationale.",
        tools_called=synth_tools,
        confidence_score=0.91, confidence_level="HIGH", duration_ms=9840,
    )
    yield _sse("trace_complete", {"trace": synth_done.model_dump()})
    all_traces.append(synth_done)
    await asyncio.sleep(0.6)

    io_done = AgentTrace(
        agent_id="immuno_oncology_analyst", division="Dynamic SubLab · Group 1", status="complete",
        message="BRCA1-mutant TNBC shows elevated PD-L1 (45-60%) and TMB (8.2 mut/Mb). MEDIOLA trial: olaparib + durvalumab achieved 63% DCR. 12 active combination trials across PARP + checkpoint inhibitor space.",
        tools_called=io_tools,
        confidence_score=0.86, confidence_level="HIGH", duration_ms=10270,
    )
    yield _sse("trace_complete", {"trace": io_done.model_dump()})
    all_traces.append(io_done)
    await asyncio.sleep(1.0)

    # ── Phase 5: Group 2 — Parallel (Structural + Safety) ──

    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="structural_biology_lead_opt", division="Dynamic SubLab · Group 2", status="running",
        message="Resolving PARP1 crystal structure and optimizing lead compounds...",
    ).model_dump()})
    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="toxicology_safety_profiler", division="Dynamic SubLab · Group 2", status="running",
        message="Profiling combination toxicity for olaparib + atezolizumab...",
    ).model_dump()})
    await asyncio.sleep(1.5)

    struct_tools = [
        ToolCall(tool_name="get_protein_structure", tool_input={"protein": "PARP1", "pdb_id": "7KK5"}, result="PDB 7KK5: PARP1 catalytic domain (res 662-1014) + olaparib co-crystal. Resolution: 2.1 Å. NAD+ binding cleft with allosteric regulatory domain. Trapping interface: H862, Y907, E988.", duration_ms=1640),
        ToolCall(tool_name="pymol_render_structure", tool_input={"pdb_id": "7KK5", "style": "cartoon+surface", "highlight_residues": ["H862", "E988", "Y907"], "color_scheme": "domain", "label": "PARP1 catalytic domain with olaparib binding site"}, result="3D render generated: PARP1 catalytic domain (residues 662-1014) with NAD+ binding pocket highlighted. Olaparib occupies the nicotinamide-binding subsite. Key trapping contacts: H862 (π-stacking), Y907 (H-bond), E988 (electrostatic). Surface: druggable pocket volume 847 Å³.", duration_ms=3840),
        ToolCall(tool_name="dock_compound", tool_input={"receptor": "PARP1_7KK5", "ligand": "talazoparib", "method": "induced_fit"}, result="Talazoparib docking: ΔG = -12.4 kcal/mol (vs olaparib -9.8). Enhanced π-stacking at H862, additional H-bond at S904. Explains 100x trapping potency difference. Retention time on DNA-PARP complex: 48 min vs 8 min (olaparib).", duration_ms=2890),
        ToolCall(tool_name="generate_moa_diagram", tool_input={"drug": "olaparib + atezolizumab", "target": "PARP1 + PD-L1", "indication": "BRCA1-mutant TNBC"}, result="MOA diagram: dual-arm mechanism. Left: PARP trapping → SSB → fork collapse → DSBs → tumor death. Right: cGAS-STING → IFN → PD-L1↑ → anti-PD-L1 → T-cell reactivation. Convergence at tumor cell elimination.", duration_ms=2140),
    ]
    safety_tools = [
        ToolCall(tool_name="get_side_effects", tool_input={"drug": "olaparib"}, result="Common: nausea (58%), fatigue (37%), anemia (25%), vomiting (32%). Serious: MDS/AML (1.2%), pneumonitis (0.8%). Dose-limiting: anemia. Grade ≥3 anemia: 16%.", duration_ms=1080),
        ToolCall(tool_name="get_side_effects", tool_input={"drug": "atezolizumab"}, result="Common: fatigue (24%), nausea (17%), decreased appetite (15%). Immune-related: hepatitis (3%), pneumonitis (2.5%), colitis (1.6%), thyroiditis (5.6%). Grade ≥3 irAE: 8%.", duration_ms=960),
        ToolCall(tool_name="search_pubmed", tool_input={"query": "PARP inhibitor anti-PD-L1 combination toxicity hematologic"}, result="89 results. MEDIOLA: Grade ≥3 anemia 12%, neutropenia 8%. TOPACIO: Grade ≥3 anemia 18%. Overlapping hematologic toxicity is dose-limiting. No unexpected synergistic toxicities.", duration_ms=1440),
        ToolCall(tool_name="predict_drug_interactions", tool_input={"drug_a": "olaparib", "drug_b": "atezolizumab"}, result="No direct PK interaction (different metabolism: CYP3A4 vs proteolytic). Pharmacodynamic overlap: additive myelosuppression. Risk: combined anemia (predicted Grade ≥3: 12-18%). Manageable with dose modification.", duration_ms=1280),
    ]

    for i in range(4):
        yield _sse("tool_call", {"agent_id": "structural_biology_lead_opt", "tool": struct_tools[i].model_dump()})
        await asyncio.sleep(1.1)
        yield _sse("tool_call", {"agent_id": "toxicology_safety_profiler", "tool": safety_tools[i].model_dump()})
        await asyncio.sleep(1.1)

    await asyncio.sleep(0.8)

    struct_done = AgentTrace(
        agent_id="structural_biology_lead_opt", division="Dynamic SubLab · Group 2", status="complete",
        message="PARP1 structure resolved (PDB 7KK5, 2.1 Å). Talazoparib shows 100x stronger trapping via enhanced π-stacking at H862. 3D structure rendered via PyMOL. MOA diagram generated for dual-arm mechanism.",
        tools_called=struct_tools,
        confidence_score=0.88, confidence_level="HIGH", duration_ms=12640,
    )
    yield _sse("trace_complete", {"trace": struct_done.model_dump()})
    all_traces.append(struct_done)
    await asyncio.sleep(0.6)

    safety_done = AgentTrace(
        agent_id="toxicology_safety_profiler", division="Dynamic SubLab · Group 2", status="complete",
        message="Combination toxicity manageable. Overlapping hematologic AEs: Grade ≥3 anemia 12-18%, neutropenia 8%. No unexpected synergistic toxicities. No direct PK interaction.",
        tools_called=safety_tools,
        confidence_score=0.84, confidence_level="HIGH", duration_ms=11380,
    )
    yield _sse("trace_complete", {"trace": safety_done.model_dump()})
    all_traces.append(safety_done)
    await asyncio.sleep(1.0)

    # ── Phase 6: Group 3 — Bispecific Antibody Engineer ──

    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="bispecific_antibody_engineer", division="Dynamic SubLab · Group 3", status="running",
        message="Assessing PD-L1/PARP-trapping bispecific antibody developability...",
    ).model_dump()})
    await asyncio.sleep(1.5)

    bispec_tools = [
        ToolCall(tool_name="antibody_developability", tool_input={"format": "bispecific_IgG", "arm_a": "anti-PD-L1 (atezolizumab CDR)", "arm_b": "talazoparib-PEG8 conjugate"}, result="Developability flags: aggregation propensity MODERATE (SAP score 0.42), viscosity at 150 mg/mL: 18 cP (acceptable). Conjugation site heterogeneity: 3 possible positions. Accelerated stability (40°C/4wk): 15% aggregation increase. Tm: 68°C (arm A), 52°C (arm B — conjugate lowers thermal stability).", duration_ms=2480),
        ToolCall(tool_name="predict_immunogenicity", tool_input={"sequence": "atezolizumab_CDR_talazoparib_conjugate", "method": "T-cell_epitope_prediction"}, result="Immunogenicity risk: LOW for anti-PD-L1 arm (humanized). MODERATE for linker-drug region — 2 predicted MHC-II binding peptides in PEG8-talazoparib junction. Recommendation: optimize linker to remove T-cell epitopes.", duration_ms=1860),
        ToolCall(tool_name="esm2_score_mutations", tool_input={"protein": "anti-PD-L1_arm", "mutations": ["S239D", "I332E", "L235A"], "property": "effector_function"}, result="S239D/I332E: enhanced ADCC (2.1x FcγRIIIa binding). L235A: silenced effector. For bispecific: recommend L235A/P329G (silent Fc) — tumor killing via PARP trapping + T-cell activation, not ADCC.", duration_ms=2240),
        ToolCall(tool_name="generate_pathway_diagram", tool_input={"title": "PD-L1/PARP-Trapping Bispecific Architecture", "nodes": ["Anti-PD-L1 Fab", "Silent Fc (L235A/P329G)", "PEG8 Linker", "Talazoparib Warhead", "PD-L1 (Tumor)", "PARP1-DNA Complex", "T-cell Activation", "Synthetic Lethality"]}, result="Architecture diagram: bispecific IgG with asymmetric arms. Arm A: anti-PD-L1 Fab → blocks checkpoint. Arm B: Fab-PEG8-talazoparib → traps PARP1. Silent Fc prevents off-target ADCC.", duration_ms=1960),
    ]

    for tool in bispec_tools:
        yield _sse("tool_call", {"agent_id": "bispecific_antibody_engineer", "tool": tool.model_dump()})
        await asyncio.sleep(1.4)

    await asyncio.sleep(0.8)

    bispec_done = AgentTrace(
        agent_id="bispecific_antibody_engineer", division="Dynamic SubLab · Group 3", status="complete",
        message="Bispecific feasibility assessed. PEG₈-linked talazoparib warhead shows 3.2x IC₅₀ shift vs free drug. 15% aggregation at 40°C/4wk. Silent Fc (L235A/P329G) recommended. Concept is exploratory — no validated format exists.",
        tools_called=bispec_tools,
        confidence_score=0.32, confidence_level="LOW", duration_ms=13680,
    )
    yield _sse("trace_complete", {"trace": bispec_done.model_dump()})
    all_traces.append(bispec_done)
    await asyncio.sleep(1.0)

    # ── Phase 7: Evidence Preparation (diagram + writeup for expert review) ──

    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="evidence_compiler", division="Orchestration", status="running",
        message="Preparing contextual evidence for expert review...",
    ).model_dump()})
    await asyncio.sleep(1.0)

    evidence_tools = [
        ToolCall(
            tool_name="generate_mechanism_diagram",
            tool_input={"title": "PD-L1/PARP-Trapping Bispecific MOA in BRCA1-mut TNBC", "nodes": ["Bispecific Ab", "PD-L1", "PARP1", "DNA DSB", "Synthetic Lethality", "T-cell Activation", "Tumor Cell Death"], "pathways": ["immune checkpoint blockade", "PARP trapping", "HRD synthetic lethality"]},
            result="Mechanism diagram: 7 nodes, 2 convergent pathways → tumor cell death. Left arm: anti-PD-L1 → T-cell reactivation → immune-mediated killing. Right arm: PARP-trapping → persistent SSBs → replication fork collapse → synthetic lethality in BRCA1⁻/⁻ cells.",
            duration_ms=2890,
        ),
        ToolCall(
            tool_name="generate_executive_brief",
            tool_input={"topic": "PD-L1/PARP bispecific antibody feasibility", "evidence_sources": 9, "confidence_range": "0.32-0.94"},
            result="Executive brief drafted: 1,200 words covering rationale, structural feasibility, CMC challenges (dual-payload stability, PARP-trapping moiety conjugation), competitive landscape (3 bispecific programs in preclinical), and risk-benefit assessment. Key concern: no validated PARP-trapping antibody conjugate format exists.",
            duration_ms=2140,
        ),
    ]
    for tool in evidence_tools:
        yield _sse("tool_call", {"agent_id": "evidence_compiler", "tool": tool.model_dump()})
        await asyncio.sleep(1.5)

    evidence_done = AgentTrace(
        agent_id="evidence_compiler", division="Orchestration", status="complete",
        message="Evidence package prepared: mechanism diagram (dual-arm convergent MOA) and executive brief (1,200 words) for expert review of bispecific antibody feasibility.",
        tools_called=evidence_tools,
        confidence_score=0.95, confidence_level="HIGH", duration_ms=6240,
    )
    yield _sse("trace_complete", {"trace": evidence_done.model_dump()})
    all_traces.append(evidence_done)
    await asyncio.sleep(1.0)

    # ── Phase 8: Adversarial Review Panel ──

    yield _sse("trace_start", {"trace": AgentTrace(
        agent_id="review_panel", division="Orchestration", status="running",
        message="Running 3-pass adversarial review (methodology → evidence → synthesis)...",
    ).model_dump()})
    await asyncio.sleep(1.5)

    review_tool = ToolCall(
        tool_name="confidence_calibration",
        tool_input={"claims": 9, "method": "3-pass adversarial"},
        result="9 claims scored. Auto-pass (≥0.70): BRCA1 synthetic lethality (0.94), PARP trapping mechanism (0.92), PD-L1 expression (0.88), MEDIOLA DCR (0.85), cGAS-STING (0.82), combination safety (0.79), PARP1 structure (0.71). Near-pass: talazoparib trapping (0.68). Soft-flag: bispecific feasibility (0.32). Mean: 0.74.",
        duration_ms=980,
    )
    yield _sse("tool_call", {"agent_id": "review_panel", "tool": review_tool.model_dump()})
    await asyncio.sleep(1.0)

    review_done = AgentTrace(
        agent_id="review_panel", division="Orchestration", status="complete",
        message="3-pass adversarial review complete. 8/9 findings APPROVED (≥0.50). 1 flagged SOFT (0.32) — bispecific antibody feasibility routed to HITL.",
        tools_called=[review_tool],
        confidence_score=0.93, confidence_level="HIGH", duration_ms=2480,
    )
    yield _sse("trace_complete", {"trace": review_done.model_dump()})
    all_traces.append(review_done)
    await asyncio.sleep(1.0)

    # ── Phase 9: HITL — Flag bispecific antibody feasibility ──

    finding_id = "review_parp_bispec_001"

    bispec_hitl = {
        "finding": "A PD-L1/PARP-trapping bispecific antibody could achieve synergistic tumor cell killing by simultaneously blocking immune checkpoint and inducing synthetic lethality in BRCA1-deficient TNBC.",
        "agent_id": "bispecific_antibody_engineer",
        "confidence_score": 0.32,
        "reason": "Below 0.50 threshold. No validated PARP-trapping antibody conjugate format exists. In silico modeling only — 15% aggregation at 40°C/4wk, 3.2x IC₅₀ shift vs free talazoparib.",
        "finding_id": finding_id,
        "status": "pending",
    }
    yield _sse("hitl_flag", {"hitl": bispec_hitl})

    # Post to Slack if configured
    thread_ts = None
    if slack_channel:
        thread_ts = await _try_slack_post(
            channel=slack_channel,
            text=(
                "Lumi HITL Review | Confidence: 32%\n"
                "Finding: PD-L1/PARP-trapping bispecific antibody feasibility for BRCA1-mutant TNBC.\n"
                "Agent: bispecific_antibody_engineer"
            ),
            username="Lumi Agent",
            icon_emoji=":microscope:",
        )

    expert_messages = [
        ("Lumi Agent", "AI Scientist", "agent",
         "I've flagged a finding on PD-L1/PARP-trapping bispecific antibody feasibility for review. "
         "Confidence is 32%. The concept has mechanistic rationale but no experimental validation."),
        ("Dr. James Rodriguez", "Antibody Engineering Lead", "expert",
         "What structural data supports a bispecific format here? PARP trapping requires the inhibitor "
         "to physically trap PARP1 on DNA — how would you achieve that from an antibody-conjugated payload?"),
        ("Lumi Agent", "AI Scientist", "agent",
         "Rosetta modeling suggests a PEG₈-linked talazoparib warhead on the Fab arm could maintain "
         "PARP-trapping activity (predicted IC₅₀ shift: 3.2x vs free talazoparib). DMS analysis shows "
         "4/12 linker configurations maintain >50% trapping efficiency."),
        ("Dr. James Rodriguez", "Antibody Engineering Lead", "expert",
         "The 3x IC₅₀ shift is concerning but not disqualifying for proof-of-concept. I'll approve this "
         "for in silico exploration only — do NOT include as a clinical recommendation."),
    ]
    if slack_channel and thread_ts:
        for name, title, role, text in expert_messages:
            await _try_slack_reply(
                channel=slack_channel,
                thread_ts=thread_ts,
                text=f"*{name}* ({title})\n{text}",
                username=name,
                icon_emoji=":microscope:" if role == "agent" else ":male-scientist:",
            )

    await asyncio.sleep(12.0)

    bispec_resolved = {
        **bispec_hitl,
        "status": "approved",
        "reason": "Dr. James Rodriguez: Approved for in silico exploration only. Not a clinical recommendation. CMC challenges make this 3-5 years from IND-enabling. Focus near-term on conventional olaparib + atezolizumab combination.",
    }
    yield _sse("hitl_resolved", {"hitl": bispec_resolved})
    all_hitl.append(HitlEvent(**bispec_resolved))
    await asyncio.sleep(1.2)

    # ── Phase 10: Integrations ──

    slack_detail = "9 findings, 1 HITL-reviewed. 5 agents across 6 domains. Confidence: 0.74."
    if slack_channel:
        await _try_slack_post(
            channel=slack_channel,
            text=f"Lumi Pipeline Complete | PARP + PD-L1 Combination — BRCA1-mutant TNBC\n{slack_detail}",
            username="Lumi",
            icon_emoji=":dna:",
        )

    integrations = [
        IntegrationEvent(integration="Slack", action="Posted findings summary to #tnbc-combination-therapy", status="complete", detail=slack_detail),
        IntegrationEvent(integration="PyMOL", action="Rendered PARP1-olaparib co-crystal structure (PDB: 7KK5)", status="complete", detail="Cartoon+surface view highlighting trapping residues H862, Y907, E988. Pocket volume: 847 Å³."),
        IntegrationEvent(integration="BioRender", action="Generated dual-arm MOA diagram for PARP+PD-L1 combination", status="complete", detail="Convergent mechanism: PARP trapping → synthetic lethality + cGAS-STING → anti-PD-L1 → immune killing."),
        IntegrationEvent(integration="Benchling", action="Created notebook entry EXP-2026-0892", status="complete", detail="Bispecific antibody design dossier linked to TNBC-CombinationTherapy project."),
    ]
    for integ in integrations:
        all_integrations.append(integ)
        yield _sse("integration", {"call": integ.model_dump()})
        await asyncio.sleep(1.2)

    # ── Phase 11: Final synthesis ──

    text = _mock_response_text_parp()
    chunks = [text[i:i + 80] for i in range(0, len(text), 80)]
    accumulated = ""
    for chunk in chunks:
        accumulated += chunk
        yield _sse("text_delta", {"delta": chunk})
        await asyncio.sleep(0.05)

    assistant_msg = Message(
        id=msg_id, role=Role.ASSISTANT, content=accumulated,
        agent_traces=all_traces, hitl_events=all_hitl, integration_events=all_integrations,
    )
    chat.messages.append(assistant_msg)
    chat.updated_at = datetime.now(timezone.utc)

    yield _sse("done", {})


# ===========================================================================
# Routes
# ===========================================================================


# ===========================================================================
# Clarifying questions
# ===========================================================================

_MOCK_CLARIFY: dict[str, list[ClarifyQuestion]] = {
    "glp1r": [
        ClarifyQuestion(id="indication", question="Which stage of Parkinson's disease are you targeting — early-stage (Hoehn & Yahr I-II) or advanced?", placeholder="e.g., Early-stage, pre-motor phase"),
        ClarifyQuestion(id="scope", question="Should the analysis focus on neuroprotection mechanisms, clinical trial feasibility, or both?", placeholder="e.g., Both — mechanism + clinical landscape"),
        ClarifyQuestion(id="comparators", question="Are there specific GLP-1 agonists to compare (semaglutide, exenatide, liraglutide), or assess the class broadly?", placeholder="e.g., Focus on semaglutide vs exenatide"),
    ],
    "pcsk9": [
        ClarifyQuestion(id="indication", question="Which cardiovascular indication — hypercholesterolemia, atherosclerotic CVD, or familial hypercholesterolemia?", placeholder="e.g., ASCVD risk reduction"),
        ClarifyQuestion(id="modality", question="Should the analysis cover all modalities (mAb, siRNA, small molecule) or focus on one?", placeholder="e.g., Compare mAb vs siRNA approaches"),
        ClarifyQuestion(id="evidence", question="Prioritize genetic evidence (Mendelian randomization, LoF variants) or clinical outcomes data?", placeholder="e.g., Both genetic + clinical"),
    ],
    "kras": [
        ClarifyQuestion(id="mutation", question="Confirm the target mutation — KRAS G12C specifically, or include G12D/G12V?", placeholder="e.g., G12C only, NSCLC context"),
        ClarifyQuestion(id="focus", question="Should the analysis prioritize PK optimization, selectivity, or resistance mechanism coverage?", placeholder="e.g., PK + resistance mechanisms"),
        ClarifyQuestion(id="modality", question="Small molecule covalent inhibitors only, or include PROTACs and combination strategies?", placeholder="e.g., Covalent inhibitors + combo strategies"),
    ],
    "parp": [
        ClarifyQuestion(id="brca_status", question="Is the target population BRCA1-specific, or should BRCA2 and HRD-positive tumors also be included?", placeholder="e.g., BRCA1/2 germline mutations and HRD-positive"),
        ClarifyQuestion(id="parp_agent", question="Which PARP inhibitor(s) should be evaluated — olaparib, talazoparib, or the class broadly?", placeholder="e.g., Focus on talazoparib (strongest PARP trapping)"),
        ClarifyQuestion(id="bispecific_priority", question="For the bispecific antibody, should we prioritize PARP-trapping potency or PD-L1 binding affinity?", placeholder="e.g., Balance both — dual mechanism is the key differentiator"),
    ],
    "default": [
        ClarifyQuestion(id="scope", question="What is the primary goal — target validation, drug design, safety assessment, or a full pipeline review?", placeholder="e.g., Full pipeline from target to candidate"),
        ClarifyQuestion(id="indication", question="Is there a specific disease indication or therapeutic area to focus on?", placeholder="e.g., Oncology, rare disease, neurodegeneration"),
        ClarifyQuestion(id="constraints", question="Any modality or approach preferences (small molecule, biologic, gene therapy)?", placeholder="e.g., Small molecule preferred"),
    ],
}


def _get_mock_questions(query: str) -> list[ClarifyQuestion]:
    """Return mock clarifying questions based on query keywords."""
    q = query.lower()
    if "glp1r" in q or "glp-1" in q or "semaglutide" in q or "parkinson" in q:
        return _MOCK_CLARIFY["glp1r"]
    elif "parp" in q or "brca" in q or "triple-negative" in q or "tnbc" in q or "bispecific" in q:
        return _MOCK_CLARIFY["parp"]
    elif "pcsk9" in q or "cardiovascular" in q or "cholesterol" in q:
        return _MOCK_CLARIFY["pcsk9"]
    elif "kras" in q or "g12c" in q:
        return _MOCK_CLARIFY["kras"]
    return _MOCK_CLARIFY["default"]


async def _get_live_questions(query: str) -> list[ClarifyQuestion]:
    """Use Haiku to generate clarifying questions for a research query."""
    try:
        from src.utils.llm import LLMClient, ModelTier
        import json as _json

        llm = LLMClient()
        response = await llm.chat(
            messages=[{"role": "user", "content": (
                f"A researcher submitted this query to a drug discovery AI system:\n\n"
                f"\"{query}\"\n\n"
                f"Generate exactly 3 brief clarifying questions to refine scope before running the analysis. "
                f"Return ONLY a JSON array of objects with keys: \"id\" (short snake_case), \"question\", \"placeholder\" (example answer).\n"
                f"Focus on: target specifics, disease stage/indication, and analysis scope/modality preferences."
            )}],
            model=ModelTier.HAIKU,
            system="You are a drug discovery research assistant. Return only valid JSON, no markdown fences.",
        )
        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        # Parse JSON
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()
        questions_data = _json.loads(cleaned)
        return [ClarifyQuestion(**q) for q in questions_data[:3]]
    except Exception as exc:
        log.warning("Failed to generate live clarifying questions: %s — using defaults", exc)
        return _get_mock_questions(query)


@router.post("/{chat_id}/clarify")
async def clarify(chat_id: str, req: ClarifyRequest) -> ClarifyResponse:
    """Generate clarifying questions for a research query before pipeline execution."""
    log.info("clarify chat_id=%s mode=%s query=%s", chat_id, req.mode, req.query[:80])
    if chat_id not in _chats:
        raise HTTPException(status_code=404, detail="Chat not found")

    if req.mode == "live":
        questions = await _get_live_questions(req.query)
    else:
        questions = _get_mock_questions(req.query)

    return ClarifyResponse(
        questions=questions,
        context_summary=f"Analyzing: {req.query[:200]}",
    )


@router.post("/{chat_id}/review/{finding_id}")
async def submit_review_decision(chat_id: str, finding_id: str, req: ReviewDecisionRequest):
    """Submit an expert review decision for a HITL-flagged finding."""
    if chat_id not in _chats:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat = _chats[chat_id]

    # Find and update the matching HITL event in stored messages
    resolved = False
    for msg in chat.messages:
        for hitl in msg.hitl_events:
            if hitl.finding_id == finding_id:
                hitl.status = req.status
                hitl.reason = req.feedback or hitl.reason
                resolved = True
                break

    if not resolved:
        raise HTTPException(status_code=404, detail="Finding not found")

    log.info("review decision chat=%s finding=%s status=%s", chat_id, finding_id, req.status)
    return {"status": "ok", "finding_id": finding_id, "decision": req.status}


@router.get("")
async def list_chats() -> list[Chat]:
    return sorted(_chats.values(), key=lambda c: c.updated_at, reverse=True)


@router.post("")
async def create_chat(req: CreateChatRequest) -> Chat:
    log.info("create_chat sublab=%s msg=%s", req.sublab, req.message[:80])
    chat_id = str(uuid.uuid4())[:8]
    title = req.message[:60] + ("..." if len(req.message) > 60 else "")
    chat = Chat(id=chat_id, title=title, sublab=req.sublab)
    user_msg = Message(id=str(uuid.uuid4())[:8], role=Role.USER, content=req.message, sublab=req.sublab)
    chat.messages.append(user_msg)
    _chats[chat_id] = chat
    return chat


@router.get("/{chat_id}")
async def get_chat(chat_id: str) -> Chat:
    if chat_id not in _chats:
        raise HTTPException(status_code=404, detail="Chat not found")
    return _chats[chat_id]


async def _stream_live(chat: Chat, msg_id: str, query: str):
    """Stream real pipeline events via asyncio.Queue bridge."""
    queue: asyncio.Queue = asyncio.Queue()

    async def on_event(event_type: str, data: dict):
        data["message_id"] = msg_id
        data["type"] = event_type
        await queue.put(data)

    async def run_pipeline():
        try:
            from src.orchestrator.pipeline import run_yohas_pipeline
            report = await run_yohas_pipeline(
                user_query=query,
                dynamic=True,
                sublab_hint=chat.sublab,
                on_event=on_event,
                enable_world_model=False,
                cost_ceiling=25.0,
            )
            # Store the completed message
            content = report.living_document_markdown or report.executive_summary
            assistant_msg = Message(
                id=msg_id, role=Role.ASSISTANT, content=content,
            )
            chat.messages.append(assistant_msg)
            chat.updated_at = datetime.now(timezone.utc)
        except Exception as exc:
            log.exception("Live pipeline failed: %s", exc)
            await on_event("text_delta", {"delta": "\n\n**Pipeline error:** An internal error occurred. Please try again."})
        finally:
            await queue.put(None)  # sentinel

    task = asyncio.create_task(run_pipeline())

    def _sse(event_type: str, data: dict) -> str:
        data["message_id"] = msg_id
        data["type"] = event_type
        return f"data: {json.dumps(data, default=str)}\n\n"

    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, default=str)}\n\n"

            # Check for PyMOL image results
            if item.get("type") == "tool_result":
                result = item.get("data", {})
                file_path = result.get("file_path", "")
                if "pymol_" in file_path:
                    filename = os.path.basename(file_path)
                    image_url = f"/api/images/{filename}"
                    yield _sse("integration", {"call": {
                        "integration": "PyMOL",
                        "action": f"Rendered {result.get('pdb_id', 'structure')}",
                        "status": "complete",
                        "detail": result.get("summary", "3D structure visualization"),
                        "image_url": image_url,
                    }})
    finally:
        if not task.done():
            task.cancel()

    yield f"data: {json.dumps({'type': 'done', 'message_id': msg_id})}\n\n"


@router.post("/{chat_id}/messages")
async def send_message(chat_id: str, req: SendMessageRequest) -> StreamingResponse:
    log.info("send_message chat_id=%s mode=%s content=%s", chat_id, req.mode, req.content[:80])
    if chat_id not in _chats:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat = _chats[chat_id]
    last = chat.messages[-1] if chat.messages else None
    if not last or last.role != Role.USER or last.content != req.content:
        user_msg = Message(id=str(uuid.uuid4())[:8], role=Role.USER, content=req.content)
        chat.messages.append(user_msg)
    msg_id = str(uuid.uuid4())[:8]
    if req.mode == "live":
        return StreamingResponse(_stream_live(chat, msg_id, req.content), media_type="text/event-stream")
    # Select mock based on query content
    q = req.content.lower()
    if any(kw in q for kw in ("parp", "brca", "triple-negative", "tnbc", "bispecific", "pd-l1")):
        mock_gen = _stream_mock_parp(chat, msg_id)
    else:
        mock_gen = _stream_mock(chat, msg_id)
    return StreamingResponse(mock_gen, media_type="text/event-stream")
