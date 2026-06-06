"""
Protein & Structure MCP Server -- Lumi Virtual Lab

Exposes tools for querying protein and structural biology databases:
  UniProt, RCSB PDB, AlphaFold DB, InterPro, STRING.

Start with:  python -m src.mcp_servers.protein.server
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

# Relative import when running inside the package; fall back for direct exec.
try:
    from src.mcp_servers.base import async_http_get, async_http_post, handle_error, standard_response
except ImportError:
    from mcp_servers.base import async_http_get, async_http_post, handle_error, standard_response  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UNIPROT_REST = "https://rest.uniprot.org"
RCSB_DATA_API = "https://data.rcsb.org/rest/v1"
RCSB_SEARCH_API = "https://search.rcsb.org/rcsbsearch/v2/query"
ALPHAFOLD_API = "https://alphafold.ebi.ac.uk/api"
INTERPRO_API = "https://www.ebi.ac.uk/interpro/api"
STRING_API = "https://string-db.org/api"

# UniProt default field list for protein info queries
_UNIPROT_FIELDS = (
    "accession,id,protein_name,gene_names,organism_name,length,"
    "cc_function,cc_subcellular_location,ft_domain,ft_binding,"
    "xref_pdb,xref_interpro"
)

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi Protein & Structure",
    instructions=(
        "Protein and structural biology database queries: "
        "UniProt, RCSB PDB, AlphaFold DB, InterPro, STRING"
    ),
)


# ===================================================================
# UniProt tools
# ===================================================================


@mcp.tool()
async def get_protein_info(uniprot_id_or_gene: str) -> dict[str, Any]:
    """Retrieve detailed protein information from UniProt by accession ID or gene name.

    Fetches accession, protein name, gene names, organism, length, function,
    subcellular location, domains, binding sites, and cross-references to PDB
    and InterPro.

    Args:
        uniprot_id_or_gene: A UniProt accession (e.g. P04637) or gene name
            (e.g. TP53). The API will search for the best match.
    """
    try:
        url = f"{UNIPROT_REST}/uniprotkb/search"
        params = {
            "query": uniprot_id_or_gene,
            "format": "json",
            "size": "1",
            "fields": _UNIPROT_FIELDS,
        }
        data = await async_http_get(url, params=params)

        results = data.get("results", [])
        if not results:
            return standard_response(
                summary=f"No UniProt entry found for '{uniprot_id_or_gene}'.",
                raw_data={"query": uniprot_id_or_gene, "results": []},
                source="UniProt",
                source_id=uniprot_id_or_gene,
                confidence=0.3,
            )

        entry = results[0]
        accession = entry.get("primaryAccession", "N/A")
        protein_name = (
            entry.get("proteinDescription", {})
            .get("recommendedName", {})
            .get("fullName", {})
            .get("value", "N/A")
        )
        gene_names = [
            g.get("geneName", {}).get("value", "")
            for g in entry.get("genes", [])
        ]
        organism = entry.get("organism", {}).get("scientificName", "N/A")
        length = entry.get("sequence", {}).get("length", "N/A")

        # Extract function comment
        function_texts = []
        for comment in entry.get("comments", []):
            if comment.get("commentType") == "FUNCTION":
                for txt in comment.get("texts", []):
                    function_texts.append(txt.get("value", ""))

        # Extract PDB cross-references
        pdb_ids = []
        for xref in entry.get("uniProtKBCrossReferences", []):
            if xref.get("database") == "PDB":
                pdb_ids.append(xref.get("id", ""))

        summary = (
            f"{accession} | {protein_name} | Gene(s): {', '.join(gene_names) or 'N/A'} | "
            f"Organism: {organism} | Length: {length} aa | "
            f"{len(pdb_ids)} PDB structures. "
            f"Function: {function_texts[0][:200] + '...' if function_texts else 'N/A'}"
        )

        return standard_response(
            summary=summary,
            raw_data=entry,
            source="UniProt",
            source_id=accession,
            confidence=0.92,
        )
    except Exception as exc:
        return handle_error("get_protein_info", exc)


@mcp.tool()
async def search_proteins(query: str, organism: str = "human") -> dict[str, Any]:
    """Search UniProt for proteins matching a free-text query filtered by organism.

    Args:
        query: Free-text search (e.g. 'kinase inhibitor', 'tumor suppressor').
        organism: Organism common or scientific name to filter by (default 'human').
    """
    try:
        url = f"{UNIPROT_REST}/uniprotkb/search"
        full_query = f"{query} AND organism_name:{organism}"
        params = {
            "query": full_query,
            "format": "json",
            "size": "10",
        }
        data = await async_http_get(url, params=params)

        results = data.get("results", [])
        entries = []
        for r in results:
            acc = r.get("primaryAccession", "N/A")
            pname = (
                r.get("proteinDescription", {})
                .get("recommendedName", {})
                .get("fullName", {})
                .get("value", "N/A")
            )
            genes = [g.get("geneName", {}).get("value", "") for g in r.get("genes", [])]
            entries.append({"accession": acc, "protein_name": pname, "genes": genes})

        summary = (
            f"Found {len(entries)} UniProt entries for '{query}' in {organism}. "
            f"Top hits: {', '.join(e['accession'] for e in entries[:5])}"
        )

        return standard_response(
            summary=summary,
            raw_data={"query": full_query, "count": len(entries), "entries": entries, "full_results": results},
            source="UniProt",
            source_id=query,
            confidence=0.80,
        )
    except Exception as exc:
        return handle_error("search_proteins", exc)


@mcp.tool()
async def get_protein_sequence(uniprot_id: str) -> dict[str, Any]:
    """Retrieve the amino acid sequence (FASTA) for a UniProt accession.

    Args:
        uniprot_id: UniProt accession ID (e.g. P04637).
    """
    try:
        url = f"{UNIPROT_REST}/uniprotkb/{uniprot_id}.fasta"
        data = await async_http_get(url)

        fasta_text = data.get("text", "")
        if not fasta_text:
            return standard_response(
                summary=f"No FASTA sequence returned for {uniprot_id}.",
                raw_data={"uniprot_id": uniprot_id},
                source="UniProt",
                source_id=uniprot_id,
                confidence=0.3,
            )

        # Parse FASTA
        lines = fasta_text.strip().split("\n")
        header = lines[0] if lines else ""
        sequence = "".join(lines[1:]) if len(lines) > 1 else ""

        summary = (
            f"Retrieved sequence for {uniprot_id}: {len(sequence)} amino acids. "
            f"Header: {header[:120]}"
        )

        return standard_response(
            summary=summary,
            raw_data={
                "uniprot_id": uniprot_id,
                "header": header,
                "sequence": sequence,
                "length": len(sequence),
            },
            source="UniProt",
            source_id=uniprot_id,
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("get_protein_sequence", exc)


@mcp.tool()
async def get_protein_features(uniprot_id: str) -> dict[str, Any]:
    """Retrieve annotated sequence features (domains, sites, modifications) for a protein.

    Args:
        uniprot_id: UniProt accession ID (e.g. P04637).
    """
    try:
        url = f"{UNIPROT_REST}/uniprotkb/{uniprot_id}"
        params = {"format": "json"}
        data = await async_http_get(url, params=params)

        features = data.get("features", [])

        # Group features by type
        feature_counts: dict[str, int] = {}
        feature_list = []
        for feat in features:
            ftype = feat.get("type", "UNKNOWN")
            feature_counts[ftype] = feature_counts.get(ftype, 0) + 1
            loc = feat.get("location", {})
            start = loc.get("start", {}).get("value", "?")
            end = loc.get("end", {}).get("value", "?")
            desc = feat.get("description", "")
            feature_list.append({
                "type": ftype,
                "start": start,
                "end": end,
                "description": desc,
                "evidences": len(feat.get("evidences", [])),
            })

        counts_str = ", ".join(f"{k}: {v}" for k, v in sorted(feature_counts.items(), key=lambda x: -x[1])[:8])
        summary = (
            f"{uniprot_id}: {len(features)} annotated features. "
            f"Types: {counts_str}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "uniprot_id": uniprot_id,
                "total_features": len(features),
                "feature_counts": feature_counts,
                "features": feature_list,
            },
            source="UniProt",
            source_id=uniprot_id,
            confidence=0.90,
        )
    except Exception as exc:
        return handle_error("get_protein_features", exc)


# ===================================================================
# RCSB PDB tools
# ===================================================================


@mcp.tool()
async def search_structures(query: str) -> dict[str, Any]:
    """Search the RCSB PDB for experimentally determined structures using free text.

    Args:
        query: Free-text search (e.g. 'p53 DNA binding domain', 'EGFR kinase').
    """
    try:
        search_payload = {
            "query": {
                "type": "terminal",
                "service": "full_text",
                "parameters": {"value": query},
            },
            "return_type": "entry",
            "request_options": {
                "paginate": {"start": 0, "rows": 15},
                "results_content_type": ["experimental"],
                "sort": [{"sort_by": "score", "direction": "desc"}],
            },
        }
        headers = {"Content-Type": "application/json"}
        data = await async_http_post(RCSB_SEARCH_API, data=search_payload, headers=headers)

        total_count = data.get("total_count", 0)
        result_set = data.get("result_set", [])
        pdb_ids = [r.get("identifier", "") for r in result_set]

        summary = (
            f"PDB search '{query}': {total_count} structures found. "
            f"Top results: {', '.join(pdb_ids[:10])}"
        )

        return standard_response(
            summary=summary,
            raw_data={
                "query": query,
                "total_count": total_count,
                "pdb_ids": pdb_ids,
                "result_set": result_set,
            },
            source="RCSB PDB",
            source_id=query,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("search_structures", exc)


@mcp.tool()
async def get_structure_info(pdb_id: str) -> dict[str, Any]:
    """Retrieve detailed metadata for a PDB structure entry.

    Returns resolution, experimental method, deposition date, title,
    organism, macromolecule names, and more.

    Args:
        pdb_id: 4-character PDB identifier (e.g. 1TUP, 6LU7).
    """
    try:
        pdb_id_upper = pdb_id.upper()
        url = f"{RCSB_DATA_API}/core/entry/{pdb_id_upper}"
        data = await async_http_get(url)

        # Extract key fields
        struct = data.get("struct", {})
        title = struct.get("title", "N/A")

        exptl = data.get("exptl", [{}])
        method = exptl[0].get("method", "N/A") if exptl else "N/A"

        refine = data.get("refine", [{}])
        resolution = refine[0].get("ls_d_res_high", "N/A") if refine else "N/A"

        deposition = (
            data.get("rcsb_accession_info", {}).get("deposit_date", "N/A")
        )

        # Polymer entities
        entity_count = len(data.get("rcsb_entry_container_identifiers", {}).get("polymer_entity_ids", []))

        # Citation
        citation = data.get("citation", [{}])
        citation[0].get("title", "") if citation else ""

        summary = (
            f"PDB {pdb_id_upper}: {title}. "
            f"Method: {method}, Resolution: {resolution} A. "
            f"Deposited: {deposition}. {entity_count} polymer entities."
        )

        return standard_response(
            summary=summary,
            raw_data=data,
            source="RCSB PDB",
            source_id=pdb_id_upper,
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("get_structure_info", exc)


@mcp.tool()
async def get_binding_sites(pdb_id: str) -> dict[str, Any]:
    """Retrieve non-polymer (ligand) entity and binding site information for a PDB entry.

    Args:
        pdb_id: 4-character PDB identifier (e.g. 6LU7).
    """
    try:
        pdb_id_upper = pdb_id.upper()

        # Fetch entry to get non-polymer entity IDs
        entry_url = f"{RCSB_DATA_API}/core/entry/{pdb_id_upper}"
        entry_data = await async_http_get(entry_url)
        nonpoly_ids = (
            entry_data.get("rcsb_entry_container_identifiers", {})
            .get("non_polymer_entity_ids", [])
        )

        ligands = []
        for entity_id in nonpoly_ids[:10]:  # limit to first 10 entities
            try:
                np_url = f"{RCSB_DATA_API}/core/nonpolymer_entity/{pdb_id_upper}/{entity_id}"
                np_data = await async_http_get(np_url)
                comp_id = (
                    np_data.get("rcsb_nonpolymer_entity_container_identifiers", {})
                    .get("comp_id", "UNK")
                )
                description = (
                    np_data.get("rcsb_nonpolymer_entity", {})
                    .get("pdbx_description", "N/A")
                )
                formula = (
                    np_data.get("rcsb_nonpolymer_entity", {})
                    .get("formula_weight", "N/A")
                )
                ligands.append({
                    "entity_id": entity_id,
                    "comp_id": comp_id,
                    "description": description,
                    "formula_weight": formula,
                    "raw": np_data,
                })
            except Exception:
                ligands.append({"entity_id": entity_id, "error": "Failed to fetch"})

        # Also attempt to get binding-site annotations via GraphQL
        binding_sites = []
        try:
            graphql_url = "https://data.rcsb.org/graphql"
            gql_query = """
            query ($id: String!) {
              entry(entry_id: $id) {
                struct_site {
                  id
                  details
                  pdbx_evidence_code
                }
                struct_site_gen {
                  site_id
                  auth_asym_id
                  auth_comp_id
                  auth_seq_id
                  label_atom_id
                }
              }
            }
            """
            gql_payload = {"query": gql_query, "variables": {"id": pdb_id_upper}}
            gql_headers = {"Content-Type": "application/json"}
            gql_data = await async_http_post(graphql_url, data=gql_payload, headers=gql_headers)

            entry_gql = gql_data.get("data", {}).get("entry", {})
            raw_sites = entry_gql.get("struct_site", []) or []
            raw_site_gen = entry_gql.get("struct_site_gen", []) or []

            # Group site residues by site_id
            site_residues: dict[str, list] = {}
            for sg in raw_site_gen:
                sid = sg.get("site_id", "")
                site_residues.setdefault(sid, []).append(sg)

            for site in raw_sites:
                sid = site.get("id", "")
                binding_sites.append({
                    "site_id": sid,
                    "details": site.get("details", ""),
                    "evidence": site.get("pdbx_evidence_code", ""),
                    "residues": site_residues.get(sid, []),
                    "residue_count": len(site_residues.get(sid, [])),
                })
        except Exception:
            pass  # GraphQL binding site data is supplementary

        ligand_names = [lig.get("comp_id", "?") for lig in ligands if "error" not in lig]
        summary = (
            f"PDB {pdb_id_upper}: {len(ligands)} non-polymer entities "
            f"({', '.join(ligand_names[:6])}), "
            f"{len(binding_sites)} annotated binding sites."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "pdb_id": pdb_id_upper,
                "ligands": ligands,
                "binding_sites": binding_sites,
            },
            source="RCSB PDB",
            source_id=pdb_id_upper,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_binding_sites", exc)


# ===================================================================
# AlphaFold DB tools
# ===================================================================


@mcp.tool()
async def get_predicted_structure(uniprot_id: str) -> dict[str, Any]:
    """Retrieve the AlphaFold predicted structure metadata for a UniProt accession.

    Returns model URLs (PDB, mmCIF), confidence metrics (pLDDT), and version info.

    Args:
        uniprot_id: UniProt accession ID (e.g. P04637, Q9Y6K9).
    """
    try:
        url = f"{ALPHAFOLD_API}/prediction/{uniprot_id}"
        data = await async_http_get(url)

        # AlphaFold returns a list with one element
        if isinstance(data, list) and data:
            entry = data[0]
        elif isinstance(data, dict):
            entry = data
        else:
            return standard_response(
                summary=f"No AlphaFold prediction found for {uniprot_id}.",
                raw_data={"uniprot_id": uniprot_id},
                source="AlphaFold DB",
                source_id=uniprot_id,
                confidence=0.3,
            )

        model_url = entry.get("pdbUrl", "N/A")
        cif_url = entry.get("cifUrl", "N/A")
        pae_url = entry.get("paeDocUrl", "") or entry.get("paeImageUrl", "")
        gene = entry.get("gene", "N/A")
        organism = entry.get("organismScientificName", "N/A")
        model_version = entry.get("latestVersion", "N/A")
        seq_length = entry.get("uniprotEnd", 0) - entry.get("uniprotStart", 0) + 1

        # Confidence info
        avg_plddt = entry.get("globalMetricValue", "N/A")

        summary = (
            f"AlphaFold prediction for {uniprot_id} (gene: {gene}, {organism}): "
            f"model v{model_version}, {seq_length} residues, "
            f"average pLDDT={avg_plddt}. "
            f"PDB: {model_url}"
        )

        return standard_response(
            summary=summary,
            raw_data={
                "uniprot_id": uniprot_id,
                "gene": gene,
                "organism": organism,
                "model_version": model_version,
                "sequence_length": seq_length,
                "average_plddt": avg_plddt,
                "pdb_url": model_url,
                "cif_url": cif_url,
                "pae_url": pae_url,
                "full_entry": entry,
            },
            source="AlphaFold DB",
            source_id=uniprot_id,
            confidence=0.88,
        )
    except Exception as exc:
        return handle_error("get_predicted_structure", exc)


@mcp.tool()
async def get_pae(uniprot_id: str) -> dict[str, Any]:
    """Retrieve the Predicted Aligned Error (PAE) matrix for an AlphaFold model.

    PAE indicates the confidence in relative positions of residue pairs.
    Low PAE values indicate high confidence in the relative positioning.

    Args:
        uniprot_id: UniProt accession ID (e.g. P04637).
    """
    try:
        # First get prediction metadata to find the PAE URL
        pred_url = f"{ALPHAFOLD_API}/prediction/{uniprot_id}"
        pred_data = await async_http_get(pred_url)

        if isinstance(pred_data, list) and pred_data:
            entry = pred_data[0]
        elif isinstance(pred_data, dict):
            entry = pred_data
        else:
            return standard_response(
                summary=f"No AlphaFold prediction found for {uniprot_id}.",
                raw_data={"uniprot_id": uniprot_id},
                source="AlphaFold DB",
                source_id=uniprot_id,
                confidence=0.3,
            )

        pae_doc_url = entry.get("paeDocUrl", "")
        if not pae_doc_url:
            # Construct the URL from the entry ID pattern
            entry_id = entry.get("entryId", f"AF-{uniprot_id}-F1")
            model_version = entry.get("latestVersion", 4)
            pae_doc_url = (
                f"https://alphafold.ebi.ac.uk/files/{entry_id}-predicted_aligned_error_v{model_version}.json"
            )

        pae_data = await async_http_get(pae_doc_url)

        # PAE JSON is typically a list with one dict containing 'predicted_aligned_error'
        # or a list of dicts with 'residue1', 'residue2', 'distance'
        pae_matrix = None
        pae_summary_stats = {}

        if isinstance(pae_data, list) and pae_data:
            first = pae_data[0]
            if isinstance(first, dict):
                pae_matrix = first.get("predicted_aligned_error")
                if pae_matrix and isinstance(pae_matrix, list):
                    # Compute summary statistics from the matrix
                    flat = []
                    for row in pae_matrix:
                        if isinstance(row, list):
                            flat.extend(row)
                    if flat:
                        pae_summary_stats = {
                            "min_pae": min(flat),
                            "max_pae": max(flat),
                            "mean_pae": sum(flat) / len(flat),
                            "matrix_size": len(pae_matrix),
                        }
        elif isinstance(pae_data, dict):
            pae_matrix = pae_data.get("predicted_aligned_error")

        mean_pae = pae_summary_stats.get("mean_pae", "N/A")
        matrix_size = pae_summary_stats.get("matrix_size", "N/A")

        summary = (
            f"PAE for {uniprot_id}: {matrix_size}x{matrix_size} matrix, "
            f"mean PAE = {mean_pae:.2f} A. " if isinstance(mean_pae, (int, float)) else
            f"PAE for {uniprot_id}: retrieved from {pae_doc_url}. "
        )

        return standard_response(
            summary=summary,
            raw_data={
                "uniprot_id": uniprot_id,
                "pae_url": pae_doc_url,
                "summary_stats": pae_summary_stats,
                "pae_matrix_truncated": (
                    pae_matrix[:5] if pae_matrix and isinstance(pae_matrix, list) else None
                ),
            },
            source="AlphaFold DB",
            source_id=uniprot_id,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_pae", exc)


# ===================================================================
# InterPro tools
# ===================================================================


@mcp.tool()
async def get_protein_domains(uniprot_id: str) -> dict[str, Any]:
    """Retrieve all InterPro domain annotations for a protein.

    Returns domain families, superfamilies, and sites mapped to the protein
    from all member databases (Pfam, SMART, PROSITE, CDD, etc.).

    Args:
        uniprot_id: UniProt accession ID (e.g. P04637).
    """
    try:
        url = f"{INTERPRO_API}/entry/all/protein/uniprot/{uniprot_id}"
        params = {"format": "json"}
        data = await async_http_get(url, params=params)

        results = data.get("results", [])
        domains = []
        for entry in results:
            metadata = entry.get("metadata", {})
            accession = metadata.get("accession", "N/A")
            name = metadata.get("name", "N/A")
            entry_type = metadata.get("type", "N/A")
            source_db = metadata.get("source_database", "N/A")
            go_terms = metadata.get("go_terms", [])

            # Get location info for this protein
            proteins_data = entry.get("proteins", [])
            locations = []
            for prot in proteins_data:
                for loc_group in prot.get("entry_protein_locations", []):
                    for frag in loc_group.get("fragments", []):
                        locations.append({
                            "start": frag.get("start", "?"),
                            "end": frag.get("end", "?"),
                        })

            domains.append({
                "accession": accession,
                "name": name,
                "type": entry_type,
                "source_database": source_db,
                "go_terms": go_terms[:5],
                "locations": locations,
            })

        domain_names = [d["name"] for d in domains[:8]]
        summary = (
            f"{uniprot_id}: {len(domains)} InterPro domain entries. "
            f"Domains: {', '.join(domain_names)}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "uniprot_id": uniprot_id,
                "total_domains": len(domains),
                "domains": domains,
            },
            source="InterPro",
            source_id=uniprot_id,
            confidence=0.90,
        )
    except Exception as exc:
        return handle_error("get_protein_domains", exc)


@mcp.tool()
async def search_domains_by_name(domain_name: str) -> dict[str, Any]:
    """Search InterPro for domain/family entries by name or keyword.

    Args:
        domain_name: Name or keyword for the domain (e.g. 'kinase',
            'zinc finger', 'immunoglobulin').
    """
    try:
        url = f"{INTERPRO_API}/entry/all"
        params = {"search": domain_name, "format": "json"}
        data = await async_http_get(url, params=params)

        results = data.get("results", [])
        entries = []
        for entry in results[:20]:
            metadata = entry.get("metadata", {})
            entries.append({
                "accession": metadata.get("accession", "N/A"),
                "name": metadata.get("name", "N/A"),
                "type": metadata.get("type", "N/A"),
                "source_database": metadata.get("source_database", "N/A"),
                "protein_count": metadata.get("counters", {}).get("proteins", 0),
            })

        total = data.get("count", len(entries))
        top_names = [e["name"] for e in entries[:5]]
        summary = (
            f"InterPro search '{domain_name}': {total} entries found. "
            f"Top: {', '.join(top_names)}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "query": domain_name,
                "total_count": total,
                "entries": entries,
            },
            source="InterPro",
            source_id=domain_name,
            confidence=0.82,
        )
    except Exception as exc:
        return handle_error("search_domains_by_name", exc)


# ===================================================================
# STRING tools
# ===================================================================


@mcp.tool()
async def get_interactions(protein: str, species: int = 9606) -> dict[str, Any]:
    """Get protein-protein interactions from STRING database.

    Returns interaction partners with combined scores and evidence channels.

    Args:
        protein: Protein name or identifier (e.g. 'TP53', 'BRCA1').
        species: NCBI taxonomy ID (default 9606 = Homo sapiens).
    """
    try:
        url = f"{STRING_API}/json/network"
        params = {
            "identifiers": protein,
            "species": str(species),
            "limit": "20",
            "caller_identity": "lumi_virtual_lab",
        }
        data = await async_http_get(url, params=params)

        # STRING returns a list of interactions
        interactions = data if isinstance(data, list) else []

        partners = set()
        interaction_details = []
        for ix in interactions:
            pref_a = ix.get("preferredName_A", ix.get("stringId_A", "?"))
            pref_b = ix.get("preferredName_B", ix.get("stringId_B", "?"))
            score = ix.get("score", 0)
            partners.add(pref_a)
            partners.add(pref_b)
            interaction_details.append({
                "protein_a": pref_a,
                "protein_b": pref_b,
                "combined_score": score,
                "nscore": ix.get("nscore", 0),
                "fscore": ix.get("fscore", 0),
                "pscore": ix.get("pscore", 0),
                "ascore": ix.get("ascore", 0),
                "escore": ix.get("escore", 0),
                "dscore": ix.get("dscore", 0),
                "tscore": ix.get("tscore", 0),
            })

        # Sort by score descending
        interaction_details.sort(key=lambda x: x["combined_score"], reverse=True)
        partners.discard(protein)

        summary = (
            f"STRING interactions for {protein} (taxid {species}): "
            f"{len(interaction_details)} interactions with {len(partners)} unique partners. "
            f"Top partners: {', '.join(list(partners)[:8])}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "query_protein": protein,
                "species": species,
                "interaction_count": len(interaction_details),
                "unique_partners": sorted(partners),
                "interactions": interaction_details,
            },
            source="STRING",
            source_id=protein,
            version="v12.0",
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_interactions", exc)


@mcp.tool()
async def get_network(proteins: str | list[str], species: int = 9606) -> dict[str, Any]:
    """Get the interaction network among a set of proteins from STRING.

    Args:
        proteins: Comma-separated protein names (e.g. 'TP53,MDM2,CDKN2A,RB1').
        species: NCBI taxonomy ID (default 9606 = Homo sapiens).
    """
    try:
        # STRING expects newline-separated identifiers for multi-protein queries
        if isinstance(proteins, list):
            protein_list = [str(p).strip() for p in proteins if str(p).strip()]
        else:
            protein_list = [p.strip() for p in proteins.split(",") if p.strip()]

        url = f"{STRING_API}/json/network"
        params = {
            "identifiers": "\r".join(protein_list),
            "species": str(species),
            "caller_identity": "lumi_virtual_lab",
        }
        data = await async_http_get(url, params=params)

        interactions = data if isinstance(data, list) else []

        edges = []
        nodes = set()
        for ix in interactions:
            pref_a = ix.get("preferredName_A", ix.get("stringId_A", "?"))
            pref_b = ix.get("preferredName_B", ix.get("stringId_B", "?"))
            score = ix.get("score", 0)
            nodes.add(pref_a)
            nodes.add(pref_b)
            edges.append({
                "source": pref_a,
                "target": pref_b,
                "combined_score": score,
            })

        edges.sort(key=lambda x: x["combined_score"], reverse=True)

        summary = (
            f"STRING network for {len(protein_list)} proteins: "
            f"{len(nodes)} nodes, {len(edges)} edges. "
            f"Queried: {', '.join(protein_list[:6])}"
            f"{'...' if len(protein_list) > 6 else ''}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "query_proteins": protein_list,
                "species": species,
                "nodes": sorted(nodes),
                "node_count": len(nodes),
                "edge_count": len(edges),
                "edges": edges,
            },
            source="STRING",
            source_id=proteins,
            version="v12.0",
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_network", exc)


@mcp.tool()
async def get_enrichment(proteins: str, species: int = 9606) -> dict[str, Any]:
    """Run functional enrichment analysis on a set of proteins using STRING.

    Returns enriched GO terms, KEGG pathways, Reactome pathways, and other
    annotation categories.

    Args:
        proteins: Comma-separated protein names (e.g. 'TP53,MDM2,CDKN2A,RB1,BRCA1').
        species: NCBI taxonomy ID (default 9606 = Homo sapiens).
    """
    try:
        if isinstance(proteins, list):
            protein_list = [str(p).strip() for p in proteins if str(p).strip()]
        else:
            protein_list = [p.strip() for p in proteins.split(",") if p.strip()]

        url = f"{STRING_API}/json/enrichment"
        params = {
            "identifiers": "\r".join(protein_list),
            "species": str(species),
            "caller_identity": "lumi_virtual_lab",
        }
        data = await async_http_get(url, params=params)

        enrichments = data if isinstance(data, list) else []

        # Group by category
        by_category: dict[str, list] = {}
        for enr in enrichments:
            cat = enr.get("category", "Other")
            by_category.setdefault(cat, []).append({
                "term": enr.get("term", "N/A"),
                "description": enr.get("description", "N/A"),
                "p_value": enr.get("p_value", 1.0),
                "fdr": enr.get("fdr", 1.0),
                "number_of_genes": enr.get("number_of_genes", 0),
                "input_genes": enr.get("inputGenes", ""),
            })

        # Sort each category by FDR
        for cat in by_category:
            by_category[cat].sort(key=lambda x: x.get("fdr", 1.0))

        # Build summary from top terms
        top_terms = []
        for cat, terms in sorted(by_category.items()):
            if terms:
                top = terms[0]
                top_terms.append(f"{cat}: {top['description']} (FDR={top['fdr']:.2e})")

        summary = (
            f"STRING enrichment for {len(protein_list)} proteins: "
            f"{len(enrichments)} enriched terms across {len(by_category)} categories. "
            f"Top: {'; '.join(top_terms[:5])}"
        )

        return standard_response(
            summary=summary,
            raw_data={
                "query_proteins": protein_list,
                "species": species,
                "total_terms": len(enrichments),
                "categories": {k: v[:10] for k, v in by_category.items()},
            },
            source="STRING",
            source_id=proteins,
            version="v12.0",
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_enrichment", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
