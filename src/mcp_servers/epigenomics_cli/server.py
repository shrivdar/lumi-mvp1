"""
Epigenomics CLI MCP Server — Lumi Virtual Lab

Wraps CLI tools for epigenomic analysis:
  MACS2 (peak calling, bedGraph comparison) and HOMER (motif finding, peak annotation).

Start with:  python -m src.mcp_servers.epigenomics_cli.server
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

from fastmcp import FastMCP

try:
    from src.mcp_servers.base import handle_error, standard_response
except ImportError:
    from mcp_servers.base import handle_error, standard_response  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi Epigenomics CLI",
    instructions="CLI epigenomics tools: MACS2 peak calling/bedGraph comparison, HOMER motif finding/peak annotation",
)


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


async def _run_cmd(cmd: list[str], timeout: float = 120.0) -> tuple[str, str, int]:
    """Run a command and return (stdout, stderr, returncode)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"Command timed out after {timeout}s: {' '.join(cmd)}")
    return stdout.decode(), stderr.decode(), proc.returncode


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def macs2_callpeak(
    treatment: str,
    control: str | None = None,
    name: str = "macs2_peaks",
    genome_size: str = "hs",
    qvalue: float = 0.05,
    outdir: str = ".",
) -> dict[str, Any]:
    """
    Call peaks from ChIP-seq or ATAC-seq data using MACS2.

    Args:
        treatment: Path to treatment BAM/BED file.
        control: Optional path to control/input BAM/BED file.
        name: Name prefix for output files.
        genome_size: Effective genome size — 'hs' (human), 'mm' (mouse), 'ce', 'dm', or a number.
        qvalue: Q-value (FDR) cutoff for peak calling.
        outdir: Output directory for results.
    """
    try:
        if not shutil.which("macs2"):
            return handle_error("macs2_callpeak", "macs2 binary not found in PATH")

        cmd = [
            "macs2", "callpeak",
            "-t", treatment,
            "-n", name,
            "-g", genome_size,
            "-q", str(qvalue),
            "--outdir", outdir,
        ]
        if control:
            cmd.extend(["-c", control])

        stdout, stderr, rc = await _run_cmd(cmd, timeout=600.0)

        if rc != 0:
            return handle_error("macs2_callpeak", f"MACS2 callpeak exited with code {rc}: {stderr[:2000]}")

        # Try to count peaks from narrowPeak file
        peak_count = 0
        peak_file = f"{outdir}/{name}_peaks.narrowPeak"
        try:
            with open(peak_file) as fh:
                peak_count = sum(1 for line in fh if line.strip())
        except FileNotFoundError:
            pass

        return standard_response(
            summary=f"MACS2 called {peak_count} peaks from {treatment} (q < {qvalue}, genome={genome_size})",
            raw_data={
                "peak_count": peak_count,
                "peak_file": peak_file,
                "output_dir": outdir,
                "name": name,
                "stderr": stderr[:2000],
            },
            source="MACS2",
            source_id=treatment,
            confidence=0.90,
        )
    except Exception as exc:
        return handle_error("macs2_callpeak", exc)


@mcp.tool()
async def macs2_bdgcmp(
    treatment_bdg: str,
    control_bdg: str,
    method: str = "ppois",
    output: str = "macs2_bdgcmp.bdg",
) -> dict[str, Any]:
    """
    Compare two bedGraph files using MACS2 bdgcmp (e.g. treatment vs control signal).

    Args:
        treatment_bdg: Path to treatment bedGraph file.
        control_bdg: Path to control bedGraph file.
        method: Comparison method — 'ppois', 'qpois', 'subtract', 'logFE', 'FE', 'logLR', 'slogLR'.
        output: Path for the output bedGraph file.
    """
    try:
        if not shutil.which("macs2"):
            return handle_error("macs2_bdgcmp", "macs2 binary not found in PATH")

        cmd = [
            "macs2", "bdgcmp",
            "-t", treatment_bdg,
            "-c", control_bdg,
            "-m", method,
            "-o", output,
        ]

        stdout, stderr, rc = await _run_cmd(cmd, timeout=300.0)

        if rc != 0:
            return handle_error("macs2_bdgcmp", f"MACS2 bdgcmp exited with code {rc}: {stderr[:2000]}")

        return standard_response(
            summary=f"MACS2 bdgcmp completed: {treatment_bdg} vs {control_bdg}, method={method}, output: {output}",
            raw_data={"output_file": output, "method": method, "stderr": stderr[:2000]},
            source="MACS2",
            source_id=treatment_bdg,
            confidence=0.90,
        )
    except Exception as exc:
        return handle_error("macs2_bdgcmp", exc)


@mcp.tool()
async def homer_find_motifs(
    target_file: str,
    genome: str = "hg38",
    output_dir: str = "homer_motifs",
    size: int = 200,
) -> dict[str, Any]:
    """
    Find enriched motifs in genomic regions using HOMER findMotifsGenome.pl.

    Args:
        target_file: Path to BED file with target regions.
        genome: Reference genome (e.g. 'hg38', 'mm10').
        output_dir: Directory for HOMER output.
        size: Size of region around peak center to use for motif finding.
    """
    try:
        if not shutil.which("findMotifsGenome.pl"):
            return handle_error("homer_find_motifs", "findMotifsGenome.pl not found in PATH")

        cmd = [
            "findMotifsGenome.pl",
            target_file, genome, output_dir,
            "-size", str(size),
        ]

        stdout, stderr, rc = await _run_cmd(cmd, timeout=1200.0)

        if rc != 0:
            return handle_error("homer_find_motifs", f"HOMER findMotifsGenome.pl exited with code {rc}: {stderr[:2000]}")

        # Try to summarize known motif results
        known_motifs: list[dict[str, str]] = []
        try:
            with open(f"{output_dir}/knownResults.txt") as fh:
                fh.readline()  # skip header
                for line in fh:
                    parts = line.strip().split("\t")
                    if len(parts) >= 4:
                        known_motifs.append({
                            "motif": parts[0],
                            "p_value": parts[2],
                            "pct_target": parts[5] if len(parts) > 5 else "N/A",
                        })
        except FileNotFoundError:
            pass

        return standard_response(
            summary=f"HOMER found {len(known_motifs)} known enriched motifs in {target_file} (genome={genome})",
            raw_data={
                "output_dir": output_dir,
                "known_motifs_count": len(known_motifs),
                "top_motifs": known_motifs[:20],
                "stderr": stderr[:2000],
            },
            source="HOMER",
            source_id=target_file,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("homer_find_motifs", exc)


@mcp.tool()
async def homer_annotate_peaks(
    peak_file: str,
    genome: str = "hg38",
) -> dict[str, Any]:
    """
    Annotate peaks with genomic features using HOMER annotatePeaks.pl.

    Args:
        peak_file: Path to peak file (BED or HOMER peak format).
        genome: Reference genome (e.g. 'hg38', 'mm10').
    """
    try:
        if not shutil.which("annotatePeaks.pl"):
            return handle_error("homer_annotate_peaks", "annotatePeaks.pl not found in PATH")

        cmd = ["annotatePeaks.pl", peak_file, genome]

        stdout, stderr, rc = await _run_cmd(cmd, timeout=600.0)

        if rc != 0:
            return handle_error(
                "homer_annotate_peaks", f"HOMER annotatePeaks.pl exited with code {rc}: {stderr[:2000]}"
            )

        # Parse annotation counts by feature type
        lines = stdout.strip().split("\n")
        feature_counts: dict[str, int] = {}
        for line in lines[1:]:  # skip header
            parts = line.split("\t")
            if len(parts) >= 8:
                annotation = parts[7].split("(")[0].strip() if len(parts) > 7 else "unknown"
                feature_counts[annotation] = feature_counts.get(annotation, 0) + 1

        total_peaks = len(lines) - 1 if lines else 0
        feature_summary = ", ".join(f"{k}: {v}" for k, v in sorted(feature_counts.items(), key=lambda x: -x[1])[:10])

        return standard_response(
            summary=f"HOMER annotated {total_peaks} peaks in {peak_file}: {feature_summary}",
            raw_data={
                "total_peaks": total_peaks,
                "feature_counts": feature_counts,
                "output_head": lines[:20],
                "stderr": stderr[:2000],
            },
            source="HOMER",
            source_id=peak_file,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("homer_annotate_peaks", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
