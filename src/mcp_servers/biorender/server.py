"""
BioRender MCP Server -- Lumi Virtual Lab

Scientific figure generation for the YOHAS pipeline.  Combines three backends:

1. **AntV MCP Server Chart** (primary) -- programmatic chart generation via
   ``@antv/mcp-server-chart`` running as a local stdio subprocess.  Returns
   persistent CDN-hosted PNG URLs for 27+ chart types.

2. **BioRender search** (supplementary) -- icon and template search against
   the BioRender public catalogue.  Returns direct links into the BioRender
   web editor for manual polish of publication-ready illustrations.

3. **MockFlow IdeaBoard MCP** (supplementary) -- interactive diagram generation
   via MockFlow's HTTP/SSE MCP endpoint.  Provides bio diagrams with domain-
   specific icons, structured flowcharts with spatial positioning, mind maps,
   data tables, and Gantt charts -- capabilities that AntV does not cover.

Agents call high-level scientific figure tools (e.g. ``generate_volcano_plot``,
``generate_pathway_diagram``, ``generate_bio_diagram``) which translate domain
data into backend-specific schemas internally.

Start with:  python -m src.mcp_servers.biorender.server
Requires:    Node.js / npx on PATH, ``mcp`` Python package
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from fastmcp import FastMCP

try:
    from src.mcp_servers.base import handle_error, standard_response
except ImportError:
    from mcp_servers.base import handle_error, standard_response  # type: ignore[no-redef]

logger = logging.getLogger("lumi.mcp.biorender")

mcp = FastMCP("biorender")

# ---------------------------------------------------------------------------
# AntV chart session management
# ---------------------------------------------------------------------------

# Lazy-initialised singleton — the first tool call that needs AntV will spin
# up the subprocess and keep it alive for the duration of the process.
_antv_session: Any | None = None
_antv_lock = asyncio.Lock()
_antv_context: Any | None = None  # context manager references for cleanup


async def _get_antv_session():
    """Return (or create) a long-lived MCP ClientSession to the AntV chart server."""
    global _antv_session, _antv_context

    if _antv_session is not None:
        return _antv_session

    async with _antv_lock:
        # Double-check after acquiring lock
        if _antv_session is not None:
            return _antv_session

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            raise ImportError(
                "The 'mcp' package is required for AntV chart generation.  "
                "Install it with: pip install mcp httpx-sse"
            )

        params = StdioServerParameters(
            command="npx",
            args=["-y", "@antv/mcp-server-chart"],
        )

        # stdio_client returns an async context manager yielding (read, write).
        # We intentionally keep the context open for the process lifetime.
        ctx = stdio_client(params)
        read_stream, write_stream = await ctx.__aenter__()
        session = ClientSession(read_stream, write_stream)
        await session.__aenter__()
        await session.initialize()

        _antv_session = session
        _antv_context = ctx
        logger.info("AntV MCP chart server connected")
        return _antv_session


async def _call_antv(tool_name: str, args: dict[str, Any]) -> str | None:
    """Call an AntV tool and extract the image URL from the response."""
    session = await _get_antv_session()
    result = await session.call_tool(tool_name, args)
    for block in result.content:
        if hasattr(block, "text"):
            urls = re.findall(r"https?://[^\s\)\"']+", block.text)
            if urls:
                return urls[0]
    return None


# ---------------------------------------------------------------------------
# MockFlow session management (HTTP/SSE transport)
# ---------------------------------------------------------------------------

_mockflow_client: Any | None = None
_mockflow_lock = asyncio.Lock()

MOCKFLOW_URL = "https://app.mockflow.com/ideaboard/mcp"


def _parse_sse_data(text: str) -> dict | None:
    """Extract JSON payload from an SSE event stream response."""
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                continue
    # Fallback: try parsing the entire response as JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def _get_mockflow_client():
    """Return (or create) a long-lived httpx.AsyncClient for MockFlow MCP calls."""
    global _mockflow_client

    if _mockflow_client is not None:
        return _mockflow_client

    async with _mockflow_lock:
        if _mockflow_client is not None:
            return _mockflow_client

        import httpx

        client = httpx.AsyncClient(timeout=60)

        # MCP initialize handshake
        resp = await client.post(MOCKFLOW_URL, json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "lumi-biorender-server", "version": "1.0.0"},
            },
        }, headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        })
        data = _parse_sse_data(resp.text)
        if not data or "result" not in data:
            raise ConnectionError("MockFlow MCP initialization failed")

        logger.info("MockFlow IdeaBoard MCP connected: %s",
                     data["result"]["serverInfo"])
        _mockflow_client = client
        return _mockflow_client


async def _call_mockflow(tool_name: str, args: dict[str, Any]) -> dict[str, Any] | None:
    """Call a MockFlow MCP tool via JSON-RPC over HTTP/SSE.

    Returns the parsed response dict which typically contains:
      - url: interactive board URL
      - thumbnailUrl: direct image URL (when authenticated)
      - success: bool
    """
    client = await _get_mockflow_client()

    resp = await client.post(MOCKFLOW_URL, json={
        "jsonrpc": "2.0",
        "id": hash(tool_name) % 100000,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args},
    }, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    })

    data = _parse_sse_data(resp.text)
    if data and "result" in data:
        for block in data["result"].get("content", []):
            if block.get("type") == "text":
                text = block["text"]
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    urls = re.findall(r"https?://[^\s\)\"']+", text)
                    return {"url": urls[0] if urls else text}

    if data and "error" in data:
        raise RuntimeError(f"MockFlow error: {data['error']}")
    return None


# ---------------------------------------------------------------------------
# Default style constants
# ---------------------------------------------------------------------------

_THEME = "academy"
_DEFAULT_WIDTH = 800
_DEFAULT_HEIGHT = 600
_SCIENTIFIC_PALETTE = [
    "#E63946",  # red
    "#457B9D",  # steel blue
    "#2A9D8F",  # teal
    "#E9C46A",  # yellow
    "#F4A261",  # orange
    "#264653",  # dark blue
    "#8338EC",  # purple
    "#06D6A0",  # mint
    "#FF006E",  # pink
    "#CCCCCC",  # grey
]


def _base_style(palette: list[str] | None = None) -> dict[str, Any]:
    return {"palette": palette or _SCIENTIFIC_PALETTE}


# ===================================================================
# Scientific figure tools (AntV-backed)
# ===================================================================


@mcp.tool()
async def generate_volcano_plot(
    data: list[dict[str, Any]],
    title: str = "Volcano Plot",
    log2fc_threshold: float = 1.0,
    pvalue_threshold: float = 0.05,
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> dict[str, Any]:
    """Generate a volcano plot from differential expression data.

    Each item in *data* must have keys ``gene``, ``log2fc``, and ``pvalue``.
    Points are auto-classified as Significant / Non-significant based on the
    provided thresholds.

    Returns a dict with ``image_url`` (CDN PNG) and provenance metadata.
    """
    try:
        import math

        scatter_data = []
        for row in data:
            row.get("gene", "")
            log2fc = float(row.get("log2fc", 0))
            pval = float(row.get("pvalue", 1))
            neg_log10p = -math.log10(max(pval, 1e-300))
            sig = abs(log2fc) >= log2fc_threshold and pval <= pvalue_threshold
            scatter_data.append({
                "x": round(log2fc, 4),
                "y": round(neg_log10p, 4),
                "group": "Significant" if sig else "Non-significant",
            })

        url = await _call_antv("generate_scatter_chart", {
            "data": scatter_data,
            "title": title,
            "width": width,
            "height": height,
            "theme": _THEME,
            "style": _base_style(["#CCCCCC", "#E63946"]),
        })

        return standard_response(
            summary=f"Volcano plot with {len(data)} genes ({sum(1 for d in scatter_data if d['group'] == 'Significant')} significant)",
            raw_data={"image_url": url, "gene_count": len(data), "thresholds": {"log2fc": log2fc_threshold, "pvalue": pvalue_threshold}},
            source="antv_mcp_chart",
            source_id="generate_volcano_plot",
        )
    except Exception as exc:
        return handle_error("generate_volcano_plot", exc)


@mcp.tool()
async def generate_expression_heatmap(
    data: list[dict[str, Any]],
    title: str = "Expression Heatmap",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> dict[str, Any]:
    """Generate a gene expression heatmap.

    Each item in *data* must have keys ``gene`` (column), ``sample`` (row),
    and ``value`` (expression intensity).
    """
    try:
        heatmap_data = [
            {"x": row["gene"], "y": row["sample"], "value": float(row["value"])}
            for row in data
        ]

        url = await _call_antv("generate_heatmap", {
            "data": heatmap_data,
            "title": title,
            "width": width,
            "height": height,
            "theme": _THEME,
        })

        genes = sorted({r["gene"] for r in data})
        samples = sorted({r["sample"] for r in data})
        return standard_response(
            summary=f"Expression heatmap: {len(genes)} genes x {len(samples)} samples",
            raw_data={"image_url": url, "genes": genes, "samples": samples},
            source="antv_mcp_chart",
            source_id="generate_expression_heatmap",
        )
    except Exception as exc:
        return handle_error("generate_expression_heatmap", exc)


@mcp.tool()
async def generate_pathway_diagram(
    nodes: list[dict[str, str]],
    edges: list[dict[str, str]],
    title: str = "Signaling Pathway",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> dict[str, Any]:
    """Generate a signaling pathway or interaction network diagram.

    *nodes*: list of ``{"name": "...", "group": "..."}``  (group is optional,
    e.g. ``"kinase"``, ``"receptor"``, ``"transcription_factor"``).

    *edges*: list of ``{"source": "...", "target": "...", "name": "..."}``
    where ``name`` describes the interaction (e.g. ``"phosphorylates"``).
    """
    try:
        url = await _call_antv("generate_network_graph", {
            "data": {"nodes": nodes, "edges": edges},
            "title": title,
            "width": width,
            "height": height,
            "theme": _THEME,
        })

        return standard_response(
            summary=f"Pathway diagram: {len(nodes)} nodes, {len(edges)} edges",
            raw_data={"image_url": url, "node_count": len(nodes), "edge_count": len(edges)},
            source="antv_mcp_chart",
            source_id="generate_pathway_diagram",
        )
    except Exception as exc:
        return handle_error("generate_pathway_diagram", exc)


@mcp.tool()
async def generate_target_comparison_radar(
    data: list[dict[str, Any]],
    title: str = "Target Comparison",
    width: int = 700,
    height: int = 600,
) -> dict[str, Any]:
    """Generate a radar chart comparing multiple drug targets across criteria.

    Each item in *data* must have keys ``criterion``, ``value`` (0-100), and
    ``target`` (group name).

    Example criteria: Expression Level, Druggability, Genetic Evidence,
    Safety Profile, Clinical Precedent.
    """
    try:
        radar_data = [
            {"name": row["criterion"], "value": float(row["value"]), "group": row["target"]}
            for row in data
        ]

        url = await _call_antv("generate_radar_chart", {
            "data": radar_data,
            "title": title,
            "width": width,
            "height": height,
            "theme": _THEME,
            "style": {**_base_style(), "lineWidth": 3},
        })

        targets = sorted({r["target"] for r in data})
        return standard_response(
            summary=f"Radar comparison of {len(targets)} targets",
            raw_data={"image_url": url, "targets": targets},
            source="antv_mcp_chart",
            source_id="generate_target_comparison_radar",
        )
    except Exception as exc:
        return handle_error("generate_target_comparison_radar", exc)


@mcp.tool()
async def generate_gene_expression_bar(
    data: list[dict[str, Any]],
    title: str = "Gene Expression",
    grouped: bool = True,
    width: int = _DEFAULT_WIDTH,
    height: int = 500,
) -> dict[str, Any]:
    """Generate a bar chart of gene expression levels.

    Each item in *data* must have keys ``gene`` (category), ``expression``
    (value), and optionally ``condition`` (group for colour coding).
    """
    try:
        bar_data = [
            {
                "category": row["gene"],
                "value": float(row["expression"]),
                **({"group": row["condition"]} if "condition" in row else {}),
            }
            for row in data
        ]

        args: dict[str, Any] = {
            "data": bar_data,
            "title": title,
            "width": width,
            "height": height,
            "theme": _THEME,
            "style": _base_style(),
        }
        if grouped and any("group" in d for d in bar_data):
            args["group"] = True
            args["stack"] = False

        url = await _call_antv("generate_bar_chart", args)

        return standard_response(
            summary=f"Expression bar chart: {len(data)} entries",
            raw_data={"image_url": url, "gene_count": len(data)},
            source="antv_mcp_chart",
            source_id="generate_gene_expression_bar",
        )
    except Exception as exc:
        return handle_error("generate_gene_expression_bar", exc)


@mcp.tool()
async def generate_drug_target_sankey(
    data: list[dict[str, Any]],
    title: str = "Drug-Target-Pathway Flow",
    width: int = _DEFAULT_WIDTH,
    height: int = 500,
) -> dict[str, Any]:
    """Generate a Sankey diagram showing drug-target-pathway relationships.

    Each item in *data* must have keys ``source``, ``target``, and ``value``
    (flow magnitude, e.g. binding affinity or evidence count).
    """
    try:
        sankey_data = [
            {"source": row["source"], "target": row["target"], "value": float(row["value"])}
            for row in data
        ]

        url = await _call_antv("generate_sankey_chart", {
            "data": sankey_data,
            "title": title,
            "width": width,
            "height": height,
            "theme": _THEME,
        })

        return standard_response(
            summary=f"Sankey diagram: {len(data)} flows",
            raw_data={"image_url": url, "flow_count": len(data)},
            source="antv_mcp_chart",
            source_id="generate_drug_target_sankey",
        )
    except Exception as exc:
        return handle_error("generate_drug_target_sankey", exc)


@mcp.tool()
async def generate_pipeline_flow(
    nodes: list[dict[str, str]],
    edges: list[dict[str, str]],
    title: str = "Pipeline Workflow",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> dict[str, Any]:
    """Generate a flowchart for an experimental or computational pipeline.

    *nodes*: list of ``{"name": "...", "group": "..."}`` where group is one of
    ``"input"``, ``"process"``, ``"decision"``, ``"output"``.

    *edges*: list of ``{"source": "...", "target": "...", "name": "..."}``
    where ``name`` labels the transition.
    """
    try:
        url = await _call_antv("generate_flow_diagram", {
            "data": {"nodes": nodes, "edges": edges},
            "title": title,
            "width": width,
            "height": height,
            "theme": _THEME,
        })

        return standard_response(
            summary=f"Pipeline flow: {len(nodes)} steps, {len(edges)} transitions",
            raw_data={"image_url": url, "step_count": len(nodes)},
            source="antv_mcp_chart",
            source_id="generate_pipeline_flow",
        )
    except Exception as exc:
        return handle_error("generate_pipeline_flow", exc)


@mcp.tool()
async def generate_moa_diagram(
    nodes: list[dict[str, str]],
    edges: list[dict[str, str]],
    title: str = "Mechanism of Action",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> dict[str, Any]:
    """Generate a mechanism-of-action illustration as a network diagram.

    Specialised wrapper around the network graph tool with styling tuned for
    drug-target-pathway MoA illustrations.  Uses the same node/edge schema as
    :func:`generate_pathway_diagram`.
    """
    try:
        url = await _call_antv("generate_network_graph", {
            "data": {"nodes": nodes, "edges": edges},
            "title": title,
            "width": width,
            "height": height,
            "theme": _THEME,
        })

        return standard_response(
            summary=f"MoA diagram: {len(nodes)} components, {len(edges)} interactions",
            raw_data={"image_url": url, "node_count": len(nodes), "edge_count": len(edges)},
            source="antv_mcp_chart",
            source_id="generate_moa_diagram",
        )
    except Exception as exc:
        return handle_error("generate_moa_diagram", exc)


@mcp.tool()
async def generate_literature_wordcloud(
    data: list[dict[str, Any]],
    title: str = "Literature Keywords",
    width: int = 700,
    height: int = 500,
) -> dict[str, Any]:
    """Generate a word cloud from literature keyword frequencies.

    Each item in *data* must have keys ``keyword`` and ``count``.
    """
    try:
        wc_data = [
            {"text": row["keyword"], "value": int(row["count"])}
            for row in data
        ]

        url = await _call_antv("generate_word_cloud", {
            "data": wc_data,
            "title": title,
            "width": width,
            "height": height,
        })

        return standard_response(
            summary=f"Word cloud: {len(data)} keywords",
            raw_data={"image_url": url, "keyword_count": len(data)},
            source="antv_mcp_chart",
            source_id="generate_literature_wordcloud",
        )
    except Exception as exc:
        return handle_error("generate_literature_wordcloud", exc)


@mcp.tool()
async def generate_confidence_distribution(
    data: list[dict[str, Any]],
    title: str = "Finding Confidence Distribution",
    width: int = _DEFAULT_WIDTH,
    height: int = 500,
) -> dict[str, Any]:
    """Generate a column chart showing confidence score distribution of findings.

    Each item in *data* must have keys ``finding`` (label) and ``score`` (0-1).
    Optionally include ``division`` for grouped display.
    """
    try:
        bar_data = [
            {
                "category": row["finding"],
                "value": round(float(row["score"]) * 100, 1),
                **({"group": row["division"]} if "division" in row else {}),
            }
            for row in data
        ]

        url = await _call_antv("generate_column_chart", {
            "data": bar_data,
            "title": title,
            "width": width,
            "height": height,
            "theme": _THEME,
            "style": _base_style(),
        })

        return standard_response(
            summary=f"Confidence chart: {len(data)} findings",
            raw_data={"image_url": url, "finding_count": len(data)},
            source="antv_mcp_chart",
            source_id="generate_confidence_distribution",
        )
    except Exception as exc:
        return handle_error("generate_confidence_distribution", exc)


@mcp.tool()
async def generate_clinical_timeline(
    data: list[dict[str, Any]],
    title: str = "Clinical Trial Timeline",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> dict[str, Any]:
    """Generate a line chart showing clinical trial progression or time series data.

    Each item in *data* must have keys ``timepoint`` (x-axis label),
    ``value`` (measurement), and optionally ``group`` (condition/arm).
    """
    try:
        line_data = [
            {
                "x": str(row["timepoint"]),
                "y": float(row["value"]),
                **({"group": row["group"]} if "group" in row else {}),
            }
            for row in data
        ]

        url = await _call_antv("generate_line_chart", {
            "data": line_data,
            "title": title,
            "width": width,
            "height": height,
            "theme": _THEME,
            "style": _base_style(),
        })

        return standard_response(
            summary=f"Timeline chart: {len(data)} data points",
            raw_data={"image_url": url, "point_count": len(data)},
            source="antv_mcp_chart",
            source_id="generate_clinical_timeline",
        )
    except Exception as exc:
        return handle_error("generate_clinical_timeline", exc)


@mcp.tool()
async def generate_category_pie(
    data: list[dict[str, Any]],
    title: str = "Category Distribution",
    donut: bool = False,
    width: int = 700,
    height: int = 500,
) -> dict[str, Any]:
    """Generate a pie (or donut) chart for categorical data.

    Each item in *data* must have keys ``category`` and ``count``.
    """
    try:
        pie_data = [
            {"category": row["category"], "value": int(row["count"])}
            for row in data
        ]

        url = await _call_antv("generate_pie_chart", {
            "data": pie_data,
            "innerRadius": 0.6 if donut else 0,
            "title": title,
            "width": width,
            "height": height,
            "theme": _THEME,
            "style": _base_style(),
        })

        return standard_response(
            summary=f"{'Donut' if donut else 'Pie'} chart: {len(data)} categories",
            raw_data={"image_url": url, "category_count": len(data)},
            source="antv_mcp_chart",
            source_id="generate_category_pie",
        )
    except Exception as exc:
        return handle_error("generate_category_pie", exc)


@mcp.tool()
async def generate_venn_diagram(
    data: list[dict[str, Any]],
    title: str = "Set Overlap",
    width: int = 700,
    height: int = _DEFAULT_HEIGHT,
) -> dict[str, Any]:
    """Generate a Venn diagram showing set overlaps.

    *data* follows the AntV Venn schema -- list of ``{"sets": [...], "size": N}``.
    Example: ``[{"sets": ["A"], "size": 10}, {"sets": ["B"], "size": 8},
    {"sets": ["A", "B"], "size": 3}]``
    """
    try:
        url = await _call_antv("generate_venn_chart", {
            "data": data,
            "title": title,
            "width": width,
            "height": height,
            "theme": _THEME,
        })

        return standard_response(
            summary=f"Venn diagram: {len(data)} set entries",
            raw_data={"image_url": url},
            source="antv_mcp_chart",
            source_id="generate_venn_diagram",
        )
    except Exception as exc:
        return handle_error("generate_venn_diagram", exc)


# ===================================================================
# BioRender search tools (supplementary)
# ===================================================================

_BIORENDER_API = "https://mcp.services.biorender.com"


@mcp.tool()
async def search_biorender_icons(
    query: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Search BioRender's icon library for scientific illustration components.

    Returns icon names and metadata.  Useful for identifying available visual
    elements when planning publication-ready figures in BioRender's web editor.
    """
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_BIORENDER_API}/api/icons",
                params={"q": query, "limit": limit},
            )
            resp.raise_for_status()
            results = resp.json()

        icons = results.get("icons", results.get("results", []))
        return standard_response(
            summary=f"Found {len(icons)} BioRender icons for '{query}'",
            raw_data={"icons": icons[:limit], "query": query},
            source="biorender",
            source_id="search_icons",
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("search_biorender_icons", exc)


@mcp.tool()
async def search_biorender_templates(
    query: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Search BioRender's template library for pre-made scientific figures.

    Returns template names and links to the BioRender web editor where users
    can customise the illustration for publication.
    """
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_BIORENDER_API}/api/templates",
                params={"q": query, "limit": limit},
            )
            resp.raise_for_status()
            results = resp.json()

        templates = results.get("templates", results.get("results", []))
        return standard_response(
            summary=f"Found {len(templates)} BioRender templates for '{query}'",
            raw_data={"templates": templates[:limit], "query": query},
            source="biorender",
            source_id="search_templates",
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("search_biorender_templates", exc)


# ===================================================================
# Utility: download figure to local file
# ===================================================================


@mcp.tool()
async def download_figure(
    image_url: str,
    filename: str,
) -> dict[str, Any]:
    """Download a generated figure from CDN to a local file.

    Useful for embedding figures into PDF/HTML reports or archiving them
    alongside pipeline outputs.
    """
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()

        with open(filename, "wb") as f:
            f.write(resp.content)

        return standard_response(
            summary=f"Downloaded figure to {filename} ({len(resp.content)} bytes)",
            raw_data={"filename": filename, "size_bytes": len(resp.content), "source_url": image_url},
            source="antv_mcp_chart",
            source_id="download_figure",
        )
    except Exception as exc:
        return handle_error("download_figure", exc)


# ===================================================================
# MockFlow-backed tools (bio diagrams, flowcharts, mind maps, etc.)
# ===================================================================


@mcp.tool()
async def generate_bio_diagram(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, str]],
    title: str = "Biological Diagram",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> dict[str, Any]:
    """Generate a biological/medical diagram with domain-specific icons.

    Uses MockFlow's bio category which matches node *matchKey* values to
    scientific icons (receptor, membrane, dna, antibody, kinase, etc.).

    *nodes*: list of ``{"text": "...", "matchKey": "...", "color": "#hex",
                         "x": int, "y": int}``
        matchKey examples: receptor, membrane, dna, antibody, endocytosis,
        lysosome, apoptosis, mitochondria, ribosome, nucleus, cell, neuron

    *edges*: list of ``{"source_idx": int, "target_idx": int, "label": "..."}``
    """
    try:
        result = await _call_mockflow("render_flowchart", {
            "nodes": nodes,
            "edges": edges,
            "title": title,
            "category": "bio",
            "width": width,
            "height": height,
        })

        return standard_response(
            summary=f"Bio diagram: {len(nodes)} components, {len(edges)} connections",
            raw_data={
                "board_url": result.get("url") if result else None,
                "thumbnail_url": result.get("thumbnailUrl") if result else None,
                "image_url": (result.get("thumbnailUrl") or result.get("url")) if result else None,
                "node_count": len(nodes),
                "edge_count": len(edges),
            },
            source="mockflow_ideaboard",
            source_id="generate_bio_diagram",
        )
    except Exception as exc:
        return handle_error("generate_bio_diagram", exc)


@mcp.tool()
async def generate_signaling_flowchart(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, str]],
    title: str = "Signaling Pathway",
    style: str = "default",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> dict[str, Any]:
    """Generate a structured signaling pathway as a flowchart.

    Unlike :func:`generate_pathway_diagram` (AntV network graph with auto-layout),
    this creates a spatially organized flowchart with explicit positioning,
    colored nodes, labeled edges, and decision diamonds.

    *nodes*: list of ``{"text": "...", "shape": "...", "color": "#hex",
                         "x": int, "y": int}``
        shape options: Rectangle, Diamond, Circle, RoundedRectangle

    *edges*: list of ``{"source_idx": int, "target_idx": int, "label": "..."}``

    *style*: ``"default"`` (clean), ``"sketchy"`` (hand-drawn), ``"3d"`` (isometric)
    """
    try:
        result = await _call_mockflow("render_flowchart", {
            "nodes": nodes,
            "edges": edges,
            "title": title,
            "style": style,
            "width": width,
            "height": height,
        })

        return standard_response(
            summary=f"Signaling flowchart: {len(nodes)} nodes, {len(edges)} edges",
            raw_data={
                "board_url": result.get("url") if result else None,
                "thumbnail_url": result.get("thumbnailUrl") if result else None,
                "image_url": (result.get("thumbnailUrl") or result.get("url")) if result else None,
                "node_count": len(nodes),
                "edge_count": len(edges),
                "style": style,
            },
            source="mockflow_ideaboard",
            source_id="generate_signaling_flowchart",
        )
    except Exception as exc:
        return handle_error("generate_signaling_flowchart", exc)


@mcp.tool()
async def generate_experiment_mindmap(
    root_topic: str,
    branches: list[dict[str, Any]],
    title: str = "Experiment Overview",
) -> dict[str, Any]:
    """Generate a mind map for experiment planning or result overview.

    *branches*: list of ``{"topic": "...", "direction": 0|1, "children": [...]}``
        direction: 0 = left, 1 = right (for visual balance)
        children: nested list of ``{"topic": "..."}`` sub-branches
    """
    try:
        result = await _call_mockflow("render_mindmap", {
            "root": root_topic,
            "branches": branches,
            "title": title,
        })

        branch_count = len(branches)
        child_count = sum(len(b.get("children", [])) for b in branches)
        return standard_response(
            summary=f"Mind map: '{root_topic}' with {branch_count} branches, {child_count} sub-topics",
            raw_data={
                "board_url": result.get("url") if result else None,
                "thumbnail_url": result.get("thumbnailUrl") if result else None,
                "image_url": (result.get("thumbnailUrl") or result.get("url")) if result else None,
                "root_topic": root_topic,
                "branch_count": branch_count,
                "child_count": child_count,
            },
            source="mockflow_ideaboard",
            source_id="generate_experiment_mindmap",
        )
    except Exception as exc:
        return handle_error("generate_experiment_mindmap", exc)


@mcp.tool()
async def generate_data_table(
    headers: list[str],
    rows: list[list[str]],
    title: str = "Data Table",
) -> dict[str, Any]:
    """Generate a formatted data table visualization.

    Returns an interactive MockFlow board with the table.  Useful for
    presenting target comparison matrices, clinical trial summaries,
    or pipeline result tables in a visual format.

    *headers*: column header labels
    *rows*: list of rows, each row is a list of cell values (strings)
    """
    try:
        result = await _call_mockflow("render_spreadsheet", {
            "headers": headers,
            "rows": rows,
            "title": title,
        })

        return standard_response(
            summary=f"Data table: {len(headers)} columns x {len(rows)} rows",
            raw_data={
                "board_url": result.get("url") if result else None,
                "thumbnail_url": result.get("thumbnailUrl") if result else None,
                "image_url": (result.get("thumbnailUrl") or result.get("url")) if result else None,
                "columns": len(headers),
                "row_count": len(rows),
            },
            source="mockflow_ideaboard",
            source_id="generate_data_table",
        )
    except Exception as exc:
        return handle_error("generate_data_table", exc)


@mcp.tool()
async def generate_pipeline_gantt(
    phases: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    title: str = "Pipeline Timeline",
) -> dict[str, Any]:
    """Generate a Gantt chart for drug discovery pipeline milestones.

    *phases*: list of ``{"name": "...", "color": "#hex"}``
    *tasks*: list of ``{"name": "...", "phase": "...", "start": "YYYY-MM-DD",
                         "end": "YYYY-MM-DD"}``
    """
    try:
        result = await _call_mockflow("render_gantt", {
            "phases": phases,
            "tasks": tasks,
            "title": title,
        })

        return standard_response(
            summary=f"Gantt chart: {len(phases)} phases, {len(tasks)} tasks",
            raw_data={
                "board_url": result.get("url") if result else None,
                "thumbnail_url": result.get("thumbnailUrl") if result else None,
                "image_url": (result.get("thumbnailUrl") or result.get("url")) if result else None,
                "phase_count": len(phases),
                "task_count": len(tasks),
            },
            source="mockflow_ideaboard",
            source_id="generate_pipeline_gantt",
        )
    except Exception as exc:
        return handle_error("generate_pipeline_gantt", exc)


# ---------------------------------------------------------------------------
# Standalone server entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
