"""
Clinical & Drug MCP Server — Lumi Virtual Lab

Exposes tools for querying clinical and pharmacological databases:
  ClinicalTrials.gov, PubMed, ChEMBL, OpenFDA, DailyMed.

Start with:  python -m src.mcp_servers.clinical.server
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

CLINICALTRIALS_API = "https://clinicaltrials.gov/api/v2/studies"
NCBI_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CHEMBL_API = "https://www.ebi.ac.uk/chembl/api/data"
OPENFDA_API = "https://api.fda.gov"
DAILYMED_API = "https://dailymed.nlm.nih.gov/dailymed/services/v2"

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi Clinical & Drug",
    instructions=(
        "Clinical trial, drug, and pharmacological database queries: "
        "ClinicalTrials.gov, PubMed, ChEMBL, OpenFDA, DailyMed"
    ),
)


# ---- 1. ClinicalTrials.gov: search trials -----------------------------------


@mcp.tool()
async def search_trials(
    condition: str,
    intervention: str | None = None,
    status: str | None = None,
    max_results: int = 20,
) -> dict[str, Any]:
    """
    Search ClinicalTrials.gov for clinical studies matching a condition.

    Args:
        condition: Disease or condition to search for (e.g. 'lung cancer').
        intervention: Optional intervention/drug to filter by.
        status: Optional overall status filter (e.g. 'RECRUITING', 'COMPLETED').
        max_results: Maximum number of results to return (default 20, max 100).
    """
    try:
        params: dict[str, Any] = {
            "query.cond": condition,
            "pageSize": min(max_results, 100),
        }
        if intervention:
            params["query.intr"] = intervention
        if status:
            params["filter.overallStatus"] = status

        headers = {"Accept": "application/json"}
        data = await async_http_get(CLINICALTRIALS_API, params=params, headers=headers)

        studies = data.get("studies", [])
        parsed_trials = []
        for study in studies:
            proto = study.get("protocolSection", {})
            id_module = proto.get("identificationModule", {})
            status_module = proto.get("statusModule", {})
            design_module = proto.get("designModule", {})
            conditions_module = proto.get("conditionsModule", {})
            arms_module = proto.get("armsInterventionsModule", {})

            nct_id = id_module.get("nctId", "N/A")
            title = id_module.get("briefTitle", "N/A")
            phase_list = design_module.get("phases", [])
            phase = ", ".join(phase_list) if phase_list else "N/A"
            overall_status = status_module.get("overallStatus", "N/A")
            enrollment_info = design_module.get("enrollmentInfo", {})
            enrollment = enrollment_info.get("count", "N/A") if isinstance(enrollment_info, dict) else "N/A"
            conds = conditions_module.get("conditions", [])
            interventions = []
            for arm in arms_module.get("interventions", []):
                interventions.append(f"{arm.get('type', '')}: {arm.get('name', '')}")

            parsed_trials.append({
                "nct_id": nct_id,
                "title": title,
                "phase": phase,
                "status": overall_status,
                "enrollment": enrollment,
                "conditions": conds,
                "interventions": interventions,
            })

        summary = (
            f"Found {len(parsed_trials)} clinical trials for '{condition}'"
            + (f" with intervention '{intervention}'" if intervention else "")
            + (f" (status: {status})" if status else "")
            + "."
        )
        if parsed_trials:
            top = parsed_trials[0]
            summary += f" Top result: {top['nct_id']} — {top['title']} ({top['phase']}, {top['status']})."

        return standard_response(
            summary=summary,
            raw_data={"total_returned": len(parsed_trials), "trials": parsed_trials},
            source="ClinicalTrials.gov",
            source_id=condition,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("search_trials", exc)


# ---- 2. ClinicalTrials.gov: trial details -----------------------------------


@mcp.tool()
async def get_trial_details(nct_id: str) -> dict[str, Any]:
    """
    Retrieve full details for a specific clinical trial by NCT ID.

    Args:
        nct_id: ClinicalTrials.gov identifier (e.g. NCT04280705).
    """
    try:
        url = f"{CLINICALTRIALS_API}/{nct_id}"
        headers = {"Accept": "application/json"}
        data = await async_http_get(url, headers=headers)

        proto = data.get("protocolSection", {})
        id_module = proto.get("identificationModule", {})
        status_module = proto.get("statusModule", {})
        desc_module = proto.get("descriptionModule", {})
        design_module = proto.get("designModule", {})
        eligibility = proto.get("eligibilityModule", {})
        contacts = proto.get("contactsLocationsModule", {})
        outcomes_module = proto.get("outcomesModule", {})

        title = id_module.get("briefTitle", "N/A")
        official_title = id_module.get("officialTitle", "N/A")
        overall_status = status_module.get("overallStatus", "N/A")
        brief_summary = desc_module.get("briefSummary", "N/A")
        phase_list = design_module.get("phases", [])
        phase = ", ".join(phase_list) if phase_list else "N/A"
        study_type = design_module.get("studyType", "N/A")
        eligibility_criteria = eligibility.get("eligibilityCriteria", "N/A")

        primary_outcomes = []
        for outcome in outcomes_module.get("primaryOutcomes", []):
            primary_outcomes.append({
                "measure": outcome.get("measure", ""),
                "timeFrame": outcome.get("timeFrame", ""),
            })

        locations = []
        for loc in contacts.get("locations", [])[:10]:
            locations.append({
                "facility": loc.get("facility", ""),
                "city": loc.get("city", ""),
                "country": loc.get("country", ""),
            })

        summary = (
            f"{nct_id}: {title}. Phase: {phase}, Status: {overall_status}, "
            f"Type: {study_type}. {len(primary_outcomes)} primary outcomes, "
            f"{len(locations)} locations."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "nct_id": nct_id,
                "title": title,
                "official_title": official_title,
                "status": overall_status,
                "phase": phase,
                "study_type": study_type,
                "brief_summary": brief_summary,
                "eligibility_criteria": eligibility_criteria,
                "primary_outcomes": primary_outcomes,
                "locations": locations,
                "full_protocol": proto,
            },
            source="ClinicalTrials.gov",
            source_id=nct_id,
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("get_trial_details", exc)


# ---- 3. ClinicalTrials.gov: search by target gene ---------------------------


@mcp.tool()
async def search_trials_by_target(target_gene: str) -> dict[str, Any]:
    """
    Search ClinicalTrials.gov for trials involving a specific gene target.

    Searches for the gene name as an intervention keyword.

    Args:
        target_gene: Gene or target name (e.g. 'EGFR', 'PD-L1', 'HER2').
    """
    try:
        params: dict[str, Any] = {
            "query.intr": target_gene,
            "pageSize": 20,
        }
        headers = {"Accept": "application/json"}
        data = await async_http_get(CLINICALTRIALS_API, params=params, headers=headers)

        studies = data.get("studies", [])
        parsed_trials = []
        for study in studies:
            proto = study.get("protocolSection", {})
            id_module = proto.get("identificationModule", {})
            status_module = proto.get("statusModule", {})
            design_module = proto.get("designModule", {})
            conditions_module = proto.get("conditionsModule", {})

            nct_id = id_module.get("nctId", "N/A")
            title = id_module.get("briefTitle", "N/A")
            phase_list = design_module.get("phases", [])
            phase = ", ".join(phase_list) if phase_list else "N/A"
            overall_status = status_module.get("overallStatus", "N/A")
            conds = conditions_module.get("conditions", [])

            parsed_trials.append({
                "nct_id": nct_id,
                "title": title,
                "phase": phase,
                "status": overall_status,
                "conditions": conds,
            })

        # Summarise phase distribution
        phase_counts: dict[str, int] = {}
        for trial in parsed_trials:
            p = trial["phase"]
            phase_counts[p] = phase_counts.get(p, 0) + 1
        phase_str = ", ".join(f"{k}: {v}" for k, v in sorted(phase_counts.items()))

        summary = (
            f"Found {len(parsed_trials)} trials targeting '{target_gene}'. "
            f"Phase distribution: {phase_str or 'N/A'}."
        )

        return standard_response(
            summary=summary,
            raw_data={"target_gene": target_gene, "total": len(parsed_trials), "trials": parsed_trials},
            source="ClinicalTrials.gov",
            source_id=target_gene,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("search_trials_by_target", exc)


# ---- 4. PubMed: search articles ---------------------------------------------


@mcp.tool()
async def search_pubmed(query: str, max_results: int = 20) -> dict[str, Any]:
    """
    Search PubMed for articles matching a query and return titles and abstracts.

    Args:
        query: Search query (e.g. 'BRCA1 breast cancer therapy').
        max_results: Maximum number of results (default 20, max 100).
    """
    try:
        max_results = min(max_results, 100)

        # Step 1: esearch to get PMIDs
        search_url = f"{NCBI_EUTILS}/esearch.fcgi"
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
            "sort": "relevance",
        }
        search_data = await async_http_get(search_url, params=search_params)

        id_list = search_data.get("esearchresult", {}).get("idlist", [])
        total_count = int(search_data.get("esearchresult", {}).get("count", 0))

        if not id_list:
            return standard_response(
                summary=f"No PubMed articles found for query: '{query}'.",
                raw_data={"query": query, "count": 0, "articles": []},
                source="PubMed (NCBI)",
                source_id=query,
                confidence=0.7,
            )

        # Step 2: efetch for abstracts (plain text)
        ids_str = ",".join(id_list)
        fetch_url = f"{NCBI_EUTILS}/efetch.fcgi"
        fetch_params = {
            "db": "pubmed",
            "id": ids_str,
            "rettype": "abstract",
            "retmode": "text",
        }
        fetch_data = await async_http_get(fetch_url, params=fetch_params)
        abstracts_text = fetch_data.get("text", "")

        # Step 3: esummary for structured metadata
        summary_url = f"{NCBI_EUTILS}/esummary.fcgi"
        summary_params = {
            "db": "pubmed",
            "id": ids_str,
            "retmode": "json",
        }
        summary_data = await async_http_get(summary_url, params=summary_params)

        result = summary_data.get("result", {})
        uid_list = result.get("uids", [])

        articles = []
        for uid in uid_list:
            entry = result.get(uid, {})
            authors = entry.get("authors", [])
            author_names = [a.get("name", "") for a in authors[:5]] if isinstance(authors, list) else []
            articles.append({
                "pmid": uid,
                "title": entry.get("title", "N/A"),
                "authors": author_names,
                "journal": entry.get("fulljournalname", entry.get("source", "N/A")),
                "pub_date": entry.get("pubdate", "N/A"),
                "doi": entry.get("elocationid", ""),
            })

        summary = (
            f"PubMed search for '{query}': {total_count} total results, "
            f"retrieved {len(articles)} articles."
        )
        if articles:
            summary += f" Most relevant: \"{articles[0]['title']}\" ({articles[0]['pub_date']})."

        return standard_response(
            summary=summary,
            raw_data={
                "query": query,
                "total_count": total_count,
                "articles": articles,
                "abstracts_text": abstracts_text[:5000],
            },
            source="PubMed (NCBI)",
            source_id=query,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("search_pubmed", exc)


# ---- 5. PubMed: article details ---------------------------------------------


@mcp.tool()
async def get_article_details(pmid: str) -> dict[str, Any]:
    """
    Retrieve detailed metadata for a PubMed article by PMID.

    Args:
        pmid: PubMed identifier (e.g. '33087860').
    """
    try:
        url = f"{NCBI_EUTILS}/esummary.fcgi"
        params = {
            "db": "pubmed",
            "id": pmid,
            "retmode": "json",
        }
        data = await async_http_get(url, params=params)

        result = data.get("result", {})
        entry = result.get(pmid, {})

        if not entry or "error" in entry:
            return standard_response(
                summary=f"No PubMed article found for PMID {pmid}.",
                raw_data={"pmid": pmid},
                source="PubMed (NCBI)",
                source_id=pmid,
                confidence=0.5,
            )

        title = entry.get("title", "N/A")
        authors = entry.get("authors", [])
        author_names = [a.get("name", "") for a in authors] if isinstance(authors, list) else []
        journal = entry.get("fulljournalname", entry.get("source", "N/A"))
        pub_date = entry.get("pubdate", "N/A")
        doi = entry.get("elocationid", "")
        pub_type = entry.get("pubtype", [])
        lang = entry.get("lang", [])
        issue = entry.get("issue", "")
        volume = entry.get("volume", "")
        pages = entry.get("pages", "")

        # Fetch abstract text
        fetch_url = f"{NCBI_EUTILS}/efetch.fcgi"
        fetch_params = {
            "db": "pubmed",
            "id": pmid,
            "rettype": "abstract",
            "retmode": "text",
        }
        fetch_data = await async_http_get(fetch_url, params=fetch_params)
        abstract_text = fetch_data.get("text", "")

        summary = (
            f"PMID {pmid}: \"{title}\" by {', '.join(author_names[:3])}"
            + (" et al." if len(author_names) > 3 else "")
            + f". {journal} ({pub_date})."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "pmid": pmid,
                "title": title,
                "authors": author_names,
                "journal": journal,
                "pub_date": pub_date,
                "doi": doi,
                "volume": volume,
                "issue": issue,
                "pages": pages,
                "pub_type": pub_type,
                "language": lang,
                "abstract": abstract_text.strip()[:3000],
                "full_metadata": entry,
            },
            source="PubMed (NCBI)",
            source_id=pmid,
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("get_article_details", exc)


# ---- 6. ChEMBL: compounds targeting a protein -------------------------------


@mcp.tool()
async def get_target_compounds(target_name: str) -> dict[str, Any]:
    """
    Find compounds with bioactivity data against a named target in ChEMBL.

    Resolves the target name to a ChEMBL target ID, then retrieves associated
    bioactivity records including pChEMBL values.

    Args:
        target_name: Name of the biological target (e.g. 'EGFR', 'Cyclooxygenase-2').
    """
    try:
        headers = {"Accept": "application/json"}

        # Step 1: Resolve target name to ChEMBL target ID
        target_url = f"{CHEMBL_API}/target/search.json"
        target_params = {"q": target_name, "limit": 1}
        target_data = await async_http_get(target_url, params=target_params, headers=headers)

        targets = target_data.get("targets", [])
        if not targets:
            return standard_response(
                summary=f"No ChEMBL target found for '{target_name}'.",
                raw_data={"target_name": target_name},
                source="ChEMBL",
                source_id=target_name,
                confidence=0.5,
            )

        target_info = targets[0]
        target_chembl_id = target_info.get("target_chembl_id", "")
        target_pref_name = target_info.get("pref_name", target_name)
        organism = target_info.get("organism", "N/A")

        # Step 2: Get bioactivity data
        activity_url = f"{CHEMBL_API}/activity.json"
        activity_params = {
            "target_chembl_id": target_chembl_id,
            "limit": 20,
        }
        activity_data = await async_http_get(activity_url, params=activity_params, headers=headers)

        activities = activity_data.get("activities", [])
        compounds = []
        for act in activities:
            compounds.append({
                "molecule_chembl_id": act.get("molecule_chembl_id", ""),
                "molecule_name": act.get("molecule_pref_name", "N/A"),
                "standard_type": act.get("standard_type", ""),
                "standard_value": act.get("standard_value", ""),
                "standard_units": act.get("standard_units", ""),
                "pchembl_value": act.get("pchembl_value", None),
                "assay_type": act.get("assay_type", ""),
                "assay_description": act.get("assay_description", ""),
            })

        # Summarise top compounds by pChEMBL
        active = [c for c in compounds if c["pchembl_value"] is not None]
        active.sort(key=lambda x: float(x["pchembl_value"] or 0), reverse=True)

        summary = (
            f"ChEMBL target '{target_pref_name}' ({target_chembl_id}, {organism}): "
            f"{len(compounds)} bioactivity records retrieved, "
            f"{len(active)} with pChEMBL values."
        )
        if active:
            top = active[0]
            summary += (
                f" Most potent: {top['molecule_name'] or top['molecule_chembl_id']} "
                f"(pChEMBL={top['pchembl_value']})."
            )

        return standard_response(
            summary=summary,
            raw_data={
                "target": {
                    "chembl_id": target_chembl_id,
                    "name": target_pref_name,
                    "organism": organism,
                },
                "compounds": compounds,
            },
            source="ChEMBL",
            source_id=target_chembl_id,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_target_compounds", exc)


# ---- 7. ChEMBL: compound information ----------------------------------------


@mcp.tool()
async def get_compound_info(chembl_id: str) -> dict[str, Any]:
    """
    Retrieve detailed compound/molecule information from ChEMBL.

    Args:
        chembl_id: ChEMBL molecule ID (e.g. CHEMBL25, CHEMBL941).
    """
    try:
        url = f"{CHEMBL_API}/molecule/{chembl_id}.json"
        headers = {"Accept": "application/json"}
        data = await async_http_get(url, headers=headers)

        pref_name = data.get("pref_name", "N/A")
        mol_type = data.get("molecule_type", "N/A")
        max_phase = data.get("max_phase", "N/A")
        first_approval = data.get("first_approval", "N/A")
        oral = data.get("oral", False)
        parenteral = data.get("parenteral", False)
        topical = data.get("topical", False)

        properties = data.get("molecule_properties", {}) or {}
        mw = properties.get("full_mwt", "N/A")
        alogp = properties.get("alogp", "N/A")
        hba = properties.get("hba", "N/A")
        hbd = properties.get("hbd", "N/A")
        psa = properties.get("psa", "N/A")
        ro5 = properties.get("num_ro5_violations", "N/A")
        smiles = data.get("molecule_structures", {}).get("canonical_smiles", "") if data.get("molecule_structures") else ""

        routes = []
        if oral:
            routes.append("oral")
        if parenteral:
            routes.append("parenteral")
        if topical:
            routes.append("topical")

        summary = (
            f"{chembl_id} ({pref_name}): {mol_type}, max phase {max_phase}"
            + (f", first approved {first_approval}" if first_approval and first_approval != "N/A" else "")
            + f". MW={mw}, ALogP={alogp}, HBA={hba}, HBD={hbd}, PSA={psa}, RO5 violations={ro5}."
            + (f" Routes: {', '.join(routes)}." if routes else "")
        )

        return standard_response(
            summary=summary,
            raw_data={
                "chembl_id": chembl_id,
                "name": pref_name,
                "molecule_type": mol_type,
                "max_phase": max_phase,
                "first_approval": first_approval,
                "routes": routes,
                "properties": {
                    "molecular_weight": mw,
                    "alogp": alogp,
                    "hba": hba,
                    "hbd": hbd,
                    "psa": psa,
                    "ro5_violations": ro5,
                    "smiles": smiles,
                },
                "full_data": data,
            },
            source="ChEMBL",
            source_id=chembl_id,
            confidence=0.95,
        )
    except Exception as exc:
        return handle_error("get_compound_info", exc)


# ---- 8. ChEMBL: drug search by name -----------------------------------------


@mcp.tool()
async def get_drug_info(drug_name: str) -> dict[str, Any]:
    """
    Search ChEMBL for a drug or molecule by name and return matching records.

    Args:
        drug_name: Drug or compound name (e.g. 'aspirin', 'imatinib').
    """
    try:
        url = f"{CHEMBL_API}/molecule/search.json"
        params = {"q": drug_name, "limit": 5}
        headers = {"Accept": "application/json"}
        data = await async_http_get(url, params=params, headers=headers)

        molecules = data.get("molecules", [])
        if not molecules:
            return standard_response(
                summary=f"No ChEMBL molecules found for '{drug_name}'.",
                raw_data={"drug_name": drug_name},
                source="ChEMBL",
                source_id=drug_name,
                confidence=0.5,
            )

        results = []
        for mol in molecules:
            properties = mol.get("molecule_properties", {}) or {}
            structures = mol.get("molecule_structures", {}) or {}
            results.append({
                "chembl_id": mol.get("molecule_chembl_id", ""),
                "name": mol.get("pref_name", "N/A"),
                "molecule_type": mol.get("molecule_type", "N/A"),
                "max_phase": mol.get("max_phase", "N/A"),
                "first_approval": mol.get("first_approval", None),
                "molecular_weight": properties.get("full_mwt", "N/A"),
                "smiles": structures.get("canonical_smiles", ""),
                "indication_class": mol.get("indication_class", ""),
            })

        top = results[0]
        summary = (
            f"Found {len(results)} ChEMBL matches for '{drug_name}'. "
            f"Top: {top['chembl_id']} ({top['name']}), type={top['molecule_type']}, "
            f"max phase={top['max_phase']}."
        )

        return standard_response(
            summary=summary,
            raw_data={"query": drug_name, "molecules": results},
            source="ChEMBL",
            source_id=drug_name,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_drug_info", exc)


# ---- 9. OpenFDA: adverse events ----------------------------------------------


@mcp.tool()
async def search_adverse_events(drug: str, max_results: int = 10) -> dict[str, Any]:
    """
    Search FDA Adverse Event Reporting System (FAERS) for adverse events
    associated with a drug.

    Args:
        drug: Generic drug name (e.g. 'ibuprofen', 'metformin').
        max_results: Maximum number of adverse event reports (default 10, max 100).
    """
    try:
        max_results = min(max_results, 100)
        url = f"{OPENFDA_API}/drug/event.json"
        params = {
            "search": f'patient.drug.openfda.generic_name:"{drug}"',
            "limit": max_results,
        }
        data = await async_http_get(url, params=params)

        results = data.get("results", [])
        if not results:
            return standard_response(
                summary=f"No adverse event reports found for '{drug}' in FDA FAERS.",
                raw_data={"drug": drug, "count": 0},
                source="OpenFDA FAERS",
                source_id=drug,
                confidence=0.7,
            )

        # Parse adverse event reports
        events = []
        reaction_counts: dict[str, int] = {}
        serious_count = 0

        for report in results:
            patient = report.get("patient", {})
            reactions = patient.get("reaction", [])
            drugs = patient.get("drug", [])
            is_serious = report.get("serious", 0)
            if is_serious:
                serious_count += 1

            reaction_names = []
            for r in reactions:
                name = r.get("reactionmeddrapt", "unknown")
                reaction_names.append(name)
                reaction_counts[name] = reaction_counts.get(name, 0) + 1

            drug_names = [d.get("medicinalproduct", "") for d in drugs[:5]]

            events.append({
                "report_id": report.get("safetyreportid", "N/A"),
                "serious": bool(is_serious),
                "reactions": reaction_names,
                "concomitant_drugs": drug_names,
                "receive_date": report.get("receivedate", "N/A"),
                "patient_sex": patient.get("patientsex", "N/A"),
                "patient_age": patient.get("patientonsetage", "N/A"),
            })

        # Top reactions
        top_reactions = sorted(reaction_counts.items(), key=lambda x: -x[1])[:10]
        top_str = "; ".join(f"{name} ({count})" for name, count in top_reactions)

        summary = (
            f"FDA FAERS: {len(events)} adverse event reports for '{drug}'. "
            f"{serious_count} serious. "
            f"Top reactions: {top_str}."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "drug": drug,
                "total_reports": len(events),
                "serious_count": serious_count,
                "top_reactions": dict(top_reactions),
                "events": events,
            },
            source="OpenFDA FAERS",
            source_id=drug,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("search_adverse_events", exc)


# ---- 10. OpenFDA: drug label -------------------------------------------------


@mcp.tool()
async def get_drug_label(drug: str) -> dict[str, Any]:
    """
    Retrieve FDA drug labeling information (package insert) for a drug.

    Args:
        drug: Generic drug name (e.g. 'metformin', 'atorvastatin').
    """
    try:
        url = f"{OPENFDA_API}/drug/label.json"
        params = {
            "search": f'openfda.generic_name:"{drug}"',
            "limit": 1,
        }
        data = await async_http_get(url, params=params)

        results = data.get("results", [])
        if not results:
            return standard_response(
                summary=f"No FDA drug label found for '{drug}'.",
                raw_data={"drug": drug},
                source="OpenFDA Drug Labels",
                source_id=drug,
                confidence=0.5,
            )

        label = results[0]
        openfda = label.get("openfda", {})

        # Extract key sections (each is a list of strings)
        sections = {}
        section_keys = [
            "indications_and_usage",
            "dosage_and_administration",
            "contraindications",
            "warnings_and_cautions",
            "warnings",
            "adverse_reactions",
            "drug_interactions",
            "mechanism_of_action",
            "pharmacodynamics",
            "pharmacokinetics",
            "boxed_warning",
            "pregnancy",
            "pediatric_use",
            "geriatric_use",
        ]
        for key in section_keys:
            val = label.get(key)
            if val:
                sections[key] = val[0][:2000] if isinstance(val, list) and val else str(val)[:2000]

        brand_names = openfda.get("brand_name", [])
        generic_names = openfda.get("generic_name", [])
        manufacturer = openfda.get("manufacturer_name", [])
        route = openfda.get("route", [])
        pharm_class = openfda.get("pharm_class_epc", [])

        summary = (
            f"FDA label for '{drug}': "
            f"brand={', '.join(brand_names[:3]) if brand_names else 'N/A'}, "
            f"manufacturer={', '.join(manufacturer[:2]) if manufacturer else 'N/A'}, "
            f"route={', '.join(route[:2]) if route else 'N/A'}, "
            f"class={', '.join(pharm_class[:2]) if pharm_class else 'N/A'}. "
            f"{len(sections)} label sections retrieved."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "drug": drug,
                "brand_names": brand_names,
                "generic_names": generic_names,
                "manufacturer": manufacturer,
                "route": route,
                "pharm_class": pharm_class,
                "sections": sections,
            },
            source="OpenFDA Drug Labels",
            source_id=drug,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("get_drug_label", exc)


# ---- 11. DailyMed: drug label sections ---------------------------------------


@mcp.tool()
async def get_drug_label_sections(drug: str) -> dict[str, Any]:
    """
    Retrieve drug label information from DailyMed (NLM) for a given drug name.

    Returns structured product labeling (SPL) entries with set IDs.

    Args:
        drug: Drug name to search for (e.g. 'metformin', 'lisinopril').
    """
    try:
        url = f"{DAILYMED_API}/spls.json"
        params = {"drug_name": drug}
        headers = {"Accept": "application/json"}
        data = await async_http_get(url, params=params, headers=headers)

        spl_data = data.get("data", [])
        if not spl_data:
            return standard_response(
                summary=f"No DailyMed labels found for '{drug}'.",
                raw_data={"drug": drug},
                source="DailyMed (NLM)",
                source_id=drug,
                confidence=0.5,
            )

        labels = []
        for spl in spl_data[:10]:
            set_id = spl.get("setid", "")
            title = spl.get("title", "N/A")
            published = spl.get("published_date", "N/A")
            labeler = spl.get("labeler", "N/A")

            labels.append({
                "set_id": set_id,
                "title": title,
                "published_date": published,
                "labeler": labeler,
            })

        summary = (
            f"DailyMed: {len(spl_data)} labeling entries for '{drug}'. "
            f"Top result: \"{labels[0]['title']}\" by {labels[0]['labeler']} "
            f"(published {labels[0]['published_date']})."
        )

        return standard_response(
            summary=summary,
            raw_data={
                "drug": drug,
                "total_count": len(spl_data),
                "labels": labels,
            },
            source="DailyMed (NLM)",
            source_id=drug,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_drug_label_sections", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
