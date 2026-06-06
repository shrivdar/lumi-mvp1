"""
PyMOL Structure MCP Server -- Lumi Virtual Lab

3D protein structure rendering in headless mode for the YOHAS pipeline.
Produces publication-quality ray-traced PNG images of protein structures,
binding sites, surfaces, alignments, and antibody-antigen complexes.

Uses PyMOL's Python API directly (headless ``-qc`` mode) — no GUI or
socket connection required.  All PyMOL calls are blocking and run via
``asyncio.to_thread()`` behind a render lock for thread safety.

Start with:
    conda run -n pymol_agent python -m src.mcp_servers.pymol_structure.server

Requires:
    pymol-open-source (install via conda-forge):
        conda create -n pymol_agent python=3.11 pymol-open-source -c conda-forge
        conda run -n pymol_agent pip install fastmcp mcp httpx-sse
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastmcp import FastMCP

try:
    from src.mcp_servers.base import handle_error, standard_response
except ImportError:
    from mcp_servers.base import handle_error, standard_response  # type: ignore[no-redef]

logger = logging.getLogger("lumi.mcp.pymol")

mcp = FastMCP("pymol_structure")

# ---------------------------------------------------------------------------
# PyMOL singleton (headless, lazy init)
# ---------------------------------------------------------------------------

_pymol_cmd: Any | None = None
_pymol_lock = asyncio.Lock()
_pymol_render_lock = asyncio.Lock()

_OUTPUT_DIR = os.environ.get("LUMI_PYMOL_OUTPUT", os.path.join(os.getcwd(), "output", "pymol"))
os.makedirs(_OUTPUT_DIR, exist_ok=True)


async def _get_pymol():
    """Return (or initialize) the PyMOL ``cmd`` module in headless mode."""
    global _pymol_cmd
    if _pymol_cmd is not None:
        return _pymol_cmd

    async with _pymol_lock:
        if _pymol_cmd is not None:
            return _pymol_cmd

        def _init():
            import pymol
            pymol.pymol_argv = ["pymol", "-qc"]
            pymol.finish_launching()
            from pymol import cmd
            return cmd

        _pymol_cmd = await asyncio.to_thread(_init)
        logger.info("PyMOL initialized in headless mode")
        return _pymol_cmd


async def _run_pymol(func, *args, **kwargs):
    """Run a blocking PyMOL function in a thread executor."""
    return await asyncio.to_thread(func, *args, **kwargs)


# ---------------------------------------------------------------------------
# Style presets
# ---------------------------------------------------------------------------

STYLE_PRESETS: dict[str, list[tuple[str, ...]]] = {
    "cartoon_rainbow": [
        ("hide", "everything", "all"),
        ("show", "cartoon", "all"),
        ("spectrum", "count", "rainbow", "all"),
        ("set", "cartoon_fancy_helices", "1"),
        ("set", "cartoon_highlight_color", "grey70"),
        ("set", "cartoon_smooth_loops", "1"),
        ("set", "ray_shadow", "1"),
        ("bg_color", "white"),
        ("orient",),
    ],
    "surface_electrostatic": [
        ("hide", "everything", "all"),
        ("show", "surface", "all"),
        ("set", "surface_color", "default"),
        ("spectrum", "pc", "blue_white_red", "all"),
        ("set", "transparency", "0.1"),
        ("set", "surface_quality", "1"),
        ("bg_color", "white"),
        ("orient",),
    ],
    "surface_chain": [
        ("hide", "everything", "all"),
        ("show", "surface", "all"),
        ("util.cbc",),
        ("set", "transparency", "0.15"),
        ("set", "surface_quality", "1"),
        ("bg_color", "white"),
        ("orient",),
    ],
    "secondary_structure": [
        ("hide", "everything", "all"),
        ("show", "cartoon", "all"),
        ("color", "firebrick", "ss h"),
        ("color", "tv_yellow", "ss s"),
        ("color", "palegreen", "ss l+''"),
        ("set", "cartoon_fancy_helices", "1"),
        ("set", "cartoon_flat_sheets", "1"),
        ("bg_color", "white"),
        ("orient",),
    ],
    "bfactor": [
        ("hide", "everything", "all"),
        ("show", "cartoon", "all"),
        ("spectrum", "b", "blue_white_red", "all"),
        ("set", "cartoon_putty_radius", "0.3"),
        ("bg_color", "white"),
        ("orient",),
    ],
    "chain_color": [
        ("hide", "everything", "all"),
        ("show", "cartoon", "all"),
        ("util.cbc",),
        ("set", "cartoon_fancy_helices", "1"),
        ("bg_color", "white"),
        ("orient",),
    ],
    "sticks": [
        ("hide", "everything", "all"),
        ("show", "sticks", "all"),
        ("show", "spheres", "all"),
        ("set", "stick_radius", "0.15"),
        ("set", "sphere_scale", "0.2"),
        ("util.cbaw",),
        ("bg_color", "white"),
        ("orient",),
    ],
    "publication": [
        ("hide", "everything", "all"),
        ("show", "cartoon", "all"),
        ("util.cbc",),
        ("set", "cartoon_fancy_helices", "1"),
        ("set", "cartoon_highlight_color", "grey70"),
        ("set", "cartoon_smooth_loops", "1"),
        ("set", "ray_shadow", "1"),
        ("set", "ray_trace_mode", "1"),
        ("set", "antialias", "2"),
        ("set", "ambient", "0.4"),
        ("set", "reflect", "0.5"),
        ("set", "specular", "0.5"),
        ("bg_color", "white"),
        ("orient",),
    ],
}


# ---------------------------------------------------------------------------
# Core rendering helper
# ---------------------------------------------------------------------------

async def _render_structure(
    pdb_id: str,
    filename: str,
    style_commands: list[tuple[str, ...]],
    width: int = 1200,
    height: int = 900,
    ray: bool = True,
    extra_commands: list[tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    """Fetch PDB, apply styling, ray-trace, save PNG, return metadata.

    All PyMOL operations are serialized behind ``_pymol_render_lock``.
    """
    async with _pymol_render_lock:
        cmd = await _get_pymol()

        def _do_render():
            cmd.reinitialize()
            cmd.fetch(pdb_id, async_=0)

            # Apply style commands
            for instruction in style_commands:
                method_name = instruction[0]
                args = instruction[1:] if len(instruction) > 1 else ()

                if method_name.startswith("util."):
                    cmd.do(f"{method_name} {' '.join(str(a) for a in args)}".strip())
                elif method_name == "bg_color":
                    cmd.bg_color(*args)
                elif hasattr(cmd, method_name):
                    getattr(cmd, method_name)(*args)
                else:
                    cmd.do(f"{method_name} {', '.join(str(a) for a in args)}".strip())

            # Extra commands (tool-specific overrides)
            if extra_commands:
                for instruction in extra_commands:
                    method_name = instruction[0]
                    args = instruction[1:] if len(instruction) > 1 else ()
                    if method_name.startswith("util."):
                        cmd.do(f"{method_name} {' '.join(str(a) for a in args)}".strip())
                    elif method_name == "bg_color":
                        cmd.bg_color(*args)
                    elif hasattr(cmd, method_name):
                        getattr(cmd, method_name)(*args)
                    else:
                        cmd.do(f"{method_name} {', '.join(str(a) for a in args)}".strip())

            filepath = os.path.join(_OUTPUT_DIR, filename)
            if ray:
                cmd.ray(width, height)
            cmd.png(filepath, width=width, height=height, dpi=300, quiet=1)
            return filepath

        filepath = await _run_pymol(_do_render)

    size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
    return {
        "file_path": filepath,
        "image_url": None,
        "pdb_id": pdb_id,
        "resolution": f"{width}x{height}",
        "size_bytes": size,
        "ray_traced": ray,
    }


# ===================================================================
# MCP Tools
# ===================================================================


@mcp.tool()
async def render_protein_structure(
    pdb_id: str,
    style: str = "cartoon_rainbow",
    width: int = 1200,
    height: int = 900,
    ray: bool = True,
) -> dict[str, Any]:
    """Render a protein structure from PDB with a named style preset.

    *pdb_id*: 4-character PDB code (e.g. ``"1UBQ"``, ``"7S4S"``)

    *style*: one of ``cartoon_rainbow``, ``surface_electrostatic``,
    ``surface_chain``, ``secondary_structure``, ``bfactor``, ``chain_color``,
    ``sticks``, ``publication``

    Returns a ray-traced PNG image of the structure.
    """
    try:
        style_key = style.lower()
        if style_key not in STYLE_PRESETS:
            available = ", ".join(sorted(STYLE_PRESETS))
            return handle_error("render_protein_structure", f"Unknown style '{style}'. Available: {available}")

        filename = f"pymol_{pdb_id}_{style_key}.png"
        result = await _render_structure(
            pdb_id=pdb_id,
            filename=filename,
            style_commands=STYLE_PRESETS[style_key],
            width=width,
            height=height,
            ray=ray,
        )
        result["style"] = style_key

        return standard_response(
            summary=f"Rendered {pdb_id} ({style_key}, {width}x{height}, {'ray-traced' if ray else 'OpenGL'})",
            raw_data=result,
            source="pymol",
            source_id="render_protein_structure",
        )
    except Exception as exc:
        return handle_error("render_protein_structure", exc)


@mcp.tool()
async def render_protein_surface(
    pdb_id: str,
    color_by: str = "chain",
    transparency: float = 0.15,
    width: int = 1200,
    height: int = 900,
) -> dict[str, Any]:
    """Render a molecular surface colored by chain, electrostatic potential, or hydrophobicity.

    *color_by*: ``"chain"`` (distinct colors per chain), ``"electrostatic"``
    (blue-white-red charge gradient), ``"hydrophobicity"`` (brown-white-blue),
    ``"element"`` (CPK coloring)
    """
    try:
        color_commands: dict[str, list[tuple[str, ...]]] = {
            "chain": [
                ("hide", "everything", "all"),
                ("show", "surface", "all"),
                ("util.cbc",),
                ("set", "transparency", str(transparency)),
                ("set", "surface_quality", "1"),
                ("bg_color", "white"),
                ("orient",),
            ],
            "electrostatic": [
                ("hide", "everything", "all"),
                ("show", "surface", "all"),
                ("spectrum", "pc", "blue_white_red", "all"),
                ("set", "transparency", str(transparency)),
                ("set", "surface_quality", "1"),
                ("bg_color", "white"),
                ("orient",),
            ],
            "hydrophobicity": [
                ("hide", "everything", "all"),
                ("show", "surface", "all"),
                ("set", "surface_color", "default"),
                ("spectrum", "sasa", "brown_white_blue", "all"),
                ("set", "transparency", str(transparency)),
                ("set", "surface_quality", "1"),
                ("bg_color", "white"),
                ("orient",),
            ],
            "element": [
                ("hide", "everything", "all"),
                ("show", "surface", "all"),
                ("util.cbaw",),
                ("set", "transparency", str(transparency)),
                ("set", "surface_quality", "1"),
                ("bg_color", "white"),
                ("orient",),
            ],
        }

        if color_by not in color_commands:
            return handle_error("render_protein_surface", f"Unknown color_by '{color_by}'. Available: {', '.join(color_commands)}")

        filename = f"pymol_{pdb_id}_surface_{color_by}.png"
        result = await _render_structure(
            pdb_id=pdb_id,
            filename=filename,
            style_commands=color_commands[color_by],
            width=width,
            height=height,
        )
        result["color_by"] = color_by

        return standard_response(
            summary=f"Surface rendering of {pdb_id} colored by {color_by}",
            raw_data=result,
            source="pymol",
            source_id="render_protein_surface",
        )
    except Exception as exc:
        return handle_error("render_protein_surface", exc)


@mcp.tool()
async def render_binding_site(
    pdb_id: str,
    site_residues: list[str],
    site_chain: str = "A",
    context_radius: float = 8.0,
    width: int = 1200,
    height: int = 900,
) -> dict[str, Any]:
    """Render a close-up of a binding site with surrounding context.

    *site_residues*: list of residue numbers to highlight (e.g. ``["45", "67", "112"]``)

    *site_chain*: chain ID containing the binding site (default ``"A"``)

    *context_radius*: angstrom radius around site to display (default 8.0)

    The binding site residues are shown as sticks with atom coloring; the
    surrounding context is shown as a transparent cartoon.
    """
    try:
        resi_sel = "+".join(site_residues)
        site_sele = f"chain {site_chain} and resi {resi_sel}"
        context_sele = f"byres (all within {context_radius} of ({site_sele}))"

        base_style = [
            ("hide", "everything", "all"),
            ("show", "cartoon", "all"),
            ("color", "grey80", "all"),
            ("set", "cartoon_transparency", "0.7"),
        ]
        extra = [
            ("show", "sticks", site_sele),
            ("show", "spheres", f"({site_sele}) and name ZN+MG+CA+FE+MN+CU+CO+NI"),
            ("util.cbaw", site_sele),
            ("show", "lines", context_sele),
            ("color", "grey60", context_sele),
            ("set", "stick_radius", "0.15"),
            ("set", "sphere_scale", "0.25"),
            ("zoom", site_sele, str(context_radius)),
            ("bg_color", "white"),
        ]

        filename = f"pymol_{pdb_id}_binding_site_{site_chain}.png"
        result = await _render_structure(
            pdb_id=pdb_id,
            filename=filename,
            style_commands=base_style,
            extra_commands=extra,
            width=width,
            height=height,
        )
        result["site_residues"] = site_residues
        result["site_chain"] = site_chain

        return standard_response(
            summary=f"Binding site of {pdb_id} chain {site_chain}: {len(site_residues)} key residues",
            raw_data=result,
            source="pymol",
            source_id="render_binding_site",
        )
    except Exception as exc:
        return handle_error("render_binding_site", exc)


@mcp.tool()
async def align_structures(
    pdb_id_1: str,
    pdb_id_2: str,
    width: int = 1200,
    height: int = 900,
) -> dict[str, Any]:
    """Superimpose two PDB structures, render the alignment, and report RMSD.

    Both structures are shown as cartoons with distinct chain colors.
    The alignment RMSD (in angstroms) is returned in the response.
    """
    try:
        async with _pymol_render_lock:
            cmd = await _get_pymol()

            def _do_align():
                cmd.reinitialize()
                cmd.fetch(pdb_id_1, pdb_id_1, async_=0)
                cmd.fetch(pdb_id_2, pdb_id_2, async_=0)
                result = cmd.align(pdb_id_1, pdb_id_2)
                rmsd = result[0] if isinstance(result, (list, tuple)) else result

                cmd.hide("everything", "all")
                cmd.show("cartoon", "all")
                cmd.color("marine", pdb_id_1)
                cmd.color("salmon", pdb_id_2)
                cmd.set("cartoon_fancy_helices", 1)
                cmd.bg_color("white")
                cmd.orient()

                filepath = os.path.join(_OUTPUT_DIR, f"pymol_align_{pdb_id_1}_{pdb_id_2}.png")
                cmd.ray(width, height)
                cmd.png(filepath, width=width, height=height, dpi=300, quiet=1)
                return filepath, float(rmsd)

            filepath, rmsd = await _run_pymol(_do_align)

        size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
        return standard_response(
            summary=f"Aligned {pdb_id_1} vs {pdb_id_2}: RMSD = {rmsd:.2f} A",
            raw_data={
                "file_path": filepath,
                "image_url": None,
                "pdb_id_1": pdb_id_1,
                "pdb_id_2": pdb_id_2,
                "rmsd_angstrom": round(rmsd, 3),
                "resolution": f"{width}x{height}",
                "size_bytes": size,
                "ray_traced": True,
            },
            source="pymol",
            source_id="align_structures",
        )
    except Exception as exc:
        return handle_error("align_structures", exc)


@mcp.tool()
async def render_antibody_complex(
    pdb_id: str,
    antigen_chain: str = "A",
    heavy_chain: str = "H",
    light_chain: str = "L",
    show_cdr_loops: bool = True,
    width: int = 1200,
    height: int = 900,
) -> dict[str, Any]:
    """Render an antibody-antigen complex with differentiated coloring.

    The antigen is shown in grey surface + cartoon.  Heavy and light chains
    are colored distinctly.  CDR loops (H1-H3, L1-L3) are highlighted in
    warmer colors if *show_cdr_loops* is True.

    *antigen_chain*: chain ID of the antigen (default ``"A"``)
    *heavy_chain*: chain ID of the antibody heavy chain (default ``"H"``)
    *light_chain*: chain ID of the antibody light chain (default ``"L"``)
    """
    try:
        async with _pymol_render_lock:
            cmd = await _get_pymol()

            def _do_render():
                cmd.reinitialize()
                cmd.fetch(pdb_id, async_=0)

                cmd.hide("everything", "all")

                # Antigen: grey surface + cartoon
                ag_sel = f"chain {antigen_chain}"
                cmd.show("cartoon", ag_sel)
                cmd.show("surface", ag_sel)
                cmd.color("grey70", ag_sel)
                cmd.set("transparency", "0.6", ag_sel)

                # Heavy chain: marine cartoon
                hc_sel = f"chain {heavy_chain}"
                cmd.show("cartoon", hc_sel)
                cmd.color("marine", hc_sel)

                # Light chain: palegreen cartoon
                lc_sel = f"chain {light_chain}"
                cmd.show("cartoon", lc_sel)
                cmd.color("palegreen", lc_sel)

                # Highlight CDR loops (approximate Kabat numbering)
                if show_cdr_loops:
                    cdr_defs = {
                        "H1": (f"chain {heavy_chain} and resi 26-35", "tv_red"),
                        "H2": (f"chain {heavy_chain} and resi 50-65", "tv_orange"),
                        "H3": (f"chain {heavy_chain} and resi 95-102", "firebrick"),
                        "L1": (f"chain {light_chain} and resi 24-34", "tv_yellow"),
                        "L2": (f"chain {light_chain} and resi 50-56", "lime"),
                        "L3": (f"chain {light_chain} and resi 89-97", "forest"),
                    }
                    for cdr_name, (sele, color) in cdr_defs.items():
                        cmd.color(color, sele)
                        cmd.show("sticks", sele)
                        cmd.set("stick_radius", "0.12", sele)

                cmd.set("cartoon_fancy_helices", 1)
                cmd.set("ray_shadow", 1)
                cmd.bg_color("white")
                cmd.orient()

                filepath = os.path.join(_OUTPUT_DIR, f"pymol_{pdb_id}_antibody.png")
                cmd.ray(width, height)
                cmd.png(filepath, width=width, height=height, dpi=300, quiet=1)
                return filepath

            filepath = await _run_pymol(_do_render)

        size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
        return standard_response(
            summary=f"Antibody-antigen complex {pdb_id} (Ag={antigen_chain}, Hc={heavy_chain}, Lc={light_chain})",
            raw_data={
                "file_path": filepath,
                "image_url": None,
                "pdb_id": pdb_id,
                "antigen_chain": antigen_chain,
                "heavy_chain": heavy_chain,
                "light_chain": light_chain,
                "cdr_loops_shown": show_cdr_loops,
                "resolution": f"{width}x{height}",
                "size_bytes": size,
                "ray_traced": True,
            },
            source="pymol",
            source_id="render_antibody_complex",
        )
    except Exception as exc:
        return handle_error("render_antibody_complex", exc)


@mcp.tool()
async def highlight_residues(
    pdb_id: str,
    residues: list[dict[str, str]],
    style: str = "cartoon_rainbow",
    width: int = 1200,
    height: int = 900,
) -> dict[str, Any]:
    """Highlight specific residues on a protein structure.

    *residues*: list of ``{"chain": "A", "resi": "67", "color": "red",
    "label": "K67N"}``

    Highlighted residues are shown as sticks overlaid on the base style.
    An optional *label* is displayed next to the residue.
    """
    try:
        style_key = style.lower()
        base_cmds = STYLE_PRESETS.get(style_key, STYLE_PRESETS["cartoon_rainbow"])

        extra: list[tuple[str, ...]] = []
        for res in residues:
            chain = res.get("chain", "A")
            resi = res["resi"]
            color = res.get("color", "red")
            label = res.get("label", "")
            sele = f"chain {chain} and resi {resi}"
            extra.append(("show", "sticks", sele))
            extra.append(("color", color, sele))
            extra.append(("set", "stick_radius", "0.18", sele))
            if label:
                extra.append(("label", f"{sele} and name CA", f"'{label}'"))

        filename = f"pymol_{pdb_id}_highlights.png"
        result = await _render_structure(
            pdb_id=pdb_id,
            filename=filename,
            style_commands=list(base_cmds),
            extra_commands=extra,
            width=width,
            height=height,
        )
        result["highlighted_residues"] = residues
        result["base_style"] = style_key

        return standard_response(
            summary=f"Highlighted {len(residues)} residues on {pdb_id}",
            raw_data=result,
            source="pymol",
            source_id="highlight_residues",
        )
    except Exception as exc:
        return handle_error("highlight_residues", exc)


@mcp.tool()
async def render_mutation_sites(
    pdb_id: str,
    mutations: list[dict[str, str]],
    width: int = 1200,
    height: int = 900,
) -> dict[str, Any]:
    """Render a protein with mutation sites highlighted and labeled.

    *mutations*: list of ``{"chain": "A", "resi": "67", "wt": "K", "mut": "N"}``

    Wild-type positions are shown in blue sticks; the mutation label
    (e.g. ``K67N``) is displayed at the alpha-carbon.
    """
    try:
        residues_to_highlight = []
        for m in mutations:
            wt = m.get("wt", "?")
            mut = m.get("mut", "?")
            resi = m["resi"]
            label = f"{wt}{resi}{mut}"
            residues_to_highlight.append({
                "chain": m.get("chain", "A"),
                "resi": resi,
                "color": "firebrick",
                "label": label,
            })

        base_cmds = list(STYLE_PRESETS["chain_color"])
        extra: list[tuple[str, ...]] = []
        for res in residues_to_highlight:
            chain = res["chain"]
            resi = res["resi"]
            sele = f"chain {chain} and resi {resi}"
            extra.append(("show", "sticks", sele))
            extra.append(("show", "spheres", f"{sele} and name CA"))
            extra.append(("color", "firebrick", sele))
            extra.append(("set", "stick_radius", "0.18", sele))
            extra.append(("set", "sphere_scale", "0.35", f"{sele} and name CA"))
            extra.append(("label", f"{sele} and name CA", f"'{res['label']}'"))

        extra.append(("set", "label_color", "black"))
        extra.append(("set", "label_size", "14"))
        extra.append(("set", "label_position", "(0, 2, 0)"))

        filename = f"pymol_{pdb_id}_mutations.png"
        result = await _render_structure(
            pdb_id=pdb_id,
            filename=filename,
            style_commands=base_cmds,
            extra_commands=extra,
            width=width,
            height=height,
        )
        result["mutations"] = mutations

        return standard_response(
            summary=f"Mutation map of {pdb_id}: {len(mutations)} sites",
            raw_data=result,
            source="pymol",
            source_id="render_mutation_sites",
        )
    except Exception as exc:
        return handle_error("render_mutation_sites", exc)


@mcp.tool()
async def measure_distance(
    pdb_id: str,
    atom1: str,
    atom2: str,
    width: int = 1200,
    height: int = 900,
) -> dict[str, Any]:
    """Measure and visualize the distance between two atoms.

    *atom1*, *atom2*: PyMOL selection strings identifying single atoms,
    e.g. ``"chain A and resi 67 and name CA"``

    Returns the distance in angstroms and a rendered image with the
    measurement dashed line.
    """
    try:
        async with _pymol_render_lock:
            cmd = await _get_pymol()

            def _do_measure():
                cmd.reinitialize()
                cmd.fetch(pdb_id, async_=0)

                cmd.hide("everything", "all")
                cmd.show("cartoon", "all")
                cmd.color("grey70", "all")
                cmd.set("cartoon_transparency", "0.5")

                # Show atoms being measured
                for sele in [atom1, atom2]:
                    cmd.show("sticks", sele)
                    cmd.show("spheres", sele)
                    cmd.util.cbaw(sele)

                cmd.set("stick_radius", "0.15")
                cmd.set("sphere_scale", "0.25")

                dist_val = cmd.distance("dist_measure", atom1, atom2)

                cmd.set("dash_color", "firebrick", "dist_measure")
                cmd.set("dash_width", "3.0", "dist_measure")

                cmd.zoom(f"({atom1}) or ({atom2})", 8)
                cmd.bg_color("white")

                filepath = os.path.join(_OUTPUT_DIR, f"pymol_{pdb_id}_distance.png")
                cmd.ray(width, height)
                cmd.png(filepath, width=width, height=height, dpi=300, quiet=1)
                return filepath, float(dist_val)

            filepath, distance = await _run_pymol(_do_measure)

        size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
        return standard_response(
            summary=f"Distance in {pdb_id}: {distance:.2f} A between selections",
            raw_data={
                "file_path": filepath,
                "image_url": None,
                "pdb_id": pdb_id,
                "atom1": atom1,
                "atom2": atom2,
                "distance_angstrom": round(distance, 3),
                "resolution": f"{width}x{height}",
                "size_bytes": size,
                "ray_traced": True,
            },
            source="pymol",
            source_id="measure_distance",
        )
    except Exception as exc:
        return handle_error("measure_distance", exc)


@mcp.tool()
async def generate_structure_movie(
    pdb_id: str,
    frames: int = 36,
    axis: str = "y",
    style: str = "publication",
    width: int = 800,
    height: int = 600,
) -> dict[str, Any]:
    """Generate a rotation movie as a sequence of PNG frames.

    Produces *frames* images rotating around *axis* (``"x"``, ``"y"``, or
    ``"z"``), suitable for assembling into a GIF or video.

    Returns a list of file paths for the generated frames.
    """
    try:
        if axis not in ("x", "y", "z"):
            return handle_error("generate_structure_movie", f"axis must be 'x', 'y', or 'z', got '{axis}'")

        style_key = style.lower()
        base_cmds = STYLE_PRESETS.get(style_key, STYLE_PRESETS["publication"])
        angle_per_frame = 360.0 / frames

        async with _pymol_render_lock:
            cmd = await _get_pymol()

            def _do_movie():
                cmd.reinitialize()
                cmd.fetch(pdb_id, async_=0)

                for instruction in base_cmds:
                    method_name = instruction[0]
                    args = instruction[1:] if len(instruction) > 1 else ()
                    if method_name.startswith("util."):
                        cmd.do(f"{method_name} {' '.join(str(a) for a in args)}".strip())
                    elif method_name == "bg_color":
                        cmd.bg_color(*args)
                    elif hasattr(cmd, method_name):
                        getattr(cmd, method_name)(*args)

                frame_paths = []
                for i in range(frames):
                    filepath = os.path.join(_OUTPUT_DIR, f"pymol_{pdb_id}_frame_{i:04d}.png")
                    cmd.ray(width, height)
                    cmd.png(filepath, width=width, height=height, dpi=150, quiet=1)
                    frame_paths.append(filepath)
                    cmd.turn(axis, angle_per_frame)

                return frame_paths

            frame_paths = await _run_pymol(_do_movie)

        return standard_response(
            summary=f"Rotation movie of {pdb_id}: {frames} frames around {axis}-axis",
            raw_data={
                "frame_paths": frame_paths,
                "pdb_id": pdb_id,
                "frame_count": frames,
                "axis": axis,
                "style": style_key,
                "resolution": f"{width}x{height}",
            },
            source="pymol",
            source_id="generate_structure_movie",
        )
    except Exception as exc:
        return handle_error("generate_structure_movie", exc)


@mcp.tool()
async def fetch_pdb_info(
    pdb_id: str,
) -> dict[str, Any]:
    """Fetch and return metadata about a PDB structure.

    Loads the structure into PyMOL and extracts: chain count, residue count,
    atom count, resolution, space group, and sequence per chain.
    """
    try:
        async with _pymol_render_lock:
            cmd = await _get_pymol()

            def _do_info():
                cmd.reinitialize()
                cmd.fetch(pdb_id, async_=0)

                chains = cmd.get_chains(pdb_id)
                n_atoms = cmd.count_atoms("all")
                n_residues = cmd.count_atoms("name CA")

                sequences = {}
                for ch in chains:
                    seq = cmd.get_fastastr(f"chain {ch}")
                    sequences[ch] = seq.strip()

                info = {
                    "pdb_id": pdb_id,
                    "chains": chains,
                    "chain_count": len(chains),
                    "atom_count": n_atoms,
                    "residue_count": n_residues,
                    "sequences": sequences,
                }
                return info

            info = await _run_pymol(_do_info)

        return standard_response(
            summary=f"PDB {pdb_id}: {info['chain_count']} chains, {info['residue_count']} residues, {info['atom_count']} atoms",
            raw_data=info,
            source="pymol",
            source_id="fetch_pdb_info",
        )
    except Exception as exc:
        return handle_error("fetch_pdb_info", exc)


# ---------------------------------------------------------------------------
# Standalone server entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
