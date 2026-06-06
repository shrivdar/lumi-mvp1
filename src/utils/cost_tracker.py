"""
Real-time cost tracking for the Lumi Virtual Lab pipeline.

Thread-safe singleton that records every LLM API call and provides
breakdowns by agent, division, phase, and model.
"""

from __future__ import annotations

import logging
import threading
import warnings
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("lumi.utils.cost_tracker")

# ---------------------------------------------------------------------------
# Pricing constants (USD per million tokens)
# ---------------------------------------------------------------------------

PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-8": {"input": 5.0, "output": 25.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
}


@dataclass
class _CallRecord:
    """Internal record of a single LLM API call."""

    model: str
    input_tokens: int
    output_tokens: int
    cost: float
    agent_id: str
    division: str
    phase: str


class CostTracker:
    """Singleton cost tracker for the entire pipeline.

    All public methods are thread-safe.
    """

    _instance: Optional["CostTracker"] = None
    _init_lock = threading.Lock()

    def __new__(cls) -> "CostTracker":
        with cls._init_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._lock = threading.Lock()
                inst._records: list[_CallRecord] = []
                cls._instance = inst
            return cls._instance

    # -- recording ----------------------------------------------------------

    def record_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        agent_id: str,
        division: str = "",
        phase: str = "",
    ) -> float:
        """Record a single LLM API call and return its cost in USD."""
        pricing = PRICING.get(model)
        if pricing is None:
            logger.warning("Unknown model %r — using sonnet pricing as fallback", model)
            pricing = PRICING["claude-sonnet-4-6"]

        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

        record = _CallRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            agent_id=agent_id,
            division=division,
            phase=phase,
        )

        with self._lock:
            self._records.append(record)

        return cost

    # -- queries ------------------------------------------------------------

    def get_total_cost(self) -> float:
        """Return the total accumulated cost in USD."""
        with self._lock:
            return sum(r.cost for r in self._records)

    def get_cost_by_agent(self) -> dict[str, float]:
        """Return cost breakdown keyed by agent_id."""
        with self._lock:
            out: dict[str, float] = {}
            for r in self._records:
                out[r.agent_id] = out.get(r.agent_id, 0.0) + r.cost
            return out

    def get_cost_by_division(self) -> dict[str, float]:
        """Return cost breakdown keyed by division."""
        with self._lock:
            out: dict[str, float] = {}
            for r in self._records:
                key = r.division or "(unassigned)"
                out[key] = out.get(key, 0.0) + r.cost
            return out

    def get_cost_by_phase(self) -> dict[str, float]:
        """Return cost breakdown keyed by phase."""
        with self._lock:
            out: dict[str, float] = {}
            for r in self._records:
                key = r.phase or "(unassigned)"
                out[key] = out.get(key, 0.0) + r.cost
            return out

    def get_cost_by_model(self) -> dict[str, float]:
        """Return cost breakdown keyed by model name."""
        with self._lock:
            out: dict[str, float] = {}
            for r in self._records:
                out[r.model] = out.get(r.model, 0.0) + r.cost
            return out

    def get_call_count(self) -> int:
        """Return the total number of recorded API calls."""
        with self._lock:
            return len(self._records)

    def check_ceiling(self, ceiling: float = 100.0) -> tuple[bool, float]:
        """Check spend against a ceiling.

        Returns:
            (exceeded, percentage) — *exceeded* is True when total >= ceiling.
            Emits a warning when spend reaches 80% of the ceiling.
        """
        total = self.get_total_cost()
        pct = (total / ceiling * 100.0) if ceiling > 0 else 0.0
        exceeded = total >= ceiling

        if pct >= 80.0 and not exceeded:
            warnings.warn(
                f"Cost warning: spending is at {pct:.1f}% of the ${ceiling:.2f} ceiling "
                f"(${total:.4f} spent)",
                stacklevel=2,
            )
            logger.warning(
                "Cost at %.1f%% of $%.2f ceiling ($%.4f spent)", pct, ceiling, total
            )

        if exceeded:
            logger.error(
                "Cost ceiling EXCEEDED: $%.4f >= $%.2f (%.1f%%)", total, ceiling, pct
            )

        return exceeded, pct

    def get_cost_report(self) -> dict:
        """Return a full cost breakdown report."""
        return {
            "total_cost": self.get_total_cost(),
            "call_count": self.get_call_count(),
            "by_agent": self.get_cost_by_agent(),
            "by_division": self.get_cost_by_division(),
            "by_phase": self.get_cost_by_phase(),
            "by_model": self.get_cost_by_model(),
        }

    def reset(self) -> None:
        """Clear all tracking data."""
        with self._lock:
            self._records.clear()


# ---------------------------------------------------------------------------
# Module-level singleton instance
# ---------------------------------------------------------------------------

cost_tracker = CostTracker()
