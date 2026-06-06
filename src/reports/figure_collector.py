"""Figure collector -- extracts visual outputs from agent tool results.

Scans AgentResult and DivisionReport objects for tool calls that produce
images (PyMOL renders, BioRender/AntV charts, MockFlow diagrams) and
assembles them into figure dicts suitable for FinalReport.figures.

Usage::

    from src.reports.figure_collector import collect_figures

    figures = collect_figures(division_reports)
    report.figures = figures
"""

from __future__ import annotations

import logging
from typing import Any

from src.utils.types import DivisionReport

logger = logging.getLogger("lumi.reports.figure_collector")

# ---------------------------------------------------------------------------
# Tool -> figure type mapping
# ---------------------------------------------------------------------------

# Tools that produce figures, mapped to (figure_type, title_template)
_FIGURE_TOOLS: dict[str, tuple[str, str]] = {
    # PyMOL (file_path)
    "render_protein_structure": ("STRUCTURE", "Protein Structure — {pdb_id}"),
    "render_protein_surface": ("SURFACE", "Molecular Surface — {pdb_id}"),
    "render_binding_site": ("BINDING_SITE", "Binding Site — {pdb_id}"),
    "align_structures": ("ALIGNMENT", "Structural Alignment — {pdb_id_1} vs {pdb_id_2}"),
    "render_antibody_complex": ("STRUCTURE", "Antibody Complex — {pdb_id}"),
    "highlight_residues": ("STRUCTURE", "Highlighted Residues — {pdb_id}"),
    "render_mutation_sites": ("STRUCTURE", "Mutation Sites — {pdb_id}"),
    "measure_distance": ("STRUCTURE", "Distance Measurement — {pdb_id}"),
    # BioRender / AntV (image_url)
    "generate_volcano_plot": ("VOLCANO", "Volcano Plot"),
    "generate_expression_heatmap": ("HEATMAP", "Expression Heatmap"),
    "generate_pathway_diagram": ("PATHWAY", "Pathway Diagram"),
    "generate_target_comparison_radar": ("OTHER", "Target Comparison Radar"),
    "generate_gene_expression_bar": ("HEATMAP", "Gene Expression"),
    "generate_drug_target_sankey": ("OTHER", "Drug-Target Sankey"),
    "generate_pipeline_flow": ("PATHWAY", "Pipeline Flow"),
    "generate_moa_diagram": ("MOA", "Mechanism of Action"),
    "generate_literature_wordcloud": ("OTHER", "Literature Word Cloud"),
    "generate_confidence_distribution": ("CONFIDENCE", "Confidence Distribution"),
    "generate_clinical_timeline": ("OTHER", "Clinical Timeline"),
    "generate_category_pie": ("OTHER", "Category Distribution"),
    "generate_venn_diagram": ("OTHER", "Venn Diagram"),
    # MockFlow (image_url)
    "generate_bio_diagram": ("PATHWAY", "Bio Diagram"),
    "generate_signaling_flowchart": ("PATHWAY", "Signaling Flowchart"),
    "generate_experiment_mindmap": ("OTHER", "Experiment Mind Map"),
    "generate_data_table": ("OTHER", "Data Table"),
    "generate_pipeline_gantt": ("OTHER", "Pipeline Gantt Chart"),
}


def _format_title(template: str, raw_data: dict[str, Any]) -> str:
    """Format a title template with available data, falling back gracefully."""
    try:
        return template.format(**raw_data)
    except (KeyError, IndexError):
        return template.split(" — ")[0]


def extract_figures_from_tool_results(
    tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract figure dicts from a list of stored tool results.

    Each tool result dict should have: ``tool_name``, ``result`` (the
    standard_response envelope from the MCP tool).

    Returns a list of figure dicts with keys: title, caption, figure_type,
    source_tool, and either image_url or file_path.
    """
    figures: list[dict[str, Any]] = []

    for tr in tool_results:
        tool_name = tr.get("tool_name", "")
        result = tr.get("result", {})

        if tool_name not in _FIGURE_TOOLS:
            continue

        # Skip error responses
        if isinstance(result, dict) and result.get("error"):
            continue

        # Extract from standard_response envelope
        raw_data = result.get("raw_data", {}) if isinstance(result, dict) else {}
        summary = result.get("summary", "") if isinstance(result, dict) else ""

        image_url = raw_data.get("image_url")
        file_path = raw_data.get("file_path")

        # Must have at least one image source
        if not image_url and not file_path:
            continue

        figure_type, title_template = _FIGURE_TOOLS[tool_name]
        title = _format_title(title_template, raw_data)

        fig: dict[str, Any] = {
            "title": title,
            "caption": summary,
            "figure_type": figure_type,
            "source_tool": tool_name,
        }

        if file_path:
            fig["file_path"] = file_path
        if image_url:
            fig["image_url"] = image_url

        figures.append(fig)

    return figures


def collect_figures(
    division_reports: list[DivisionReport],
) -> list[dict[str, Any]]:
    """Collect all figures from division reports.

    Scans each specialist AgentResult for stored tool results that
    produced images and returns a deduplicated list of figure dicts.
    """
    figures: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for dr in division_reports:
        for sr in dr.specialist_results:
            agent_figures = extract_figures_from_tool_results(
                sr.raw_data.get("tool_results", [])
            )
            for fig in agent_figures:
                # Deduplicate by image source
                key = fig.get("file_path") or fig.get("image_url", "")
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    figures.append(fig)

    logger.info("Collected %d figures from %d division reports", len(figures), len(division_reports))
    return figures
