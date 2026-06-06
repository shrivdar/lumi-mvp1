"""Offline integration test for :meth:`BaseAgent.execute`.

Runs a full agent execution loop under ``LUMI_OFFLINE=1`` so it requires
NO network and NO API key. Relies on the offline-mode contract in
``src.utils.llm`` (deterministic synthetic response containing a
``Finding:`` block, zero cost, no tool_use). If offline mode is somehow
not active, the test skips rather than erroring.

``is_offline()`` reads the environment on every call, so setting the env
var via ``monkeypatch`` before constructing the client is sufficient — no
module reloading is required (and reloading would break identity-based
``ModelTier`` comparisons in sibling test modules).
"""

from __future__ import annotations

import pytest

from src.agents.base_agent import BaseAgent
from src.utils.llm import ModelTier, is_offline
from src.utils.types import Priority, Task


@pytest.fixture(autouse=True)
def _force_offline(monkeypatch):
    """Activate offline mode for every test in this module."""
    monkeypatch.setenv("LUMI_OFFLINE", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


async def test_execute_offline_produces_claim_at_zero_cost():
    if not is_offline():
        pytest.skip(
            "Offline mode not active in this environment; "
            "re-run with LUMI_OFFLINE=1 and no ANTHROPIC_API_KEY."
        )

    agent = BaseAgent(
        name="offline_test_agent",
        system_prompt="You are an offline test agent.",
        model=ModelTier.HAIKU,
    )

    task = Task(
        task_id="offline-task-1",
        description="Summarize the role of gene X in disease Y.",
        priority=Priority.MEDIUM,
    )

    result = await agent.execute(task)

    assert result.task_id == "offline-task-1"
    assert result.agent_id == "offline_test_agent"
    assert len(result.findings) >= 1
    assert result.cost == 0
    # Offline response has no tool_use, so it terminates in one round.
    assert result.model_used == ModelTier.HAIKU.value


async def test_execute_offline_finding_has_confidence():
    if not is_offline():
        pytest.skip("Offline mode not active; re-run with LUMI_OFFLINE=1.")

    agent = BaseAgent(
        name="offline_conf_agent",
        system_prompt="p",
        model=ModelTier.HAIKU,
    )
    task = Task(
        task_id="offline-task-2",
        description="Assess feasibility of target Z.",
        priority=Priority.HIGH,
    )

    result = await agent.execute(task)

    assert len(result.findings) >= 1
    # The offline mock emits a Confidence: line, so the claim carries a level.
    assert result.findings[0].confidence.level is not None
