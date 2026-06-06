"""
Base agent class for all specialist agents in the Lumi Virtual Lab swarm.

Every specialist inherits from :class:`BaseAgent` and customises behaviour
via its *system_prompt*, registered *tools*, and *model* tier.  The
execution loop follows a CodeAct-style pattern: the LLM generates tool
calls (including arbitrary Python code execution), observes results, and
iterates until it produces a final text response.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import subprocess
import textwrap
import time
from typing import Any, Callable

from src.utils.llm import LLMClient, ModelTier
from src.utils.types import (
    AgentResult,
    Claim,
    ConfidenceAssessment,
    ConfidenceLevel,
    EvidenceSource,
    Task,
)

logger = logging.getLogger("lumi.agents.base")

# ---------------------------------------------------------------------------
# Approved packages for sandboxed code execution
# ---------------------------------------------------------------------------

APPROVED_PACKAGES: frozenset[str] = frozenset(
    {
        # Standard library (safe subset)
        "math", "statistics", "collections", "itertools", "functools",
        "json", "csv", "re", "io", "pathlib", "datetime",
        "textwrap", "copy", "operator", "string", "hashlib", "base64",
        "typing", "dataclasses", "enum", "abc", "contextlib", "warnings",
        # Scientific computing
        "numpy", "pandas", "polars", "scipy", "statsmodels",
        # Bioinformatics
        "Bio",  # biopython
        "scanpy", "anndata", "scvi",
        "biotite", "prody",
        "cobra",  # cobrapy
        "pyensembl", "pyranges",
        # Machine learning
        "sklearn", "xgboost", "lightgbm", "torch", "transformers",
        # Networks / graphs
        "networkx", "igraph",
        # Cheminformatics
        "rdkit", "datamol",
        # Protein models
        "esm",  # fair-esm
        # Visualisation (non-interactive)
        "matplotlib", "seaborn", "plotly",
        # HTTP (for API calls within code)
        "requests", "httpx",
        # Misc utilities
        "tqdm", "pydantic",
    }
)

# ---------------------------------------------------------------------------
# Default CodeAct tool definition
# ---------------------------------------------------------------------------

CODEACT_TOOL: dict[str, Any] = {
    "name": "execute_code",
    "description": (
        "Execute Python code. You have access to numpy, pandas, scipy, "
        "statsmodels, biopython, scanpy, networkx, matplotlib, and other "
        "scientific packages. Print results to stdout."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute",
            }
        },
        "required": ["code"],
    },
}


class BaseAgent:
    """Base class for all specialist agents in the YOHAS-VB swarm."""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        model: ModelTier = ModelTier.SONNET,
        tools: list[dict] | None = None,
        max_steps: int = 8,
        division: str = "",
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self.tools: list[dict] = tools or []
        self.max_steps = max_steps
        self.division = division

        # LLM client with cost tracking and retry logic
        self.llm = LLMClient()

        # Tool registry: name -> callable
        self._tool_registry: dict[str, Callable] = {}

        # Always include the CodeAct tool
        if not any(t.get("name") == "execute_code" for t in self.tools):
            self.tools.append(CODEACT_TOOL)

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def register_tool(
        self,
        name: str,
        func: Callable,
        description: str,
        input_schema: dict,
    ) -> None:
        """Register a callable tool that this agent can use."""
        self._tool_registry[name] = func
        self.tools.append(
            {
                "name": name,
                "description": description,
                "input_schema": input_schema,
            }
        )

    # ------------------------------------------------------------------
    # Main execution loop
    # ------------------------------------------------------------------

    async def execute(
        self,
        task: Task,
        on_tool_call: Callable[..., Any] | None = None,
    ) -> AgentResult:
        """Execute a task using the agent's tools and LLM reasoning.

        Args:
            task: The task to execute.
            on_tool_call: Optional async callback invoked after each tool call.
                Signature: (tool_name, tool_input, result, duration_ms) -> None
        """
        start_time = time.time()
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": self._format_task(task)}
        ]
        tools_used: list[str] = []
        tool_results_log: list[dict[str, Any]] = []
        code_executed: list[str] = []
        steps = 0

        while steps < self.max_steps:
            # Call LLM
            response = await self.llm.chat(
                messages=messages,
                model=self.model,
                system=self.system_prompt,
                tools=self._format_tools_for_api() if self.tools else None,
            )

            # Check for tool use blocks
            has_tool_use = any(
                getattr(block, "type", None) == "tool_use"
                for block in response.content
            )

            if has_tool_use:
                tool_results: list[dict[str, Any]] = []
                for block in response.content:
                    if getattr(block, "type", None) != "tool_use":
                        continue

                    tool_name: str = block.name
                    tool_input: dict = block.input
                    tools_used.append(tool_name)

                    tool_start = time.time()
                    try:
                        if tool_name == "execute_code":
                            result = await self._execute_code(
                                tool_input.get("code", "")
                            )
                            code_executed.append(tool_input.get("code", ""))
                        elif tool_name in self._tool_registry:
                            result = await self._call_tool(tool_name, tool_input)
                        else:
                            result = {"error": f"Unknown tool: {tool_name}"}
                    except Exception as exc:
                        result = {"error": str(exc)}

                    # Log tool result for figure collection
                    if isinstance(result, dict) and not result.get("error"):
                        tool_results_log.append({
                            "tool_name": tool_name,
                            "result": result,
                        })

                    # Stream tool call event
                    if on_tool_call is not None:
                        tool_dur = int((time.time() - tool_start) * 1000)
                        result_str = json.dumps(result) if isinstance(result, dict) else str(result)
                        try:
                            await on_tool_call(tool_name, tool_input, result_str[:500], tool_dur)
                        except Exception:
                            pass  # Don't let streaming errors break execution

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": (
                                json.dumps(result)
                                if isinstance(result, dict)
                                else str(result)
                            ),
                        }
                    )

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
                steps += 1

            else:
                # Agent finished — extract final text
                final_text = "".join(
                    block.text
                    for block in response.content
                    if hasattr(block, "text")
                )
                duration = time.time() - start_time

                return AgentResult(
                    agent_id=self.name,
                    task_id=task.task_id,
                    findings=self._extract_findings(final_text),
                    raw_data={
                        "final_response": final_text,
                        "tool_results": tool_results_log,
                    },
                    code_executed=code_executed,
                    tools_used=list(set(tools_used)),
                    cost=self.llm.get_cost()["total"],
                    duration_seconds=duration,
                    model_used=self.model.value,
                )

        # Max steps exceeded — return partial results
        duration = time.time() - start_time
        return AgentResult(
            agent_id=self.name,
            task_id=task.task_id,
            findings=[],
            raw_data={
                "warning": "Max steps exceeded",
                "last_messages": str(messages[-2:]),
                "tool_results": tool_results_log,
            },
            code_executed=code_executed,
            tools_used=list(set(tools_used)),
            cost=self.llm.get_cost()["total"],
            duration_seconds=duration,
            model_used=self.model.value,
        )

    # ------------------------------------------------------------------
    # Helper: format a Task into an LLM prompt
    # ------------------------------------------------------------------

    def _format_task(self, task: Task) -> str:
        """Format a *Task* into a clear prompt string for the LLM."""
        parts = [
            f"## Task: {task.task_id}",
            "",
            f"**Description:** {task.description}",
        ]
        if task.division:
            parts.append(f"**Division:** {task.division}")
        if task.agent:
            parts.append(f"**Assigned agent:** {task.agent}")
        parts.append(f"**Priority:** {task.priority.value}")
        if task.dependencies:
            parts.append(f"**Depends on:** {', '.join(task.dependencies)}")

        parts.extend(
            [
                "",
                "---",
                "",
                "Please complete this task thoroughly. For each finding:",
                "1. State the finding clearly (prefix with 'Finding:').",
                "2. Provide a confidence level (prefix with 'Confidence:' — "
                "HIGH / MEDIUM / LOW / INSUFFICIENT).",
                "3. Cite evidence sources where possible (prefix with 'Evidence:').",
                "4. Note any caveats or alternative explanations.",
                "",
                "EFFICIENCY: Be strategic with tool calls. Gather the 3-5 most "
                "important evidence sources, then synthesize. Do NOT exhaustively "
                "search every possible database — focus on the highest-value "
                "queries for this specific task. Stop once you have sufficient "
                "evidence to make a well-supported conclusion.",
                "",
                "When you have completed your analysis, provide a final summary "
                "of all findings.",
            ]
        )
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Helper: format tools for Anthropic API
    # ------------------------------------------------------------------

    def _format_tools_for_api(self) -> list[dict[str, Any]]:
        """Return tools in Anthropic API format."""
        formatted: list[dict[str, Any]] = []
        for tool in self.tools:
            formatted.append(
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("input_schema", {"type": "object", "properties": {}}),
                }
            )
        return formatted

    # ------------------------------------------------------------------
    # Helper: call a registered tool
    # ------------------------------------------------------------------

    async def _call_tool(self, name: str, tool_input: dict) -> Any:
        """Look up *name* in the registry and invoke the callable.

        Handles both sync and async callables transparently.
        """
        func = self._tool_registry[name]
        if inspect.iscoroutinefunction(func):
            return await func(**tool_input)
        else:
            # Run sync functions in the default executor to avoid blocking
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: func(**tool_input))

    # ------------------------------------------------------------------
    # Helper: sandboxed code execution
    # ------------------------------------------------------------------

    async def _execute_code(self, code: str) -> dict[str, Any]:
        """Execute Python *code* in a subprocess with sandboxing.

        Only imports from :data:`APPROVED_PACKAGES` are allowed.  The
        subprocess is killed after 60 seconds.
        """
        # --- Validate imports ---
        violations = self._check_imports(code)
        if violations:
            return {
                "error": (
                    f"Import not allowed. Disallowed packages: {', '.join(sorted(violations))}. "
                    f"Approved packages: {', '.join(sorted(APPROVED_PACKAGES))}"
                )
            }

        # Wrap the code so we capture stdout/stderr
        wrapper = textwrap.dedent(
            """\
            import sys, io
            _stdout = io.StringIO()
            _stderr = io.StringIO()
            sys.stdout = _stdout
            sys.stderr = _stderr
            try:
            {indented_code}
            except Exception as _exc:
                print(f"Error: {{_exc}}", file=_stderr)
            finally:
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__
                print("__STDOUT__")
                print(_stdout.getvalue(), end="")
                print("__STDERR__")
                print(_stderr.getvalue(), end="")
            """
        ).format(indented_code=textwrap.indent(code, "    "))

        loop = asyncio.get_running_loop()

        def _run() -> dict[str, Any]:
            try:
                proc = subprocess.run(
                    ["python", "-c", wrapper],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                raw = proc.stdout
                stdout = ""
                stderr = ""
                if "__STDOUT__" in raw and "__STDERR__" in raw:
                    parts = raw.split("__STDOUT__", 1)[1]
                    stdout_part, stderr_part = parts.split("__STDERR__", 1)
                    stdout = stdout_part.strip()
                    stderr = stderr_part.strip()
                else:
                    stdout = raw.strip()
                    stderr = proc.stderr.strip()

                # Combine process-level stderr with captured stderr
                if proc.stderr.strip():
                    stderr = (stderr + "\n" + proc.stderr.strip()).strip()

                return {"stdout": stdout, "stderr": stderr, "returncode": proc.returncode}

            except subprocess.TimeoutExpired:
                return {"error": "Code execution timed out after 60 seconds"}
            except Exception as exc:
                return {"error": f"Execution failed: {exc}"}

        return await loop.run_in_executor(None, _run)

    @staticmethod
    def _check_imports(code: str) -> set[str]:
        """Return the set of top-level package names imported in *code*
        that are NOT in :data:`APPROVED_PACKAGES`.

        Also rejects dynamic import mechanisms that bypass static analysis.
        """
        # Block dynamic import / code execution patterns
        dangerous_patterns = re.compile(
            r"__import__\s*\(|"
            r"importlib\s*\.|"
            r"\bexec\s*\(|"
            r"\beval\s*\(|"
            r"\bcompile\s*\(",
            re.MULTILINE,
        )
        if dangerous_patterns.search(code):
            return {"__dynamic_import__"}

        violations: set[str] = set()
        # Match 'import foo', 'import foo.bar', 'from foo import ...', 'from foo.bar import ...'
        import_re = re.compile(
            r"^\s*(?:import|from)\s+([\w]+)", re.MULTILINE
        )
        for match in import_re.finditer(code):
            pkg = match.group(1)
            if pkg not in APPROVED_PACKAGES:
                # Also allow anything that ships with cpython (best effort)
                try:
                    import importlib

                    spec = importlib.util.find_spec(pkg)  # type: ignore[union-attr]
                    if spec is not None and spec.origin is not None and "site-packages" not in spec.origin:
                        continue  # stdlib — allow
                except Exception:
                    pass
                violations.add(pkg)
        return violations

    # ------------------------------------------------------------------
    # Helper: extract findings / claims from agent text
    # ------------------------------------------------------------------

    def _extract_findings(self, text: str) -> list[Claim]:
        """Best-effort extraction of structured claims from free text.

        Looks for patterns like:
        - ``Finding: <text>``
        - ``Confidence: HIGH|MEDIUM|LOW|INSUFFICIENT``
        - ``Evidence: <source description>``
        """
        claims: list[Claim] = []

        # Split on "Finding:" markers
        finding_blocks = re.split(r"(?i)\bFinding\s*[:]\s*", text)
        # First chunk is preamble — skip it
        for block in finding_blocks[1:]:
            claim_text = ""
            confidence_level = ConfidenceLevel.MEDIUM
            confidence_score = 0.5
            evidence_sources: list[EvidenceSource] = []

            lines = block.strip().split("\n")
            claim_lines: list[str] = []
            for line in lines:
                line_stripped = line.strip()

                # Confidence
                conf_match = re.match(
                    r"(?i)Confidence\s*[:]\s*(HIGH|MEDIUM|LOW|INSUFFICIENT)",
                    line_stripped,
                )
                if conf_match:
                    level_str = conf_match.group(1).upper()
                    confidence_level = ConfidenceLevel(level_str)
                    confidence_score = {
                        "HIGH": 0.85,
                        "MEDIUM": 0.55,
                        "LOW": 0.25,
                        "INSUFFICIENT": 0.1,
                    }.get(level_str, 0.5)
                    continue

                # Evidence
                ev_match = re.match(r"(?i)Evidence\s*[:]\s*(.*)", line_stripped)
                if ev_match:
                    ev_text = ev_match.group(1).strip()
                    evidence_sources.append(
                        EvidenceSource(
                            source_db="agent_cited",
                            source_id=ev_text[:200],
                        )
                    )
                    continue

                # Otherwise it's part of the claim text
                if line_stripped:
                    claim_lines.append(line_stripped)

                # Stop at next section marker
                if re.match(r"(?i)(Finding|---|\*\*)", line_stripped) and claim_lines:
                    break

            claim_text = " ".join(claim_lines).strip()
            if not claim_text:
                continue

            claims.append(
                Claim(
                    claim_text=claim_text,
                    supporting_evidence=evidence_sources,
                    confidence=ConfidenceAssessment(
                        level=confidence_level,
                        score=confidence_score,
                    ),
                    agent_id=self.name,
                )
            )

        # Fallback: if no "Finding:" markers were found, create a single
        # claim from the whole text (truncated).
        if not claims and text.strip():
            claims.append(
                Claim(
                    claim_text=text.strip()[:500],
                    confidence=ConfidenceAssessment(
                        level=ConfidenceLevel.LOW,
                        score=0.3,
                    ),
                    agent_id=self.name,
                )
            )

        return claims
