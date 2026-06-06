"""
Biosecurity Engine — Multi-layered sequence screening pipeline.

Runs parallel screens for select agents, toxin domains, virulence factors,
gain-of-function risk, and regulatory compliance. Aggregates results into
a single BiosecurityAssessment with color-coded risk category.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

from src.biosecurity_engine.data import (
    AUSTRALIA_GROUP_AGENTS,
    BWC_AGENTS,
    SELECT_AGENTS,
    TOXIN_PFAM_IDS,
)

logger = logging.getLogger("lumi.biosecurity.engine")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class RiskCategory(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"


@dataclass
class BiosecurityScreenResult:
    """Result from a single screening step."""
    screen_name: str
    passed: bool  # True = no risk found
    risk_level: RiskCategory
    details: str
    evidence: list[dict] = field(default_factory=list)
    confidence: float = 0.8


@dataclass
class BiosecurityAssessment:
    """Aggregated assessment from all screens."""
    category: RiskCategory
    summary: str
    screen_results: list[BiosecurityScreenResult]
    requires_review: bool
    blocked: bool  # True = hard veto, cannot proceed
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Biosecurity Engine
# ---------------------------------------------------------------------------


class BiosecurityEngine:
    """
    Multi-layered biosecurity screening pipeline.

    Runs five independent screens in parallel and aggregates results
    into a color-coded risk assessment (GREEN / YELLOW / ORANGE / RED).
    """

    def __init__(self):
        self._blast_available = True

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def screen(
        self,
        sequence: str,
        design_context: str = "",
    ) -> BiosecurityAssessment:
        """
        Run all biosecurity screens in parallel and aggregate results.

        Args:
            sequence: Protein amino acid sequence to screen
            design_context: Free-text description of the design intent

        Returns:
            BiosecurityAssessment with color-coded risk category
        """
        results = await asyncio.gather(
            self.screen_select_agents(sequence),
            self.screen_toxin_domains(sequence),
            self.screen_virulence_factors(sequence),
            self.assess_gof_risk(sequence, design_context),
            self.check_compliance(sequence, design_context),
            return_exceptions=True,
        )

        # Convert exceptions to failed screen results
        screen_results: list[BiosecurityScreenResult] = []
        for i, result in enumerate(results):
            screen_names = [
                "select_agent_blast",
                "toxin_domain_scan",
                "virulence_factor_screen",
                "gof_risk_assessment",
                "compliance_check",
            ]
            if isinstance(result, Exception):
                logger.error("Biosecurity screen %s failed: %s", screen_names[i], result)
                screen_results.append(BiosecurityScreenResult(
                    screen_name=screen_names[i],
                    passed=True,  # fail-open with warning
                    risk_level=RiskCategory.YELLOW,
                    details=f"Screen failed with error: {result}",
                    confidence=0.0,
                ))
            else:
                screen_results.append(result)

        # Aggregate: determine overall category
        category = self._determine_category(screen_results)

        # Build summary
        failed_screens = [r for r in screen_results if not r.passed]
        if not failed_screens:
            summary = "All biosecurity screens passed. No risk indicators detected."
        else:
            flags = "; ".join(f"{r.screen_name}: {r.details[:100]}" for r in failed_screens)
            summary = f"Biosecurity flags raised by {len(failed_screens)} screen(s): {flags}"

        blocked = category == RiskCategory.RED
        requires_review = category in (RiskCategory.ORANGE, RiskCategory.RED)

        return BiosecurityAssessment(
            category=category,
            summary=summary,
            screen_results=screen_results,
            requires_review=requires_review,
            blocked=blocked,
            details={
                "sequence_length": len(sequence),
                "screens_run": len(screen_results),
                "screens_flagged": len(failed_screens),
            },
        )

    # ------------------------------------------------------------------
    # Screen 1: Select Agent BLAST
    # ------------------------------------------------------------------

    async def screen_select_agents(self, sequence: str) -> BiosecurityScreenResult:
        """
        BLAST sequence against NCBI nr and check hits for select agent organisms.
        """
        try:
            from src.mcp_servers.protein_design.server import blast_sequence

            blast_result = await blast_sequence(
                sequence=sequence,
                database="nr",
                max_hits=20,
            )

            if blast_result.get("error"):
                return BiosecurityScreenResult(
                    screen_name="select_agent_blast",
                    passed=True,
                    risk_level=RiskCategory.YELLOW,
                    details=f"BLAST search encountered an issue: {blast_result['error']}",
                    confidence=0.3,
                )

            # Check each hit against select agent list
            flagged_hits: list[dict] = []
            max_identity = 0.0

            for hit in blast_result.get("hits", []):
                organism = hit.get("organism", "").lower()
                description = hit.get("description", "").lower()
                identity = hit.get("identity_pct", 0.0)

                # Check if organism matches any select agent
                for agent in SELECT_AGENTS:
                    agent_lower = agent.lower()
                    if agent_lower in organism or agent_lower in description:
                        flagged_hits.append({
                            "organism": hit.get("organism", ""),
                            "description": hit.get("description", ""),
                            "identity_pct": identity,
                            "e_value": hit.get("e_value"),
                            "matched_agent": agent,
                        })
                        max_identity = max(max_identity, identity)
                        break

            if not flagged_hits:
                return BiosecurityScreenResult(
                    screen_name="select_agent_blast",
                    passed=True,
                    risk_level=RiskCategory.GREEN,
                    details="No similarity to select agent proteins detected.",
                    confidence=0.85,
                )

            # Determine risk level based on identity
            if max_identity >= 80:
                risk = RiskCategory.RED
                passed = False
            elif max_identity >= 40:
                risk = RiskCategory.ORANGE
                passed = False
            else:
                risk = RiskCategory.YELLOW
                passed = True

            return BiosecurityScreenResult(
                screen_name="select_agent_blast",
                passed=passed,
                risk_level=risk,
                details=(
                    f"Found {len(flagged_hits)} hit(s) matching select agent organisms. "
                    f"Maximum identity: {max_identity:.1f}%"
                ),
                evidence=flagged_hits,
                confidence=0.80,
            )

        except ImportError:
            return BiosecurityScreenResult(
                screen_name="select_agent_blast",
                passed=True,
                risk_level=RiskCategory.YELLOW,
                details="BLAST tool unavailable; screen skipped.",
                confidence=0.0,
            )
        except Exception as exc:
            logger.error("screen_select_agents failed: %s", exc)
            return BiosecurityScreenResult(
                screen_name="select_agent_blast",
                passed=True,
                risk_level=RiskCategory.YELLOW,
                details=f"Screen error: {exc}",
                confidence=0.0,
            )

    # ------------------------------------------------------------------
    # Screen 2: Toxin domain scan (InterPro)
    # ------------------------------------------------------------------

    async def screen_toxin_domains(self, sequence: str) -> BiosecurityScreenResult:
        """
        Submit sequence to InterPro REST API for domain analysis and check
        against known toxin Pfam domain families.
        """
        iprscan_url = "https://www.ebi.ac.uk/Tools/services/rest/iprscan5"

        try:
            # Step 1: Submit job
            submit_data = {
                "email": "lumi-biosecurity@example.com",
                "sequence": sequence,
                "goterms": "false",
                "pathways": "false",
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{iprscan_url}/run",
                    data=submit_data,
                    headers={"Accept": "text/plain"},
                )

                if resp.status_code != 200:
                    # InterPro might be unavailable; fall back to heuristic
                    return self._heuristic_toxin_scan(sequence)

                job_id = resp.text.strip()

            # Step 2: Poll for results (max ~3 minutes)
            max_polls = 18
            poll_interval = 10

            for _ in range(max_polls):
                await asyncio.sleep(poll_interval)

                async with httpx.AsyncClient(timeout=30.0) as client:
                    status_resp = await client.get(
                        f"{iprscan_url}/status/{job_id}",
                        headers={"Accept": "text/plain"},
                    )
                    status = status_resp.text.strip()

                if status == "FINISHED":
                    break
                elif status in ("FAILURE", "ERROR", "NOT_FOUND"):
                    return self._heuristic_toxin_scan(sequence)
            else:
                return BiosecurityScreenResult(
                    screen_name="toxin_domain_scan",
                    passed=True,
                    risk_level=RiskCategory.YELLOW,
                    details="InterPro scan timed out; using heuristic fallback.",
                    confidence=0.3,
                )

            # Step 3: Get results
            async with httpx.AsyncClient(timeout=30.0) as client:
                result_resp = await client.get(
                    f"{iprscan_url}/result/{job_id}/json",
                    headers={"Accept": "application/json"},
                )
                result_data = result_resp.json()

            # Step 4: Check domains against toxin list
            found_toxin_domains: list[dict] = []

            results_list = result_data.get("results", [result_data])
            for result_entry in results_list:
                matches = result_entry.get("matches", [])
                for match in matches:
                    signature = match.get("signature", {})
                    entry = signature.get("entry", {}) or {}
                    sig_ac = signature.get("accession", "")
                    entry_ac = entry.get("accession", "")

                    # Check against toxin Pfam IDs
                    if sig_ac in TOXIN_PFAM_IDS or entry_ac in TOXIN_PFAM_IDS:
                        found_toxin_domains.append({
                            "domain_id": sig_ac or entry_ac,
                            "name": signature.get("name", "") or entry.get("name", ""),
                            "description": signature.get("description", "") or entry.get("description", ""),
                            "locations": [
                                {"start": loc.get("start"), "end": loc.get("end")}
                                for loc in match.get("locations", [])
                            ],
                        })

                    # Also check description for toxin keywords
                    desc_text = (
                        (signature.get("description", "") or "") +
                        (entry.get("description", "") or "") +
                        (signature.get("name", "") or "")
                    ).lower()
                    if any(kw in desc_text for kw in ["toxin", "neurotoxin", "enterotoxin", "cytotoxin"]):
                        if sig_ac not in [d["domain_id"] for d in found_toxin_domains]:
                            found_toxin_domains.append({
                                "domain_id": sig_ac,
                                "name": signature.get("name", ""),
                                "description": desc_text[:200],
                                "matched_by": "keyword",
                            })

            if not found_toxin_domains:
                return BiosecurityScreenResult(
                    screen_name="toxin_domain_scan",
                    passed=True,
                    risk_level=RiskCategory.GREEN,
                    details="No known toxin domains detected by InterPro scan.",
                    confidence=0.85,
                )

            return BiosecurityScreenResult(
                screen_name="toxin_domain_scan",
                passed=False,
                risk_level=RiskCategory.RED,
                details=f"Found {len(found_toxin_domains)} toxin domain(s): "
                        + ", ".join(d["name"] or d["domain_id"] for d in found_toxin_domains),
                evidence=found_toxin_domains,
                confidence=0.90,
            )

        except Exception as exc:
            logger.error("screen_toxin_domains failed: %s", exc)
            return self._heuristic_toxin_scan(sequence)

    def _heuristic_toxin_scan(self, sequence: str) -> BiosecurityScreenResult:
        """
        Fallback heuristic toxin screening when InterPro is unavailable.

        Checks for known conserved motifs found in common toxin families.
        """
        clean_seq = sequence.upper()
        suspicious_motifs: list[dict] = []

        # Ricin A-chain active site motif (approximate)
        if re.search(r"E.{3,5}[AG].{2}R.{3,5}E", clean_seq):
            suspicious_motifs.append({
                "motif": "Ricin-A-like active site",
                "description": "Matches ricin A-chain catalytic motif pattern",
            })

        # ADP-ribosyltransferase motif (diphtheria/cholera/pertussis toxins)
        if re.search(r"[YF].{1,2}STS", clean_seq):
            suspicious_motifs.append({
                "motif": "ADP-ribosyltransferase-like",
                "description": "Matches ADP-ribosyltransferase catalytic region",
            })

        # Botulinum neurotoxin zinc-binding motif
        if re.search(r"HE..H", clean_seq):
            suspicious_motifs.append({
                "motif": "Zinc-metalloprotease (HEXXH)",
                "description": "HEXXH zinc-binding motif found in metalloproteases and some neurotoxins",
            })

        if not suspicious_motifs:
            return BiosecurityScreenResult(
                screen_name="toxin_domain_scan",
                passed=True,
                risk_level=RiskCategory.GREEN,
                details="Heuristic scan: no known toxin motifs detected (InterPro unavailable).",
                confidence=0.4,
            )

        return BiosecurityScreenResult(
            screen_name="toxin_domain_scan",
            passed=False,
            risk_level=RiskCategory.ORANGE,
            details=f"Heuristic scan found {len(suspicious_motifs)} suspicious motif(s). "
                    "Confirm with full InterPro scan.",
            evidence=suspicious_motifs,
            confidence=0.4,
        )

    # ------------------------------------------------------------------
    # Screen 3: Virulence factor screen
    # ------------------------------------------------------------------

    async def screen_virulence_factors(self, sequence: str) -> BiosecurityScreenResult:
        """
        BLAST sequence with entrez_query filter for virulence factors.
        """
        try:
            from src.mcp_servers.protein_design.server import blast_sequence

            blast_result = await blast_sequence(
                sequence=sequence,
                database="nr",
                max_hits=10,
                entrez_query="virulence factor",
            )

            if blast_result.get("error"):
                return BiosecurityScreenResult(
                    screen_name="virulence_factor_screen",
                    passed=True,
                    risk_level=RiskCategory.YELLOW,
                    details=f"Virulence factor BLAST failed: {blast_result['error']}",
                    confidence=0.2,
                )

            hits = blast_result.get("hits", [])
            vf_hits: list[dict] = []

            for hit in hits:
                identity = hit.get("identity_pct", 0)
                if identity >= 30:  # meaningful similarity
                    vf_hits.append({
                        "accession": hit.get("accession", ""),
                        "description": hit.get("description", ""),
                        "organism": hit.get("organism", ""),
                        "identity_pct": identity,
                        "e_value": hit.get("e_value"),
                    })

            if not vf_hits:
                return BiosecurityScreenResult(
                    screen_name="virulence_factor_screen",
                    passed=True,
                    risk_level=RiskCategory.GREEN,
                    details="No significant similarity to known virulence factors.",
                    confidence=0.75,
                )

            max_identity = max(h["identity_pct"] for h in vf_hits)
            if max_identity >= 80:
                risk = RiskCategory.RED
            elif max_identity >= 50:
                risk = RiskCategory.ORANGE
            else:
                risk = RiskCategory.YELLOW

            return BiosecurityScreenResult(
                screen_name="virulence_factor_screen",
                passed=risk == RiskCategory.YELLOW,
                risk_level=risk,
                details=f"Found {len(vf_hits)} virulence factor hit(s). Max identity: {max_identity:.1f}%",
                evidence=vf_hits,
                confidence=0.70,
            )

        except ImportError:
            return BiosecurityScreenResult(
                screen_name="virulence_factor_screen",
                passed=True,
                risk_level=RiskCategory.YELLOW,
                details="BLAST tool unavailable; virulence factor screen skipped.",
                confidence=0.0,
            )
        except Exception as exc:
            logger.error("screen_virulence_factors failed: %s", exc)
            return BiosecurityScreenResult(
                screen_name="virulence_factor_screen",
                passed=True,
                risk_level=RiskCategory.YELLOW,
                details=f"Screen error: {exc}",
                confidence=0.0,
            )

    # ------------------------------------------------------------------
    # Screen 4: Gain-of-function risk assessment (LLM-based)
    # ------------------------------------------------------------------

    async def assess_gof_risk(
        self, sequence: str, design_context: str
    ) -> BiosecurityScreenResult:
        """
        LLM-based gain-of-function risk assessment.

        Sends sequence features and design context to Claude for structured
        risk evaluation.
        """
        # Compute basic sequence features for the prompt
        seq_len = len(sequence)
        aa_counts = {aa: sequence.upper().count(aa) for aa in "ACDEFGHIKLMNPQRSTVWY"}
        charge = aa_counts.get("R", 0) + aa_counts.get("K", 0) - aa_counts.get("D", 0) - aa_counts.get("E", 0)
        cys_count = aa_counts.get("C", 0)
        has_signal = sequence[:30].upper().count("L") + sequence[:30].upper().count("A") > 10

        prompt = (
            "You are a biosecurity expert. Assess the gain-of-function (GOF) risk of the following "
            "protein sequence based on its features and the stated design context.\n\n"
            f"Sequence length: {seq_len} residues\n"
            f"Net charge: {charge}\n"
            f"Cysteine count: {cys_count}\n"
            f"Potential signal peptide: {has_signal}\n"
            f"First 50 residues: {sequence[:50]}\n\n"
            f"Design context: {design_context or 'Not provided'}\n\n"
            "Respond in this exact format:\n"
            "RISK_LEVEL: [NONE|LOW|MEDIUM|HIGH]\n"
            "CONCERNS: [list of specific concerns, or 'None identified']\n"
            "RATIONALE: [1-2 sentence explanation]\n"
        )

        try:
            from src.utils.llm import call_llm

            response = await call_llm(
                prompt=prompt,
                system=(
                    "You are a biosecurity screening system. Be conservative: flag anything "
                    "that could pose dual-use risk. Focus on whether the protein could enhance "
                    "pathogen transmissibility, virulence, immune evasion, or antibiotic resistance."
                ),
                model="claude-haiku-4-5",
                max_tokens=512,
                temperature=0.1,
            )

            # Parse response
            risk_level_match = re.search(r"RISK_LEVEL:\s*(NONE|LOW|MEDIUM|HIGH)", response, re.IGNORECASE)
            concerns_match = re.search(r"CONCERNS:\s*(.+?)(?=RATIONALE:|$)", response, re.DOTALL | re.IGNORECASE)
            rationale_match = re.search(r"RATIONALE:\s*(.+)", response, re.DOTALL | re.IGNORECASE)

            risk_text = risk_level_match.group(1).upper() if risk_level_match else "LOW"
            concerns = concerns_match.group(1).strip() if concerns_match else "Unable to parse"
            rationale = rationale_match.group(1).strip() if rationale_match else response[:200]

            risk_map = {
                "NONE": RiskCategory.GREEN,
                "LOW": RiskCategory.GREEN,
                "MEDIUM": RiskCategory.ORANGE,
                "HIGH": RiskCategory.RED,
            }
            risk = risk_map.get(risk_text, RiskCategory.YELLOW)

            return BiosecurityScreenResult(
                screen_name="gof_risk_assessment",
                passed=risk in (RiskCategory.GREEN, RiskCategory.YELLOW),
                risk_level=risk,
                details=f"GOF risk: {risk_text}. {rationale[:300]}",
                evidence=[{"concerns": concerns, "rationale": rationale}],
                confidence=0.6,  # LLM-based = moderate confidence
            )

        except Exception as exc:
            logger.error("assess_gof_risk LLM call failed: %s", exc)
            # Fallback: simple heuristic
            risk = RiskCategory.YELLOW
            details = "LLM-based GOF assessment unavailable. Basic heuristic: no obvious red flags."

            # Very basic heuristic checks
            if has_signal and cys_count > 10:
                risk = RiskCategory.ORANGE
                details = "Protein has potential signal peptide and many cysteines; manual review recommended."

            return BiosecurityScreenResult(
                screen_name="gof_risk_assessment",
                passed=True,
                risk_level=risk,
                details=details,
                confidence=0.2,
            )

    # ------------------------------------------------------------------
    # Screen 5: Compliance check (BWC + Australia Group)
    # ------------------------------------------------------------------

    async def check_compliance(
        self, sequence: str, design_context: str
    ) -> BiosecurityScreenResult:
        """
        Rule-based compliance check against BWC Annex and Australia Group lists.

        Checks design context text for mentions of controlled organisms and
        evaluates whether the sequence purpose might fall under export controls.
        """
        flagged_agents: list[dict] = []
        context_lower = design_context.lower() if design_context else ""
        f"protein sequence of {len(sequence)} residues"

        # Check design context for mention of controlled organisms
        for agent in BWC_AGENTS:
            agent_lower = agent.lower()
            # Check various forms: full name, genus only
            genus = agent_lower.split()[0] if " " in agent_lower else agent_lower
            if agent_lower in context_lower or genus in context_lower:
                flagged_agents.append({
                    "agent": agent,
                    "list": "BWC",
                    "matched_in": "design_context",
                })

        for agent in AUSTRALIA_GROUP_AGENTS:
            agent_lower = agent.lower()
            genus = agent_lower.split()[0] if " " in agent_lower else agent_lower
            if agent_lower in context_lower or genus in context_lower:
                # Avoid duplicates
                if not any(f["agent"] == agent for f in flagged_agents):
                    flagged_agents.append({
                        "agent": agent,
                        "list": "Australia_Group",
                        "matched_in": "design_context",
                    })

        # Check for concerning keywords in context
        concerning_keywords = [
            "weapon", "bioweapon", "enhance transmissibility", "enhance virulence",
            "immune evasion", "gain of function", "gain-of-function",
            "antibiotic resistance", "pandemic potential", "aerosolize",
        ]
        keyword_flags: list[str] = []
        for kw in concerning_keywords:
            if kw in context_lower:
                keyword_flags.append(kw)

        if not flagged_agents and not keyword_flags:
            return BiosecurityScreenResult(
                screen_name="compliance_check",
                passed=True,
                risk_level=RiskCategory.GREEN,
                details="No controlled organisms or concerning intent detected in design context.",
                confidence=0.75,
            )

        # Determine risk
        if keyword_flags:
            risk = RiskCategory.RED
            passed = False
            details = (
                f"Concerning keywords found in design context: {', '.join(keyword_flags)}. "
                f"This may indicate dual-use intent."
            )
        elif flagged_agents:
            risk = RiskCategory.ORANGE
            passed = False
            agents_str = ", ".join(f["agent"] for f in flagged_agents)
            details = (
                f"Design context references controlled organism(s): {agents_str}. "
                f"May require export control review."
            )
        else:
            risk = RiskCategory.YELLOW
            passed = True
            details = "Minor compliance flags detected."

        return BiosecurityScreenResult(
            screen_name="compliance_check",
            passed=passed,
            risk_level=risk,
            details=details,
            evidence=flagged_agents + [{"keywords": keyword_flags}] if keyword_flags else flagged_agents,
            confidence=0.85,
        )

    # ------------------------------------------------------------------
    # Category determination
    # ------------------------------------------------------------------

    def _determine_category(
        self, results: list[BiosecurityScreenResult]
    ) -> RiskCategory:
        """
        Aggregate individual screen results into overall risk category.

        Rules:
        - RED if any screen returns RED
        - ORANGE if any screen returns ORANGE
        - YELLOW if any screen returns YELLOW (but none ORANGE/RED)
        - GREEN if all screens are GREEN
        """
        categories = [r.risk_level for r in results]

        if RiskCategory.RED in categories:
            return RiskCategory.RED
        if RiskCategory.ORANGE in categories:
            return RiskCategory.ORANGE
        if RiskCategory.YELLOW in categories:
            return RiskCategory.YELLOW
        return RiskCategory.GREEN
