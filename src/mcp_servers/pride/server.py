"""
PRIDE Archive MCP Server — Lumi Virtual Lab

Exposes tools for querying the PRIDE proteomics repository:
  project search, project details, project files.

Start with:  python -m src.mcp_servers.pride.server
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

# Relative import when running inside the package; fall back for direct exec.
try:
    from src.mcp_servers.base import async_http_get, handle_error, standard_response
except ImportError:
    from mcp_servers.base import async_http_get, handle_error, standard_response  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRIDE_API = "https://www.ebi.ac.uk/pride/ws/archive/v2"

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi PRIDE",
    instructions="PRIDE Archive queries: proteomics project search, project details, and project files",
)


# ---- 1. Search projects ----------------------------------------------------


@mcp.tool()
async def pride_search_projects(query: str, page_size: int = 20) -> dict[str, Any]:
    """
    Search the PRIDE Archive for proteomics projects.

    Args:
        query: Search keyword (e.g. 'phosphoproteomics', 'breast cancer', 'BRCA1').
        page_size: Number of results per page (default 20).
    """
    try:
        url = f"{PRIDE_API}/search/projects"
        params: dict[str, Any] = {"keyword": query, "pageSize": page_size}

        data = await async_http_get(url, params=params)

        # PRIDE returns _embedded.compactprojects or similar
        projects = []
        if isinstance(data, dict):
            projects = data.get("_embedded", {}).get("compactprojects", [])
            if not projects:
                projects = data.get("_embedded", {}).get("projects", [])
            if not projects and isinstance(data.get("data"), list):
                projects = data["data"]

        summaries = []
        for proj in projects[:10]:
            accession = proj.get("accession", "N/A")
            title = proj.get("title", "Untitled")
            summaries.append(f"{accession}: {title[:80]}")

        total = data.get("page", {}).get("totalElements", len(projects)) if isinstance(data, dict) else len(projects)

        summary = (
            f"PRIDE search '{query}': {total} projects found. "
            f"Top hits: {'; '.join(summaries[:5])}"
            if projects
            else f"No PRIDE projects found for '{query}'."
        )

        return standard_response(
            summary=summary,
            raw_data={"total": total, "projects": projects},
            source="PRIDE Archive",
            source_id=query,
            confidence=0.8,
        )
    except Exception as exc:
        return handle_error("pride_search_projects", exc)


# ---- 2. Get project details -------------------------------------------------


@mcp.tool()
async def pride_get_project(accession: str) -> dict[str, Any]:
    """
    Get detailed information about a PRIDE project by its accession number.

    Args:
        accession: PRIDE project accession (e.g. 'PXD000001').
    """
    try:
        url = f"{PRIDE_API}/projects/{accession}"

        data = await async_http_get(url, params=None)

        title = data.get("title", "Untitled")
        data.get("projectDescription", "No description available.")
        data.get("sampleProcessingProtocol", "N/A")
        submission_type = data.get("submissionType", "N/A")
        organisms = data.get("organisms", [])
        data.get("instruments", [])
        pub_date = data.get("publicationDate", "N/A")
        references = data.get("references", [])

        organism_names = []
        for org in organisms[:5]:
            if isinstance(org, dict):
                organism_names.append(org.get("name", str(org)))
            else:
                organism_names.append(str(org))

        summary = (
            f"PRIDE {accession}: {title}. "
            f"Organisms: {', '.join(organism_names) or 'N/A'}. "
            f"Submission type: {submission_type}. Published: {pub_date}. "
            f"References: {len(references)}."
        )

        return standard_response(
            summary=summary,
            raw_data=data,
            source="PRIDE Archive",
            source_id=accession,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("pride_get_project", exc)


# ---- 3. Get project files ---------------------------------------------------


@mcp.tool()
async def pride_get_project_files(accession: str) -> dict[str, Any]:
    """
    Get the list of files associated with a PRIDE project.

    Args:
        accession: PRIDE project accession (e.g. 'PXD000001').
    """
    try:
        url = f"{PRIDE_API}/projects/{accession}/files"

        data = await async_http_get(url, params=None)

        # Files may be in _embedded or directly as a list
        files = []
        if isinstance(data, list):
            files = data
        elif isinstance(data, dict):
            files = data.get("_embedded", {}).get("files", [])
            if not files and isinstance(data.get("data"), list):
                files = data["data"]

        file_summaries = []
        total_size = 0
        for f in files[:20]:
            fname = f.get("fileName", "unknown")
            fsize = f.get("fileSizeBytes", 0)
            ftype = f.get("fileCategory", {})
            if isinstance(ftype, dict):
                ftype = ftype.get("value", "unknown")
            file_summaries.append(f"{fname} ({ftype}, {fsize} bytes)")
            total_size += fsize if isinstance(fsize, (int, float)) else 0

        summary = (
            f"PRIDE {accession}: {len(files)} files, total size ~{total_size / (1024**3):.2f} GB. "
            f"Files: {'; '.join(file_summaries[:5])}"
            if files
            else f"No files found for PRIDE project {accession}."
        )

        return standard_response(
            summary=summary,
            raw_data={"file_count": len(files), "files": files},
            source="PRIDE Archive",
            source_id=accession,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("pride_get_project_files", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
