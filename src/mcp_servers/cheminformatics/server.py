"""
Cheminformatics MCP Server -- Lumi Virtual Lab

Exposes tools for molecular descriptor calculation, drug-likeness assessment,
fingerprinting, similarity search, substructure matching (via RDKit), PubChem
compound queries, and ZINC database searches.

Start with:  python -m src.mcp_servers.cheminformatics.server
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from fastmcp import FastMCP

try:
    from src.mcp_servers.base import async_http_get, handle_error, standard_response
except ImportError:
    from mcp_servers.base import async_http_get, handle_error, standard_response

# ---------------------------------------------------------------------------
# Optional RDKit import
# ---------------------------------------------------------------------------
try:
    from rdkit import Chem
    from rdkit.Chem import (
        AllChem,
        DataStructs,
        Descriptors,
        rdMolDescriptors,
    )

    HAS_RDKIT = True
except ImportError:
    HAS_RDKIT = False

logger = logging.getLogger("lumi.mcp.cheminformatics")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PUBCHEM_PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
ZINC_API = "https://zinc15.docking.org"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_rdkit() -> None:
    """Raise if RDKit is not available."""
    if not HAS_RDKIT:
        raise RuntimeError(
            "RDKit is not installed.  Install it with:  "
            "conda install -c conda-forge rdkit   or   pip install rdkit"
        )


def _mol_from_smiles(smiles: str) -> Any:
    """Parse a SMILES string into an RDKit Mol object, raising on failure."""
    _require_rdkit()
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: '{smiles}'")
    return mol


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "Lumi Cheminformatics",
    instructions=(
        "Cheminformatics toolkit for the Lumi Virtual Lab.  Provides molecular "
        "descriptor calculation (RDKit), drug-likeness checks, fingerprinting, "
        "similarity & substructure search, PubChem queries, ZINC lookups, and "
        "format conversion."
    ),
)


# ===== RDKit local-computation tools ========================================


@mcp.tool()
async def calculate_descriptors(smiles: str) -> dict[str, Any]:
    """Calculate key physicochemical descriptors for a molecule.

    Computes molecular weight, LogP (Wildman-Crippen), hydrogen-bond donors
    and acceptors, topological polar surface area (TPSA), rotatable bond count,
    aromatic ring count, and heavy-atom count.

    Args:
        smiles: SMILES representation of the molecule.

    Returns:
        Dictionary of computed descriptors.
    """
    try:
        mol = _mol_from_smiles(smiles)
        canonical = Chem.MolToSmiles(mol)

        descriptors = {
            "canonical_smiles": canonical,
            "molecular_weight": round(Descriptors.MolWt(mol), 3),
            "logp": round(Descriptors.MolLogP(mol), 3),
            "hba": Descriptors.NumHAcceptors(mol),
            "hbd": Descriptors.NumHDonors(mol),
            "tpsa": round(Descriptors.TPSA(mol), 2),
            "rotatable_bonds": Descriptors.NumRotatableBonds(mol),
            "aromatic_rings": rdMolDescriptors.CalcNumAromaticRings(mol),
            "heavy_atoms": mol.GetNumHeavyAtoms(),
            "molecular_formula": rdMolDescriptors.CalcMolFormula(mol),
            "num_rings": rdMolDescriptors.CalcNumRings(mol),
            "fraction_csp3": round(rdMolDescriptors.CalcFractionCSP3(mol), 3),
        }

        summary = (
            f"Descriptors for {canonical}: MW={descriptors['molecular_weight']}, "
            f"LogP={descriptors['logp']}, TPSA={descriptors['tpsa']}, "
            f"HBA={descriptors['hba']}, HBD={descriptors['hbd']}"
        )
        return standard_response(
            summary=summary,
            raw_data=descriptors,
            source="RDKit",
            source_id=canonical,
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("calculate_descriptors", exc)


@mcp.tool()
async def check_drug_likeness(smiles: str) -> dict[str, Any]:
    """Evaluate drug-likeness using Lipinski's Rule of Five and Veber rules.

    Lipinski Rule of 5: MW <= 500, LogP <= 5, HBD <= 5, HBA <= 10.
    Veber rules: TPSA <= 140 A^2, rotatable bonds <= 10.

    Args:
        smiles: SMILES representation of the molecule.

    Returns:
        Pass/fail status for each rule set, individual violations, and an
        overall drug-likeness assessment.
    """
    try:
        mol = _mol_from_smiles(smiles)
        canonical = Chem.MolToSmiles(mol)

        mw = round(Descriptors.MolWt(mol), 3)
        logp = round(Descriptors.MolLogP(mol), 3)
        hbd = Descriptors.NumHDonors(mol)
        hba = Descriptors.NumHAcceptors(mol)
        tpsa = round(Descriptors.TPSA(mol), 2)
        rot_bonds = Descriptors.NumRotatableBonds(mol)

        # Lipinski violations
        lipinski_violations: list[str] = []
        if mw > 500:
            lipinski_violations.append(f"MW={mw} > 500")
        if logp > 5:
            lipinski_violations.append(f"LogP={logp} > 5")
        if hbd > 5:
            lipinski_violations.append(f"HBD={hbd} > 5")
        if hba > 10:
            lipinski_violations.append(f"HBA={hba} > 10")

        lipinski_pass = len(lipinski_violations) <= 1  # Ro5 allows 1 violation

        # Veber violations
        veber_violations: list[str] = []
        if tpsa > 140:
            veber_violations.append(f"TPSA={tpsa} > 140")
        if rot_bonds > 10:
            veber_violations.append(f"RotBonds={rot_bonds} > 10")

        veber_pass = len(veber_violations) == 0

        overall = lipinski_pass and veber_pass

        summary = (
            f"Drug-likeness for {canonical}: "
            f"Lipinski={'PASS' if lipinski_pass else 'FAIL'} "
            f"({len(lipinski_violations)} violations), "
            f"Veber={'PASS' if veber_pass else 'FAIL'} "
            f"({len(veber_violations)} violations). "
            f"Overall: {'DRUG-LIKE' if overall else 'NOT DRUG-LIKE'}"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "canonical_smiles": canonical,
                "overall_drug_like": overall,
                "lipinski": {
                    "pass": lipinski_pass,
                    "num_violations": len(lipinski_violations),
                    "violations": lipinski_violations,
                    "mw": mw,
                    "logp": logp,
                    "hbd": hbd,
                    "hba": hba,
                },
                "veber": {
                    "pass": veber_pass,
                    "num_violations": len(veber_violations),
                    "violations": veber_violations,
                    "tpsa": tpsa,
                    "rotatable_bonds": rot_bonds,
                },
            },
            source="RDKit",
            source_id=canonical,
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("check_drug_likeness", exc)


@mcp.tool()
async def compute_fingerprint(
    smiles: str,
    fp_type: str = "morgan",
    radius: int = 2,
    n_bits: int = 2048,
) -> dict[str, Any]:
    """Compute a molecular fingerprint and return on-bit positions.

    Args:
        smiles: SMILES representation of the molecule.
        fp_type: Fingerprint type. Supported: 'morgan' (ECFP-like),
                 'rdkit' (topological), 'maccs' (MACCS keys).
        radius: Morgan fingerprint radius (only used for 'morgan').
        n_bits: Bit vector length (only used for 'morgan' and 'rdkit').

    Returns:
        Fingerprint type, parameters, number of on-bits, on-bit positions,
        and density.
    """
    try:
        mol = _mol_from_smiles(smiles)
        canonical = Chem.MolToSmiles(mol)

        fp_type_lower = fp_type.lower()
        if fp_type_lower == "morgan":
            fp = AllChem.GetMorganFingerprintAsBitVect(mol, radius, nBits=n_bits)
            fp_name = f"Morgan (radius={radius}, nBits={n_bits})"
        elif fp_type_lower == "rdkit":
            fp = Chem.RDKFingerprint(mol, fpSize=n_bits)
            fp_name = f"RDKit topological (nBits={n_bits})"
        elif fp_type_lower == "maccs":
            fp = AllChem.GetMACCSKeysFingerprint(mol)
            n_bits = len(fp)
            fp_name = f"MACCS keys ({n_bits} bits)"
        else:
            return handle_error(
                "compute_fingerprint",
                f"Unsupported fingerprint type '{fp_type}'. Use 'morgan', 'rdkit', or 'maccs'.",
            )

        on_bits = list(fp.GetOnBits())
        density = round(len(on_bits) / len(fp), 4) if len(fp) > 0 else 0.0

        summary = (
            f"{fp_name} for {canonical}: {len(on_bits)} on-bits "
            f"(density={density})"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "canonical_smiles": canonical,
                "fingerprint_type": fp_type_lower,
                "fingerprint_name": fp_name,
                "n_bits": len(fp),
                "num_on_bits": len(on_bits),
                "on_bits": on_bits,
                "density": density,
                "radius": radius if fp_type_lower == "morgan" else None,
            },
            source="RDKit",
            source_id=canonical,
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("compute_fingerprint", exc)


@mcp.tool()
async def compute_similarity(
    smiles1: str,
    smiles2: str,
) -> dict[str, Any]:
    """Compute Tanimoto similarity between two molecules using Morgan fingerprints.

    Args:
        smiles1: SMILES of the first molecule.
        smiles2: SMILES of the second molecule.

    Returns:
        Tanimoto similarity coefficient (0-1), canonical SMILES of both
        molecules, and qualitative similarity assessment.
    """
    try:
        mol1 = _mol_from_smiles(smiles1)
        mol2 = _mol_from_smiles(smiles2)
        can1 = Chem.MolToSmiles(mol1)
        can2 = Chem.MolToSmiles(mol2)

        fp1 = AllChem.GetMorganFingerprintAsBitVect(mol1, 2, nBits=2048)
        fp2 = AllChem.GetMorganFingerprintAsBitVect(mol2, 2, nBits=2048)

        tanimoto = round(float(DataStructs.TanimotoSimilarity(fp1, fp2)), 4)

        # Dice similarity as a complementary metric
        dice = round(float(DataStructs.DiceSimilarity(fp1, fp2)), 4)

        if tanimoto >= 0.85:
            assessment = "very high (likely same pharmacophore / analogue)"
        elif tanimoto >= 0.7:
            assessment = "high (structurally related)"
        elif tanimoto >= 0.5:
            assessment = "moderate"
        elif tanimoto >= 0.3:
            assessment = "low"
        else:
            assessment = "very low (structurally dissimilar)"

        summary = (
            f"Tanimoto similarity: {tanimoto} ({assessment}). "
            f"Dice similarity: {dice}"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "smiles1": can1,
                "smiles2": can2,
                "tanimoto": tanimoto,
                "dice": dice,
                "assessment": assessment,
                "fingerprint": "Morgan radius=2, 2048 bits",
            },
            source="RDKit",
            source_id=f"{can1}|{can2}",
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("compute_similarity", exc)


@mcp.tool()
async def substructure_search(
    smiles: str,
    pattern: str,
) -> dict[str, Any]:
    """Check whether a molecule contains a given substructure (SMARTS or SMILES).

    Args:
        smiles: SMILES of the molecule to search in.
        pattern: SMARTS or SMILES pattern to search for.

    Returns:
        Whether the substructure is present, matched atom indices, and the
        number of matches found.
    """
    try:
        mol = _mol_from_smiles(smiles)
        canonical = Chem.MolToSmiles(mol)

        # Try SMARTS first, fall back to SMILES
        query = Chem.MolFromSmarts(pattern)
        pattern_type = "SMARTS"
        if query is None:
            query = Chem.MolFromSmiles(pattern)
            pattern_type = "SMILES"
        if query is None:
            return handle_error(
                "substructure_search",
                f"Could not parse pattern '{pattern}' as SMARTS or SMILES.",
            )

        matches = mol.GetSubstructMatches(query)
        has_match = len(matches) > 0

        # Convert tuples to lists for JSON serialisation
        match_atoms = [list(m) for m in matches]

        summary = (
            f"Substructure {'FOUND' if has_match else 'NOT FOUND'}: "
            f"{pattern} ({pattern_type}) in {canonical}. "
            f"{len(matches)} match(es)."
        )
        return standard_response(
            summary=summary,
            raw_data={
                "canonical_smiles": canonical,
                "pattern": pattern,
                "pattern_type": pattern_type,
                "has_match": has_match,
                "num_matches": len(matches),
                "matched_atom_indices": match_atoms,
            },
            source="RDKit",
            source_id=canonical,
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("substructure_search", exc)


# ===== PubChem API tools ====================================================


@mcp.tool()
async def search_compound(name_or_smiles: str) -> dict[str, Any]:
    """Search PubChem for a compound by name or SMILES.

    Args:
        name_or_smiles: Compound name (e.g. 'aspirin') or SMILES string.

    Returns:
        PubChem CID, IUPAC name, molecular weight, formula, canonical SMILES,
        and other identifiers.
    """
    try:
        # Heuristic: if it contains special characters typical of SMILES, treat
        # as SMILES; otherwise search by name.
        smiles_chars = {"(", ")", "=", "#", "[", "]", "@", "/", "\\", "%"}
        is_smiles = any(c in name_or_smiles for c in smiles_chars)

        if is_smiles:
            encoded = quote(name_or_smiles, safe="")
            url = f"{PUBCHEM_PUG}/compound/smiles/{encoded}/JSON"
        else:
            encoded = quote(name_or_smiles, safe="")
            url = f"{PUBCHEM_PUG}/compound/name/{encoded}/JSON"

        data = await async_http_get(url)

        compounds = data.get("PC_Compounds", [])
        if not compounds:
            return handle_error(
                "search_compound",
                f"No compounds found for '{name_or_smiles}'.",
            )

        compound = compounds[0]
        cid = compound.get("id", {}).get("id", {}).get("cid")

        # Extract properties from the nested structure
        props: dict[str, Any] = {}
        for prop in compound.get("props", []):
            urn = prop.get("urn", {})
            label = urn.get("label", "")
            name_val = urn.get("name", "")
            value = prop.get("value", {})
            val = value.get("sval") or value.get("ival") or value.get("fval")

            if label == "IUPAC Name" and name_val == "Preferred":
                props["iupac_name"] = val
            elif label == "Molecular Formula":
                props["molecular_formula"] = val
            elif label == "Molecular Weight":
                props["molecular_weight"] = val
            elif label == "SMILES" and name_val == "Canonical":
                props["canonical_smiles"] = val
            elif label == "InChI":
                props["inchi"] = val
            elif label == "InChIKey":
                props["inchikey"] = val

        summary = (
            f"PubChem CID {cid}: "
            f"{props.get('iupac_name', 'N/A')}, "
            f"MW={props.get('molecular_weight', 'N/A')}, "
            f"formula={props.get('molecular_formula', 'N/A')}"
        )
        return standard_response(
            summary=summary,
            raw_data={"cid": cid, **props},
            source="PubChem",
            source_id=str(cid),
            confidence=0.92,
        )
    except Exception as exc:
        return handle_error("search_compound", exc)


@mcp.tool()
async def get_compound_bioactivity(cid: int) -> dict[str, Any]:
    """Retrieve bioactivity assay summaries for a PubChem compound.

    Args:
        cid: PubChem Compound ID.

    Returns:
        List of bioassays with activity outcomes, target names, and assay
        descriptions (capped at 50 entries for readability).
    """
    try:
        url = f"{PUBCHEM_PUG}/compound/cid/{cid}/assaysummary/JSON"
        data = await async_http_get(url, timeout=60.0)

        table = data.get("Table", {})
        columns = table.get("Columns", {}).get("Column", [])
        rows = table.get("Row", [])

        # Build structured records
        activities: list[dict[str, Any]] = []
        for row in rows[:50]:
            cells = row.get("Cell", [])
            record: dict[str, Any] = {}
            for i, col_name in enumerate(columns):
                if i < len(cells):
                    record[col_name] = cells[i]
            activities.append(record)

        active_count = sum(
            1 for a in activities
            if str(a.get("Activity Outcome", "")).lower() == "active"
        )

        summary = (
            f"Bioactivity for CID {cid}: {len(rows)} assays total, "
            f"showing {len(activities)}. "
            f"{active_count} active."
        )
        return standard_response(
            summary=summary,
            raw_data={
                "cid": cid,
                "total_assays": len(rows),
                "shown": len(activities),
                "active_count": active_count,
                "activities": activities,
            },
            source="PubChem",
            source_id=str(cid),
            confidence=0.88,
        )
    except Exception as exc:
        return handle_error("get_compound_bioactivity", exc)


@mcp.tool()
async def get_compound_safety(cid: int) -> dict[str, Any]:
    """Retrieve GHS hazard classification and safety data for a PubChem compound.

    Args:
        cid: PubChem Compound ID.

    Returns:
        GHS hazard codes, pictograms, signal word, and hazard statements.
    """
    try:
        # Use the PUG View API for GHS data
        url = (
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/"
            f"{cid}/JSON?heading=GHS+Classification"
        )
        data = await async_http_get(url, timeout=45.0)

        # Navigate the nested PUG View structure to extract GHS info
        record = data.get("Record", {})
        sections = record.get("Section", [])

        ghs_info: dict[str, Any] = {
            "cid": cid,
            "hazard_statements": [],
            "precautionary_statements": [],
            "pictograms": [],
            "signal_word": None,
        }

        def _extract_sections(secs: list[dict]) -> None:
            for sec in secs:
                heading = sec.get("TOCHeading", "")
                # Recurse into child sections
                if "Section" in sec:
                    _extract_sections(sec["Section"])

                for info in sec.get("Information", []):
                    name = info.get("Name", "")
                    val = info.get("Value", {})
                    strings = val.get("StringWithMarkup", [])
                    text_vals = [s.get("String", "") for s in strings if s.get("String")]

                    if "Signal" in name:
                        ghs_info["signal_word"] = text_vals[0] if text_vals else None
                    elif "Pictogram" in name:
                        # Extract pictogram markup references
                        for s in strings:
                            for markup in s.get("Markup", []):
                                extra = markup.get("Extra", "")
                                if extra:
                                    ghs_info["pictograms"].append(extra)
                    elif "Hazard Statements" in heading or "GHS Hazard Statements" in name:
                        ghs_info["hazard_statements"].extend(text_vals)
                    elif "Precautionary" in name:
                        ghs_info["precautionary_statements"].extend(text_vals)

        _extract_sections(sections)

        # Deduplicate
        ghs_info["hazard_statements"] = list(set(ghs_info["hazard_statements"]))
        ghs_info["precautionary_statements"] = list(set(ghs_info["precautionary_statements"]))
        ghs_info["pictograms"] = list(set(ghs_info["pictograms"]))

        n_hazards = len(ghs_info["hazard_statements"])
        summary = (
            f"GHS safety for CID {cid}: "
            f"signal={ghs_info['signal_word'] or 'N/A'}, "
            f"{n_hazards} hazard statement(s), "
            f"{len(ghs_info['pictograms'])} pictogram(s)"
        )
        return standard_response(
            summary=summary,
            raw_data=ghs_info,
            source="PubChem",
            source_id=str(cid),
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_compound_safety", exc)


# ===== ZINC database tool ===================================================


@mcp.tool()
async def search_zinc(
    smiles: str,
    similarity: float = 0.7,
) -> dict[str, Any]:
    """Search the ZINC database for commercially-available compounds similar to a query.

    Args:
        smiles: SMILES of the query molecule.
        similarity: Minimum Tanimoto similarity threshold (0.0-1.0).

    Returns:
        List of ZINC hits with IDs, SMILES, similarity scores, and vendor
        availability.
    """
    try:
        quote(smiles, safe="")
        url = f"{ZINC_API}/substances/search/"
        params = {
            "q": smiles,
            "similarity": str(similarity),
            "output_format": "json",
        }
        data = await async_http_get(url, params=params, timeout=60.0)

        # ZINC returns a list or a dict depending on the endpoint version
        results: list[dict[str, Any]] = []
        if isinstance(data, list):
            results = data[:50]
        elif isinstance(data, dict):
            results = data.get("results", data.get("substances", []))[:50]

        hits: list[dict[str, Any]] = []
        for item in results:
            hits.append({
                "zinc_id": item.get("zinc_id") or item.get("id"),
                "smiles": item.get("smiles"),
                "similarity": item.get("similarity"),
                "purchasable": item.get("purchasable") or item.get("purchasability"),
                "name": item.get("name"),
            })

        summary = (
            f"ZINC search for similarity >= {similarity}: "
            f"{len(hits)} hit(s) found"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "query_smiles": smiles,
                "similarity_threshold": similarity,
                "num_hits": len(hits),
                "hits": hits,
            },
            source="ZINC15",
            source_id=smiles,
            confidence=0.80,
        )
    except Exception as exc:
        return handle_error("search_zinc", exc)


# ===== Molecular conversion tool ============================================


@mcp.tool()
async def convert_molecule(
    input_str: str,
    input_format: str = "smiles",
    output_format: str = "inchi",
) -> dict[str, Any]:
    """Convert a molecule between SMILES, InChI, and InChIKey representations.

    Args:
        input_str: Molecule string in the specified input format.
        input_format: Input format -- 'smiles' or 'inchi'.
        output_format: Desired output format -- 'smiles', 'inchi', or 'inchikey'.

    Returns:
        Converted molecule string in the requested format, along with all
        available representations.
    """
    try:
        _require_rdkit()

        fmt_in = input_format.lower().strip()
        fmt_out = output_format.lower().strip()

        # Parse input
        mol = None
        if fmt_in == "smiles":
            mol = Chem.MolFromSmiles(input_str)
        elif fmt_in == "inchi":
            mol = Chem.MolFromInchi(input_str) if hasattr(Chem, "MolFromInchi") else None
            if mol is None:
                from rdkit.Chem.inchi import MolFromInchi
                mol = MolFromInchi(input_str)
        else:
            return handle_error(
                "convert_molecule",
                f"Unsupported input format '{input_format}'. Use 'smiles' or 'inchi'.",
            )

        if mol is None:
            return handle_error(
                "convert_molecule",
                f"Could not parse input as {input_format}: '{input_str}'",
            )

        # Generate all representations
        canonical_smiles = Chem.MolToSmiles(mol)

        try:
            from rdkit.Chem.inchi import MolToInchi, InchiToInchiKey
            inchi = MolToInchi(mol)
            inchikey = InchiToInchiKey(inchi) if inchi else None
        except ImportError:
            inchi = Chem.MolToInchi(mol) if hasattr(Chem, "MolToInchi") else None
            inchikey = Chem.InchiToInchiKey(inchi) if inchi and hasattr(Chem, "InchiToInchiKey") else None

        all_representations = {
            "smiles": canonical_smiles,
            "inchi": inchi,
            "inchikey": inchikey,
        }

        # Select requested output
        output_value = all_representations.get(fmt_out)
        if output_value is None and fmt_out not in all_representations:
            return handle_error(
                "convert_molecule",
                f"Unsupported output format '{output_format}'. Use 'smiles', 'inchi', or 'inchikey'.",
            )

        summary = (
            f"Converted {input_format} -> {output_format}: {output_value}"
        )
        return standard_response(
            summary=summary,
            raw_data={
                "input": input_str,
                "input_format": fmt_in,
                "output_format": fmt_out,
                "output_value": output_value,
                "all_representations": all_representations,
            },
            source="RDKit",
            source_id=canonical_smiles,
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("convert_molecule", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
