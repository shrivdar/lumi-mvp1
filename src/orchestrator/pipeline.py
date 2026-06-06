"""YOHAS Pipeline entry point — wires all Tier 1 components together.

Provides :func:`run_yohas_pipeline`, the single async function that
external code calls to execute a full analysis.  Internally it
instantiates and coordinates the CSO Orchestrator, Chief of Staff,
Review Panel, Biosecurity Officer, and World Model.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

from src.divisions.base_lead import DivisionLead
from src.orchestrator.stream_events import PipelineEventEmitter, StreamCallback
from src.utils.cost_tracker import cost_tracker
from src.utils.types import FinalReport

from src.orchestrator.cso import CSOOrchestrator
from src.orchestrator.world_model import WorldModel

logger = logging.getLogger("lumi.orchestrator.pipeline")

# ---------------------------------------------------------------------------
# Default World Model path
# ---------------------------------------------------------------------------

_DEFAULT_WM_PATH = "data/world_model.db"


async def run_yohas_pipeline(
    user_query: str,
    divisions: dict[str, DivisionLead] | None = None,
    dynamic: bool = False,
    sublab_hint: str | None = None,
    world_model_path: str = _DEFAULT_WM_PATH,
    cost_ceiling: float = 100.0,
    enable_world_model: bool = True,
    on_event: StreamCallback | None = None,
) -> FinalReport:
    """Execute the full 9-phase YOHAS orchestration pipeline.

    This is the primary entry point for running a Lumi Virtual Lab
    analysis.  It:

    1. Initialises the World Model (persistent knowledge store).
    2. Checks cost ceiling before starting.
    3. Runs the CSO Orchestrator (which internally handles all 9 phases).
    4. Persists results to the World Model.
    5. Returns the final report.

    Args:
        user_query: The natural-language research query from the user.
        divisions: Optional mapping of division_name -> DivisionLead.
            If None, the CSO operates in planning-only mode.
        dynamic: When True, the orchestrator dynamically composes agent
            teams from the tool catalog instead of using the static
            17-agent roster. The full ``create_system()`` is not needed;
            only the biosecurity division is created for the veto gate.
        sublab_hint: Optional hint for the SubLab planner (used as
            context, not constraint). Only used when ``dynamic=True``.
        world_model_path: Path to the SQLite world model database.
        cost_ceiling: Maximum allowed spend in USD. Pipeline will not
            start if ceiling is already exceeded.
        enable_world_model: Whether to persist results to the World Model.

    Returns:
        A fully populated :class:`FinalReport`.
    """
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("[Pipeline] Starting YOHAS pipeline")
    logger.info("[Pipeline] Query: %s", user_query[:200])
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Pre-flight checks
    # ------------------------------------------------------------------

    # Cost ceiling check
    exceeded, pct = cost_tracker.check_ceiling(cost_ceiling)
    if exceeded:
        logger.error(
            "[Pipeline] Cost ceiling exceeded (%.1f%% of $%.2f) — aborting",
            pct,
            cost_ceiling,
        )
        return FinalReport(
            query_id="cost_exceeded",
            user_query=user_query,
            executive_summary=(
                f"Pipeline aborted: cost ceiling of ${cost_ceiling:.2f} has "
                f"been exceeded ({pct:.1f}% spent)."
            ),
            limitations=["Cost ceiling exceeded."],
            total_cost=cost_tracker.get_total_cost(),
            total_duration_seconds=time.time() - start_time,
        )

    # ------------------------------------------------------------------
    # Initialise World Model
    # ------------------------------------------------------------------

    world_model: Optional[WorldModel] = None
    if enable_world_model:
        try:
            world_model = WorldModel(db_path=world_model_path)
            await world_model.initialize()
            stats = await world_model.get_stats()
            logger.info(
                "[Pipeline] World Model loaded — %d entities, %d claims, %d analyses",
                stats.get("entities_count", 0),
                stats.get("claims_count", 0),
                stats.get("analysis_history_count", 0),
            )
        except Exception as exc:
            logger.warning(
                "[Pipeline] World Model init failed: %s — continuing without it",
                exc,
            )
            world_model = None

    # ------------------------------------------------------------------
    # Run the CSO Orchestrator
    # ------------------------------------------------------------------

    try:
        # Build tool catalog for dynamic mode
        tool_catalog = None
        if dynamic:
            from src.mcp_bridge import build_tool_catalog
            tool_catalog = build_tool_catalog()
            logger.info(
                "[Pipeline] Dynamic mode: tool catalog with %d tools",
                len(tool_catalog),
            )
            # In dynamic mode, only create biosecurity division if not provided
            if divisions is None:
                from src.factory import create_minimal_system
                divisions = create_minimal_system()

        emitter = PipelineEventEmitter(on_event)

        # Wire HITL config from env vars
        from src.orchestrator.hitl.router import HITLConfig
        slack_channel = os.environ.get("LUMI_SLACK_CHANNEL", "")
        hitl_config = HITLConfig(slack_channel=slack_channel)

        cso = CSOOrchestrator(
            divisions=divisions,
            tool_catalog=tool_catalog,
            sublab_hint=sublab_hint,
            emitter=emitter,
            hitl_config=hitl_config,
        )

        # Wire MCP Slack sender if available
        if slack_channel:
            try:
                from src.mcp_servers.slack.server import slack_post_message
                cso.hitl_router.notifier.set_mcp_sender(slack_post_message)
                logger.info("[Pipeline] Slack notifier wired to channel %s", slack_channel)
            except ImportError:
                logger.debug("[Pipeline] Slack MCP server not available for HITL notifier")
        report = await cso.run(user_query)

    except Exception as exc:
        logger.exception("[Pipeline] CSO Orchestrator failed: %s", exc)
        report = FinalReport(
            query_id="pipeline_error",
            user_query=user_query,
            executive_summary=f"Pipeline failed with error: {exc}",
            limitations=[f"Pipeline error: {exc}"],
            total_cost=cost_tracker.get_total_cost(),
            total_duration_seconds=time.time() - start_time,
        )

    # ------------------------------------------------------------------
    # Persist to World Model
    # ------------------------------------------------------------------

    if world_model is not None:
        try:
            await world_model.update_from_report(report)
            logger.info("[Pipeline] Results persisted to World Model")
        except Exception as exc:
            logger.warning("[Pipeline] World Model update failed: %s", exc)

    # ------------------------------------------------------------------
    # Final cost report
    # ------------------------------------------------------------------

    cost_report = cost_tracker.get_cost_report()
    report.total_cost = cost_report["total_cost"]
    report.total_duration_seconds = time.time() - start_time

    logger.info("=" * 60)
    logger.info("[Pipeline] YOHAS pipeline complete")
    logger.info("[Pipeline] Duration: %.1fs", report.total_duration_seconds)
    logger.info("[Pipeline] Total cost: $%.4f", report.total_cost)
    logger.info(
        "[Pipeline] Cost by model: %s",
        {k: f"${v:.4f}" for k, v in cost_report.get("by_model", {}).items()},
    )
    logger.info("[Pipeline] LLM calls: %d", cost_report.get("call_count", 0))
    logger.info("=" * 60)

    # Close World Model connection
    if world_model is not None:
        try:
            await world_model.close()
        except Exception:
            pass

    return report


async def run_quick_analysis(
    user_query: str,
    divisions: dict[str, DivisionLead] | None = None,
) -> FinalReport:
    """Run a lightweight analysis without the World Model or full review.

    Useful for quick queries or testing. Skips World Model persistence
    and uses a lower cost ceiling.

    Args:
        user_query: The research query.
        divisions: Optional division mapping.

    Returns:
        A :class:`FinalReport`.
    """
    return await run_yohas_pipeline(
        user_query=user_query,
        divisions=divisions,
        cost_ceiling=25.0,
        enable_world_model=False,
    )
