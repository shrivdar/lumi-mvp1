"""Chief of Staff — intelligence briefing agent for the CSO.

Uses Claude Haiku for fast, low-cost intelligence gathering: assessing
the research landscape, data availability, recent developments, and
recommending which divisions to activate.
"""

from __future__ import annotations

import json
import logging
import textwrap

from src.utils.llm import LLMClient, ModelTier

logger = logging.getLogger("lumi.orchestrator.chief_of_staff")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

CHIEF_OF_STAFF_SYSTEM_PROMPT = textwrap.dedent("""\
    You are the Chief of Staff for Lumi Virtual Lab's CSO Orchestrator.

    Your role is to provide rapid intelligence briefings that help the CSO
    make informed decisions about how to approach a research query. You
    assess:

    1. Field landscape — what is the current state of research in this area?
    2. Data availability — what databases, datasets, and tools are relevant?
    3. Recent developments — any breakthroughs or key papers in the last 1-2 years?
    4. Feasibility — how tractable is this query with available tools?
    5. Division recommendations — which divisions should be activated?

    Be concise and actionable. Provide your assessment as structured JSON.
    Do NOT perform the actual analysis — only scout the terrain.
""")

BRIEFING_PROMPT_TEMPLATE = textwrap.dedent("""\
    Provide an intelligence briefing for the following research query.

    Research brief:
    {research_brief}

    Return ONLY a JSON object with these keys:

    - "field_landscape": string — 2-3 sentence overview of the current
      state of research in this area.
    - "data_availability": object with keys:
        - "databases": list of relevant database names
          (e.g., "UniProt", "PDB", "ClinicalTrials.gov")
        - "tools": list of computational tools relevant to this query
          (e.g., "ESM-2", "AlphaFold", "COBRApy")
        - "data_quality": "HIGH" / "MEDIUM" / "LOW" — how well-covered
          is this area in existing databases?
    - "recent_developments": list of strings — key recent findings or
      papers relevant to this query (2-5 items).
    - "feasibility_assessment": object with keys:
        - "overall": "HIGH" / "MEDIUM" / "LOW"
        - "strengths": list of strings
        - "challenges": list of strings
        - "estimated_confidence": float 0-1 — expected confidence in
          the final output
    - "recommended_divisions": list of objects, each with:
        - "name": division name
        - "priority": "CRITICAL" / "HIGH" / "MEDIUM" / "LOW"
        - "rationale": 1 sentence explaining why this division is needed
    - "key_questions": list of 3-5 strings — the most important
      scientific questions to address.
    - "potential_risks": list of strings — risks or pitfalls to watch for.
""")


class ChiefOfStaff:
    """Intelligence briefing agent that scouts the research terrain.

    Uses Haiku for speed and cost efficiency. Provides the CSO with a
    structured assessment of the research landscape before planning begins.
    """

    def __init__(self) -> None:
        self.llm = LLMClient()

    async def generate_briefing(self, research_brief: dict) -> dict:
        """Generate an intelligence briefing for the given research brief.

        Args:
            research_brief: Output from the CSO's intake phase, containing
                query_type, target, disease, scope, etc.

        Returns:
            A dict with keys: field_landscape, data_availability,
            recent_developments, feasibility_assessment,
            recommended_divisions, key_questions, potential_risks.
        """
        prompt = BRIEFING_PROMPT_TEMPLATE.format(
            research_brief=json.dumps(research_brief, indent=2, default=str)
        )

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=ModelTier.HAIKU,
                system=CHIEF_OF_STAFF_SYSTEM_PROMPT,
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            briefing = self._parse_json(text)

            logger.info(
                "[ChiefOfStaff] Briefing complete — feasibility=%s, %d divisions recommended",
                briefing.get("feasibility_assessment", {}).get("overall", "?"),
                len(briefing.get("recommended_divisions", [])),
            )
            return briefing

        except Exception as exc:
            logger.error("[ChiefOfStaff] Briefing failed: %s", exc)
            return self._fallback_briefing(research_brief)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_json(self, text: str) -> dict:
        """Parse JSON from LLM response, handling markdown fences."""
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
        if start != -1:
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

        logger.warning("[ChiefOfStaff] Failed to parse JSON: %s...", cleaned[:200])
        return {}

    @staticmethod
    def _fallback_briefing(research_brief: dict) -> dict:
        """Return a minimal fallback briefing when the LLM call fails."""
        target = research_brief.get("target", "unknown target")
        disease = research_brief.get("disease", "unknown disease")

        return {
            "field_landscape": (
                f"Research on {target} in the context of {disease} is an active "
                f"area. A comprehensive assessment requires multi-modal analysis."
            ),
            "data_availability": {
                "databases": [
                    "UniProt", "PDB", "PubMed", "ClinicalTrials.gov",
                    "Open Targets", "ChEMBL",
                ],
                "tools": ["ESM-2", "AlphaFold", "COBRApy"],
                "data_quality": "MEDIUM",
            },
            "recent_developments": [
                "Unable to retrieve recent developments due to briefing failure."
            ],
            "feasibility_assessment": {
                "overall": "MEDIUM",
                "strengths": ["Multiple databases available"],
                "challenges": ["Briefing generation failed — limited context"],
                "estimated_confidence": 0.5,
            },
            "recommended_divisions": [
                {
                    "name": "Target Identification",
                    "priority": "HIGH",
                    "rationale": "Core target analysis required.",
                },
                {
                    "name": "Target Safety",
                    "priority": "HIGH",
                    "rationale": "Safety assessment is always needed.",
                },
                {
                    "name": "Clinical Intelligence",
                    "priority": "MEDIUM",
                    "rationale": "Clinical context informs feasibility.",
                },
            ],
            "key_questions": [
                f"What is the evidence supporting {target} as a viable target?",
                f"What are the known safety liabilities of {target}?",
                "What therapeutic modalities are applicable?",
            ],
            "potential_risks": [
                "Intelligence briefing was generated from fallback — may be incomplete."
            ],
        }
