# Lumi

[![CI](https://github.com/shrivdar/lumi-mvp1/actions/workflows/ci.yml/badge.svg)](https://github.com/shrivdar/lumi-mvp1/actions/workflows/ci.yml)

Multi-agent virtual lab for drug discovery. A 9-phase orchestration pipeline coordinates specialist AI agents across biology, chemistry, and clinical domains to produce confidence-scored findings with biosecurity veto gates, adversarial review, and human-in-the-loop routing.

## How it works

1. Submit a research question via the Streamlit UI or pipeline API
2. **CSO** (Opus) plans the investigation; **ChiefOfStaff** (Haiku) briefs on the landscape
3. **BiosecurityOfficer** (Sonnet) screens for dual-use risk — RED = hard veto
4. Division leads dispatch tasks to 17 specialist agents backed by MCP tool servers
5. **ReviewPanel** (Sonnet) runs adversarial 3-pass review with up to 3 refinement cycles
6. **WorldModel** persists findings across sessions; final report includes confidence + provenance

## Architecture

**Tier 1 — Orchestration**: CSOOrchestrator, ChiefOfStaff, BiosecurityOfficer, ReviewPanel, WorldModel

**Tier 2 — Divisions** (8): Target ID · Target Safety · Modality · Molecular Design · Clinical · CompBio · Experimental · Biosecurity

**Tier 3 — Specialist Agents** (17): statistical_genetics, functional_genomics, single_cell_atlas, bio_pathways, fda_safety, toxicogenomics, target_biologist, pharmacologist, protein_intelligence, antibody_engineer, structure_design, lead_optimization, developability, clinical_trialist, literature_synthesis, assay_design, dual_use_screening

**Domain Engines**: Biosecurity Engine (5-screen screening) · Yami Simulator (protein intelligence) · Virtual Cell (metabolic modeling)

## Setup

```bash
pip install -e .                  # core
pip install -e ".[bio,ml,chem]"   # all optional deps
pip install -e ".[dev]"           # dev tools
```

## Project structure

```
src/
  orchestrator/          # CSO, ChiefOfStaff, ReviewPanel, BiosecurityOfficer, WorldModel
  divisions/             # 8 division leads coordinating agent groups
  agents/                # 17 specialist agents + base class
  biosecurity_engine/    # 5-screen biosecurity screening pipeline
  yami_simulator/        # Protein intelligence (ESM-2, AlphaFold)
  virtual_cell/          # Metabolic modeling (COBRApy)
  mcp_servers/           # MCP tool servers (genomics, protein, clinical, etc.)
  utils/                 # Confidence scoring, LLM client, provenance, types
  factory.py             # System factory — wires agents, divisions, MCP bridge
  mcp_bridge.py          # Master tool registry
app.py                   # Streamlit UI
```

## Stack

Python 3.11+ · Claude Opus/Sonnet/Haiku (anthropic SDK) · FastMCP v3 · Streamlit · SQLite (WorldModel)

## Development

### Install

```bash
make install
# or directly:
pip install -e ".[dev]"
```

Heavy optional extras (`[bio]`, `[ml]`, `[chem]`) pull in torch, scanpy, and rdkit — omit them for a lightweight dev setup.

### Lint

```bash
make lint
# expands to: ruff check src/ api/
```

### Test

```bash
make test
# expands to: LUMI_OFFLINE=1 python -m pytest -q
```

### Offline mode

Set `LUMI_OFFLINE=1` to run the pipeline, agents, and full test suite with deterministic mock LLM responses — no API key required. This is what CI uses.

```bash
LUMI_OFFLINE=1 python -m pytest -q
```

### Live runs

For live calls to the Anthropic API, copy `.env.template` to `.env` and set your key:

```bash
cp .env.template .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

Models used: CSOOrchestrator → `claude-opus-4-8`; ReviewPanel / BiosecurityOfficer → `claude-sonnet-4-6`; ChiefOfStaff → `claude-haiku-4-5`.
