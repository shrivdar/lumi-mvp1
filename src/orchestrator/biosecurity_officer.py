"""Biosecurity Officer — hard veto agent for the YOHAS pipeline.

Evaluates queries and generated sequences against biosecurity criteria.
Has the authority to HARD VETO any analysis that poses biosecurity risk.

Threat classification (traffic-light scheme):
- RED    -> HARD VETO.  Pipeline halts immediately.
- ORANGE -> Flag for review.  Proceed with mandatory human oversight.
- YELLOW -> Proceed with caution.  Note added to report.
- GREEN  -> All clear.  Proceed normally.
"""

from __future__ import annotations

import json
import logging
import textwrap
import uuid

from src.utils.llm import LLMClient, ModelTier
from src.utils.types import (
    BiosecurityAssessment,
    BiosecurityCategory,
)

logger = logging.getLogger("lumi.orchestrator.biosecurity_officer")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

BIOSECURITY_SYSTEM_PROMPT = textwrap.dedent("""\
    You are the Biosecurity Officer for Lumi Virtual Lab. You have
    ABSOLUTE VETO AUTHORITY over any analysis or design output.

    Your mandate is to prevent the generation of dangerous biological
    knowledge or sequences that could be misused. You evaluate against:

    1. Select Agent / Toxin List — CDC/USDA regulated agents and toxins.
    2. Dual-Use Research of Concern (DURC) — Fink Report categories.
    3. Gain-of-Function (GoF) indicators — enhanced pathogenicity,
       transmissibility, immune evasion, host-range expansion.
    4. Biological Weapons Convention (BWC) compliance.
    5. Australia Group export controls.

    Threat classification:
    - RED: Clear dual-use / select agent / GoF risk. HARD VETO.
    - ORANGE: Possible concern requiring human review. Flag and
      proceed only with explicit human oversight.
    - YELLOW: Minor concern. Proceed with notes.
    - GREEN: No concern identified. Proceed normally.

    You MUST err on the side of caution. When in doubt, flag it.

    Always respond with structured JSON assessments.
""")

EVALUATION_PROMPT_TEMPLATE = textwrap.dedent("""\
    Evaluate the following for biosecurity concerns.

    Assessment context:
    {assessment_json}

    Perform the following checks:
    1. Select agent / toxin association — does this involve or resemble
       CDC/USDA select agents or toxins?
    2. Dual-use potential — could the knowledge or sequences generated
       be misused for harmful purposes (Fink Report categories)?
    3. Gain-of-function indicators — does this involve enhancing
       pathogenicity, transmissibility, immune evasion, or host range?
    4. BWC / export control compliance — any treaty or regulation issues?
    5. Toxin motif presence — are there known toxin protein domains?

    Return ONLY a JSON object with:
    - "category": "GREEN" / "YELLOW" / "ORANGE" / "RED"
    - "veto": boolean — true ONLY for RED
    - "checks": list of objects, each with:
        - "check_name": string
        - "passed": boolean (true = safe)
        - "category": "GREEN" / "YELLOW" / "ORANGE" / "RED"
        - "details": string explanation
    - "notes": string — summary of findings
    - "audit_trail": string — detailed reasoning for the record
    - "recommended_action": string — what should happen next
""")


class BiosecurityOfficer:
    """Biosecurity screening agent with hard veto authority.

    Evaluates all analyses and designs for biosecurity risk before
    they are included in the final report.
    """

    def __init__(self) -> None:
        self.llm = LLMClient()

    async def evaluate(self, assessment: BiosecurityAssessment) -> dict:
        """Evaluate a biosecurity assessment and determine proceed/veto.

        Args:
            assessment: A :class:`BiosecurityAssessment` containing
                screening results from specialist biosecurity agents.

        Returns:
            A dict with keys: proceed (bool), veto (bool), category,
            notes, audit_trail, checks, recommended_action.
        """
        audit_id = assessment.audit_id or f"audit_{uuid.uuid4().hex[:12]}"

        # If there are already agent results with a RED flag, fast-path veto
        for result in assessment.agent_results:
            if result.category == BiosecurityCategory.RED:
                logger.error(
                    "[BiosecurityOfficer] RED flag from screen '%s': %s",
                    result.screen_name,
                    result.details,
                )
                return {
                    "proceed": False,
                    "veto": True,
                    "category": "RED",
                    "notes": (
                        f"Automatic VETO: Screen '{result.screen_name}' "
                        f"returned RED. Details: {result.details}"
                    ),
                    "audit_trail": (
                        f"audit_id={audit_id}; auto_veto=true; "
                        f"trigger={result.screen_name}; "
                        f"details={result.details}"
                    ),
                    "checks": [],
                    "recommended_action": "HALT — do not proceed under any circumstances.",
                }

        # Run LLM-based evaluation
        assessment_data = {
            "category": assessment.category.value,
            "existing_screen_results": [
                {
                    "screen_name": r.screen_name,
                    "passed": r.passed,
                    "category": r.category.value,
                    "details": r.details,
                    "flagged_domains": r.flagged_domains,
                }
                for r in assessment.agent_results
            ],
            "pre_existing_veto": assessment.veto,
            "veto_reasons": assessment.veto_reasons,
            "audit_id": audit_id,
        }

        prompt = EVALUATION_PROMPT_TEMPLATE.format(
            assessment_json=json.dumps(assessment_data, indent=2, default=str)
        )

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=ModelTier.SONNET,
                system=BIOSECURITY_SYSTEM_PROMPT,
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            result = self._parse_json(text)

            category = result.get("category", "GREEN").upper()
            veto = result.get("veto", False)

            # Enforce: RED always means veto
            if category == "RED":
                veto = True

            proceed = not veto
            if category == "ORANGE":
                proceed = True  # Proceed but flag

            output = {
                "proceed": proceed,
                "veto": veto,
                "category": category,
                "notes": result.get("notes", ""),
                "audit_trail": (
                    f"audit_id={audit_id}; "
                    f"llm_category={category}; "
                    f"veto={veto}; "
                    f"{result.get('audit_trail', '')}"
                ),
                "checks": result.get("checks", []),
                "recommended_action": result.get("recommended_action", ""),
            }

            logger.info(
                "[BiosecurityOfficer] Evaluation: category=%s veto=%s",
                category,
                veto,
            )
            return output

        except Exception as exc:
            logger.error("[BiosecurityOfficer] Evaluation failed: %s", exc)
            # On failure, default to cautious proceed (YELLOW) — do not block
            # on LLM errors, but flag for manual review
            return {
                "proceed": True,
                "veto": False,
                "category": "YELLOW",
                "notes": (
                    f"Biosecurity evaluation encountered an error: {exc}. "
                    f"Proceeding with YELLOW flag for manual review."
                ),
                "audit_trail": (
                    f"audit_id={audit_id}; error={exc}; "
                    f"default_category=YELLOW"
                ),
                "checks": [],
                "recommended_action": (
                    "Manual biosecurity review recommended due to "
                    "evaluation error."
                ),
            }

    async def screen_sequence(self, sequence: str, context: str = "") -> dict:
        """Screen a biological sequence for biosecurity concerns.

        This is a convenience method for screening individual sequences
        (proteins, DNA, etc.) outside of the full pipeline.

        Args:
            sequence: The biological sequence to screen.
            context: Optional context about the sequence's purpose.

        Returns:
            Same structure as :meth:`evaluate`.
        """
        screen_prompt = textwrap.dedent(f"""\
            Screen the following biological sequence for biosecurity concerns.

            Sequence (first 500 chars): {sequence[:500]}
            Sequence length: {len(sequence)}
            Context: {context or "Not provided"}

            Check for:
            1. Similarity to select agents or toxins
            2. Known virulence factor domains
            3. Gain-of-function indicators
            4. Dual-use potential

            Return ONLY a JSON object with:
            - "category": "GREEN" / "YELLOW" / "ORANGE" / "RED"
            - "veto": boolean
            - "notes": string summary
            - "flagged_domains": list of concerning domain names
            - "audit_trail": string
        """)

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": screen_prompt}],
                model=ModelTier.SONNET,
                system=BIOSECURITY_SYSTEM_PROMPT,
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            result = self._parse_json(text)

            category = result.get("category", "YELLOW").upper()
            veto = category == "RED"

            return {
                "proceed": not veto,
                "veto": veto,
                "category": category,
                "notes": result.get("notes", ""),
                "audit_trail": result.get("audit_trail", ""),
                "flagged_domains": result.get("flagged_domains", []),
                "checks": [],
                "recommended_action": "HALT" if veto else "Proceed",
            }

        except Exception as exc:
            logger.error("[BiosecurityOfficer] Sequence screen failed: %s", exc)
            return {
                "proceed": True,
                "veto": False,
                "category": "YELLOW",
                "notes": f"Sequence screening error: {exc}",
                "audit_trail": f"error={exc}",
                "flagged_domains": [],
                "checks": [],
                "recommended_action": "Manual review recommended.",
            }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_json(self, text: str) -> dict:
        """Parse JSON from LLM response with fence handling."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

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

        logger.warning("[BiosecurityOfficer] JSON parse failed: %s...", cleaned[:200])
        return {}
