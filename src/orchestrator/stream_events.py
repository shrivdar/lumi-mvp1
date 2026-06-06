"""Pipeline event emitter for real-time SSE streaming.

Provides a typed callback interface that emits events matching
the frontend's StreamEvent discriminated union. All methods are
no-ops when no callback is provided.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger("lumi.orchestrator.stream_events")

StreamCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class PipelineEventEmitter:
    """Wraps a StreamCallback with typed convenience methods."""

    def __init__(self, callback: StreamCallback | None = None):
        self._cb = callback

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self._cb is not None:
            try:
                await self._cb(event_type, data)
            except Exception:
                logger.warning("Stream callback failed for %s", event_type, exc_info=True)

    async def trace_start(
        self,
        agent_id: str,
        division: str,
        message: str,
    ) -> None:
        await self._emit("trace_start", {
            "trace": {
                "agent_id": agent_id,
                "division": division,
                "status": "running",
                "message": message,
                "tools_called": [],
                "confidence_score": None,
                "confidence_level": None,
                "duration_ms": None,
            }
        })

    async def tool_call(
        self,
        agent_id: str,
        tool_name: str,
        tool_input: dict | None = None,
        result: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        await self._emit("tool_call", {
            "agent_id": agent_id,
            "tool": {
                "tool_name": tool_name,
                "tool_input": tool_input or {},
                "result": result,
                "duration_ms": duration_ms,
            },
        })

    async def trace_complete(
        self,
        agent_id: str,
        division: str,
        message: str,
        tools_called: list[dict] | None = None,
        confidence_score: float | None = None,
        confidence_level: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        await self._emit("trace_complete", {
            "trace": {
                "agent_id": agent_id,
                "division": division,
                "status": "complete",
                "message": message,
                "tools_called": tools_called or [],
                "confidence_score": confidence_score,
                "confidence_level": confidence_level,
                "duration_ms": duration_ms,
            }
        })

    async def trace_error(
        self,
        agent_id: str,
        division: str,
        message: str,
        duration_ms: int | None = None,
    ) -> None:
        await self._emit("trace_complete", {
            "trace": {
                "agent_id": agent_id,
                "division": division,
                "status": "error",
                "message": message,
                "tools_called": [],
                "confidence_score": None,
                "confidence_level": None,
                "duration_ms": duration_ms,
            }
        })

    async def hitl_flag(
        self,
        finding: str,
        agent_id: str,
        confidence_score: float,
        reason: str,
    ) -> None:
        await self._emit("hitl_flag", {
            "hitl": {
                "finding": finding,
                "agent_id": agent_id,
                "confidence_score": confidence_score,
                "reason": reason,
                "status": "pending",
            }
        })

    async def hitl_resolved(
        self,
        finding: str,
        agent_id: str,
        confidence_score: float,
        reason: str,
        status: str = "approved",
    ) -> None:
        await self._emit("hitl_resolved", {
            "hitl": {
                "finding": finding,
                "agent_id": agent_id,
                "confidence_score": confidence_score,
                "reason": reason,
                "status": status,
            }
        })

    async def integration(
        self,
        name: str,
        action: str,
        status: str = "complete",
        detail: str = "",
    ) -> None:
        await self._emit("integration", {
            "call": {
                "integration": name,
                "action": action,
                "status": status,
                "detail": detail,
            }
        })

    async def text_delta(self, delta: str) -> None:
        await self._emit("text_delta", {"delta": delta})

    async def done(self) -> None:
        await self._emit("done", {})
