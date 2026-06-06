"""SubLab Planner — LLM-driven dynamic team composition.

Given a research brief, intelligence briefing, and the full tool catalog,
uses Opus to design a query-specific multi-agent team (SubLab) with
cross-domain tool assignments.
"""

from __future__ import annotations

import json
import logging
import textwrap
from typing import Any

from src.utils.llm import LLMClient, ModelTier
from src.utils.types import AgentSpec, SubLabPlan

logger = logging.getLogger("lumi.orchestrator.sublab_planner")

_SUBLAB_PLANNING_PROMPT = textwrap.dedent("""\
    You are the Chief Scientific Officer planning a dynamic research team.

    Given the research brief, intelligence briefing, and the full tool catalog
    below, design a team of specialist agents. Each agent gets a subset of
    tools tailored to their role. Agents can combine tools from different
    domains — this is the key advantage over the static division structure.

    Research brief:
    {research_brief}

    Intelligence briefing:
    {intel_brief}

    {sublab_hint_section}

    Tool catalog:
    {tool_catalog}

    Design your team as a JSON object (no markdown fences) with these keys:
    - "agents": array of agent specs, each with:
        - "name": descriptive agent name (e.g. "Genomic Evidence Analyst")
        - "role": one-sentence role description
        - "tools": array of tool names from the catalog above
        - "domains": array of domain expertise keys to compose the agent's
          system prompt. Valid keys: statistical_genetics, functional_genomics,
          single_cell_atlas, bio_pathways, fda_safety, toxicogenomics,
          target_biologist, pharmacologist, protein_intelligence,
          antibody_engineer, structure_design, lead_optimization,
          developability, clinical_trialist, literature_synthesis,
          assay_design, dual_use_screening
        - "model_tier": "SONNET" for most agents, "HAIKU" for simple
          data-gathering tasks
    - "execution_groups": array of arrays of agent names. Groups execute
      sequentially; agents within a group execute in parallel. Earlier
      groups' results are passed as context to later groups.
    - "rationale": brief explanation of your team design

    Guidelines:
    - Prefer 3-6 agents with 5-15 tools each.
    - Cross-domain tool composition is encouraged (e.g. a genomics agent
      that also has literature search tools).
    - A visualization/figure agent with biorender tools is useful if the
      query would benefit from visual output.
    - Place data-gathering agents in early groups, synthesis agents in later groups.
    - Every tool name must exactly match a name from the catalog.

    Return ONLY the JSON object.
""")


class SubLabPlanner:
    """Plans dynamic agent teams based on query and tool catalog."""

    def __init__(self) -> None:
        self.llm = LLMClient()

    async def plan_sublab(
        self,
        research_brief: dict,
        intel_brief: dict,
        tool_catalog_text: str,
        sublab_hint: str | None = None,
    ) -> SubLabPlan:
        """Use Opus to design a query-specific agent team.

        Args:
            research_brief: Parsed research brief from the intake phase.
            intel_brief: Intelligence briefing from ChiefOfStaff.
            tool_catalog_text: Compact text catalog from
                :func:`~src.mcp_bridge.get_catalog_prompt_text`.
            sublab_hint: Optional hint from the UI picker (used as
                context, not constraint).

        Returns:
            A validated :class:`SubLabPlan`.
        """
        hint_section = ""
        if sublab_hint:
            hint_section = f"User-provided sublab hint (use as context, not constraint):\n{sublab_hint}"

        prompt = _SUBLAB_PLANNING_PROMPT.format(
            research_brief=json.dumps(research_brief, indent=2, default=str),
            intel_brief=json.dumps(intel_brief, indent=2, default=str),
            sublab_hint_section=hint_section,
            tool_catalog=tool_catalog_text,
        )

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=ModelTier.OPUS,
                max_tokens=4096,
            )

            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )

            plan_data = self._parse_json(text)
            plan = self._validate_plan(plan_data)

            logger.info(
                "[SubLabPlanner] Plan: %d agents, %d execution groups",
                len(plan.agents),
                len(plan.execution_groups),
            )
            for spec in plan.agents:
                logger.info(
                    "[SubLabPlanner]   Agent '%s' (%s): %d tools, domains=%s",
                    spec.name,
                    spec.model_tier,
                    len(spec.tools),
                    spec.domains,
                )
            for gi, group in enumerate(plan.execution_groups):
                logger.info(
                    "[SubLabPlanner]   Group %d (parallel): %s",
                    gi + 1,
                    group,
                )
            logger.info("[SubLabPlanner] Rationale: %s", plan.rationale[:200])
            return plan

        except Exception as exc:
            logger.error("[SubLabPlanner] Planning failed: %s — using fallback", exc)
            return self._fallback_plan(research_brief)

    def _validate_plan(self, data: dict) -> SubLabPlan:
        """Validate and construct a SubLabPlan from parsed JSON."""
        agents: list[AgentSpec] = []
        for a in data.get("agents", []):
            agents.append(AgentSpec(
                name=a.get("name", "Unnamed Agent"),
                role=a.get("role", "Research agent"),
                tools=a.get("tools", []),
                domains=a.get("domains", []),
                model_tier=a.get("model_tier", "SONNET"),
            ))

        return SubLabPlan(
            agents=agents,
            execution_groups=data.get("execution_groups", [[a.name for a in agents]]),
            rationale=data.get("rationale", ""),
        )

    def _fallback_plan(self, research_brief: dict) -> SubLabPlan:
        """Generate a minimal fallback plan with two generic agents."""
        target = research_brief.get("target", "the target")
        return SubLabPlan(
            agents=[
                AgentSpec(
                    name="Evidence Gatherer",
                    role=f"Gather multi-source evidence for {target}",
                    tools=[
                        "query_target_disease", "get_target_info",
                        "query_gwas_associations", "get_gene_expression",
                        "search_papers", "search_pubmed",
                        "get_pathways_for_gene", "get_go_annotations",
                    ],
                    domains=["statistical_genetics", "functional_genomics", "literature_synthesis"],
                    model_tier="SONNET",
                ),
                AgentSpec(
                    name="Safety & Clinical Analyst",
                    role=f"Assess safety profile and clinical landscape for {target}",
                    tools=[
                        "get_knockout_phenotypes", "query_gene_chemical_interactions",
                        "search_adverse_events", "search_trials",
                        "get_drug_info", "get_side_effects",
                    ],
                    domains=["fda_safety", "toxicogenomics", "clinical_trialist"],
                    model_tier="SONNET",
                ),
            ],
            execution_groups=[
                ["Evidence Gatherer", "Safety & Clinical Analyst"],
            ],
            rationale="Fallback plan: parallel evidence gathering and safety analysis.",
        )

    @staticmethod
    def _parse_json(text: str) -> Any:
        """Extract JSON from LLM response, handling markdown fences."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Find JSON object boundaries
        start = cleaned.find("{")
        if start == -1:
            return {}
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start : i + 1])
                    except json.JSONDecodeError:
                        break
        return {}
