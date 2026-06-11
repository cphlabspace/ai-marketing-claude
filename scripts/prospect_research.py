#!/usr/bin/env python3
"""
Oprema Prospect Research — Perplexity Search API Module

RESEARCH PHILOSOPHY
===================
Category-first: we want to know WHAT THIS COMPANY DOES (installs CCTV?
access control? fire alarms?), not just whether they use Oprema brands.
Any company operating in Oprema's categories is a prospect — even if they
currently buy from Hikvision or Honeywell. Brands found are recorded as
sales intelligence for the rep, not as the fit gate.

Search queries (multi-query in a single API call):
  1. Firmographics — Companies House, accreditations, legal entity
  2. Services & Categories — what do they install/service?
  3. Growth & Buying Signals — hiring, acquisitions, procurement changes
  4. Contacts & Incumbents   — who to call, who they currently buy from

Uses Perplexity Search API (pip install perplexityai):
  - Returns structured results: title, url, snippet, date
  - Multi-query: all 4 queries in 2 API calls (5-query max per call)
  - Country filter: GB for UK-specific results
  - Domain filter: Companies House, LinkedIn, trade press

Usage:
    pip install perplexityai
    python3 prospect_research.py "CDN Networks Limited" "cdnnetworks.co.uk"
    python3 prospect_research.py "Acme Security" "" --output acme.json

Requires: PERPLEXITY_API_KEY environment variable (set in .env)

Fallback: if perplexityai not installed or blocked, uses Apify REST API
          (requires APIFY_API_TOKEN in .env)
"""

import sys
import os
import json
import argparse
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path


def load_env_file():
    """Load .env file from repo root if present (no external dependencies needed)."""
    for candidate in [
        Path(__file__).parent.parent / ".env",
        Path(".env"),
    ]:
        if candidate.exists():
            with open(candidate) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, val = line.partition("=")
                        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
            break


load_env_file()

# Apify RAG fallback
APIFY_RAG_ACTOR = "apify/rag-web-browser"
APIFY_API_BASE  = "https://api.apify.com/v2"

# ---------------------------------------------------------------------------
# Oprema brand portfolio — used in query 2 as secondary intelligence check
# ---------------------------------------------------------------------------

OPREMA_BRANDS_TIER1 = ["Dahua", "Hanwha", "Ernitec", "Paxton", "Ajax", "Bosch"]
OPREMA_BRANDS_TIER2 = ["Olix", "Secure Logiq", "Comelit", "Apollo",
                        "Advanced Electronics", "Lanview", "Intratone"]
OPREMA_BRANDS_TIER3 = ["STP", "ICS", "Texecom", "Hochiki", "RGL", "CQR",
                        "Raytec", "CDVI", "AMG", "Vanderbilt"]

NON_OPREMA_BRANDS = [
    "Hikvision", "Axis", "Avigilon", "Milestone", "Genetec",
    "HID", "Salto", "Allegion", "Gallagher", "Inner Range",
    "Notifier", "Gent", "Kentec", "C-TEC", "Nittan",
    "Pyronix", "Honeywell Security", "Paradox", "DSC",
]

# UK security trade press + key data sources — boost domain relevance
UK_SECURITY_DOMAINS = [
    "find-and-update.company-information.service.gov.uk",
    "ifsecglobal.com",
    "psimagazine.co.uk",
    "securitynewsdesk.com",
    "fireandsecuritymatters.co.uk",
    "installermagazine.co.uk",
    "uk.linkedin.com",
    "linkedin.com",
]


def _format_search_results(results) -> str:
    """Convert Perplexity Search API result objects to readable text."""
    if not results:
        return "No results found."
    parts = []
    for r in results:
        title   = getattr(r, "title", "") or ""
        url     = getattr(r, "url", "") or ""
        snippet = getattr(r, "snippet", "") or ""
        date    = getattr(r, "date", "") or ""
        date_str = f" [{date}]" if date else ""
        parts.append(f"### {title}{date_str}\n{url}\n\n{snippet[:2000]}")
    return "\n\n---\n\n".join(parts)


def _format_results_dict(results) -> list:
    """Convert results to list of dicts for JSON storage."""
    out = []
    for r in results:
        out.append({
            "title":   getattr(r, "title", ""),
            "url":     getattr(r, "url", ""),
            "snippet": getattr(r, "snippet", ""),
            "date":    getattr(r, "date", ""),
        })
    return out


def perplexity_search(api_key: str, queries: list, country: str = "GB",
                      domain_filter: list = None, max_results: int = 5) -> list:
    """
    Run one or more search queries via the Perplexity Search API.
    Returns list of result objects (one per query when multi-query).

    Raises RuntimeError on API errors (including 403 cloud IP block).
    """
    try:
        from perplexity import Perplexity
    except ImportError:
        raise RuntimeError(
            "perplexityai not installed. Run: pip install perplexityai"
        )

    client = Perplexity(api_key=api_key)

    kwargs = {
        "query":               queries if len(queries) > 1 else queries[0],
        "max_results":         max_results,
        "search_context_size": "high",
        "country":             country,
    }
    if domain_filter:
        kwargs["search_domain_filter"] = domain_filter[:20]

    search = client.search.create(**kwargs)
    return search.results


def apify_rag_query(apify_token: str, query: str) -> str:
    """Fallback: Apify RAG Web Browser via direct REST API."""
    run_url = (
        f"{APIFY_API_BASE}/acts/{APIFY_RAG_ACTOR}/run-sync-get-dataset-items"
        f"?token={apify_token}&timeout=55"
    )
    payload = json.dumps({"query": query, "maxResults": 3}).encode("utf-8")
    req = urllib.request.Request(
        run_url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=65) as resp:
            items = json.loads(resp.read().decode("utf-8"))
        if not items:
            return "No results from Apify RAG."
        parts = []
        for item in items[:3]:
            url   = item.get("metadata", {}).get("url", "")
            title = item.get("metadata", {}).get("title", "")
            md    = item.get("markdown", "") or item.get("text", "")
            parts.append(f"### {title}\n{url}\n\n{md[:3000]}")
        return "\n\n---\n\n".join(parts)
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Apify RAG error {e.code}: {err[:300]}")


def research_company(company_name: str, website: str,
                     perplexity_key: str = None, apify_token: str = None,
                     crm_data: dict = None) -> dict:
    """
    Run all 4 research queries for a company using Perplexity Search API.

    Strategy: send queries in batches of up to 5 (Search API limit).
    - Batch 1: firmographics + services+brands + growth signals (3 queries)
    - Batch 2: contacts + incumbents (1 query)

    Falls back to Apify RAG if Perplexity is blocked or unavailable.
    """

    site_clause = f"site:{website}" if website else f'"{company_name}" UK'
    all_brands  = (OPREMA_BRANDS_TIER1 + OPREMA_BRANDS_TIER2 +
                   OPREMA_BRANDS_TIER3 + NON_OPREMA_BRANDS)

    q_firmographics = (
        f'"{company_name}" Companies House UK registration number SIC director '
        f'security installer SSAIB NSI BAFE NICEIC accreditation'
    )

    q_services = (
        f'"{company_name}" UK CCTV access control fire alarm intruder security '
        f'installer services brands {" ".join(OPREMA_BRANDS_TIER1[:4])} '
        f'Hikvision Axis Pyronix {site_clause}'
    )

    q_signals = (
        f'"{company_name}" UK hiring vacancy engineer procurement contract win '
        f'acquisition new office 2024 2025 2026'
    )

    q_contacts = (
        f'"{company_name}" UK managing director owner procurement manager '
        f'contacts distributor supplier Norbain ADI Rexel Videcon'
    )

    results = {
        "company_name":  company_name,
        "website":       website,
        "research_date": datetime.now().strftime("%Y-%m-%d"),
        "crm_data":      crm_data or {},
        "queries":       {},
        "raw_results":   {},
    }

    use_perplexity = bool(perplexity_key)
    engine_used    = "none"

    if use_perplexity:
        # ------------------------------------------------------------------
        # Batch 1: firmographics + services + growth signals (3 queries)
        # ------------------------------------------------------------------
        print("  [1/2] Perplexity Search — firmographics, services & signals...",
              flush=True)
        try:
            batch1 = perplexity_search(
                perplexity_key,
                [q_firmographics, q_services, q_signals],
                country="GB",
                domain_filter=UK_SECURITY_DOMAINS,
                max_results=5,
            )
            # Multi-query returns results grouped per query
            # For 3 queries the SDK returns 3 result-sets
            # Multi-query SDK groups results per query.
            # Each element in batch1 may be a result-group (list) or a single result.
            def _group(items, idx):
                """Extract the idx-th query group from multi-query results."""
                if not items:
                    return []
                first = items[0]
                # Grouped: list-of-lists
                if hasattr(first, "__iter__") and not hasattr(first, "title"):
                    return list(items[idx]) if idx < len(items) else []
                # Flat list — split evenly by number of queries (3)
                n = len(items)
                size = max(1, n // 3)
                return items[idx * size: (idx + 1) * size]

            results["queries"]["firmographics"]   = _format_search_results(_group(batch1, 0))
            results["queries"]["brands_services"] = _format_search_results(_group(batch1, 1))
            results["queries"]["growth_signals"]  = _format_search_results(_group(batch1, 2))
            engine_used = "perplexity-search"

        except RuntimeError as e:
            err_str = str(e)
            if "403" in err_str or "allowlist" in err_str.lower():
                print("    [Perplexity blocked from this IP — switching to Apify fallback]",
                      flush=True)
                use_perplexity = False
            else:
                print(f"    [Perplexity error: {err_str[:120]}]", flush=True)
                use_perplexity = False

        # ------------------------------------------------------------------
        # Batch 2: contacts + incumbents
        # ------------------------------------------------------------------
        if use_perplexity:
            print("  [2/2] Perplexity Search — contacts & incumbents...", flush=True)
            try:
                batch2 = perplexity_search(
                    perplexity_key,
                    [q_contacts],
                    country="GB",
                    domain_filter=["uk.linkedin.com", "linkedin.com",
                                   "find-and-update.company-information.service.gov.uk"],
                    max_results=5,
                )
                results["queries"]["contacts_incumbents"] = _format_search_results(
                    batch2 if not isinstance(batch2[0], list) else batch2[0]
                )
            except RuntimeError as e:
                results["queries"]["contacts_incumbents"] = f"ERROR: {e}"

    # ------------------------------------------------------------------
    # Apify fallback (if Perplexity unavailable or blocked)
    # ------------------------------------------------------------------
    if not use_perplexity and apify_token:
        engine_used = "apify-rag"
        print("  [1/4] Apify RAG — firmographics...", flush=True)
        for key, query in [
            ("firmographics",       q_firmographics),
            ("brands_services",     q_services),
            ("growth_signals",      q_signals),
            ("contacts_incumbents", q_contacts),
        ]:
            if key in results["queries"]:
                continue
            try:
                results["queries"][key] = apify_rag_query(apify_token, query)
            except RuntimeError as e:
                results["queries"][key] = f"ERROR (Apify): {e}"

    elif not use_perplexity and not apify_token:
        msg = "ERROR: No research engine available. Set PERPLEXITY_API_KEY or APIFY_API_TOKEN."
        for key in ("firmographics", "brands_services", "growth_signals", "contacts_incumbents"):
            results["queries"].setdefault(key, msg)

    results["engine_used"] = engine_used
    return results


def save_results(results: dict, output_path: str):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  Research saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Oprema Prospect Research — Perplexity Search API (primary) + Apify (fallback)"
    )
    parser.add_argument("company_name", help="Company name")
    parser.add_argument("website", nargs="?", default="", help="Website URL (optional)")
    parser.add_argument("--output", "-o", help="Output JSON path")
    parser.add_argument("--api-key",      help="Perplexity API key (or PERPLEXITY_API_KEY env var)")
    parser.add_argument("--apify-token",  help="Apify API token (or APIFY_API_TOKEN env var)")
    parser.add_argument("--crm-json",     help="JSON string of CRM fields to embed in output")
    args = parser.parse_args()

    perplexity_key = args.api_key     or os.environ.get("PERPLEXITY_API_KEY")
    apify_token    = args.apify_token or os.environ.get("APIFY_API_TOKEN")

    if not perplexity_key and not apify_token:
        print("ERROR: Set PERPLEXITY_API_KEY (preferred) or APIFY_API_TOKEN (fallback)")
        sys.exit(1)

    crm_data = json.loads(args.crm_json) if args.crm_json else None

    safe = "".join(c if c.isalnum() else "_" for c in args.company_name).strip("_")
    output_path = args.output or f"research_{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    engine_label = ""
    if perplexity_key and apify_token:
        engine_label = "Perplexity Search API (+ Apify fallback)"
    elif perplexity_key:
        engine_label = "Perplexity Search API"
    else:
        engine_label = "Apify RAG Web Browser"

    print(f"\nOprema Prospect Research")
    print(f"{'='*50}")
    print(f"Company: {args.company_name}")
    print(f"Website: {args.website or '(will search)'}")
    print(f"Engine:  {engine_label}")
    if crm_data:
        print(f"CRM:     Revenue={crm_data.get('revenue_duns','—')}  "
              f"Employees={crm_data.get('employees_duns','—')}  "
              f"D&B={crm_data.get('dandb_category','—')}")
    print(f"Output:  {output_path}\n")

    results = research_company(
        args.company_name, args.website,
        perplexity_key=perplexity_key,
        apify_token=apify_token,
        crm_data=crm_data,
    )
    save_results(results, output_path)

    engine_actual = results.get("engine_used", "unknown")
    print(f"\nEngine used: {engine_actual}")
    print(f"Pass {output_path} to prospect_scorer.py to score and generate brief.")
    return output_path


if __name__ == "__main__":
    main()
