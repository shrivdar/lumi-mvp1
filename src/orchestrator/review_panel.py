"""Review Panel — adversarial quality gate for the YOHAS pipeline.

Performs a 3-pass review of division outputs using Claude Sonnet:
1. Methodology pass — are the methods sound?
2. Evidence pass — is the evidence sufficient and correctly interpreted?
3. Synthesis pass — does the overall narrative hold together?

Returns a :class:`ReviewVerdict` that can APPROVE, REVISE, or REJECT.
"""

from __future__ import annotations

import json
import logging
import textwrap

from src.utils.llm import LLMClient, ModelTier
from src.utils.types import (
    DivisionReport,
    ReviewVerdict,
    ReviewVerdictType,
)

logger = logging.getLogger("lumi.orchestrator.review_panel")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

REVIEW_SYSTEM_PROMPT = textwrap.dedent("""\
    You are the Review Panel for Lumi Virtual Lab — an adversarial scientific
    quality gate. Your role is to critically evaluate the outputs of division
    analyses and ensure they meet the highest standards of scientific rigour.

    You are deliberately sceptical. You look for:
    - Methodological flaws or inappropriate methods
    - Unsupported claims or logical leaps
    - Missing analyses that should have been performed
    - Contradictions between divisions
    - Overconfident conclusions given the evidence
    - Missing controls, confounders, or alternative explanations

    You do NOT access data or perform analyses yourself. You evaluate
    the quality of what others have produced.

    Your verdicts:
    - APPROVE: The analysis meets quality standards. Minor issues noted.
    - REVISE: Significant issues found. Specific divisions must redo work.
    - REJECT: Fundamental flaws. The analysis cannot be salvaged.
""")

METHODOLOGY_PROMPT_TEMPLATE = textwrap.dedent("""\
    METHODOLOGY REVIEW — Pass 1 of 3

    Evaluate the methodological soundness of the following division reports.

    {reports_text}

    For each division, assess:
    1. Were appropriate methods used for the question being asked?
    2. Were the right tools and databases consulted?
    3. Are there methodological gaps or inappropriate shortcuts?
    4. Were proper statistical methods applied where relevant?

    Return a JSON object with:
    - "division_assessments": dict mapping division name to object with:
        - "methodology_score": float 0-1
        - "issues": list of issue strings
        - "missing_methods": list of methods that should have been used
    - "cross_division_issues": list of strings about methodological
      inconsistencies across divisions
""")

EVIDENCE_PROMPT_TEMPLATE = textwrap.dedent("""\
    EVIDENCE REVIEW — Pass 2 of 3

    Evaluate the evidence quality in the following division reports.

    {reports_text}

    Methodology review findings from Pass 1:
    {methodology_findings}

    For each division, assess:
    1. Are claims supported by sufficient evidence?
    2. Are confidence levels appropriately calibrated?
    3. Are there logical leaps or unsupported inferences?
    4. Is contradicting evidence acknowledged?
    5. Are evidence sources credible and up-to-date?

    Return a JSON object with:
    - "evidence_assessments": dict mapping division name to object with:
        - "evidence_score": float 0-1
        - "unsupported_claims": list of claim descriptions lacking evidence
        - "overconfident_claims": list of claims with inflated confidence
        - "missing_evidence": list of evidence that should have been gathered
    - "contradictions": list of objects with "claim_a", "claim_b",
      "divisions_involved", "severity" (HIGH/MEDIUM/LOW)
""")

SYNTHESIS_REVIEW_PROMPT_TEMPLATE = textwrap.dedent("""\
    SYNTHESIS REVIEW — Pass 3 of 3

    Evaluate the overall coherence and completeness of the analysis.

    {reports_text}

    Methodology findings (Pass 1):
    {methodology_findings}

    Evidence findings (Pass 2):
    {evidence_findings}

    Provide your final verdict as a JSON object with:
    - "verdict": "APPROVE" or "REVISE" or "REJECT"
    - "issues": list of objects, each with:
        - "priority": "HIGH" / "MEDIUM" / "LOW"
        - "description": what the issue is
        - "required_fix": what needs to be done to address it
    - "missing_analyses": list of strings describing analyses that
      should have been performed but were not
    - "confidence_assessment": string — your overall narrative assessment
      of the confidence quality across the entire analysis
    - "strengths": list of strings — what was done well
    - "overall_score": float 0-1

    Decision criteria:
    - APPROVE if overall_score >= 0.7 and no HIGH-priority issues
    - REVISE if overall_score >= 0.4 or there are fixable HIGH-priority issues
    - REJECT if overall_score < 0.4 and issues are fundamental/unfixable
""")


class ReviewPanel:
    """Adversarial review agent that performs 3-pass quality assessment.

    Uses Sonnet for the review passes to balance quality with cost.
    """

    def __init__(self) -> None:
        self.llm = LLMClient()

    async def review(
        self,
        analytical: list[DivisionReport],
        design: list[DivisionReport] | None = None,
    ) -> ReviewVerdict:
        """Perform a 3-pass review of division reports.

        Args:
            analytical: Reports from the analytical execution phase.
            design: Reports from the design execution phase (optional).

        Returns:
            A :class:`ReviewVerdict` with verdict, issues, and assessment.
        """
        all_reports = list(analytical)
        if design:
            all_reports.extend(design)

        if not all_reports:
            logger.warning("[ReviewPanel] No reports to review — auto-approving")
            return ReviewVerdict(
                verdict=ReviewVerdictType.APPROVE,
                issues=[],
                missing_analyses=["No division reports were produced."],
                confidence_assessment="No reports to review.",
            )

        reports_text = self._format_reports(all_reports)

        # Pass 1: Methodology
        logger.info("[ReviewPanel] Pass 1 — Methodology review")
        methodology_findings = await self._methodology_pass(reports_text)

        # Pass 2: Evidence
        logger.info("[ReviewPanel] Pass 2 — Evidence review")
        evidence_findings = await self._evidence_pass(
            reports_text, methodology_findings
        )

        # Pass 3: Synthesis + Verdict
        logger.info("[ReviewPanel] Pass 3 — Synthesis review + verdict")
        verdict = await self._synthesis_pass(
            reports_text, methodology_findings, evidence_findings
        )

        logger.info(
            "[ReviewPanel] Verdict: %s (%d issues, %d missing analyses)",
            verdict.verdict.value,
            len(verdict.issues),
            len(verdict.missing_analyses),
        )
        return verdict

    # ------------------------------------------------------------------
    # Review passes
    # ------------------------------------------------------------------

    async def _methodology_pass(self, reports_text: str) -> dict:
        """Pass 1: Evaluate methodological soundness."""
        prompt = METHODOLOGY_PROMPT_TEMPLATE.format(reports_text=reports_text)

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=ModelTier.SONNET,
                system=REVIEW_SYSTEM_PROMPT,
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            return self._parse_json(text)
        except Exception as exc:
            logger.error("[ReviewPanel] Methodology pass failed: %s", exc)
            return {
                "division_assessments": {},
                "cross_division_issues": [f"Methodology review failed: {exc}"],
            }

    async def _evidence_pass(
        self, reports_text: str, methodology_findings: dict
    ) -> dict:
        """Pass 2: Evaluate evidence quality."""
        prompt = EVIDENCE_PROMPT_TEMPLATE.format(
            reports_text=reports_text,
            methodology_findings=json.dumps(
                methodology_findings, indent=2, default=str
            ),
        )

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=ModelTier.SONNET,
                system=REVIEW_SYSTEM_PROMPT,
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            return self._parse_json(text)
        except Exception as exc:
            logger.error("[ReviewPanel] Evidence pass failed: %s", exc)
            return {
                "evidence_assessments": {},
                "contradictions": [],
            }

    async def _synthesis_pass(
        self,
        reports_text: str,
        methodology_findings: dict,
        evidence_findings: dict,
    ) -> ReviewVerdict:
        """Pass 3: Final synthesis review and verdict."""
        prompt = SYNTHESIS_REVIEW_PROMPT_TEMPLATE.format(
            reports_text=reports_text,
            methodology_findings=json.dumps(
                methodology_findings, indent=2, default=str
            ),
            evidence_findings=json.dumps(
                evidence_findings, indent=2, default=str
            ),
        )

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=ModelTier.SONNET,
                system=REVIEW_SYSTEM_PROMPT,
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            result = self._parse_json(text)

            verdict_str = result.get("verdict", "APPROVE").upper()
            try:
                verdict_type = ReviewVerdictType(verdict_str)
            except ValueError:
                verdict_type = ReviewVerdictType.REVISE

            return ReviewVerdict(
                verdict=verdict_type,
                issues=result.get("issues", []),
                missing_analyses=result.get("missing_analyses", []),
                confidence_assessment=result.get("confidence_assessment", ""),
            )

        except Exception as exc:
            logger.error("[ReviewPanel] Synthesis pass failed: %s", exc)
            return ReviewVerdict(
                verdict=ReviewVerdictType.APPROVE,
                issues=[
                    {
                        "priority": "MEDIUM",
                        "description": f"Review synthesis failed: {exc}",
                        "required_fix": "Manual review recommended.",
                    }
                ],
                missing_analyses=[],
                confidence_assessment=(
                    "Review process encountered an error. "
                    "Auto-approving with caveat."
                ),
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _format_reports(self, reports: list[DivisionReport]) -> str:
        """Format division reports into a readable text block for review."""
        sections: list[str] = []
        for r in reports:
            section = (
                f"## Division: {r.division_name}\n"
                f"Lead Agent: {r.lead_agent}\n"
                f"Confidence: {r.confidence.level.value} "
                f"(score={r.confidence.score})\n"
                f"Caveats: {', '.join(r.confidence.caveats) if r.confidence.caveats else 'None'}\n\n"
                f"Synthesis:\n{r.synthesis}\n\n"
            )

            # Summarise specialist results
            if r.specialist_results:
                section += "Specialist Results:\n"
                for sr in r.specialist_results:
                    findings_text = "; ".join(
                        f"{c.claim_text} [{c.confidence.level.value}]"
                        for c in sr.findings[:5]
                    ) or "No structured findings"
                    section += (
                        f"  - {sr.agent_id}: {findings_text}\n"
                        f"    Tools used: {', '.join(sr.tools_used) or 'None'}\n"
                    )

            if r.lateral_flags:
                section += f"\nLateral Flags: {', '.join(r.lateral_flags)}\n"

            sections.append(section)

        return "\n---\n\n".join(sections)

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

        logger.warning("[ReviewPanel] JSON parse failed: %s...", cleaned[:200])
        return {}
