"""Smoke tests for the FastAPI metadata endpoints that drive the frontend.

These guard the route-ordering fix: literal ``/meta/*`` paths must be matched
before the parametrized ``/{sublab_id}`` routes, and the metadata must expose
every registered specialist (incl. ``competitive_intelligence``).

No network / API key required.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_meta_agents_reachable_and_lists_competitive_intelligence():
    # Regression: "/meta/agents" must not be captured by "/{sublab_id}/agents".
    resp = client.get("/api/sublabs/meta/agents")
    assert resp.status_code == 200
    ids = {a["id"] for a in resp.json()}
    assert "competitive_intelligence" in ids


def test_meta_tools_and_integrations_reachable():
    assert client.get("/api/sublabs/meta/tools").status_code == 200
    assert client.get("/api/sublabs/meta/integrations").status_code == 200


def test_sublab_agents_route_still_works():
    resp = client.get("/api/sublabs/target-validation/agents")
    assert resp.status_code == 200
    ids = {a["id"] for a in resp.json()}
    assert "competitive_intelligence" in ids


def test_list_sublabs():
    resp = client.get("/api/sublabs")
    assert resp.status_code == 200
    assert "target-validation" in resp.json()
