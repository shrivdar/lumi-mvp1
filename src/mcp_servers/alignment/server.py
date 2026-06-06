"""
Alignment MCP Server — Lumi Virtual Lab

Wraps CLI bioinformatics tools for sequence alignment:
  samtools (view, stats, index, depth) and BWA MEM.

Start with:  python -m src.mcp_servers.alignment.server
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
    "Lumi Alignment",
    instructions="CLI alignment tools: samtools view/stats/index/depth, BWA MEM",
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
async def samtools_view(
    input_file: str,
    region: str | None = None,
    flags: str | None = None,
) -> dict[str, Any]:
    """
    Run samtools view on a BAM/CRAM/SAM file.

    Args:
        input_file: Path to input BAM/CRAM/SAM file.
        region: Optional genomic region (e.g. 'chr1:1000-2000').
        flags: Optional samtools flags (e.g. '-f 4' for unmapped reads).
    """
    try:
        if not shutil.which("samtools"):
            return handle_error("samtools_view", "samtools binary not found in PATH")

        cmd = ["samtools", "view"]
        if flags:
            cmd.extend(flags.split())
        cmd.append(input_file)
        if region:
            cmd.append(region)

        stdout, stderr, rc = await _run_cmd(cmd)

        if rc != 0:
            return handle_error("samtools_view", f"samtools view exited with code {rc}: {stderr}")

        lines = stdout.strip().split("\n") if stdout.strip() else []
        summary = f"samtools view returned {len(lines)} alignment records from {input_file}"
        if region:
            summary += f" (region: {region})"

        return standard_response(
            summary=summary,
            raw_data={"record_count": len(lines), "output_head": lines[:50], "stderr": stderr},
            source="samtools view",
            source_id=input_file,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("samtools_view", exc)


@mcp.tool()
async def samtools_stats(input_file: str) -> dict[str, Any]:
    """
    Run samtools stats on a BAM/CRAM file to get alignment statistics.

    Args:
        input_file: Path to input BAM/CRAM file.
    """
    try:
        if not shutil.which("samtools"):
            return handle_error("samtools_stats", "samtools binary not found in PATH")

        cmd = ["samtools", "stats", input_file]
        stdout, stderr, rc = await _run_cmd(cmd)

        if rc != 0:
            return handle_error("samtools_stats", f"samtools stats exited with code {rc}: {stderr}")

        # Parse SN (Summary Numbers) lines
        sn_metrics: dict[str, str] = {}
        for line in stdout.split("\n"):
            if line.startswith("SN\t"):
                parts = line.split("\t")
                if len(parts) >= 3:
                    key = parts[1].rstrip(":")
                    sn_metrics[key] = parts[2]

        summary = (
            f"samtools stats on {input_file}: "
            f"raw total sequences={sn_metrics.get('raw total sequences', 'N/A')}, "
            f"reads mapped={sn_metrics.get('reads mapped', 'N/A')}, "
            f"error rate={sn_metrics.get('error rate', 'N/A')}"
        )

        return standard_response(
            summary=summary,
            raw_data={"summary_numbers": sn_metrics, "stderr": stderr},
            source="samtools stats",
            source_id=input_file,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("samtools_stats", exc)


@mcp.tool()
async def samtools_index(input_file: str) -> dict[str, Any]:
    """
    Index a BAM file using samtools index.

    Args:
        input_file: Path to a sorted BAM file.
    """
    try:
        if not shutil.which("samtools"):
            return handle_error("samtools_index", "samtools binary not found in PATH")

        cmd = ["samtools", "index", input_file]
        stdout, stderr, rc = await _run_cmd(cmd)

        if rc != 0:
            return handle_error("samtools_index", f"samtools index exited with code {rc}: {stderr}")

        index_path = f"{input_file}.bai"
        summary = f"Successfully indexed {input_file} -> {index_path}"

        return standard_response(
            summary=summary,
            raw_data={"input_file": input_file, "index_file": index_path, "stderr": stderr},
            source="samtools index",
            source_id=input_file,
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("samtools_index", exc)


@mcp.tool()
async def samtools_depth(
    input_file: str,
    region: str | None = None,
) -> dict[str, Any]:
    """
    Calculate read depth at each position using samtools depth.

    Args:
        input_file: Path to input BAM/CRAM file.
        region: Optional genomic region (e.g. 'chr1:1000-2000').
    """
    try:
        if not shutil.which("samtools"):
            return handle_error("samtools_depth", "samtools binary not found in PATH")

        cmd = ["samtools", "depth"]
        if region:
            cmd.extend(["-r", region])
        cmd.append(input_file)

        stdout, stderr, rc = await _run_cmd(cmd)

        if rc != 0:
            return handle_error("samtools_depth", f"samtools depth exited with code {rc}: {stderr}")

        lines = stdout.strip().split("\n") if stdout.strip() else []
        depths = []
        total_depth = 0
        for line in lines:
            parts = line.split("\t")
            if len(parts) >= 3:
                d = int(parts[2])
                total_depth += d
                depths.append(d)

        avg_depth = total_depth / len(depths) if depths else 0.0

        summary = (
            f"samtools depth on {input_file}: {len(lines)} positions, "
            f"average depth={avg_depth:.1f}"
        )
        if region:
            summary += f" (region: {region})"

        return standard_response(
            summary=summary,
            raw_data={
                "positions": len(lines),
                "average_depth": round(avg_depth, 2),
                "min_depth": min(depths) if depths else 0,
                "max_depth": max(depths) if depths else 0,
                "output_head": lines[:50],
                "stderr": stderr,
            },
            source="samtools depth",
            source_id=input_file,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("samtools_depth", exc)


@mcp.tool()
async def bwa_align(
    reference: str,
    reads_file: str,
    output_file: str | None = None,
) -> dict[str, Any]:
    """
    Run BWA MEM alignment of reads against a reference genome.

    Args:
        reference: Path to indexed reference FASTA.
        reads_file: Path to FASTQ reads file.
        output_file: Optional output SAM file path. If not provided, output is captured in memory.
    """
    try:
        if not shutil.which("bwa"):
            return handle_error("bwa_align", "bwa binary not found in PATH")

        cmd = ["bwa", "mem", reference, reads_file]
        stdout, stderr, rc = await _run_cmd(cmd, timeout=600.0)

        if rc != 0:
            return handle_error("bwa_align", f"bwa mem exited with code {rc}: {stderr}")

        if output_file:
            with open(output_file, "w") as f:
                f.write(stdout)

        alignment_lines = [ln for ln in stdout.split("\n") if ln and not ln.startswith("@")]
        header_lines = [ln for ln in stdout.split("\n") if ln.startswith("@")]

        summary = (
            f"BWA MEM aligned {reads_file} to {reference}: "
            f"{len(alignment_lines)} alignment records, {len(header_lines)} header lines"
        )
        if output_file:
            summary += f". Output written to {output_file}"

        return standard_response(
            summary=summary,
            raw_data={
                "alignment_count": len(alignment_lines),
                "header_count": len(header_lines),
                "output_file": output_file,
                "stderr_head": stderr[:2000],
            },
            source="bwa mem",
            source_id=reads_file,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("bwa_align", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
