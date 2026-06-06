"""Unit tests for ``src.utils.confidence`` calibration logic.

Pure, deterministic functions — no network, no API key.
"""

from __future__ import annotations

from src.utils.confidence import calibrate_confidence
from src.utils.types import ConfidenceLevel


def test_empty_evidence_is_insufficient():
    assessment = calibrate_confidence([])
    assert assessment.level == ConfidenceLevel.INSUFFICIENT
    assert assessment.score == 0.0
    assert assessment.caveats  # records a "no evidence" caveat


def test_high_confidence_requires_three_independent_strong_sources():
    evidence = [
        {"source": "a", "strength": 0.9, "convergence": 0.8, "independent": True},
        {"source": "b", "strength": 0.85, "convergence": 0.8, "independent": True},
        {"source": "c", "strength": 0.8, "convergence": 0.75, "independent": True},
    ]
    assessment = calibrate_confidence(evidence)
    assert assessment.level == ConfidenceLevel.HIGH
    assert assessment.independent_replication == 3
    assert assessment.score >= 0.75


def test_medium_confidence_for_moderate_single_source():
    evidence = [{"source": "a", "strength": 0.6}]
    assessment = calibrate_confidence(evidence)
    assert assessment.level == ConfidenceLevel.MEDIUM


def test_low_confidence_for_weak_evidence():
    evidence = [{"source": "a", "strength": 0.3}]
    assessment = calibrate_confidence(evidence)
    assert assessment.level == ConfidenceLevel.LOW


def test_insufficient_for_negligible_strength():
    evidence = [{"source": "a", "strength": 0.05}]
    assessment = calibrate_confidence(evidence)
    assert assessment.level == ConfidenceLevel.INSUFFICIENT


def test_aggregates_optional_metrics():
    evidence = [
        {
            "source": "a",
            "strength": 0.7,
            "methodology_score": 0.8,
            "p_value": 0.01,
            "effect_size": 1.2,
            "caveat": "small sample",
            "alternative": "confounding",
        },
        {
            "source": "b",
            "strength": 0.6,
            "methodology_score": 0.6,
            "p_value": 0.04,
            "effect_size": 0.9,
        },
    ]
    assessment = calibrate_confidence(evidence)

    # statistical_significance uses the minimum (strongest) p-value.
    assert assessment.statistical_significance == 0.01
    # effect_size uses the maximum.
    assert assessment.effect_size == 1.2
    # methodology robustness is the mean of provided scores.
    assert assessment.methodology_robustness == 0.7
    assert "small sample" in assessment.caveats
    assert "confounding" in assessment.alternative_explanations


def test_score_clamped_to_unit_interval():
    # Out-of-range strengths get clamped by the weighted mean.
    evidence = [{"source": "a", "strength": 5.0}, {"source": "b", "strength": 5.0}]
    assessment = calibrate_confidence(evidence)
    assert 0.0 <= assessment.score <= 1.0


def test_three_sources_but_not_independent_is_not_high():
    # Strong scores but no independent flag -> should not reach HIGH.
    evidence = [
        {"source": "a", "strength": 0.9},
        {"source": "b", "strength": 0.9},
        {"source": "c", "strength": 0.9},
    ]
    assessment = calibrate_confidence(evidence)
    assert assessment.level == ConfidenceLevel.MEDIUM
    assert assessment.independent_replication is None
