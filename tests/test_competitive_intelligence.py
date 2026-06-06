"""Tests for the Competitive Intelligence specialist agent.

Covers two contracts:

1. The factory builds a :class:`BaseAgent` with the expected ``name`` /
   ``division`` and an ``execute_code`` tool registered.
2. Under offline mode (``LUMI_OFFLINE=1`` and no ``ANTHROPIC_API_KEY``) a full
   ``execute`` round produces at least one finding at zero cost, requiring no
   network and no API key.

The autouse fixture forces offline mode BEFORE any agent/client is constructed.
``is_offline()`` reads the environment on every call, so monkeypatching the env
is sufficient — no module reloading (which would break identity-based
``ModelTier`` comparisons elsewhere).
"""

from __future__ import annotations

import pytest

from src.agents.base_agent import BaseAgent
from src.agents.competitive_intelligence import create_competitive_intelligence_agent
from src.utils.llm import ModelTier, is_offline
from src.utils.types import Priority, Task


@pytest.fixture(autouse=True)
def _force_offline(monkeypatch):
    """Activate offline mode for every test in this module."""
    monkeypatch.setenv("LUMI_OFFLINE", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_factory_returns_configured_agent():
    agent = create_competitive_intelligence_agent()

    assert isinstance(agent, BaseAgent)
    assert agent.name == "Competitive Intelligence"
    assert agent.division == "Computational Biology"
    assert agent.model == ModelTier.SONNET

    # The CodeAct execute_code tool is always wired in by BaseAgent.
    tool_names = {tool["name"] for tool in agent.tools}
    assert "execute_code" in tool_names


async def test_execute_offline_produces_findings_at_zero_cost():
    if not is_offline():
        pytest.skip(
            "Offline mode not active in this environment; "
            "re-run with LUMI_OFFLINE=1 and no ANTHROPIC_API_KEY."
        )

    agent = create_competitive_intelligence_agent()

    task = Task(
        task_id="comp-intel-1",
        description=(
            "Assess the competitive and IP landscape for PCSK9-targeting "
            "therapies in hypercholesterolemia."
        ),
        division="Computational Biology",
        agent="competitive_intelligence",
        priority=Priority.HIGH,
    )

    result = await agent.execute(task)

    assert result.task_id == "comp-intel-1"
    assert result.agent_id == "Competitive Intelligence"
    assert len(result.findings) >= 1
    assert result.cost == 0
    assert result.model_used == ModelTier.SONNET.value
