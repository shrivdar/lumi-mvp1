"""Unit tests for :class:`BaseAgent` pure helpers.

These tests exercise deterministic, non-networked logic:
- ``_extract_findings`` claim extraction from free text.
- ``_check_imports`` sandbox import allow/deny logic.
- CodeAct tool auto-registration.

No API key or network access is required.
"""

from __future__ import annotations

from src.agents.base_agent import APPROVED_PACKAGES, BaseAgent
from src.utils.llm import ModelTier
from src.utils.types import ConfidenceLevel


def _make_agent() -> BaseAgent:
    """Construct a minimal agent. Safe to call without an API key."""
    return BaseAgent(
        name="test_agent",
        system_prompt="You are a test agent.",
        model=ModelTier.HAIKU,
    )


# ---------------------------------------------------------------------------
# _extract_findings
# ---------------------------------------------------------------------------

def test_extract_findings_single_block():
    agent = _make_agent()
    text = (
        "Some preamble.\n"
        "Finding: Gene X is associated with disease Y.\n"
        "Confidence: HIGH\n"
        "Evidence: PMID 12345\n"
    )
    claims = agent._extract_findings(text)

    assert len(claims) == 1
    claim = claims[0]
    assert "Gene X is associated with disease Y" in claim.claim_text
    assert claim.confidence.level == ConfidenceLevel.HIGH
    assert claim.agent_id == "test_agent"
    assert len(claim.supporting_evidence) == 1
    assert "PMID 12345" in claim.supporting_evidence[0].source_id


def test_extract_findings_multiple_blocks_with_distinct_confidence():
    agent = _make_agent()
    text = (
        "Finding: First claim here.\n"
        "Confidence: HIGH\n"
        "Evidence: source-a\n"
        "Finding: Second claim here.\n"
        "Confidence: LOW\n"
        "Evidence: source-b\n"
        "Finding: Third claim with no evidence.\n"
        "Confidence: INSUFFICIENT\n"
    )
    claims = agent._extract_findings(text)

    assert len(claims) == 3
    assert claims[0].confidence.level == ConfidenceLevel.HIGH
    assert claims[1].confidence.level == ConfidenceLevel.LOW
    assert claims[2].confidence.level == ConfidenceLevel.INSUFFICIENT
    assert "First claim here" in claims[0].claim_text
    assert "Second claim here" in claims[1].claim_text


def test_extract_findings_is_case_insensitive():
    agent = _make_agent()
    text = "finding: lowercase marker.\nconfidence: medium\nevidence: lower-src"
    claims = agent._extract_findings(text)

    assert len(claims) == 1
    assert claims[0].confidence.level == ConfidenceLevel.MEDIUM
    assert len(claims[0].supporting_evidence) == 1


def test_extract_findings_plain_text_fallback():
    agent = _make_agent()
    text = "There are no structured markers here, just a plain summary paragraph."
    claims = agent._extract_findings(text)

    assert len(claims) == 1
    # Fallback claims are conservatively marked LOW confidence.
    assert claims[0].confidence.level == ConfidenceLevel.LOW
    assert claims[0].claim_text.startswith("There are no structured markers")


def test_extract_findings_empty_string_returns_empty():
    agent = _make_agent()
    assert agent._extract_findings("") == []
    assert agent._extract_findings("   \n\t ") == []


def test_extract_findings_truncates_long_fallback():
    agent = _make_agent()
    long_text = "x" * 2000
    claims = agent._extract_findings(long_text)
    assert len(claims) == 1
    assert len(claims[0].claim_text) <= 500


# ---------------------------------------------------------------------------
# _check_imports
# ---------------------------------------------------------------------------

def test_check_imports_allows_approved_scientific_packages():
    assert BaseAgent._check_imports("import numpy as np") == set()
    assert BaseAgent._check_imports("import pandas") == set()
    assert BaseAgent._check_imports("from scipy import stats") == set()


def test_check_imports_allows_stdlib():
    # Bare stdlib imports must not be flagged even though they are not
    # listed explicitly in APPROVED_PACKAGES.
    assert BaseAgent._check_imports("import sys") == set()
    assert BaseAgent._check_imports("import os") == set()
    assert BaseAgent._check_imports("import json") == set()
    assert BaseAgent._check_imports("import math") == set()
    assert BaseAgent._check_imports("import sys\nimport os\nimport json") == set()


def test_check_imports_blocks_unapproved_third_party():
    violations = BaseAgent._check_imports("import some_random_thirdparty_lib")
    assert "some_random_thirdparty_lib" in violations


def test_check_imports_blocks_dynamic_import_patterns():
    assert BaseAgent._check_imports("__import__('os')") == {"__dynamic_import__"}
    assert BaseAgent._check_imports("eval('1+1')") == {"__dynamic_import__"}
    assert BaseAgent._check_imports("exec('x=1')") == {"__dynamic_import__"}
    assert BaseAgent._check_imports("importlib.import_module('os')") == {"__dynamic_import__"}


def test_check_imports_mixed_allows_stdlib_blocks_thirdparty():
    code = "import os\nimport numpy\nimport sketchy_pkg"
    violations = BaseAgent._check_imports(code)
    assert violations == {"sketchy_pkg"}


# ---------------------------------------------------------------------------
# CodeAct tool registration
# ---------------------------------------------------------------------------

def test_execute_code_tool_always_present():
    agent = _make_agent()
    tool_names = {t.get("name") for t in agent.tools}
    assert "execute_code" in tool_names


def test_execute_code_tool_not_duplicated_when_provided():
    custom_codeact = {"name": "execute_code", "description": "custom", "input_schema": {}}
    agent = BaseAgent(
        name="t",
        system_prompt="p",
        model=ModelTier.HAIKU,
        tools=[custom_codeact],
    )
    code_tools = [t for t in agent.tools if t.get("name") == "execute_code"]
    assert len(code_tools) == 1


def test_register_tool_adds_to_registry_and_tools():
    agent = _make_agent()

    def my_tool(x: int) -> int:
        return x + 1

    agent.register_tool("my_tool", my_tool, "adds one", {"type": "object", "properties": {}})
    assert "my_tool" in agent._tool_registry
    assert any(t.get("name") == "my_tool" for t in agent.tools)


def test_approved_packages_is_frozenset():
    # Sanity: the allowlist is immutable and contains core scientific deps.
    assert isinstance(APPROVED_PACKAGES, frozenset)
    assert "numpy" in APPROVED_PACKAGES
    assert "rdkit" in APPROVED_PACKAGES
