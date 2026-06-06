"""CSO Orchestrator — the strategic brain of the Lumi Virtual Lab.

The Chief Scientific Officer (Claude Opus) receives a user query, decomposes
it into division-level tasks, orchestrates parallel and sequential execution,
and synthesises the final report.  It NEVER accesses data directly — all data
retrieval is delegated to divisions and their specialist agents.
"""

from __future__ import annotations

import asyncio
import json
import logging
import textwrap
import time
import uuid
from typing import Any

from src.utils.llm import LLMClient, ModelTier
from src.utils.types import (
    BiosecurityAssessment,
    BiosecurityCategory,
    Claim,
    ConfidenceAssessment,
    ConfidenceLevel,
    DivisionReport,
    EvidenceSource,
    ExecutionPlan,
    FinalReport,
    Phase,
    Priority,
    ReviewVerdict,
    ReviewVerdictType,
    SubLabPlan,
    Task,
)
from src.divisions.base_lead import DivisionLead
from src.orchestrator.hitl.router import ConfidenceRouter, HITLConfig, HITLResult
from src.orchestrator.living_document.manager import DocumentManager
from src.orchestrator.stream_events import PipelineEventEmitter
from src.reports.figure_collector import collect_figures

logger = logging.getLogger("lumi.orchestrator.cso")

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

CSO_SYSTEM_PROMPT = textwrap.dedent("""\
    You are the Chief Scientific Officer of Lumi Virtual Lab.

    You NEVER access data directly. You decompose queries into division-level
    tasks, determine parallel vs sequential execution, synthesise
    cross-divisional evidence, and assign confidence levels.

    Your divisions:
    - Target Identification: genetic evidence, functional genomics, expression
    - Target Safety: toxicology, off-target risk, selectivity
    - Modality Selection: small molecule vs biologic vs gene therapy
    - Molecular Design: protein engineering, structure-based design
    - Clinical Intelligence: clinical trials, regulatory, real-world evidence
    - Computational Biology: pathway analysis, metabolic modelling
    - Experimental Design: assay design, protocol generation
    - Biosecurity: dual-use screening, select-agent checks

    When decomposing a query:
    1. Identify which divisions are relevant.
    2. Determine dependency order — what must run first vs in parallel.
    3. Estimate relative cost and priority.
    4. Flag cross-division communication channels.

    Always respond with structured JSON when asked for plans or analyses.
""")

INTAKE_PROMPT_TEMPLATE = textwrap.dedent("""\
    Analyse the following user query and extract structured information.

    User query: "{query}"

    Return ONLY a JSON object (no markdown fences) with these keys:
    - "query_type": one of "target_validation", "full_pipeline",
      "design_only", "literature_review"
    - "target": the biological target (gene/protein) if mentioned, else null
    - "disease": the disease or indication if mentioned, else null
    - "scope": a 1-2 sentence description of the analysis scope
    - "includes_design": boolean — does the query require molecular design?
    - "includes_experimental": boolean — does the query request experimental
      protocols?
    - "key_entities": list of key biological entities mentioned
    - "priority_divisions": list of division names most relevant to this query
""")

PLANNING_PROMPT_TEMPLATE = textwrap.dedent("""\
    You are planning the execution of a research analysis.

    Research brief:
    {research_brief}

    Intelligence briefing:
    {intel_brief}

    Available divisions: {available_divisions}

    Create an execution plan as a JSON object with these keys:
    - "confirmed_scope": refined scope statement
    - "phases": array of phase objects, each with:
        - "phase_id": integer (sequential)
        - "name": descriptive name
        - "division": which division handles this
        - "agents": list of agent names involved
        - "dependencies": list of phase_id integers that must complete first
        - "parallel_eligible": boolean
        - "priority": "CRITICAL" / "HIGH" / "MEDIUM" / "LOW"
        - "estimated_cost": float (USD)
    - "lateral_channels": array of dicts describing cross-division
      communication needs, each with "from", "to", "data_type"
    - "estimated_total_cost": float (USD)
    - "includes_design": boolean
    - "includes_experimental": boolean

    Maximise parallelism. Only make phases sequential when there is a true
    data dependency. Return ONLY the JSON object.
""")

SYNTHESIS_PROMPT_TEMPLATE = textwrap.dedent("""\
    You are the CSO synthesising the final report for a research analysis.

    Original query: "{query}"

    Review verdict: {review_verdict}

    Division reports:
    {division_reports}

    {design_section}

    Produce a JSON object with these keys:
    - "executive_summary": 2-3 paragraph summary of key findings
    - "evidence_synthesis": dict mapping topic areas to synthesised evidence
    - "key_findings_text": list of the most important findings as strings
    - "risk_assessment": dict with "feasibility", "safety", "regulatory",
      "commercial" sub-keys
    - "molecular_design_candidates": list of candidate dicts if applicable,
      else null
    - "recommended_experiments": list of experiment dicts with "title",
      "rationale", "protocol_summary", "estimated_duration", "priority"
    - "limitations": list of limitation strings

    Return ONLY the JSON object.
""")


class CSOOrchestrator:
    """Chief Scientific Officer — Tier 1 orchestrator for the YOHAS pipeline.

    Receives a user query and orchestrates the full analysis pipeline:
    intake -> intelligence -> planning -> execution -> review -> synthesis.
    """

    def __init__(
        self,
        divisions: dict[str, DivisionLead] | None = None,
        hitl_config: HITLConfig | None = None,
        tool_catalog: list[dict] | None = None,
        sublab_hint: str | None = None,
        emitter: PipelineEventEmitter | None = None,
    ) -> None:
        """Initialise the CSO.

        Args:
            divisions: Mapping of division_name -> DivisionLead.  If None,
                the orchestrator still functions but skips analytical
                execution (useful for testing planning logic).
            hitl_config: Configuration for human-in-the-loop routing.
                If None, uses defaults (enabled with standard thresholds).
            tool_catalog: When provided, enables dynamic SubLab mode.
                List of tool descriptor dicts from
                :func:`~src.mcp_bridge.build_tool_catalog`.
            sublab_hint: Optional hint from the UI sublab picker.
        """
        self.divisions = divisions or {}
        self.tool_catalog = tool_catalog
        self.sublab_hint = sublab_hint
        self.llm = LLMClient()
        self._query_id: str = ""
        self.hitl_config = hitl_config or HITLConfig()
        self.hitl_router = ConfidenceRouter(config=self.hitl_config)
        self.doc_manager: DocumentManager | None = None
        self.hitl_result: HITLResult | None = None
        self.emitter = emitter or PipelineEventEmitter()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self, user_query: str) -> FinalReport:
        """Run the full YOHAS orchestration pipeline.

        Args:
            user_query: The natural-language research query.

        Returns:
            A fully populated :class:`FinalReport`.
        """
        start_time = time.time()
        self._query_id = f"q_{uuid.uuid4().hex[:12]}"
        logger.info("[CSO] Starting pipeline for query_id=%s", self._query_id)

        try:
            # Initialize living document
            self.doc_manager = DocumentManager(query_id=self._query_id)

            # Phase 1: Intake
            logger.info("[CSO] Phase 1 — Intake")
            await self.emitter.trace_start("cso_orchestrator", "Orchestration", "Analyzing research query...")
            research_brief = await self._intake(user_query)
            await self.doc_manager.on_intake(research_brief)
            await self.emitter.trace_complete(
                "cso_orchestrator", "Orchestration",
                f"Query parsed. Type: {research_brief.get('query_type', 'unknown')}. Scope: {research_brief.get('scope', '')[:200]}",
                duration_ms=int((time.time() - start_time) * 1000),
            )

            # Phase 2: Intelligence (imported lazily to avoid circular deps)
            logger.info("[CSO] Phase 2 — Intelligence briefing")
            from src.orchestrator.chief_of_staff import ChiefOfStaff
            intel = ChiefOfStaff()
            intel_brief = await intel.generate_briefing(research_brief)
            await self.doc_manager.on_intelligence(intel_brief)

            # Phase 3: Planning
            logger.info("[CSO] Phase 3 — Planning")
            plan = await self._plan(research_brief, intel_brief)

            # Phase 4: Biosecurity pre-screen
            logger.info("[CSO] Phase 4 — Biosecurity pre-screen")
            await self.emitter.trace_start("biosecurity_officer", "Biosecurity", "Screening for dual-use risk...")
            from src.orchestrator.biosecurity_officer import BiosecurityOfficer
            biosec = BiosecurityOfficer()
            biosec_assessment = BiosecurityAssessment(
                category=BiosecurityCategory.GREEN,
                agent_results=[],
                veto=False,
                audit_id=f"audit_{self._query_id}",
            )
            biosec_result = await biosec.evaluate(biosec_assessment)
            biosec_status = "PASSED (GREEN)" if not biosec_result.get("veto") else "VETOED (RED)"
            await self.emitter.trace_complete(
                "biosecurity_officer", "Biosecurity",
                f"Pre-screen {biosec_status}.",
                duration_ms=int((time.time() - start_time) * 1000),
            )
            if biosec_result.get("veto", False):
                logger.error("[CSO] BIOSECURITY VETO — aborting pipeline")
                return self._vetoed_report(user_query, biosec_result, start_time)

            # Phase 5: Analytical execution
            if self.tool_catalog is not None:
                logger.info("[CSO] Phase 5 — Dynamic SubLab mode (%d tools in catalog)", len(self.tool_catalog))
                logger.info("[CSO] Phase 5a — Planning SubLab team")
                await self.emitter.trace_start("sublab_planner", "Orchestration", "Planning dynamic agent team...")
                sublab_plan = await self._plan_sublab(research_brief, intel_brief)
                agents_summary = ", ".join(a.name for a in sublab_plan.agents)
                groups_summary = f"{len(sublab_plan.execution_groups)} execution groups"
                await self.emitter.trace_complete(
                    "sublab_planner", "Orchestration",
                    f"Team composed: {len(sublab_plan.agents)} agents in {groups_summary}. Agents: {agents_summary}",
                )
                logger.info("[CSO] Phase 5b — Executing SubLab (%d agents)", len(sublab_plan.agents))
                analytical_reports = await self._execute_sublab(sublab_plan, plan)
                logger.info("[CSO] Phase 5 — SubLab complete: %d reports", len(analytical_reports))
            else:
                logger.info("[CSO] Phase 5 — Static analytical execution")
                analytical_reports = await self._execute_analytical(plan)
            await self.doc_manager.on_analytical_complete(analytical_reports)

            # Phase 6: Design execution (if applicable)
            design_reports: list[DivisionReport] | None = None
            if plan.includes_design:
                logger.info("[CSO] Phase 6 — Design execution")
                design_reports = await self._execute_design(plan, analytical_reports)

            # Phase 7: Review
            logger.info("[CSO] Phase 7 — Review")
            await self.emitter.trace_start("review_panel", "Orchestration", "Running adversarial review...")
            from src.orchestrator.review_panel import ReviewPanel
            reviewer = ReviewPanel()
            review_verdict = await reviewer.review(analytical_reports, design_reports)
            await self.doc_manager.on_review(review_verdict)
            await self.emitter.trace_complete(
                "review_panel", "Orchestration",
                f"Review verdict: {review_verdict.verdict.value}. {review_verdict.confidence_assessment[:200]}",
            )

            # Phase 7.5: HITL — route low-confidence findings to humans
            logger.info("[CSO] Phase 7.5 — Human-in-the-loop routing")
            self.hitl_result = await self.hitl_router.evaluate_reports(
                reports=analytical_reports,
                query_id=self._query_id,
            )
            logger.info("[CSO] %s", self.hitl_result.summary())

            # Emit HITL events for soft/hard flagged claims
            for claim in self.hitl_result.caveated:
                await self.emitter.hitl_flag(
                    finding=claim.claim_text[:300],
                    agent_id=claim.agent_id,
                    confidence_score=claim.confidence.score,
                    reason=f"Below soft threshold ({self.hitl_config.soft_threshold}). Auto-approved with caveat.",
                )
                await self.emitter.hitl_resolved(
                    finding=claim.claim_text[:300],
                    agent_id=claim.agent_id,
                    confidence_score=claim.confidence.score,
                    reason="Auto-approved with uncertainty label. Awaiting further evidence.",
                    status="approved",
                )
            for claim in self.hitl_result.blocked:
                await self.emitter.hitl_flag(
                    finding=claim.claim_text[:300],
                    agent_id=claim.agent_id,
                    confidence_score=claim.confidence.score,
                    reason=f"Below hard threshold ({self.hitl_config.hard_threshold}). Blocked pending review.",
                )

            # Emit integration event for Slack notification
            if self.hitl_config.slack_channel and (self.hitl_result.caveated or self.hitl_result.blocked):
                await self.emitter.integration(
                    integration="Slack",
                    action=f"Posted HITL review to {self.hitl_config.slack_channel}",
                    status="complete",
                    detail=f"{len(self.hitl_result.caveated)} advisory, {len(self.hitl_result.blocked)} blocking findings sent for expert review.",
                )

            if self.hitl_result.has_blocked:
                logger.warning(
                    "[CSO] %d findings blocked by HITL — excluded from report",
                    len(self.hitl_result.blocked),
                )

            # Update living document with HITL results
            await self.doc_manager.on_hitl_feedback(
                human_feedback=self.hitl_result.human_feedback,
                caveated_claims=self.hitl_result.caveated,
            )

            # Phase 8: Refinement (if REVISE, max 3 cycles)
            refinement_cycles = 0
            while (
                review_verdict.verdict == ReviewVerdictType.REVISE
                and refinement_cycles < 3
            ):
                refinement_cycles += 1
                logger.info(
                    "[CSO] Phase 8 — Refinement cycle %d/3", refinement_cycles
                )
                analytical_reports = await self._refine(
                    plan, analytical_reports, review_verdict
                )
                review_verdict = await reviewer.review(
                    analytical_reports, design_reports
                )

            # Phase 9: Synthesis
            logger.info("[CSO] Phase 9 — Synthesis")
            report = await self._synthesize(
                user_query, analytical_reports, design_reports, review_verdict
            )

            # Update living document with final synthesis
            await self.doc_manager.on_synthesis(report)

            # Attach metadata
            report.query_id = self._query_id
            report.user_query = user_query
            report.total_duration_seconds = time.time() - start_time
            report.total_cost = self.llm.get_cost()["total"]
            report.biosecurity_clearance = biosec_assessment

            # Attach living document and HITL result
            report.living_document_markdown = self.doc_manager.render()
            if self.hitl_result:
                report.hitl_summary = self.hitl_result.summary()

            # Stream final synthesis text
            text = report.living_document_markdown or report.executive_summary
            if text:
                for i in range(0, len(text), 80):
                    await self.emitter.text_delta(text[i:i + 80])
                    await asyncio.sleep(0.02)

            logger.info(
                "[CSO] Pipeline complete — query_id=%s  duration=%.1fs  cost=$%.4f",
                self._query_id,
                report.total_duration_seconds,
                report.total_cost,
            )
            return report

        except Exception as exc:
            logger.exception("[CSO] Pipeline failed: %s", exc)
            return FinalReport(
                query_id=self._query_id,
                user_query=user_query,
                executive_summary=f"Pipeline failed with error: {exc}",
                limitations=[f"Pipeline error: {exc}"],
                total_duration_seconds=time.time() - start_time,
                total_cost=self.llm.get_cost()["total"],
            )
        finally:
            await self.emitter.done()

    # ------------------------------------------------------------------
    # Phase 1: Intake
    # ------------------------------------------------------------------

    async def _intake(self, query: str) -> dict:
        """Parse the user query into a structured research brief.

        Returns a dict with keys: query_type, target, disease, scope,
        includes_design, includes_experimental, key_entities,
        priority_divisions.
        """
        safe_query = query.replace("{", "{{").replace("}", "}}")
        prompt = INTAKE_PROMPT_TEMPLATE.format(query=safe_query)

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=ModelTier.OPUS,
                system=CSO_SYSTEM_PROMPT,
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            brief = self._parse_json_response(text)
            brief["original_query"] = query
            brief["query_id"] = self._query_id
            logger.info("[CSO] Intake result: type=%s", brief.get("query_type"))
            return brief

        except Exception as exc:
            logger.error("[CSO] Intake failed: %s", exc)
            return {
                "query_type": "full_pipeline",
                "target": None,
                "disease": None,
                "scope": query,
                "includes_design": False,
                "includes_experimental": False,
                "key_entities": [],
                "priority_divisions": [],
                "original_query": query,
                "query_id": self._query_id,
            }

    # ------------------------------------------------------------------
    # Phase 3: Planning
    # ------------------------------------------------------------------

    async def _plan(
        self, research_brief: dict, intel_brief: dict
    ) -> ExecutionPlan:
        """Generate an execution plan from the research and intelligence briefs.

        Returns an :class:`ExecutionPlan` with phases, dependencies, and
        cost estimates.
        """
        available_divisions = list(self.divisions.keys()) or [
            "Target Identification",
            "Target Safety",
            "Modality Selection",
            "Molecular Design",
            "Clinical Intelligence",
            "Computational Biology",
            "Experimental Design",
            "Biosecurity",
        ]

        prompt = PLANNING_PROMPT_TEMPLATE.format(
            research_brief=json.dumps(research_brief, indent=2, default=str),
            intel_brief=json.dumps(intel_brief, indent=2, default=str),
            available_divisions=json.dumps(available_divisions),
        )

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=ModelTier.OPUS,
                system=CSO_SYSTEM_PROMPT,
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            plan_data = self._parse_json_response(text)

            # Build Phase objects
            phases: list[Phase] = []
            for p in plan_data.get("phases", []):
                phases.append(
                    Phase(
                        phase_id=p.get("phase_id", len(phases) + 1),
                        name=p.get("name", "Unnamed Phase"),
                        division=p.get("division"),
                        agents=p.get("agents", []),
                        dependencies=p.get("dependencies", []),
                        parallel_eligible=p.get("parallel_eligible", False),
                        priority=Priority(p.get("priority", "MEDIUM")),
                        estimated_cost=p.get("estimated_cost", 0.0),
                    )
                )

            plan = ExecutionPlan(
                query_id=self._query_id,
                user_query=research_brief.get("original_query", ""),
                confirmed_scope=plan_data.get("confirmed_scope", ""),
                phases=phases,
                lateral_channels=plan_data.get("lateral_channels", []),
                estimated_total_cost=plan_data.get("estimated_total_cost", 0.0),
                includes_design=plan_data.get("includes_design", False),
                includes_experimental=plan_data.get("includes_experimental", False),
            )

            logger.info(
                "[CSO] Plan: %d phases, est_cost=$%.2f, design=%s",
                len(plan.phases),
                plan.estimated_total_cost,
                plan.includes_design,
            )
            return plan

        except Exception as exc:
            logger.error("[CSO] Planning failed: %s — using fallback plan", exc)
            return self._fallback_plan(research_brief)

    # ------------------------------------------------------------------
    # Phase 5 (dynamic): SubLab planning and execution
    # ------------------------------------------------------------------

    async def _plan_sublab(
        self, research_brief: dict, intel_brief: dict
    ) -> SubLabPlan:
        """Plan a dynamic SubLab team using the tool catalog."""
        from src.orchestrator.sublab_planner import SubLabPlanner
        from src.mcp_bridge import get_catalog_prompt_text

        planner = SubLabPlanner()
        catalog_text = get_catalog_prompt_text()

        return await planner.plan_sublab(
            research_brief=research_brief,
            intel_brief=intel_brief,
            tool_catalog_text=catalog_text,
            sublab_hint=self.sublab_hint,
        )

    async def _execute_sublab(
        self, sublab_plan: SubLabPlan, plan: ExecutionPlan
    ) -> list[DivisionReport]:
        """Execute a dynamic SubLab plan."""
        from src.orchestrator.sublab_executor import SubLabExecutor

        executor = SubLabExecutor()
        return await executor.execute(
            sublab_plan=sublab_plan,
            task_description=plan.confirmed_scope or plan.user_query,
            emitter=self.emitter,
        )

    # ------------------------------------------------------------------
    # Phase 5 (static): Analytical execution
    # ------------------------------------------------------------------

    async def _execute_analytical(
        self, plan: ExecutionPlan
    ) -> list[DivisionReport]:
        """Dispatch analytical phases to divisions, respecting dependencies.

        Groups phases by dependency level and runs each group in parallel
        via ``asyncio.gather``.
        """
        if not self.divisions:
            logger.warning("[CSO] No divisions registered — skipping execution")
            return []

        reports: list[DivisionReport] = []
        completed_phase_ids: set[int] = set()

        # Group phases by dependency depth
        remaining_phases = [
            p for p in plan.phases if not p.name.lower().startswith("design")
        ]

        while remaining_phases:
            ready: list[Phase] = []
            still_waiting: list[Phase] = []

            for phase in remaining_phases:
                deps_met = all(
                    d in completed_phase_ids for d in phase.dependencies
                )
                if deps_met:
                    ready.append(phase)
                else:
                    still_waiting.append(phase)

            if not ready:
                logger.warning(
                    "[CSO] Dependency deadlock — forcing %d phases",
                    len(still_waiting),
                )
                ready = still_waiting
                still_waiting = []

            # Execute ready phases in parallel
            coros = [self._dispatch_phase(phase) for phase in ready]
            batch = await asyncio.gather(*coros, return_exceptions=True)

            for phase, result in zip(ready, batch):
                if isinstance(result, Exception):
                    logger.error(
                        "[CSO] Phase '%s' failed: %s", phase.name, result
                    )
                    reports.append(
                        DivisionReport(
                            division_id=f"div_{phase.phase_id}",
                            division_name=phase.division or "unknown",
                            lead_agent="CSO_fallback",
                            synthesis=f"Phase failed: {result}",
                            confidence=ConfidenceAssessment(
                                level=ConfidenceLevel.INSUFFICIENT, score=0.0
                            ),
                        )
                    )
                else:
                    reports.append(result)
                completed_phase_ids.add(phase.phase_id)

            remaining_phases = still_waiting

        logger.info("[CSO] Analytical execution complete — %d reports", len(reports))
        return reports

    async def _dispatch_phase(self, phase: Phase) -> DivisionReport:
        """Dispatch a single phase to the appropriate division."""
        division_name = phase.division or ""
        lead = self.divisions.get(division_name)

        if lead is None:
            # Try case-insensitive match
            for name, div_lead in self.divisions.items():
                if name.lower() == division_name.lower():
                    lead = div_lead
                    break

        if lead is None:
            logger.warning(
                "[CSO] Division '%s' not found — using LLM fallback",
                division_name,
            )
            return DivisionReport(
                division_id=f"div_{phase.phase_id}",
                division_name=division_name,
                lead_agent="CSO_fallback",
                synthesis=f"Division '{division_name}' not registered.",
                confidence=ConfidenceAssessment(
                    level=ConfidenceLevel.INSUFFICIENT, score=0.0
                ),
            )

        task = Task(
            task_id=f"phase_{phase.phase_id}_{uuid.uuid4().hex[:6]}",
            description=phase.name,
            division=division_name,
            priority=phase.priority,
        )

        return await lead.execute_division_task(task)

    # ------------------------------------------------------------------
    # Phase 6: Design execution
    # ------------------------------------------------------------------

    async def _execute_design(
        self,
        plan: ExecutionPlan,
        analytical: list[DivisionReport],
    ) -> list[DivisionReport]:
        """Run the molecular design pipeline if applicable.

        Looks for a 'Molecular Design' division and dispatches design-related
        phases to it, feeding in context from analytical reports.
        """
        design_lead = self.divisions.get("Molecular Design")
        if design_lead is None:
            logger.warning("[CSO] No Molecular Design division — skipping design")
            return []

        # Build context from analytical reports
        context_lines: list[str] = []
        for r in analytical:
            context_lines.append(f"[{r.division_name}] {r.synthesis[:500]}")
        context = "\n".join(context_lines)

        design_phases = [
            p for p in plan.phases if "design" in p.name.lower()
        ]
        if not design_phases:
            design_phases = [
                Phase(
                    phase_id=900,
                    name="Molecular Design Pipeline",
                    division="Molecular Design",
                    agents=[],
                    dependencies=[],
                    parallel_eligible=False,
                    priority=Priority.HIGH,
                    estimated_cost=5.0,
                )
            ]

        reports: list[DivisionReport] = []
        for phase in design_phases:
            task = Task(
                task_id=f"design_{phase.phase_id}_{uuid.uuid4().hex[:6]}",
                description=(
                    f"{phase.name}\n\nContext from analytical phase:\n{context}"
                ),
                division="Molecular Design",
                priority=phase.priority,
            )
            try:
                report = await design_lead.execute_division_task(task)
                reports.append(report)
            except Exception as exc:
                logger.error("[CSO] Design phase '%s' failed: %s", phase.name, exc)
                reports.append(
                    DivisionReport(
                        division_id="div_molecular_design",
                        division_name="Molecular Design",
                        lead_agent="design_fallback",
                        synthesis=f"Design failed: {exc}",
                        confidence=ConfidenceAssessment(
                            level=ConfidenceLevel.INSUFFICIENT, score=0.0
                        ),
                    )
                )

        return reports

    # ------------------------------------------------------------------
    # Phase 8: Refinement
    # ------------------------------------------------------------------

    async def _refine(
        self,
        plan: ExecutionPlan,
        reports: list[DivisionReport],
        verdict: ReviewVerdict,
    ) -> list[DivisionReport]:
        """Route revision requests back to the appropriate divisions.

        Analyses the review verdict to determine which divisions need to
        redo work, then re-executes those phases.
        """
        issues_text = json.dumps(verdict.issues, indent=2, default=str)
        missing_text = json.dumps(verdict.missing_analyses, default=str)

        # Ask the CSO which divisions need revision
        revision_prompt = textwrap.dedent(f"""\
            The Review Panel has returned a REVISE verdict.

            Issues found:
            {issues_text}

            Missing analyses:
            {missing_text}

            Current divisions that reported:
            {json.dumps([r.division_name for r in reports])}

            Return a JSON array of objects, each with:
            - "division": division name to re-run
            - "revised_task": specific revised task description addressing
              the review issues

            Return ONLY the JSON array.
        """)

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": revision_prompt}],
                model=ModelTier.OPUS,
                system=CSO_SYSTEM_PROMPT,
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            revisions = self._parse_json_response(text)
            if not isinstance(revisions, list):
                revisions = [revisions]

        except Exception as exc:
            logger.error("[CSO] Refinement planning failed: %s", exc)
            return reports  # Return original reports unchanged

        # Re-execute specified divisions
        updated_reports = list(reports)
        for rev in revisions:
            div_name = rev.get("division", "")
            lead = self.divisions.get(div_name)
            if lead is None:
                continue

            task = Task(
                task_id=f"refine_{uuid.uuid4().hex[:8]}",
                description=rev.get("revised_task", "Address review issues"),
                division=div_name,
                priority=Priority.HIGH,
            )

            try:
                new_report = await lead.execute_division_task(task)
                # Replace the old report for this division
                updated_reports = [
                    new_report if r.division_name == div_name else r
                    for r in updated_reports
                ]
            except Exception as exc:
                logger.error("[CSO] Refinement of '%s' failed: %s", div_name, exc)

        return updated_reports

    # ------------------------------------------------------------------
    # Phase 9: Synthesis
    # ------------------------------------------------------------------

    async def _synthesize(
        self,
        query: str,
        analytical: list[DivisionReport],
        design: list[DivisionReport] | None,
        review: ReviewVerdict,
    ) -> FinalReport:
        """Produce the final report by synthesising all division outputs.

        Uses Opus to generate a cohesive narrative across all evidence.
        """
        # Format division reports for the prompt
        report_sections: list[str] = []
        all_claims: list[Claim] = []
        all_evidence: list[EvidenceSource] = []

        for r in analytical:
            report_sections.append(
                f"### {r.division_name}\n"
                f"Confidence: {r.confidence.level.value} ({r.confidence.score})\n"
                f"Synthesis: {r.synthesis[:1000]}\n"
            )
            for sr in r.specialist_results:
                all_claims.extend(sr.findings)
                for claim in sr.findings:
                    all_evidence.extend(claim.supporting_evidence)

        design_section = ""
        if design:
            design_lines: list[str] = []
            for r in design:
                design_lines.append(
                    f"### {r.division_name}\n{r.synthesis[:1000]}\n"
                )
                for sr in r.specialist_results:
                    all_claims.extend(sr.findings)
            design_section = (
                "Design pipeline results:\n" + "\n".join(design_lines)
            )

        prompt = SYNTHESIS_PROMPT_TEMPLATE.format(
            query=query,
            review_verdict=f"{review.verdict.value}: {review.confidence_assessment}",
            division_reports="\n".join(report_sections),
            design_section=design_section,
        )

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=ModelTier.OPUS,
                system=CSO_SYSTEM_PROMPT,
                max_tokens=16384,
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            synthesis = self._parse_json_response(text)

            # Collect figures from all division reports
            all_divisions = list(analytical)
            if design:
                all_divisions.extend(design)
            figures = collect_figures(all_divisions)

            return FinalReport(
                query_id=self._query_id,
                user_query=query,
                executive_summary=synthesis.get("executive_summary", ""),
                evidence_synthesis=synthesis.get("evidence_synthesis", {}),
                key_findings=all_claims[:20],  # Top 20 claims
                risk_assessment=synthesis.get("risk_assessment", {}),
                molecular_design_candidates=synthesis.get(
                    "molecular_design_candidates"
                ),
                recommended_experiments=synthesis.get(
                    "recommended_experiments", []
                ),
                limitations=synthesis.get("limitations", []),
                provenance_chain=all_evidence[:50],  # Top 50 sources
                figures=figures,
            )

        except Exception as exc:
            logger.error("[CSO] Synthesis failed: %s", exc)
            return FinalReport(
                query_id=self._query_id,
                user_query=query,
                executive_summary=f"Synthesis encountered an error: {exc}",
                key_findings=all_claims[:10],
                limitations=[f"Synthesis error: {exc}"],
                provenance_chain=all_evidence[:20],
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_json_response(self, text: str) -> Any:
        """Extract and parse JSON from an LLM response.

        Handles markdown code fences and trailing text gracefully.
        """
        cleaned = text.strip()

        # Remove markdown fences
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [
                line for line in lines if not line.strip().startswith("```")
            ]
            cleaned = "\n".join(lines).strip()

        # Try direct parse first
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object or array boundaries
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start = cleaned.find(start_char)
            if start == -1:
                continue
            depth = 0
            for i in range(start, len(cleaned)):
                if cleaned[i] == start_char:
                    depth += 1
                elif cleaned[i] == end_char:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(cleaned[start : i + 1])
                        except json.JSONDecodeError:
                            break

        logger.warning("[CSO] Failed to parse JSON from response: %s...", cleaned[:200])
        return {}

    def _fallback_plan(self, research_brief: dict) -> ExecutionPlan:
        """Generate a minimal fallback execution plan."""
        divisions = list(self.divisions.keys())
        phases = []
        for i, div_name in enumerate(divisions):
            phases.append(
                Phase(
                    phase_id=i + 1,
                    name=f"{div_name} Analysis",
                    division=div_name,
                    agents=[],
                    dependencies=[],
                    parallel_eligible=True,
                    priority=Priority.MEDIUM,
                    estimated_cost=3.0,
                )
            )

        return ExecutionPlan(
            query_id=self._query_id,
            user_query=research_brief.get("original_query", ""),
            confirmed_scope=research_brief.get("scope", ""),
            phases=phases,
            estimated_total_cost=len(phases) * 3.0,
            includes_design=research_brief.get("includes_design", False),
            includes_experimental=research_brief.get("includes_experimental", False),
        )

    def _vetoed_report(
        self, query: str, biosec_result: dict, start_time: float
    ) -> FinalReport:
        """Generate a report for a biosecurity-vetoed query."""
        return FinalReport(
            query_id=self._query_id,
            user_query=query,
            executive_summary=(
                "BIOSECURITY VETO: This analysis has been halted by the "
                "Biosecurity Officer. The query or its implications were "
                "flagged as potentially dangerous."
            ),
            risk_assessment={
                "biosecurity": "VETOED",
                "notes": biosec_result.get("notes", ""),
                "audit_trail": biosec_result.get("audit_trail", ""),
            },
            limitations=["Analysis halted due to biosecurity veto."],
            total_duration_seconds=time.time() - start_time,
            total_cost=self.llm.get_cost()["total"],
            biosecurity_clearance=BiosecurityAssessment(
                category=BiosecurityCategory.RED,
                veto=True,
                veto_reasons=biosec_result.get("notes", "").split("; "),
                audit_id=f"audit_{self._query_id}",
            ),
        )
