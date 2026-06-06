#!/usr/bin/env bash
set -euo pipefail

# SessionStart hook — prepares dev environment for Claude Code web sessions.
# Idempotent: skips pip install if anthropic is already importable.

echo "[lumi] SessionStart: checking dev environment..."

# Install dev deps only if the core package isn't already available.
if python -c "import anthropic" 2>/dev/null; then
    echo "[lumi] Dev deps already installed, skipping pip install."
else
    echo "[lumi] Installing dev deps (pip install -e '[dev]')..."
    pip install -q -e ".[dev]" || echo "[lumi] WARNING: pip install exited non-zero; continuing."
fi

# Remind about offline mode — tests and pipeline work without an API key.
echo "[lumi] Tip: set LUMI_OFFLINE=1 to run tests/pipeline without an API key."
echo "[lumi] Tip: for live runs, copy .env.template to .env and set ANTHROPIC_API_KEY."
echo "[lumi] SessionStart complete."
