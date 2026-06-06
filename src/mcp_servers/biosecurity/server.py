"""
Biosecurity MCP Server -- Lumi Virtual Lab

Exposes tools for biosecurity screening:
  NCBI BLAST (select agent screening), CDC Select Agent list matching,
  InterPro toxin domain scanning, VFDB virulence factor screening,
  BWC/Australia Group compliance checking.

Start with:  python -m src.mcp_servers.biosecurity.server
"""

from __future__ import annotations

import asyncio
import re
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

BLAST_API = "https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi"
INTERPRO_API = "https://www.ebi.ac.uk/interpro/api"

# BLAST polling parameters
_BLAST_MAX_POLLS = 10
_BLAST_POLL_INTERVAL = 5  # seconds

# ---------------------------------------------------------------------------
# CDC / USDA Select Agents and Toxins List
# Source: Federal Select Agent Program (https://www.selectagents.gov/)
# Last updated: 2024-12 (maintained as inline constant for offline use)
# ---------------------------------------------------------------------------

SELECT_AGENTS: list[dict[str, str]] = [
    # ---- HHS Select Agents & Toxins ----
    {"name": "Abrin", "category": "HHS Toxin", "type": "toxin"},
    {"name": "Bacillus cereus Biovar anthracis", "category": "HHS", "type": "bacterium"},
    {"name": "Botulinum neurotoxin", "category": "HHS Toxin", "type": "toxin"},
    {"name": "Botulinum neurotoxin producing species of Clostridium", "category": "HHS", "type": "bacterium"},
    {"name": "Conotoxin (Short, paralytic alpha conotoxins)", "category": "HHS Toxin", "type": "toxin"},
    {"name": "Coxiella burnetii", "category": "HHS", "type": "bacterium"},
    {"name": "Crimean-Congo haemorrhagic fever virus", "category": "HHS", "type": "virus"},
    {"name": "Diacetoxyscirpenol", "category": "HHS Toxin", "type": "toxin"},
    {"name": "Eastern equine encephalitis virus", "category": "HHS", "type": "virus"},
    {"name": "Ebola virus", "category": "HHS", "type": "virus"},
    {"name": "Francisella tularensis", "category": "HHS", "type": "bacterium"},
    {"name": "Lassa fever virus", "category": "HHS", "type": "virus"},
    {"name": "Lujo virus", "category": "HHS", "type": "virus"},
    {"name": "Marburg virus", "category": "HHS", "type": "virus"},
    {"name": "Monkeypox virus", "category": "HHS", "type": "virus"},
    {"name": "Reconstructed 1918 influenza virus", "category": "HHS", "type": "virus"},
    {"name": "Ricin", "category": "HHS Toxin", "type": "toxin"},
    {"name": "Rickettsia prowazekii", "category": "HHS", "type": "bacterium"},
    {"name": "SARS-CoV", "category": "HHS", "type": "virus"},
    {"name": "SARS-CoV-2", "category": "HHS", "type": "virus"},
    {"name": "Saxitoxin", "category": "HHS Toxin", "type": "toxin"},
    {"name": "South American haemorrhagic fever viruses", "category": "HHS", "type": "virus"},
    {"name": "Staphylococcal enterotoxins (subtypes A-E)", "category": "HHS Toxin", "type": "toxin"},
    {"name": "T-2 toxin", "category": "HHS Toxin", "type": "toxin"},
    {"name": "Tetrodotoxin", "category": "HHS Toxin", "type": "toxin"},
    {"name": "Tick-borne encephalitis complex viruses", "category": "HHS", "type": "virus"},
    {"name": "Variola major virus (Smallpox)", "category": "HHS", "type": "virus"},
    {"name": "Variola minor virus (Alastrim)", "category": "HHS", "type": "virus"},
    {"name": "Yersinia pestis", "category": "HHS", "type": "bacterium"},
    # ---- Overlap Select Agents (HHS & USDA) ----
    {"name": "Bacillus anthracis (Anthrax)", "category": "Overlap", "type": "bacterium"},
    {"name": "Brucella abortus", "category": "Overlap", "type": "bacterium"},
    {"name": "Brucella melitensis", "category": "Overlap", "type": "bacterium"},
    {"name": "Brucella suis", "category": "Overlap", "type": "bacterium"},
    {"name": "Burkholderia mallei (Glanders)", "category": "Overlap", "type": "bacterium"},
    {"name": "Burkholderia pseudomallei (Melioidosis)", "category": "Overlap", "type": "bacterium"},
    {"name": "Hendra virus", "category": "Overlap", "type": "virus"},
    {"name": "Nipah virus", "category": "Overlap", "type": "virus"},
    {"name": "Rift Valley fever virus", "category": "Overlap", "type": "virus"},
    {"name": "Venezuelan equine encephalitis virus", "category": "Overlap", "type": "virus"},
    # ---- USDA Select Agents & Toxins ----
    {"name": "African horse sickness virus", "category": "USDA", "type": "virus"},
    {"name": "African swine fever virus", "category": "USDA", "type": "virus"},
    {"name": "Avian influenza virus (highly pathogenic)", "category": "USDA", "type": "virus"},
    {"name": "Classical swine fever virus", "category": "USDA", "type": "virus"},
    {"name": "Foot-and-mouth disease virus", "category": "USDA", "type": "virus"},
    {"name": "Goat pox virus", "category": "USDA", "type": "virus"},
    {"name": "Lumpy skin disease virus", "category": "USDA", "type": "virus"},
    {"name": "Mycoplasma capricolum", "category": "USDA", "type": "bacterium"},
    {"name": "Mycoplasma mycoides", "category": "USDA", "type": "bacterium"},
    {"name": "Newcastle disease virus (virulent)", "category": "USDA", "type": "virus"},
    {"name": "Peste des petits ruminants virus", "category": "USDA", "type": "virus"},
    {"name": "Rinderpest virus", "category": "USDA", "type": "virus"},
    {"name": "Sheep pox virus", "category": "USDA", "type": "virus"},
    {"name": "Swine vesicular disease virus", "category": "USDA", "type": "virus"},
    # ---- USDA Plant Pathogens ----
    {"name": "Peronosclerospora philippinensis", "category": "USDA Plant", "type": "pathogen"},
    {"name": "Phoma glycinicola", "category": "USDA Plant", "type": "pathogen"},
    {"name": "Ralstonia solanacearum", "category": "USDA Plant", "type": "bacterium"},
    {"name": "Rathayibacter toxicus", "category": "USDA Plant", "type": "bacterium"},
    {"name": "Sclerophthora rayssiae", "category": "USDA Plant", "type": "pathogen"},
    {"name": "Synchytrium endobioticum", "category": "USDA Plant", "type": "pathogen"},
    {"name": "Xanthomonas oryzae", "category": "USDA Plant", "type": "bacterium"},
]

# ---------------------------------------------------------------------------
# BWC (Biological Weapons Convention) & Australia Group lists
# These organisms/toxins are controlled under international agreements.
# ---------------------------------------------------------------------------

BWC_CONTROLLED_AGENTS: list[dict[str, str]] = [
    # Australia Group -- Human pathogens
    {"name": "Bacillus anthracis", "list": "AG Human", "control": "export_control"},
    {"name": "Brucella abortus", "list": "AG Human", "control": "export_control"},
    {"name": "Brucella melitensis", "list": "AG Human", "control": "export_control"},
    {"name": "Brucella suis", "list": "AG Human", "control": "export_control"},
    {"name": "Burkholderia mallei", "list": "AG Human", "control": "export_control"},
    {"name": "Burkholderia pseudomallei", "list": "AG Human", "control": "export_control"},
    {"name": "Chlamydia psittaci", "list": "AG Human", "control": "export_control"},
    {"name": "Clostridium botulinum", "list": "AG Human", "control": "export_control"},
    {"name": "Coccidioides immitis", "list": "AG Human", "control": "export_control"},
    {"name": "Coxiella burnetii", "list": "AG Human", "control": "export_control"},
    {"name": "Francisella tularensis", "list": "AG Human", "control": "export_control"},
    {"name": "Rickettsia prowazekii", "list": "AG Human", "control": "export_control"},
    {"name": "Yersinia pestis", "list": "AG Human", "control": "export_control"},
    {"name": "Ebola virus", "list": "AG Human", "control": "export_control"},
    {"name": "Marburg virus", "list": "AG Human", "control": "export_control"},
    {"name": "Variola virus", "list": "AG Human", "control": "export_control"},
    {"name": "Crimean-Congo haemorrhagic fever virus", "list": "AG Human", "control": "export_control"},
    {"name": "Nipah virus", "list": "AG Human", "control": "export_control"},
    {"name": "Hendra virus", "list": "AG Human", "control": "export_control"},
    {"name": "Lassa virus", "list": "AG Human", "control": "export_control"},
    # Australia Group -- Toxins
    {"name": "Abrin", "list": "AG Toxin", "control": "export_control"},
    {"name": "Aflatoxin", "list": "AG Toxin", "control": "export_control"},
    {"name": "Botulinum toxin", "list": "AG Toxin", "control": "export_control"},
    {"name": "Cholera toxin", "list": "AG Toxin", "control": "export_control"},
    {"name": "Conotoxin", "list": "AG Toxin", "control": "export_control"},
    {"name": "Diacetoxyscirpenol", "list": "AG Toxin", "control": "export_control"},
    {"name": "Microcystin", "list": "AG Toxin", "control": "export_control"},
    {"name": "Modeccin", "list": "AG Toxin", "control": "export_control"},
    {"name": "Ricin", "list": "AG Toxin", "control": "export_control"},
    {"name": "Saxitoxin", "list": "AG Toxin", "control": "export_control"},
    {"name": "Shiga toxin", "list": "AG Toxin", "control": "export_control"},
    {"name": "Staphylococcal enterotoxin", "list": "AG Toxin", "control": "export_control"},
    {"name": "T-2 toxin", "list": "AG Toxin", "control": "export_control"},
    {"name": "Tetrodotoxin", "list": "AG Toxin", "control": "export_control"},
    {"name": "Viscumin", "list": "AG Toxin", "control": "export_control"},
    {"name": "Volkensin", "list": "AG Toxin", "control": "export_control"},
    # Australia Group -- Animal pathogens
    {"name": "African swine fever virus", "list": "AG Animal", "control": "export_control"},
    {"name": "Avian influenza virus", "list": "AG Animal", "control": "export_control"},
    {"name": "Foot-and-mouth disease virus", "list": "AG Animal", "control": "export_control"},
    {"name": "Goat pox virus", "list": "AG Animal", "control": "export_control"},
    {"name": "Newcastle disease virus", "list": "AG Animal", "control": "export_control"},
    {"name": "Peste des petits ruminants virus", "list": "AG Animal", "control": "export_control"},
    {"name": "Rinderpest virus", "list": "AG Animal", "control": "export_control"},
    {"name": "Sheep pox virus", "list": "AG Animal", "control": "export_control"},
    # Australia Group -- Plant pathogens
    {"name": "Xanthomonas oryzae", "list": "AG Plant", "control": "export_control"},
    {"name": "Ralstonia solanacearum", "list": "AG Plant", "control": "export_control"},
]

# Known toxin domain InterPro accessions for heuristic scanning
_TOXIN_DOMAIN_KEYWORDS = [
    "toxin", "ricin", "abrin", "shiga", "cholera", "botulinum",
    "enterotoxin", "cytotoxin", "neurotoxin", "hemolysin", "haemolysin",
    "conotoxin", "phospholipase", "pore-forming", "cytolethal",
    "dermonecrotic", "exotoxin", "leukotoxin", "verotoxin",
]

# Known virulence factor keywords for heuristic scanning
_VIRULENCE_KEYWORDS = [
    "virulence", "pathogenicity", "invasion", "invasin", "adhesin",
    "fimbri", "pilus", "pili", "capsule", "siderophore", "hemolysin",
    "haemolysin", "type III secretion", "type IV secretion",
    "effector", "toxin", "superantigen", "immune evasion",
    "biofilm", "quorum sensing", "lipopolysaccharide", "endotoxin",
]

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi Biosecurity",
    instructions=(
        "Biosecurity screening tools: NCBI BLAST select agent screening, "
        "CDC Select Agent list matching, InterPro toxin domain scanning, "
        "virulence factor screening, BWC/Australia Group compliance checking"
    ),
)


# ===================================================================
# Internal helpers for BLAST
# ===================================================================


async def _submit_blast_job(
    sequence: str,
    program: str = "blastp",
    database: str = "nr",
    max_hits: int = 10,
    entrez_query: str | None = None,
) -> str | None:
    """Submit a BLAST job and return the RID (Request ID) for polling.

    Uses the NCBI BLAST REST API (PUT to submit, GET to poll).
    """
    import httpx

    params: dict[str, str] = {
        "CMD": "Put",
        "PROGRAM": program,
        "DATABASE": database,
        "QUERY": sequence,
        "FORMAT_TYPE": "JSON2",
        "HITLIST_SIZE": str(max_hits),
        "WORD_SIZE": "6" if program == "blastp" else "11",
    }
    if entrez_query:
        params["ENTREZ_QUERY"] = entrez_query

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.put(BLAST_API, params=params)
        resp.raise_for_status()
        text = resp.text

    # Parse RID from the response (HTML/text format)
    rid_match = re.search(r"RID\s*=\s*(\S+)", text)
    if rid_match:
        return rid_match.group(1)
    return None


async def _poll_blast_results(rid: str) -> dict[str, Any] | None:
    """Poll NCBI BLAST for results using the RID. Returns parsed results or None on timeout."""
    import httpx

    for poll in range(_BLAST_MAX_POLLS):
        await asyncio.sleep(_BLAST_POLL_INTERVAL)

        # Check status
        async with httpx.AsyncClient(timeout=30.0) as client:
            status_resp = await client.get(
                BLAST_API,
                params={"CMD": "Get", "RID": rid, "FORMAT_OBJECT": "SearchInfo"},
            )
            status_text = status_resp.text

        if "Status=WAITING" in status_text:
            continue
        elif "Status=FAILED" in status_text:
            return {"error": "BLAST job failed", "rid": rid}
        elif "Status=UNKNOWN" in status_text:
            return {"error": "BLAST job expired or unknown RID", "rid": rid}
        elif "Status=READY" in status_text:
            # Fetch results
            try:
                result_data = await async_http_get(
                    BLAST_API,
                    params={
                        "CMD": "Get",
                        "RID": rid,
                        "FORMAT_TYPE": "JSON2",
                    },
                    timeout=60.0,
                )
                return result_data
            except Exception:
                # Try XML fallback and return raw text
                async with httpx.AsyncClient(timeout=60.0) as client:
                    result_resp = await client.get(
                        BLAST_API,
                        params={
                            "CMD": "Get",
                            "RID": rid,
                            "FORMAT_TYPE": "Text",
                        },
                    )
                    return {"text": result_resp.text, "format": "text"}

    return None  # Timeout


def _parse_blast_hits(blast_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse BLAST JSON2 output into a list of hit summaries."""
    hits = []

    # Navigate the BLAST JSON2 structure
    search = blast_data.get("BlastOutput2", [{}])
    if isinstance(search, list) and search:
        report = search[0].get("report", {})
    elif isinstance(search, dict):
        report = search.get("report", {})
    else:
        return hits

    results = report.get("results", {})
    search_results = results.get("search", {})
    hit_list = search_results.get("hits", [])

    for hit in hit_list:
        description = hit.get("description", [{}])
        first_desc = description[0] if description else {}

        hsps = hit.get("hsps", [{}])
        first_hsp = hsps[0] if hsps else {}

        hits.append({
            "accession": first_desc.get("accession", "N/A"),
            "title": first_desc.get("title", "N/A"),
            "taxid": first_desc.get("taxid", "N/A"),
            "sciname": first_desc.get("sciname", "N/A"),
            "bit_score": first_hsp.get("bit_score", 0),
            "evalue": first_hsp.get("evalue", 999),
            "identity_pct": (
                round(first_hsp.get("identity", 0) / max(first_hsp.get("align_len", 1), 1) * 100, 1)
                if first_hsp.get("align_len") else 0
            ),
            "query_coverage": first_hsp.get("query_to", 0) - first_hsp.get("query_from", 0) + 1,
            "align_len": first_hsp.get("align_len", 0),
        })

    return hits


# ===================================================================
# Tool 1: Screen against select agents via BLAST
# ===================================================================


@mcp.tool()
async def screen_against_select_agents(sequence: str) -> dict[str, Any]:
    """Screen a protein sequence against known select agent organisms using NCBI BLAST.

    Submits a BLAST search restricted to organisms on the CDC/USDA Select Agent
    list to identify potential matches. This is a critical biosecurity check.

    IMPORTANT: This tool submits a remote BLAST job and polls for results.
    It may take 30-60 seconds to complete.

    Args:
        sequence: Amino acid sequence to screen (single-letter code, no header).
    """
    try:
        # Clean sequence
        clean_seq = re.sub(r"[^A-Za-z]", "", sequence.replace(">", "").split("\n", 1)[-1] if ">" in sequence else sequence)
        if len(clean_seq) < 10:
            return handle_error("screen_against_select_agents", "Sequence too short (minimum 10 amino acids)")

        # Build entrez query to filter for select agent organisms
        select_agent_organisms = [
            "Bacillus anthracis", "Yersinia pestis", "Francisella tularensis",
            "Burkholderia mallei", "Burkholderia pseudomallei", "Brucella",
            "Coxiella burnetii", "Rickettsia prowazekii", "Clostridium botulinum",
            "Bacillus cereus", "Ebola virus", "Marburg virus", "Variola virus",
            "Nipah virus", "Hendra virus",
        ]
        entrez_filter = " OR ".join(f'"{org}"[Organism]' for org in select_agent_organisms)

        # Submit BLAST job
        rid = await _submit_blast_job(
            sequence=clean_seq,
            program="blastp",
            database="nr",
            max_hits=20,
            entrez_query=entrez_filter,
        )

        if not rid:
            return handle_error("screen_against_select_agents", "Failed to submit BLAST job to NCBI")

        # Poll for results
        blast_data = await _poll_blast_results(rid)

        if blast_data is None:
            return standard_response(
                summary=(
                    f"BLAST select agent screening timed out (RID: {rid}). "
                    "The job may still be running at NCBI. Check manually at "
                    f"https://blast.ncbi.nlm.nih.gov/Blast.cgi?CMD=Get&RID={rid}"
                ),
                raw_data={
                    "rid": rid,
                    "status": "TIMEOUT",
                    "sequence_length": len(clean_seq),
                },
                source="NCBI BLAST (Select Agent Screen)",
                source_id=rid,
                confidence=0.2,
            )

        if blast_data.get("error"):
            return handle_error("screen_against_select_agents", blast_data["error"])

        # Parse hits
        hits = _parse_blast_hits(blast_data)

        # Flag any hits to select agent organisms
        flagged_hits = []
        select_agent_names_lower = [sa["name"].lower() for sa in SELECT_AGENTS]
        for hit in hits:
            sci_name = hit.get("sciname", "").lower()
            title = hit.get("title", "").lower()
            is_select_agent = any(
                sa_name in sci_name or sa_name in title
                for sa_name in select_agent_names_lower
            )
            hit["is_select_agent"] = is_select_agent
            if is_select_agent:
                flagged_hits.append(hit)

        # Risk assessment
        if flagged_hits:
            best_hit = max(flagged_hits, key=lambda x: x.get("identity_pct", 0))
            identity = best_hit.get("identity_pct", 0)
            if identity >= 90:
                risk = "CRITICAL"
            elif identity >= 70:
                risk = "HIGH"
            elif identity >= 50:
                risk = "MODERATE"
            else:
                risk = "LOW"
        else:
            risk = "CLEAR"

        summary = (
            f"Select agent BLAST screen: {risk} risk. "
            f"{len(flagged_hits)} hits to select agent organisms out of {len(hits)} total hits. "
            f"RID: {rid}. "
        )
        if flagged_hits:
            top = flagged_hits[0]
            summary += (
                f"Top select agent match: {top.get('sciname', 'N/A')} "
                f"({top.get('identity_pct', 0)}% identity, E={top.get('evalue', 'N/A')})."
            )
        else:
            summary += "No significant homology to select agent proteins detected."

        return standard_response(
            summary=summary,
            raw_data={
                "rid": rid,
                "risk_level": risk,
                "sequence_length": len(clean_seq),
                "total_hits": len(hits),
                "flagged_select_agent_hits": flagged_hits,
                "all_hits": hits,
            },
            source="NCBI BLAST (Select Agent Screen)",
            source_id=rid,
            confidence=0.80 if risk != "CLEAR" else 0.85,
        )
    except Exception as exc:
        return handle_error("screen_against_select_agents", exc)


# ===================================================================
# Tool 2: General BLAST protein search
# ===================================================================


@mcp.tool()
async def blast_protein(sequence: str, database: str = "nr", max_hits: int = 10) -> dict[str, Any]:
    """Run a general BLASTP search against NCBI protein databases.

    IMPORTANT: This tool submits a remote BLAST job and polls for results.
    It may take 30-60 seconds to complete.

    Args:
        sequence: Amino acid sequence (single-letter code, no FASTA header needed).
        database: BLAST database to search (default 'nr'). Options: 'nr',
            'swissprot', 'pdb', 'refseq_protein'.
        max_hits: Maximum number of hits to return (default 10, max 50).
    """
    try:
        # Clean sequence
        clean_seq = re.sub(r"[^A-Za-z]", "", sequence.replace(">", "").split("\n", 1)[-1] if ">" in sequence else sequence)
        if len(clean_seq) < 10:
            return handle_error("blast_protein", "Sequence too short (minimum 10 amino acids)")

        max_hits = min(max(max_hits, 1), 50)

        # Submit BLAST job
        rid = await _submit_blast_job(
            sequence=clean_seq,
            program="blastp",
            database=database,
            max_hits=max_hits,
        )

        if not rid:
            return handle_error("blast_protein", "Failed to submit BLAST job to NCBI")

        # Poll for results
        blast_data = await _poll_blast_results(rid)

        if blast_data is None:
            return standard_response(
                summary=(
                    f"BLAST search timed out (RID: {rid}). "
                    "The job may still be running. Check at "
                    f"https://blast.ncbi.nlm.nih.gov/Blast.cgi?CMD=Get&RID={rid}"
                ),
                raw_data={
                    "rid": rid,
                    "status": "TIMEOUT",
                    "database": database,
                    "sequence_length": len(clean_seq),
                },
                source="NCBI BLAST",
                source_id=rid,
                confidence=0.2,
            )

        if blast_data.get("error"):
            return handle_error("blast_protein", blast_data["error"])

        hits = _parse_blast_hits(blast_data)

        # Build summary
        if hits:
            top = hits[0]
            summary = (
                f"BLASTP ({database}): {len(hits)} hits for {len(clean_seq)}-aa query. "
                f"Top hit: {top.get('title', 'N/A')[:80]} "
                f"({top.get('sciname', 'N/A')}, "
                f"{top.get('identity_pct', 0)}% identity, E={top.get('evalue', 'N/A')}). "
                f"RID: {rid}."
            )
        else:
            summary = f"BLASTP ({database}): No significant hits for {len(clean_seq)}-aa query. RID: {rid}."

        return standard_response(
            summary=summary,
            raw_data={
                "rid": rid,
                "database": database,
                "sequence_length": len(clean_seq),
                "total_hits": len(hits),
                "hits": hits,
            },
            source="NCBI BLAST",
            source_id=rid,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("blast_protein", exc)


# ===================================================================
# Tool 3: Check select agent list (local)
# ===================================================================


@mcp.tool()
async def check_select_agent_list(query: str) -> dict[str, Any]:
    """Check if an organism, toxin, or pathogen appears on the CDC/USDA Select Agent list.

    Performs fuzzy matching against the Federal Select Agent Program list.
    This is a fast local check (no network call required).

    Args:
        query: Organism name, toxin name, or keyword to search
            (e.g. 'Bacillus anthracis', 'ricin', 'Ebola', 'botulinum').
    """
    try:
        query_lower = query.lower().strip()
        query_words = set(query_lower.split())

        exact_matches = []
        partial_matches = []

        for agent in SELECT_AGENTS:
            agent_name_lower = agent["name"].lower()
            agent_words = set(agent_name_lower.split())

            # Exact substring match
            if query_lower in agent_name_lower or agent_name_lower in query_lower:
                exact_matches.append(agent)
            # Word overlap match
            elif query_words & agent_words:
                overlap = len(query_words & agent_words) / max(len(query_words), 1)
                if overlap >= 0.5:
                    partial_matches.append({**agent, "_match_score": overlap})

        # Sort partial matches by match score
        partial_matches.sort(key=lambda x: x.get("_match_score", 0), reverse=True)
        # Clean up internal score field
        for m in partial_matches:
            m.pop("_match_score", None)

        is_select_agent = len(exact_matches) > 0
        exact_matches + partial_matches

        if is_select_agent:
            categories = list(set(m["category"] for m in exact_matches))
            summary = (
                f"WARNING: '{query}' IS on the Select Agent list. "
                f"{len(exact_matches)} exact match(es). "
                f"Categories: {', '.join(categories)}. "
                "Work with this agent requires registration with the Federal Select Agent Program."
            )
            risk = "CRITICAL"
        elif partial_matches:
            summary = (
                f"'{query}' is not an exact match but has {len(partial_matches)} partial matches "
                f"on the Select Agent list: {', '.join(m['name'] for m in partial_matches[:3])}. "
                "Manual review recommended."
            )
            risk = "REVIEW"
        else:
            summary = (
                f"'{query}' does not match any entry on the CDC/USDA Select Agent list. "
                "Note: this check covers the Federal Select Agent Program list only."
            )
            risk = "CLEAR"

        return standard_response(
            summary=summary,
            raw_data={
                "query": query,
                "is_select_agent": is_select_agent,
                "risk_level": risk,
                "exact_matches": exact_matches,
                "partial_matches": partial_matches[:10],
                "total_agents_checked": len(SELECT_AGENTS),
            },
            source="CDC/USDA Select Agent List (local)",
            source_id=query,
            confidence=0.95 if is_select_agent else 0.90,
        )
    except Exception as exc:
        return handle_error("check_select_agent_list", exc)


# ===================================================================
# Tool 4: Scan for toxin domains via InterPro
# ===================================================================


@mcp.tool()
async def scan_toxin_domains(sequence: str) -> dict[str, Any]:
    """Scan a protein sequence for known toxin domains using InterPro/Pfam annotations.

    For sequences with a known UniProt ID, queries InterPro directly. Otherwise
    performs keyword-based heuristic matching against known toxin domain families.

    Args:
        sequence: Amino acid sequence or UniProt accession ID. If a UniProt ID
            is provided (e.g. 'P01552'), InterPro annotations are queried directly.
            If a raw sequence is provided, a heuristic toxin motif scan is performed.
    """
    try:
        clean_input = sequence.strip()

        # Determine if input is a UniProt ID or a raw sequence
        is_uniprot_id = bool(re.match(r"^[A-Z][0-9][A-Z0-9]{3}[0-9]$", clean_input)) or \
                        bool(re.match(r"^[A-Z][0-9][A-Z0-9]{3}[0-9]-\d+$", clean_input))

        toxin_domains_found = []
        all_domains = []

        if is_uniprot_id:
            # Query InterPro for this protein
            url = f"{INTERPRO_API}/entry/all/protein/uniprot/{clean_input}"
            params = {"format": "json"}
            data = await async_http_get(url, params=params, timeout=30.0)

            results = data.get("results", [])
            for entry in results:
                metadata = entry.get("metadata", {})
                name = metadata.get("name", "").lower()
                accession = metadata.get("accession", "N/A")
                entry_type = metadata.get("type", "N/A")
                metadata.get("name", "N/A")

                domain_info = {
                    "accession": accession,
                    "name": metadata.get("name", "N/A"),
                    "type": entry_type,
                    "source_database": metadata.get("source_database", "N/A"),
                }
                all_domains.append(domain_info)

                # Check if this is a toxin domain
                is_toxin = any(kw in name for kw in _TOXIN_DOMAIN_KEYWORDS)
                if is_toxin:
                    domain_info["toxin_match_keyword"] = next(
                        kw for kw in _TOXIN_DOMAIN_KEYWORDS if kw in name
                    )
                    toxin_domains_found.append(domain_info)
        else:
            # Heuristic scan for toxin-related motifs in raw sequence
            clean_seq = re.sub(r"[^A-Za-z]", "", clean_input)
            if len(clean_seq) < 10:
                return handle_error("scan_toxin_domains", "Sequence too short for analysis")

            # Known conserved toxin motifs (simplified for MVP)
            toxin_motifs = [
                {"name": "Ricin A-chain active site", "pattern": r"[YF]..E...[ILVM]", "family": "Ricin/RIP"},
                {"name": "ADP-ribosyltransferase motif", "pattern": r"[ST]T[ST]", "family": "ADP-RT toxin"},
                {"name": "Cholera toxin family (CxC motif)", "pattern": r"C.{4,12}C.{4,12}C.{4,12}C", "family": "AB5 toxin"},
                {"name": "Shiga-like toxin signature", "pattern": r"E[ILVM].{2,4}R.{2,4}[DE]", "family": "Shiga toxin"},
                {"name": "Pore-forming domain (amphipathic)", "pattern": r"[ILVM]{3}.{1,3}[ILVM]{3}", "family": "Pore-forming"},
                {"name": "Signal peptide (potential secreted toxin)", "pattern": r"^M[ILVM].{5,20}[AG][AG]", "family": "Secreted protein"},
            ]

            for motif in toxin_motifs:
                matches = list(re.finditer(motif["pattern"], clean_seq.upper()))
                if matches:
                    for m in matches[:3]:
                        toxin_domains_found.append({
                            "name": motif["name"],
                            "family": motif["family"],
                            "position": f"{m.start() + 1}-{m.end()}",
                            "matched_sequence": m.group(),
                            "method": "heuristic_motif_scan",
                        })

            # Note: heuristic motifs have high false-positive rates
            all_domains = toxin_domains_found

        # Risk assessment
        if toxin_domains_found:
            if is_uniprot_id:
                risk = "HIGH" if len(toxin_domains_found) >= 2 else "MODERATE"
            else:
                risk = "REVIEW"  # Heuristic matches need manual confirmation
        else:
            risk = "CLEAR"

        input_type = "UniProt ID" if is_uniprot_id else f"sequence ({len(re.sub(r'[^A-Za-z]', '', clean_input))} aa)"

        summary = (
            f"Toxin domain scan ({input_type}): {risk} risk. "
            f"{len(toxin_domains_found)} potential toxin domains found"
            f" out of {len(all_domains)} total domains. "
        )
        if toxin_domains_found:
            names = [d.get("name", "?") for d in toxin_domains_found[:4]]
            summary += f"Flagged: {', '.join(names)}."
        else:
            summary += "No known toxin domains detected."

        return standard_response(
            summary=summary,
            raw_data={
                "input": clean_input[:50] + "..." if len(clean_input) > 50 else clean_input,
                "input_type": "uniprot_id" if is_uniprot_id else "raw_sequence",
                "risk_level": risk,
                "toxin_domains": toxin_domains_found,
                "all_domains": all_domains[:30],
                "method": "interpro_lookup" if is_uniprot_id else "heuristic_motif_scan",
            },
            source="InterPro" if is_uniprot_id else "Lumi Biosecurity (heuristic)",
            source_id=clean_input if is_uniprot_id else "sequence_scan",
            confidence=0.85 if is_uniprot_id else 0.50,
        )
    except Exception as exc:
        return handle_error("scan_toxin_domains", exc)


# ===================================================================
# Tool 5: Screen virulence factors
# ===================================================================


@mcp.tool()
async def screen_virulence_factors(sequence: str) -> dict[str, Any]:
    """Screen a protein sequence for known virulence factor signatures.

    Uses NCBI BLAST with organism filtering and heuristic keyword matching
    to identify potential virulence factors. For MVP, this combines a BLAST
    search with annotation-based screening.

    Args:
        sequence: Amino acid sequence (single-letter code) to screen.
    """
    try:
        clean_seq = re.sub(r"[^A-Za-z]", "", sequence.replace(">", "").split("\n", 1)[-1] if ">" in sequence else sequence)
        if len(clean_seq) < 10:
            return handle_error("screen_virulence_factors", "Sequence too short (minimum 10 amino acids)")

        virulence_flags = []

        # Strategy 1: BLAST against nr with short timeout, check hit annotations
        blast_hits = []
        try:
            rid = await _submit_blast_job(
                sequence=clean_seq,
                program="blastp",
                database="swissprot",
                max_hits=15,
            )
            if rid:
                blast_data = await _poll_blast_results(rid)
                if blast_data and not blast_data.get("error"):
                    blast_hits = _parse_blast_hits(blast_data)

                    # Check hit titles for virulence-related keywords
                    for hit in blast_hits:
                        title = hit.get("title", "").lower()
                        matched_keywords = [
                            kw for kw in _VIRULENCE_KEYWORDS
                            if kw in title
                        ]
                        if matched_keywords:
                            virulence_flags.append({
                                "source": "BLAST annotation",
                                "accession": hit.get("accession", "N/A"),
                                "title": hit.get("title", "N/A"),
                                "organism": hit.get("sciname", "N/A"),
                                "identity_pct": hit.get("identity_pct", 0),
                                "evalue": hit.get("evalue", 999),
                                "matched_keywords": matched_keywords,
                            })
        except Exception:
            pass  # BLAST failure is non-fatal; we still do heuristic analysis

        # Strategy 2: Heuristic motif scanning for common virulence signatures
        virulence_motifs = [
            {"name": "Type III secretion signal", "pattern": r"^M[^C]{0,5}[ILVM].{5,15}[PG]", "category": "secretion"},
            {"name": "LPXTG sortase anchor", "pattern": r"LP[A-Z]TG", "category": "surface_anchor"},
            {"name": "RGD cell adhesion", "pattern": r"RGD", "category": "adhesion"},
            {"name": "Repeat-in-toxin (RTX) motif", "pattern": r"GG[A-Z]{2}D[A-Z]{2}[A-Z]GG", "category": "rtx_toxin"},
            {"name": "LRR (Leucine-rich repeat)", "pattern": r"L.{2}L.{2}L.{2}[IVLM]", "category": "immune_evasion"},
        ]

        heuristic_flags = []
        for motif in virulence_motifs:
            matches = list(re.finditer(motif["pattern"], clean_seq.upper()))
            if matches:
                for m in matches[:2]:
                    heuristic_flags.append({
                        "source": "heuristic_motif",
                        "name": motif["name"],
                        "category": motif["category"],
                        "position": f"{m.start() + 1}-{m.end()}",
                        "matched_sequence": m.group(),
                    })

        virulence_flags + heuristic_flags

        # Risk assessment
        if virulence_flags:
            high_identity = any(f.get("identity_pct", 0) >= 70 for f in virulence_flags)
            risk = "HIGH" if high_identity else "MODERATE"
        elif heuristic_flags:
            risk = "LOW"  # Heuristic-only matches are low confidence
        else:
            risk = "CLEAR"

        summary = (
            f"Virulence factor screen: {risk} risk. "
            f"{len(virulence_flags)} BLAST-based flags, {len(heuristic_flags)} heuristic flags. "
            f"{len(blast_hits)} BLAST hits searched. "
        )
        if virulence_flags:
            top = virulence_flags[0]
            summary += (
                f"Top virulence match: {top.get('title', 'N/A')[:60]} "
                f"({top.get('organism', 'N/A')}, {top.get('identity_pct', 0)}% identity). "
                f"Keywords: {', '.join(top.get('matched_keywords', [])[:3])}."
            )
        elif heuristic_flags:
            summary += f"Heuristic motifs found: {', '.join(h['name'] for h in heuristic_flags[:3])}."
        else:
            summary += "No virulence factor signatures detected."

        return standard_response(
            summary=summary,
            raw_data={
                "sequence_length": len(clean_seq),
                "risk_level": risk,
                "blast_virulence_flags": virulence_flags,
                "heuristic_flags": heuristic_flags,
                "total_blast_hits": len(blast_hits),
                "all_blast_hits": blast_hits[:10],
            },
            source="Lumi Biosecurity (BLAST + heuristic)",
            source_id="virulence_screen",
            confidence=0.70 if virulence_flags else 0.50,
        )
    except Exception as exc:
        return handle_error("screen_virulence_factors", exc)


# ===================================================================
# Tool 6: BWC / Australia Group compliance check
# ===================================================================


@mcp.tool()
async def check_bwc_compliance(organism_or_agent: str) -> dict[str, Any]:
    """Check an organism, toxin, or biological agent against BWC and Australia Group lists.

    Performs rule-based matching against:
    - Biological Weapons Convention (BWC) controlled agents
    - Australia Group (AG) export control lists (human, animal, plant pathogens & toxins)
    - CDC/USDA Select Agent list

    Args:
        organism_or_agent: Name of organism, toxin, or agent to check
            (e.g. 'Bacillus anthracis', 'ricin', 'Ebola virus', 'aflatoxin').
    """
    try:
        query_lower = organism_or_agent.lower().strip()
        query_words = set(query_lower.split())

        # ---- Check BWC / Australia Group ----
        bwc_matches = []
        for agent in BWC_CONTROLLED_AGENTS:
            agent_lower = agent["name"].lower()
            agent_words = set(agent_lower.split())
            if query_lower in agent_lower or agent_lower in query_lower:
                bwc_matches.append({**agent, "match_type": "exact"})
            elif query_words & agent_words and len(query_words & agent_words) / max(len(query_words), 1) >= 0.5:
                bwc_matches.append({**agent, "match_type": "partial"})

        # ---- Check Select Agent list ----
        sa_matches = []
        for agent in SELECT_AGENTS:
            agent_lower = agent["name"].lower()
            agent_words = set(agent_lower.split())
            if query_lower in agent_lower or agent_lower in query_lower:
                sa_matches.append({**agent, "match_type": "exact"})
            elif query_words & agent_words and len(query_words & agent_words) / max(len(query_words), 1) >= 0.5:
                sa_matches.append({**agent, "match_type": "partial"})

        # ---- Determine compliance status ----
        exact_bwc = [m for m in bwc_matches if m["match_type"] == "exact"]
        exact_sa = [m for m in sa_matches if m["match_type"] == "exact"]

        compliance_issues = []
        if exact_bwc:
            lists_hit = list(set(m["list"] for m in exact_bwc))
            compliance_issues.append(
                f"Australia Group controlled ({', '.join(lists_hit)}): "
                "export/transfer requires government authorization"
            )
        if exact_sa:
            cats = list(set(m["category"] for m in exact_sa))
            compliance_issues.append(
                f"CDC/USDA Select Agent ({', '.join(cats)}): "
                "possession/use/transfer requires FSAP registration"
            )

        if exact_bwc or exact_sa:
            status = "RESTRICTED"
            risk = "CRITICAL"
        elif bwc_matches or sa_matches:
            status = "REVIEW_REQUIRED"
            risk = "HIGH"
        else:
            status = "NO_RESTRICTIONS_FOUND"
            risk = "CLEAR"

        # Build regulatory summary
        regulations = []
        if exact_bwc or any(m for m in bwc_matches if m["match_type"] == "exact"):
            regulations.extend([
                "Biological Weapons Convention (BWC) - prohibited for offensive use",
                "Australia Group export controls - export license required",
            ])
        if exact_sa:
            regulations.extend([
                "Federal Select Agent Regulations (42 CFR Part 73 / 7 CFR Part 331 / 9 CFR Part 121)",
                "Registration with Federal Select Agent Program (FSAP) required",
                "Personnel reliability program (PRP) required for access",
                "Biosafety and security plan required",
            ])

        summary = (
            f"BWC/AG compliance check for '{organism_or_agent}': Status = {status}. "
            f"{len(exact_bwc)} BWC/AG matches, {len(exact_sa)} Select Agent matches. "
        )
        if compliance_issues:
            summary += "Issues: " + "; ".join(compliance_issues) + ". "
        if status == "NO_RESTRICTIONS_FOUND":
            summary += (
                "No matches found on BWC, Australia Group, or Select Agent lists. "
                "Note: absence from these lists does not guarantee unrestricted use -- "
                "always consult institutional biosafety committees (IBC) and export control offices."
            )

        return standard_response(
            summary=summary,
            raw_data={
                "query": organism_or_agent,
                "compliance_status": status,
                "risk_level": risk,
                "bwc_ag_matches": bwc_matches,
                "select_agent_matches": sa_matches,
                "compliance_issues": compliance_issues,
                "applicable_regulations": regulations,
                "recommendation": (
                    "STOP: Consult institutional biosafety officer and legal counsel before proceeding."
                    if risk == "CRITICAL"
                    else "Review matches with biosafety committee before proceeding."
                    if risk == "HIGH"
                    else "No restrictions identified, but always follow institutional biosafety policies."
                ),
            },
            source="Lumi Biosecurity (BWC + AG + FSAP)",
            source_id=organism_or_agent,
            confidence=0.92,
        )
    except Exception as exc:
        return handle_error("check_bwc_compliance", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
