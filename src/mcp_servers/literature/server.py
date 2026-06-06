"""
Literature MCP Server — Lumi Virtual Lab

Exposes tools for querying scientific literature databases:
  Semantic Scholar, bioRxiv/medRxiv, Europe PMC.

Start with:  python -m src.mcp_servers.literature.server
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

SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
BIORXIV_API = "https://api.biorxiv.org"
EUROPE_PMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest"

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Lumi Literature",
    instructions=(
        "Scientific literature queries: "
        "Semantic Scholar, bioRxiv/medRxiv, Europe PMC"
    ),
)


# ---- 1. Semantic Scholar: search papers --------------------------------------


@mcp.tool()
async def search_papers(
    query: str,
    year_range: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """
    Search Semantic Scholar for academic papers matching a query.

    Args:
        query: Search query (e.g. 'CRISPR gene therapy delivery').
        year_range: Optional year range filter (e.g. '2020-2025').
        max_results: Maximum number of results (default 10, max 100).
    """
    try:
        max_results = min(max_results, 100)
        url = f"{SEMANTIC_SCHOLAR_API}/paper/search"
        params: dict[str, Any] = {
            "query": query,
            "limit": max_results,
            "fields": "title,abstract,year,citationCount,authors,journal,externalIds",
        }
        if year_range:
            params["year"] = year_range

        headers = {"Accept": "application/json"}
        data = await async_http_get(url, params=params, headers=headers)

        total = data.get("total", 0)
        papers_raw = data.get("data", [])

        papers = []
        for p in papers_raw:
            authors = p.get("authors", [])
            author_names = [a.get("name", "") for a in authors[:5]] if isinstance(authors, list) else []
            external_ids = p.get("externalIds", {}) or {}
            journal_info = p.get("journal", {}) or {}

            papers.append({
                "paper_id": p.get("paperId", ""),
                "title": p.get("title", "N/A"),
                "abstract": (p.get("abstract") or "")[:500],
                "year": p.get("year"),
                "citation_count": p.get("citationCount", 0),
                "authors": author_names,
                "journal": journal_info.get("name", "N/A") if isinstance(journal_info, dict) else "N/A",
                "doi": external_ids.get("DOI", ""),
                "pmid": external_ids.get("PubMed", ""),
                "arxiv_id": external_ids.get("ArXiv", ""),
            })

        summary = (
            f"Semantic Scholar: {total} total results for '{query}'"
            + (f" ({year_range})" if year_range else "")
            + f", retrieved {len(papers)}."
        )
        if papers:
            top = papers[0]
            summary += (
                f" Top result: \"{top['title']}\" ({top['year']}, "
                f"{top['citation_count']} citations)."
            )

        return standard_response(
            summary=summary,
            raw_data={"query": query, "total": total, "papers": papers},
            source="Semantic Scholar",
            source_id=query,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("search_papers", exc)


# ---- 2. Semantic Scholar: paper details --------------------------------------


@mcp.tool()
async def get_paper_details(paper_id: str) -> dict[str, Any]:
    """
    Retrieve detailed metadata for a paper from Semantic Scholar.

    Args:
        paper_id: Semantic Scholar paper ID, DOI, ArXiv ID, or 'PMID:12345'.
    """
    try:
        url = f"{SEMANTIC_SCHOLAR_API}/paper/{paper_id}"
        params = {
            "fields": (
                "title,abstract,year,citationCount,referenceCount,"
                "authors,journal,externalIds,tldr,fieldsOfStudy"
            ),
        }
        headers = {"Accept": "application/json"}
        data = await async_http_get(url, params=params, headers=headers)

        title = data.get("title", "N/A")
        abstract = data.get("abstract", "")
        year = data.get("year")
        citation_count = data.get("citationCount", 0)
        reference_count = data.get("referenceCount", 0)
        authors = data.get("authors", [])
        author_names = [a.get("name", "") for a in authors] if isinstance(authors, list) else []
        journal_info = data.get("journal", {}) or {}
        journal_name = journal_info.get("name", "N/A") if isinstance(journal_info, dict) else "N/A"
        external_ids = data.get("externalIds", {}) or {}
        tldr = data.get("tldr", {}) or {}
        tldr_text = tldr.get("text", "") if isinstance(tldr, dict) else ""
        fields = data.get("fieldsOfStudy", []) or []

        summary = (
            f"\"{title}\" ({year}). "
            f"Authors: {', '.join(author_names[:3])}"
            + (" et al." if len(author_names) > 3 else "")
            + f". {journal_name}. "
            f"{citation_count} citations, {reference_count} references. "
            f"Fields: {', '.join(fields[:5]) if fields else 'N/A'}."
        )
        if tldr_text:
            summary += f" TL;DR: {tldr_text}"

        return standard_response(
            summary=summary,
            raw_data={
                "paper_id": data.get("paperId", paper_id),
                "title": title,
                "abstract": abstract,
                "year": year,
                "citation_count": citation_count,
                "reference_count": reference_count,
                "authors": author_names,
                "journal": journal_name,
                "doi": external_ids.get("DOI", ""),
                "pmid": external_ids.get("PubMed", ""),
                "tldr": tldr_text,
                "fields_of_study": fields,
            },
            source="Semantic Scholar",
            source_id=data.get("paperId", paper_id),
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("get_paper_details", exc)


# ---- 3. Semantic Scholar: citations -----------------------------------------


@mcp.tool()
async def get_citations(paper_id: str, max_results: int = 20) -> dict[str, Any]:
    """
    Get papers that cite a given paper (forward citations) from Semantic Scholar.

    Args:
        paper_id: Semantic Scholar paper ID, DOI, or 'PMID:12345'.
        max_results: Maximum citations to return (default 20, max 1000).
    """
    try:
        max_results = min(max_results, 1000)
        url = f"{SEMANTIC_SCHOLAR_API}/paper/{paper_id}/citations"
        params = {
            "fields": "title,year,citationCount,authors",
            "limit": max_results,
        }
        headers = {"Accept": "application/json"}
        data = await async_http_get(url, params=params, headers=headers)

        citations_raw = data.get("data", [])
        citations = []
        for entry in citations_raw:
            citing = entry.get("citingPaper", {})
            authors = citing.get("authors", [])
            author_names = [a.get("name", "") for a in authors[:3]] if isinstance(authors, list) else []
            citations.append({
                "paper_id": citing.get("paperId", ""),
                "title": citing.get("title", "N/A"),
                "year": citing.get("year"),
                "citation_count": citing.get("citationCount", 0),
                "authors": author_names,
            })

        # Year distribution
        year_counts: dict[int, int] = {}
        for c in citations:
            y = c.get("year")
            if y:
                year_counts[y] = year_counts.get(y, 0) + 1

        recent_years = sorted(year_counts.items(), reverse=True)[:5]
        year_str = ", ".join(f"{y}: {n}" for y, n in recent_years)

        summary = (
            f"{len(citations)} citing papers retrieved for {paper_id}. "
            f"Year distribution (recent): {year_str or 'N/A'}."
        )
        if citations:
            most_cited = max(citations, key=lambda x: x.get("citation_count", 0))
            summary += (
                f" Most-cited citing paper: \"{most_cited['title']}\" "
                f"({most_cited['year']}, {most_cited['citation_count']} citations)."
            )

        return standard_response(
            summary=summary,
            raw_data={
                "paper_id": paper_id,
                "total_returned": len(citations),
                "citations": citations,
                "year_distribution": dict(sorted(year_counts.items())),
            },
            source="Semantic Scholar",
            source_id=paper_id,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_citations", exc)


# ---- 4. Semantic Scholar: references ----------------------------------------


@mcp.tool()
async def get_references(paper_id: str, max_results: int = 20) -> dict[str, Any]:
    """
    Get papers referenced by a given paper (backward references) from Semantic Scholar.

    Args:
        paper_id: Semantic Scholar paper ID, DOI, or 'PMID:12345'.
        max_results: Maximum references to return (default 20, max 1000).
    """
    try:
        max_results = min(max_results, 1000)
        url = f"{SEMANTIC_SCHOLAR_API}/paper/{paper_id}/references"
        params = {
            "fields": "title,year,citationCount,authors",
            "limit": max_results,
        }
        headers = {"Accept": "application/json"}
        data = await async_http_get(url, params=params, headers=headers)

        refs_raw = data.get("data", [])
        references = []
        for entry in refs_raw:
            cited = entry.get("citedPaper", {})
            authors = cited.get("authors", [])
            author_names = [a.get("name", "") for a in authors[:3]] if isinstance(authors, list) else []
            references.append({
                "paper_id": cited.get("paperId", ""),
                "title": cited.get("title", "N/A"),
                "year": cited.get("year"),
                "citation_count": cited.get("citationCount", 0),
                "authors": author_names,
            })

        # Year distribution
        year_counts: dict[int, int] = {}
        for r in references:
            y = r.get("year")
            if y:
                year_counts[y] = year_counts.get(y, 0) + 1

        summary = (
            f"{len(references)} references retrieved for {paper_id}. "
            f"Year range: {min(year_counts.keys()) if year_counts else 'N/A'}"
            f"–{max(year_counts.keys()) if year_counts else 'N/A'}."
        )
        if references:
            most_cited = max(references, key=lambda x: x.get("citation_count", 0))
            summary += (
                f" Most influential reference: \"{most_cited['title']}\" "
                f"({most_cited['year']}, {most_cited['citation_count']} citations)."
            )

        return standard_response(
            summary=summary,
            raw_data={
                "paper_id": paper_id,
                "total_returned": len(references),
                "references": references,
                "year_distribution": dict(sorted(year_counts.items())),
            },
            source="Semantic Scholar",
            source_id=paper_id,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_references", exc)


# ---- 5. Semantic Scholar: author papers --------------------------------------


@mcp.tool()
async def get_author_papers(author_name: str, max_results: int = 20) -> dict[str, Any]:
    """
    Find an author on Semantic Scholar and retrieve their publications.

    Args:
        author_name: Full author name (e.g. 'Jennifer Doudna', 'Feng Zhang').
        max_results: Maximum papers to return (default 20, max 1000).
    """
    try:
        max_results = min(max_results, 1000)
        headers = {"Accept": "application/json"}

        # Step 1: Search for the author
        search_url = f"{SEMANTIC_SCHOLAR_API}/author/search"
        search_params = {"query": author_name, "limit": 1}
        search_data = await async_http_get(search_url, params=search_params, headers=headers)

        authors_list = search_data.get("data", [])
        if not authors_list:
            return standard_response(
                summary=f"No Semantic Scholar author found for '{author_name}'.",
                raw_data={"author_name": author_name},
                source="Semantic Scholar",
                source_id=author_name,
                confidence=0.5,
            )

        author_info = authors_list[0]
        author_id = author_info.get("authorId", "")
        resolved_name = author_info.get("name", author_name)

        # Step 2: Get papers by this author
        papers_url = f"{SEMANTIC_SCHOLAR_API}/author/{author_id}/papers"
        papers_params = {
            "fields": "title,year,citationCount",
            "limit": max_results,
        }
        papers_data = await async_http_get(papers_url, params=papers_params, headers=headers)

        papers_raw = papers_data.get("data", [])
        papers = []
        total_citations = 0
        for p in papers_raw:
            cc = p.get("citationCount", 0) or 0
            total_citations += cc
            papers.append({
                "paper_id": p.get("paperId", ""),
                "title": p.get("title", "N/A"),
                "year": p.get("year"),
                "citation_count": cc,
            })

        # Sort by citation count
        papers.sort(key=lambda x: x.get("citation_count", 0), reverse=True)

        summary = (
            f"Author '{resolved_name}' (ID: {author_id}): "
            f"{len(papers)} papers retrieved, {total_citations} total citations."
        )
        if papers:
            top = papers[0]
            summary += (
                f" Most cited: \"{top['title']}\" "
                f"({top['year']}, {top['citation_count']} citations)."
            )

        return standard_response(
            summary=summary,
            raw_data={
                "author_id": author_id,
                "author_name": resolved_name,
                "total_papers": len(papers),
                "total_citations": total_citations,
                "papers": papers,
            },
            source="Semantic Scholar",
            source_id=author_id,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_author_papers", exc)


# ---- 6. bioRxiv/medRxiv: search preprints -----------------------------------


@mcp.tool()
async def search_preprints(
    query: str,
    server: str = "biorxiv",
    max_results: int = 10,
) -> dict[str, Any]:
    """
    Search bioRxiv or medRxiv for preprints matching a query.

    Uses the content detail endpoint with keyword filtering on title/abstract.

    Args:
        query: Search keywords (e.g. 'single cell RNA-seq cancer').
        server: Preprint server to search — 'biorxiv' or 'medrxiv' (default 'biorxiv').
        max_results: Maximum results to return (default 10, max 25).
    """
    try:
        max_results = min(max_results, 25)
        server = server.lower()
        if server not in ("biorxiv", "medrxiv"):
            server = "biorxiv"

        # bioRxiv API uses date-range content detail endpoint
        # Fetch a batch and filter locally by query keywords
        url = f"{BIORXIV_API}/details/{server}/2020-01-01/2026-12-31/0/25"
        data = await async_http_get(url)

        collection = data.get("collection", [])
        query_lower = query.lower()
        query_terms = query_lower.split()

        # Filter by keyword match in title or abstract
        matched = []
        for article in collection:
            title = (article.get("title") or "").lower()
            abstract = (article.get("abstract") or "").lower()
            combined = title + " " + abstract
            # Require at least half the query terms to match
            matches = sum(1 for term in query_terms if term in combined)
            if matches >= max(1, len(query_terms) // 2):
                matched.append({
                    "doi": article.get("doi", ""),
                    "title": article.get("title", "N/A"),
                    "authors": article.get("authors", "N/A"),
                    "date": article.get("date", "N/A"),
                    "category": article.get("category", "N/A"),
                    "abstract": (article.get("abstract") or "")[:500],
                    "server": server,
                    "match_score": matches / len(query_terms) if query_terms else 0,
                })

        matched.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        matched = matched[:max_results]

        summary = (
            f"{server}: {len(matched)} preprints matching '{query}' "
            f"(from {len(collection)} scanned)."
        )
        if matched:
            top = matched[0]
            summary += f" Top match: \"{top['title']}\" ({top['date']})."

        return standard_response(
            summary=summary,
            raw_data={
                "query": query,
                "server": server,
                "total_scanned": len(collection),
                "matched": len(matched),
                "preprints": matched,
            },
            source=f"{server}",
            source_id=query,
            confidence=0.8,
        )
    except Exception as exc:
        return handle_error("search_preprints", exc)


# ---- 7. bioRxiv: preprint details --------------------------------------------


@mcp.tool()
async def get_preprint_details(doi: str) -> dict[str, Any]:
    """
    Retrieve detailed metadata for a bioRxiv or medRxiv preprint by DOI.

    Args:
        doi: DOI of the preprint (e.g. '10.1101/2024.01.15.575123').
    """
    try:
        url = f"{BIORXIV_API}/details/biorxiv/{doi}"
        data = await async_http_get(url)

        collection = data.get("collection", [])
        if not collection:
            # Try medRxiv
            url = f"{BIORXIV_API}/details/medrxiv/{doi}"
            data = await async_http_get(url)
            collection = data.get("collection", [])

        if not collection:
            return standard_response(
                summary=f"No preprint found for DOI: {doi}.",
                raw_data={"doi": doi},
                source="bioRxiv/medRxiv",
                source_id=doi,
                confidence=0.5,
            )

        # Take the most recent version
        article = collection[-1] if collection else collection[0]

        title = article.get("title", "N/A")
        authors = article.get("authors", "N/A")
        date = article.get("date", "N/A")
        category = article.get("category", "N/A")
        abstract = article.get("abstract", "")
        version = article.get("version", "1")
        server = article.get("server", "biorxiv")
        published_doi = article.get("published", "")
        jatsxml = article.get("jatsxml", "")

        summary = (
            f"\"{title}\" ({date}, v{version}). "
            f"Authors: {authors[:200]}. "
            f"Category: {category}. Server: {server}."
        )
        if published_doi:
            summary += f" Published version: {published_doi}."

        return standard_response(
            summary=summary,
            raw_data={
                "doi": doi,
                "title": title,
                "authors": authors,
                "date": date,
                "category": category,
                "abstract": abstract,
                "version": version,
                "server": server,
                "published_doi": published_doi,
                "jatsxml_url": jatsxml,
                "all_versions": collection,
            },
            source=f"{server}",
            source_id=doi,
            confidence=0.9,
        )
    except Exception as exc:
        return handle_error("get_preprint_details", exc)


# ---- 8. Europe PMC: full-text search -----------------------------------------


@mcp.tool()
async def search_fulltext(query: str, max_results: int = 10) -> dict[str, Any]:
    """
    Search Europe PMC for articles with full-text content matching a query.

    Europe PMC provides access to PubMed, PMC, and other literature databases
    with full-text search capabilities.

    Args:
        query: Search query (e.g. 'CRISPR delivery nanoparticle').
        max_results: Maximum results to return (default 10, max 100).
    """
    try:
        max_results = min(max_results, 100)
        url = f"{EUROPE_PMC_API}/search"
        params = {
            "query": query,
            "resultType": "core",
            "format": "json",
            "pageSize": max_results,
        }
        data = await async_http_get(url, params=params)

        hit_count = data.get("hitCount", 0)
        results_list = data.get("resultList", {}).get("result", [])

        articles = []
        for r in results_list:
            authors_list = r.get("authorList", {}).get("author", [])
            author_names = []
            if isinstance(authors_list, list):
                author_names = [
                    a.get("fullName", a.get("lastName", ""))
                    for a in authors_list[:5]
                ]

            articles.append({
                "pmid": r.get("pmid", ""),
                "pmcid": r.get("pmcid", ""),
                "doi": r.get("doi", ""),
                "title": r.get("title", "N/A"),
                "authors": author_names,
                "journal": r.get("journalTitle", "N/A"),
                "pub_year": r.get("pubYear", "N/A"),
                "citation_count": r.get("citedByCount", 0),
                "abstract": (r.get("abstractText") or "")[:500],
                "source": r.get("source", ""),
                "is_open_access": r.get("isOpenAccess", "N") == "Y",
                "full_text_available": r.get("hasTextMinedTerms", "N") == "Y",
            })

        summary = (
            f"Europe PMC: {hit_count} total results for '{query}', "
            f"retrieved {len(articles)}."
        )
        if articles:
            top = articles[0]
            summary += (
                f" Top result: \"{top['title']}\" ({top['pub_year']}, "
                f"{top['citation_count']} citations"
                + (", open access" if top["is_open_access"] else "")
                + ")."
            )

        return standard_response(
            summary=summary,
            raw_data={
                "query": query,
                "total_hits": hit_count,
                "articles": articles,
            },
            source="Europe PMC",
            source_id=query,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("search_fulltext", exc)


# ---- 9. Europe PMC: article citations ----------------------------------------


@mcp.tool()
async def get_article_citations(pmid: str) -> dict[str, Any]:
    """
    Retrieve articles that cite a given PubMed article, via Europe PMC.

    Args:
        pmid: PubMed identifier of the article (e.g. '33087860').
    """
    try:
        url = f"{EUROPE_PMC_API}/MED/{pmid}/citations"
        params = {
            "format": "json",
            "pageSize": 25,
        }
        data = await async_http_get(url, params=params)

        hit_count = data.get("hitCount", 0)
        citations_raw = data.get("citationList", {}).get("citation", [])

        citations = []
        for c in citations_raw:
            citations.append({
                "id": c.get("id", ""),
                "source": c.get("source", ""),
                "title": c.get("title", "N/A"),
                "authors": c.get("authorString", "N/A"),
                "journal": c.get("journalAbbreviation", "N/A"),
                "pub_year": c.get("pubYear", "N/A"),
                "citation_count": c.get("citedByCount", 0),
            })

        # Year distribution
        year_counts: dict[str, int] = {}
        for c in citations:
            y = c.get("pub_year", "N/A")
            if y and y != "N/A":
                year_counts[y] = year_counts.get(y, 0) + 1

        summary = (
            f"Europe PMC: {hit_count} citations for PMID {pmid}, "
            f"retrieved {len(citations)}."
        )
        if citations:
            most_cited = max(citations, key=lambda x: x.get("citation_count", 0))
            summary += (
                f" Most cited: \"{most_cited['title']}\" "
                f"({most_cited['pub_year']}, {most_cited['citation_count']} citations)."
            )

        return standard_response(
            summary=summary,
            raw_data={
                "pmid": pmid,
                "total_citations": hit_count,
                "citations": citations,
                "year_distribution": dict(sorted(year_counts.items())),
            },
            source="Europe PMC",
            source_id=pmid,
            confidence=0.85,
        )
    except Exception as exc:
        return handle_error("get_article_citations", exc)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
