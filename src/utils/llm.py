"""LLM client with model routing, cost tracking, and tool-use loop.

Provides:
- ``ModelTier`` — enum mapping logical tiers to concrete model IDs.
- ``LLMClient`` — stateful async client with tool-calling support,
  automatic retry with exponential backoff, and integrated cost tracking.
- ``call_llm`` — simple one-shot helper kept for convenience.
- ``ConcurrencyGate`` — shared semaphore + jitter to prevent API overload
  when 15-30 agents call the API simultaneously.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from collections import defaultdict
from enum import Enum
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Optional

import anthropic

logger = logging.getLogger("lumi.utils.llm")


# ---------------------------------------------------------------------------
# Model tiers
# ---------------------------------------------------------------------------

class ModelTier(str, Enum):
    """Available Claude model tiers ordered by capability / cost."""
    OPUS = "claude-opus-4-8"
    SONNET = "claude-sonnet-4-6"
    HAIKU = "claude-haiku-4-5"


# Per-million-token pricing (USD)
_MODEL_PRICING: dict[ModelTier, dict[str, float]] = {
    ModelTier.OPUS:   {"input": 5.0,   "output": 25.0},
    ModelTier.SONNET: {"input": 3.0,   "output": 15.0},
    ModelTier.HAIKU:  {"input": 1.0,   "output": 5.0},
}

# Task-type -> model routing table
_TASK_ROUTING: dict[str, ModelTier] = {
    "strategic":   ModelTier.OPUS,
    "review":      ModelTier.OPUS,
    "synthesis":   ModelTier.OPUS,
    "analysis":    ModelTier.SONNET,
    "code":        ModelTier.SONNET,
    "design":      ModelTier.SONNET,
    "extraction":  ModelTier.HAIKU,
    "briefing":    ModelTier.HAIKU,
    "search":      ModelTier.HAIKU,
}


# ---------------------------------------------------------------------------
# Concurrency gate — prevents API overload from parallel agents
# ---------------------------------------------------------------------------

class ConcurrencyGate:
    """Process-wide concurrency limiter for Anthropic API calls.

    When 15-30 agents fire ``asyncio.gather`` simultaneously, they can
    exceed API rate limits or cause connection pool exhaustion.  This
    gate ensures at most ``max_concurrent`` requests are in-flight at
    any time, with a small random jitter to desynchronise bursts.

    Usage:
        The gate is a module-level singleton (``_GLOBAL_GATE``).
        ``LLMClient`` acquires it before every API call automatically.
    """

    def __init__(self, max_concurrent: int = 5, jitter_seconds: float = 0.5) -> None:
        self.max_concurrent = max_concurrent
        self.jitter_seconds = jitter_seconds
        self._semaphore: asyncio.Semaphore | None = None
        self._in_flight: int = 0
        self._total_waited: float = 0.0

    @property
    def semaphore(self) -> asyncio.Semaphore:
        """Lazy init — must be created inside a running event loop."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self._semaphore

    async def acquire(self) -> None:
        """Acquire a slot, adding jitter if the gate is >50% utilised."""
        if self._in_flight > self.max_concurrent // 2:
            jitter = random.uniform(0.05, self.jitter_seconds)
            self._total_waited += jitter
            logger.debug(
                "ConcurrencyGate: %d/%d in-flight, adding %.2fs jitter",
                self._in_flight,
                self.max_concurrent,
                jitter,
            )
            await asyncio.sleep(jitter)

        await self.semaphore.acquire()
        self._in_flight += 1

    def release(self) -> None:
        """Release a slot back to the pool."""
        self._in_flight -= 1
        self.semaphore.release()

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "max_concurrent": self.max_concurrent,
            "in_flight": self._in_flight,
            "total_jitter_waited": round(self._total_waited, 2),
        }


# Module-level singleton — shared by ALL LLMClient instances
_GLOBAL_GATE = ConcurrencyGate(
    max_concurrent=int(os.environ.get("LUMI_MAX_CONCURRENT_LLM", "2")),
    jitter_seconds=float(os.environ.get("LUMI_LLM_JITTER", "1.5")),
)


def get_concurrency_gate() -> ConcurrencyGate:
    """Return the process-wide concurrency gate (for monitoring/tuning)."""
    return _GLOBAL_GATE


# ---------------------------------------------------------------------------
# Offline / mock mode
# ---------------------------------------------------------------------------

def is_offline() -> bool:
    """Return True when the client should run without touching the network.

    Offline mode is active when ``LUMI_OFFLINE`` is truthy OR when
    ``ANTHROPIC_API_KEY`` is unset/empty. This lets the platform run
    deterministically without an API key (e.g. in CI or local demos).
    """
    if os.environ.get("LUMI_OFFLINE"):
        return True
    return not os.environ.get("ANTHROPIC_API_KEY")


def _rejects_sampling_params(model: "ModelTier | str") -> bool:
    """Return True for models that 400 on temperature/top_p/top_k.

    Opus 4.7 and later (incl. Opus 4.8) reject all sampling parameters.
    Accepts either a ``ModelTier`` enum or a raw model-id string; resolving
    via ``.value`` is required because ``str(ModelTier.OPUS)`` yields
    ``'ModelTier.OPUS'``, not the model id.
    """
    mid = model.value if isinstance(model, ModelTier) else str(model)
    return mid.startswith("claude-opus-4-")


def _offline_text(messages: list[dict[str, Any]]) -> str:
    """Build a deterministic synthetic response containing a Finding block.

    The text always includes a ``Finding:`` / ``Confidence:`` / ``Evidence:``
    block so downstream claim extraction produces a Claim. We derive a short
    task reference from the last user message if available.
    """
    task_ref = "the submitted task"
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                task_ref = content.strip().replace("\n", " ")[:120]
                break
            if isinstance(content, list):
                for block in content:
                    text = block.get("text") if isinstance(block, dict) else None
                    if text:
                        task_ref = text.strip().replace("\n", " ")[:120]
                        break
                if task_ref != "the submitted task":
                    break
    return (
        "Offline mock response (no API key / LUMI_OFFLINE set).\n"
        f"Finding: Offline deterministic analysis of {task_ref}.\n"
        "Confidence: MEDIUM\n"
        "Evidence: offline-mock"
    )


def _make_offline_response(messages: list[dict[str, Any]]) -> SimpleNamespace:
    """Construct a synthetic, duck-typed Anthropic-Message-like object.

    The object exposes ``.content`` (a list of one text block with ``.type``
    and ``.text``) and ``.usage`` (with integer ``input_tokens`` /
    ``output_tokens``). It never contains tool_use blocks, so agent loops
    terminate immediately.
    """
    text_block = SimpleNamespace(type="text", text=_offline_text(messages))
    usage = SimpleNamespace(input_tokens=0, output_tokens=0)
    return SimpleNamespace(content=[text_block], usage=usage, stop_reason="end_turn")


# ---------------------------------------------------------------------------
# Simple one-shot helper (kept for backward compatibility)
# ---------------------------------------------------------------------------

async def call_llm(
    prompt: str,
    system: str = "",
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 2048,
    temperature: float = 0.3,
) -> str:
    """Call Claude API and return the text response.

    This is a thin convenience wrapper.  For production agent code
    prefer :class:`LLMClient` which tracks costs and supports tools.
    """
    messages = [{"role": "user", "content": prompt}]

    # Offline mode: return a deterministic synthetic response, no network.
    if is_offline():
        return _offline_text(messages)

    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        # Opus 4.7+ rejects sampling params (temperature/top_p/top_k → HTTP 400).
        # Only send temperature for models that accept it.
        if not _rejects_sampling_params(model):
            kwargs["temperature"] = temperature
        if system:
            kwargs["system"] = system

        response = await client.messages.create(**kwargs)
        return response.content[0].text  # type: ignore[union-attr]

    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        return f"[LLM error: {exc}]"


# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

class LLMClient:
    """Async Anthropic client with model routing, cost tracking,
    and an automatic tool-use execution loop.

    Usage::

        llm = LLMClient()
        resp = await llm.chat([{"role": "user", "content": "Hello"}])
        print(llm.get_cost())
    """

    def __init__(self) -> None:
        # In offline mode we never touch the network, so skip creating the
        # real SDK client entirely (constructing it with no key is tolerated
        # by the SDK, but there's no reason to do it offline).
        if is_offline():
            self._client = None
        else:
            # Disable SDK built-in retry — we handle retries ourselves in
            # chat() with gate-aware backoff. SDK retries fight our gate and
            # cause storms.
            self._client = anthropic.AsyncAnthropic(max_retries=0)
        self._total_cost: float = 0.0
        self._cost_by_model: dict[str, float] = defaultdict(float)
        self._call_count: int = 0

    # -- cost helpers -------------------------------------------------------

    def _record_usage(self, model: ModelTier, usage: Any) -> float:
        """Compute and record cost for a single API call. Returns the cost."""
        pricing = _MODEL_PRICING.get(model, _MODEL_PRICING[ModelTier.SONNET])
        cost = (
            usage.input_tokens * pricing["input"] / 1_000_000
            + usage.output_tokens * pricing["output"] / 1_000_000
        )
        self._total_cost += cost
        self._cost_by_model[model.value] += cost
        self._call_count += 1
        logger.debug(
            "LLM call #%d  model=%s  in=%d  out=%d  cost=$%.4f",
            self._call_count,
            model.value,
            usage.input_tokens,
            usage.output_tokens,
            cost,
        )
        return cost

    def get_cost(self) -> dict[str, Any]:
        """Return cumulative cost breakdown.

        Returns:
            Dict with keys ``total`` (float), ``by_model`` (dict[str, float]),
            and ``call_count`` (int).
        """
        return {
            "total": round(self._total_cost, 6),
            "by_model": dict(self._cost_by_model),
            "call_count": self._call_count,
        }

    # -- model routing ------------------------------------------------------

    @staticmethod
    def route_model(task_type: str) -> ModelTier:
        """Select the appropriate model tier for a given task type.

        Routing rules:
            - ``"strategic"`` / ``"review"`` / ``"synthesis"`` -> OPUS
            - ``"analysis"`` / ``"code"`` / ``"design"`` -> SONNET
            - ``"extraction"`` / ``"briefing"`` / ``"search"`` -> HAIKU

        Falls back to SONNET for unknown task types.
        """
        return _TASK_ROUTING.get(task_type.lower(), ModelTier.SONNET)

    # -- core chat ----------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: ModelTier = ModelTier.SONNET,
        system: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        max_tokens: int = 8192,
        temperature: float = 0.3,
    ) -> anthropic.types.Message:
        """Send a single chat request to the Anthropic API.

        Uses a global concurrency gate to limit in-flight requests,
        then retries rate-limit errors with exponential backoff + jitter.
        The gate is released *before* sleeping on retry so other agents
        can use the slot while this one waits.

        Args:
            messages: Conversation messages in Anthropic format.
            model: Model tier to use.
            system: Optional system prompt.
            tools: Optional tool definitions (Anthropic tool-use schema).
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature.

        Returns:
            The raw ``anthropic.types.Message`` response (or a duck-typed
            synthetic equivalent in offline mode).
        """
        # Offline mode: return a deterministic synthetic response immediately.
        # No network, no concurrency gate, no retries/sleeps. Cost is recorded
        # as 0/0 tokens so get_cost() reports $0.
        if is_offline():
            response = _make_offline_response(messages)
            self._record_usage(model, response.usage)
            return response

        kwargs: dict[str, Any] = {
            "model": model.value,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        # NOTE: Opus 4.7+ (incl. Opus 4.8) rejects sampling params — sending
        # temperature/top_p/top_k returns HTTP 400. Only send temperature for
        # tiers that accept it. (Opus also supports thinking={"type": "adaptive"};
        # not enabled here to keep the existing tool-use loop unchanged.)
        if not _rejects_sampling_params(model):
            kwargs["temperature"] = temperature
        if system is not None:
            kwargs["system"] = system
        if tools is not None:
            kwargs["tools"] = tools

        gate = _GLOBAL_GATE
        last_exc: Exception | None = None

        for attempt in range(1, 8):  # up to 7 attempts
            await gate.acquire()
            try:
                response = await self._client.messages.create(**kwargs)
                self._record_usage(model, response.usage)
                return response
            except anthropic.RateLimitError as exc:
                last_exc = exc
                if attempt < 7:
                    # Exponential backoff with jitter: 4s, 8s, 16s, 32s, 60s, 60s
                    base_wait = min(2 ** (attempt + 1), 60)
                    wait = base_wait + random.uniform(0, base_wait * 0.5)
                    logger.warning(
                        "Rate limited (attempt %d/7, %d in-flight). "
                        "Waiting %.1fs before retry...",
                        attempt,
                        gate._in_flight,
                        wait,
                    )
                    await asyncio.sleep(wait)
            finally:
                gate.release()

        raise last_exc  # type: ignore[misc]

    # -- tool-use loop ------------------------------------------------------

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_executor: Callable[[str, dict[str, Any]], Awaitable[Any]],
        model: ModelTier = ModelTier.SONNET,
        system: Optional[str] = None,
        max_steps: int = 20,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Run an agentic tool-use loop until a text response or *max_steps*.

        The loop sends a message, inspects the response for ``tool_use``
        content blocks, executes them via *tool_executor*, feeds the
        results back, and repeats.

        Args:
            messages: Initial conversation messages.
            tools: Tool definitions (Anthropic tool-use format).
            tool_executor: Async callback ``(tool_name, tool_input) -> result``.
                Must return a string (or something str()-able).
            model: Model tier.
            system: Optional system prompt.
            max_steps: Safety cap on iterations.

        Returns:
            A tuple ``(final_text, tool_call_log)`` where
            *tool_call_log* is a list of dicts with keys
            ``name``, ``input``, ``result``, ``step``, ``is_error``.
        """
        conversation = list(messages)  # shallow copy
        tool_call_log: list[dict[str, Any]] = []

        for step in range(1, max_steps + 1):
            response = await self.chat(
                messages=conversation,
                model=model,
                system=system,
                tools=tools,
            )

            # Collect tool_use blocks from the response
            tool_use_blocks = [
                block for block in response.content
                if block.type == "tool_use"
            ]

            if not tool_use_blocks:
                # No more tool calls — extract final text and return
                final_text = _extract_text(response)
                return final_text, tool_call_log

            # Build the assistant message (preserves all content blocks)
            conversation.append({"role": "assistant", "content": response.content})

            # Execute each tool call and build tool_result blocks
            tool_result_blocks: list[dict[str, Any]] = []
            for block in tool_use_blocks:
                tool_name: str = block.name
                tool_input: dict[str, Any] = block.input
                logger.info("Step %d — calling tool %s", step, tool_name)

                try:
                    result = await tool_executor(tool_name, tool_input)
                    result_str = str(result) if not isinstance(result, str) else result
                    is_error = False
                except Exception as exc:  # noqa: BLE001
                    result_str = f"Tool execution error: {exc}"
                    is_error = True
                    logger.warning("Tool %s failed: %s", tool_name, exc)

                tool_call_log.append({
                    "name": tool_name,
                    "input": tool_input,
                    "result": result_str,
                    "step": step,
                    "is_error": is_error,
                })

                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                    **({"is_error": True} if is_error else {}),
                })

            conversation.append({"role": "user", "content": tool_result_blocks})

        # Exhausted max_steps — do one final call without tools to get a summary
        logger.warning("Reached max_steps=%d, requesting final summary.", max_steps)
        conversation.append({
            "role": "user",
            "content": (
                "You have reached the maximum number of tool-use steps. "
                "Please provide your final answer based on what you have so far."
            ),
        })
        response = await self.chat(
            messages=conversation,
            model=model,
            system=system,
            max_tokens=8192,
        )
        return _extract_text(response), tool_call_log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_text(response: anthropic.types.Message) -> str:
    """Pull the concatenated text from a Message response."""
    parts: list[str] = []
    for block in response.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts)
