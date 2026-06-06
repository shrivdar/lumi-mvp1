"""Tests for LLM model-tier routing and model-id constants.

These tests exercise pure, deterministic logic in ``src.utils.llm`` and
never touch the network or require an API key.
"""

from __future__ import annotations

import pytest

from src.utils.llm import LLMClient, ModelTier, _rejects_sampling_params


# ---------------------------------------------------------------------------
# Model id constants
# ---------------------------------------------------------------------------

def test_model_tier_values():
    """The concrete model ids must match the pinned tier constants."""
    assert ModelTier.OPUS.value == "claude-opus-4-8"
    assert ModelTier.SONNET.value == "claude-sonnet-4-6"
    assert ModelTier.HAIKU.value == "claude-haiku-4-5"


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "task_type, expected",
    [
        ("strategic", ModelTier.OPUS),
        ("review", ModelTier.OPUS),
        ("synthesis", ModelTier.OPUS),
        ("analysis", ModelTier.SONNET),
        ("code", ModelTier.SONNET),
        ("design", ModelTier.SONNET),
        ("extraction", ModelTier.HAIKU),
        ("briefing", ModelTier.HAIKU),
        ("search", ModelTier.HAIKU),
    ],
)
def test_route_model_known_task_types(task_type, expected):
    assert LLMClient.route_model(task_type) is expected


@pytest.mark.parametrize(
    "task_type",
    ["unknown", "", "totally-made-up", "REVIEWING-BUT-NOT-EXACT"],
)
def test_route_model_unknown_falls_back_to_sonnet(task_type):
    assert LLMClient.route_model(task_type) is ModelTier.SONNET


def test_route_model_is_case_insensitive():
    """Routing lowercases the task type before lookup."""
    assert LLMClient.route_model("STRATEGIC") is ModelTier.OPUS
    assert LLMClient.route_model("Analysis") is ModelTier.SONNET
    assert LLMClient.route_model("Search") is ModelTier.HAIKU


# ---------------------------------------------------------------------------
# Sampling-param guard (Opus 4.7+ rejects temperature/top_p/top_k → HTTP 400)
# ---------------------------------------------------------------------------

def test_opus_rejects_sampling_params_enum():
    # Must resolve via .value — str(ModelTier.OPUS) is 'ModelTier.OPUS', not the id.
    assert _rejects_sampling_params(ModelTier.OPUS) is True
    assert _rejects_sampling_params(ModelTier.SONNET) is False
    assert _rejects_sampling_params(ModelTier.HAIKU) is False


@pytest.mark.parametrize(
    "model_id, expected",
    [
        ("claude-opus-4-8", True),
        ("claude-opus-4-7", True),
        ("claude-opus-4-6", True),
        ("claude-sonnet-4-6", False),
        ("claude-haiku-4-5", False),
    ],
)
def test_opus_rejects_sampling_params_string(model_id, expected):
    assert _rejects_sampling_params(model_id) is expected
