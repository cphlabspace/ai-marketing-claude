#!/usr/bin/env python3
"""
Oprema Prospect Research — Perplexity API Module

RESEARCH PHILOSOPHY
===================
Category-first: we want to know WHAT THIS COMPANY DOES (installs CCTV?
access control? fire alarms?), not just whether they use Oprema brands.
Any company operating in Oprema's categories is a prospect — even if they
currently buy from Hikvision or Honeywell. Brands found are recorded as
sales intelligence for the rep, not as the fit gate.

Queries:
  1. Firmographics — Companies House, accreditations, legal entity
  2. Services & Categories — what do they install/service? (primary)
                             which specific brands? (secondary)
  3. Growth & Buying Signals — hiring, acquisitions, procurement changes
  4. Contacts & Incumbents   — who to call, who they currently buy from

Usage:
    python3 prospect_research.py "Acme Security Ltd" "acmesecurity.co.uk"
    python3 prospect_research.py "CDN Networks Limited" ""       # no website known
    python3 prospect_research.py "Acme Security" "" --output acme.json

Requires: PERPLEXITY_API_KEY environment variable
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
        Path(__file__).parent.parent / ".env",  # repo root
        Path(".env"),                             # cwd
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


PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL   = "sonar-pro"  # current model; fallback: "sonar"

# Apify RAG Web Browser — used as fallback when Perplexity is unreachable
# (Perplexity blocks cloud/datacenter IPs via Cloudflare; Apify direct API
# works from any machine that has the APIFY_API_TOKEN set)
APIFY_RAG_ACTOR    = "apify/rag-web-browser"
APIFY_API_BASE     = "https://api.apify.com/v2"

# ---------------------------------------------------------------------------
# Oprema brand portfolio (profit-ranked) — used in Query 2 as secondary check
# ---------------------------------------------------------------------------

OPREMA_BRANDS_TIER1 = ["Dahua", "Hanwha", "Ernitec", "Paxton", "Ajax", "Bosch"]
OPREMA_BRANDS_TIER2 = ["Olix", "Secure Logiq", "Comelit", "Apollo",
                        "Advanced Electronics", "Lanview", "Intratone"]
OPREMA_BRANDS_TIER3 = ["STP", "ICS", "Texecom", "Hochiki", "RGL", "CQR",
                        "Raytec", "CDVI", "AMG", "Vanderbilt"]

# Common non-Oprema brands in the same categories — finding these still
# signals category fit and provides pitch intelligence
NON_OPREMA_BRANDS = [
    "Hikvision", "Axis", "Avigilon", "Milestone", "Genetec",    # CCTV
    "HID", "Salto", "Allegion", "Gallagher", "Inner Range",     # Access
    "Notifier", "Gent", "Kentec", "C-TEC", "Nittan",            # Fire
    "Pyronix", "Honeywell Security", "Paradox", "DSC",          # Intruder
]


def _http_post(url: str, payload: bytes, headers: dict, timeout: int = 45) -> bytes:
    """POST with urllib; respects HTTP_PROXY / HTTPS_PROXY env vars automatically."""
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def perplexity_query(api_key: str, prompt: str, system: str = None) -> str:
    """Send a query to Perplexity (sonar-pro). Raises RuntimeError on failure."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": PERPLEXITY_MODEL,
        "messages": messages,
        "max_tokens": 2000,
        "temperature": 0.1,
        "search_recency_filter": "month",
        "return_citations": True,
    }).encode("utf-8")

    try:
        body = _http_post(
            PERPLEXITY_API_URL,
            payload,
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        data = json.loads(body.decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Perplexity API error {e.code}: {err_body}")


def apify_rag_query(apify_token: str, query: str) -> str:
    """
    Fallback research via Apify RAG Web Browser REST API.
    Used when Perplexity is blocked (cloud datacenter IP restriction).
    Requires APIFY_API_TOKEN in environment or .env file.
    """
    import time

    # Start a synchronous run (wait up to 60s)
    run_url = (
        f"{APIFY_API_BASE}/acts/{APIFY_RAG_ACTOR}/run-sync-get-dataset-items"
        f"?token={apify_token}&timeout=55"
    )
    payload = json.dumps({"query": query, "maxResults": 3}).encode("utf-8")

    try:
        body = _http_post(
            run_url, payload,
            {"Content-Type": "application/json"},
            timeout=65,
        )
        items = json.loads(body.decode("utf-8"))
        if not items:
            return "No results returned by Apify RAG."
        # Concatenate markdown from each result
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


def research_query(prompt: str, system: str,
                   perplexity_key: str, apify_token: str) -> str:
    """
    Run a single research query.
    Primary engine: Perplexity sonar-pro (best quality, web-grounded).
    Fallback: Apify RAG Web Browser (when Perplexity is blocked from cloud IPs).
    """
    # Try Perplexity first
    if perplexity_key:
        try:
            return perplexity_query(perplexity_key, prompt, system)
        except RuntimeError as e:
            err_str = str(e)
            blocked = "403" in err_str or "allowlist" in err_str.lower() or "cloudflare" in err_str.lower()
            if blocked and apify_token:
                print("    [Perplexity blocked from this IP — using Apify fallback]", flush=True)
            elif blocked:
                print(f"    [Perplexity blocked (403) — no Apify token available]", flush=True)
                raise
            else:
                raise

    # Apify fallback (also primary path if no Perplexity key)
    if apify_token:
        # Extract a short search query from the longer prompt
        first_line = prompt.strip().split("\n")[0][:200]
        return apify_rag_query(apify_token, first_line)

    raise RuntimeError("No research engine available: set PERPLEXITY_API_KEY or APIFY_API_TOKEN")


def research_company(company_name: str, website: str, api_key: str,
                     crm_data: dict = None, apify_token: str = None) -> dict:
    """Run all 4 research queries for a company. Returns structured dict."""

    site_clause = f"(website: {website})" if website else "(no website provided — find it)"

    system = (
        "You are a B2B sales intelligence analyst for Oprema, a UK security products "
        "distributor. Research UK security/fire/access installation companies. "
        "Focus on WHAT THEY DO (categories/services) first, WHICH BRANDS they use second. "
        "A company installing any CCTV, access control, fire or intruder system is a "
        "prospect for Oprema regardless of brand. "
        "Be factual. Label facts: VERIFIED (primary source URL), INFERRED (derived), "
        "UNVERIFIED (confirm before asserting)."
    )

    results = {
        "company_name":  company_name,
        "website":       website,
        "research_date": datetime.now().strftime("%Y-%m-%d"),
        "crm_data":      crm_data or {},
        "queries":       {}
    }

    # ------------------------------------------------------------------
    # Query 1: Firmographics & Companies House
    # ------------------------------------------------------------------
    q1 = f"""Research the UK company "{company_name}" {site_clause}.

Find and report:
1. Exact legal entity name on Companies House (may differ from trading name)
2. Companies House registration number (8 digits)
3. Incorporation date and current status (Active / Dissolved / Dormant)
4. SIC code(s) — especially: 43210 (electrical installation), 80200 (security systems),
   84250 (fire service activities), 43290 (other specialist construction)
5. Registered office address (full postcode)
6. Current directors / officers (name, appointment date)
7. Any parent company, group structure, or recent acquisitions
8. Industry accreditations: SSAIB, NSI NACOSS, NSI Gold, BAFE, NICEIC, Safe Contractor,
   ISO 9001, Constructionline
9. If the website is unknown, find it and report it.

Label each fact VERIFIED (Companies House / official register URL) or INFERRED."""

    print(f"  [1/4] Companies House & firmographics...")
    try:
        results["queries"]["firmographics"] = research_query(q1, system, api_key, apify_token)
    except Exception as e:
        results["queries"]["firmographics"] = f"ERROR: {e}"

    # ------------------------------------------------------------------
    # Query 2: Services / Categories (PRIMARY) + Brands (SECONDARY)
    # ------------------------------------------------------------------
    all_brands = (OPREMA_BRANDS_TIER1 + OPREMA_BRANDS_TIER2 +
                  OPREMA_BRANDS_TIER3 + NON_OPREMA_BRANDS)

    q2 = f"""Research "{company_name}" {site_clause} — a security/fire/access installer in the UK.

PART A — SERVICES AND CATEGORIES (most important):
What does this company actually install, service and maintain? Report for each:
1. CCTV / Video Surveillance — do they install cameras, NVRs, video systems? (yes/no/inferred)
2. Access Control — do they install door entry, intercoms, readers, barriers? (yes/no/inferred)
3. Fire Detection — do they design/install/maintain fire alarm systems? (yes/no/inferred)
4. Intruder / Burglar Alarms — do they install alarm panels, detectors, ARC monitoring? (yes/no/inferred)
5. Networking / Cabling — do they do structured cabling, PoE, network infrastructure? (yes/no/inferred)
6. Any other security or building services?

PART B — SPECIFIC BRANDS (secondary intelligence for sales rep):
Which specific manufacturer brands do they install or are certified for?
Check for Oprema brands: {", ".join(OPREMA_BRANDS_TIER1 + OPREMA_BRANDS_TIER2 + OPREMA_BRANDS_TIER3)}
Also check for other common brands: {", ".join(NON_OPREMA_BRANDS)}
Note: finding non-Oprema brands is useful intel — report all you find.

PART C — Market and size:
- Segments served: residential / commercial / industrial / retail / education / healthcare
- Geographic coverage
- Number of engineers or headcount signals
- Typical project size signals

Label each finding VERIFIED (from company website or manufacturer partner page) or INFERRED."""

    print(f"  [2/4] Services, categories & brand intelligence...")
    try:
        results["queries"]["brands_services"] = research_query(q2, system, api_key, apify_token)
    except Exception as e:
        results["queries"]["brands_services"] = f"ERROR: {e}"

    # ------------------------------------------------------------------
    # Query 3: Growth signals & buying intelligence
    # ------------------------------------------------------------------
    q3 = f"""Search for recent commercial intelligence about "{company_name}" {site_clause}.

Find and report:
1. Acquisitions made or acquisition of this company (last 3 years)
2. New office openings or relocations
3. Recent contract wins, tender awards, or framework listings
4. Current job vacancies — especially: procurement coordinator, stock manager,
   CCTV engineer, fire engineer, access control engineer, sales manager
5. Senior management changes or new hires
6. Press coverage in trade media: IFSEC International, PSI Magazine, CCTV Image,
   SecurityNewsDesk, Fire & Security Matters, Installer Magazine
7. LinkedIn company page: recent posts, follower count, hiring posts
8. Any financial difficulty, restructuring, or closure signals
9. Any indication they are reviewing or changing their current suppliers/distributors

Focus on the last 12 months. VERIFIED = direct URL source, INFERRED = derived."""

    print(f"  [3/4] Growth signals, news & buying intelligence...")
    try:
        results["queries"]["growth_signals"] = research_query(q3, system, api_key, apify_token)
    except Exception as e:
        results["queries"]["growth_signals"] = f"ERROR: {e}"

    # ------------------------------------------------------------------
    # Query 4: Contacts & Incumbent Distributors
    # ------------------------------------------------------------------
    q4 = f"""Research key personnel and supply chain intelligence for "{company_name}" {site_clause}.

CONTACTS — find names and titles for:
1. Managing Director / CEO / Owner / Founder
2. Operations Director / General Manager
3. Procurement Manager / Stock Manager / Purchasing
4. Head of Installations / Installation Manager
5. Technical Sales Manager / Sales Director
6. Any other named contacts from their website or LinkedIn

For each contact note: name, title, and source (Companies House / LinkedIn / website)

INCUMBENT DISTRIBUTORS — who do they currently buy from?
Look for mentions of: Rexel, Comark, ADI Global, Norbain, Videcon, CIE Group,
CSE Distributors, Seidor, EET Europarts, TLC Direct, or any other named distributor.
Also check manufacturer dealer-locator or partner pages for this company.

If you find non-Oprema brands (e.g. Hikvision, Pyronix, HID) note which distributor
typically supplies those brands in the UK — this reveals the likely incumbent.

VERIFIED = registry or official source · LINKEDIN-SOURCED = note as such"""

    print(f"  [4/4] Contacts & incumbent distributor intelligence...")
    try:
        results["queries"]["contacts_incumbents"] = research_query(q4, system, api_key, apify_token)
    except Exception as e:
        results["queries"]["contacts_incumbents"] = f"ERROR: {e}"

    return results


def save_results(results: dict, output_path: str):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  Research saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Oprema Prospect Research — Perplexity (primary) + Apify (fallback)"
    )
    parser.add_argument("company_name", help="Company name")
    parser.add_argument("website", nargs="?", default="", help="Website URL (optional)")
    parser.add_argument("--output", "-o", help="Output JSON path")
    parser.add_argument("--api-key", help="Perplexity API key (or PERPLEXITY_API_KEY env var)")
    parser.add_argument("--apify-token", help="Apify API token (or APIFY_API_TOKEN env var)")
    parser.add_argument("--crm-json", help="JSON string of CRM fields to embed in output")
    args = parser.parse_args()

    perplexity_key = args.api_key or os.environ.get("PERPLEXITY_API_KEY")
    apify_token    = args.apify_token or os.environ.get("APIFY_API_TOKEN")

    if not perplexity_key and not apify_token:
        print("ERROR: Set PERPLEXITY_API_KEY (preferred) or APIFY_API_TOKEN (fallback)")
        sys.exit(1)

    crm_data = json.loads(args.crm_json) if args.crm_json else None

    safe = "".join(c if c.isalnum() else "_" for c in args.company_name).strip("_")
    output_path = args.output or f"research_{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    engine = "Perplexity sonar-pro" if perplexity_key else "Apify RAG"
    print(f"\nOprema Prospect Research")
    print(f"{'='*50}")
    print(f"Company: {args.company_name}")
    print(f"Website: {args.website or '(will search)'}")
    print(f"Engine:  {engine}{' (+ Apify fallback)' if perplexity_key and apify_token else ''}")
    if crm_data:
        print(f"CRM:     Revenue={crm_data.get('revenue_duns','—')}  "
              f"Employees={crm_data.get('employees_duns','—')}  "
              f"D&B={crm_data.get('dandb_category','—')}")
    print(f"Output:  {output_path}\n")

    results = research_company(
        args.company_name, args.website, perplexity_key,
        crm_data=crm_data, apify_token=apify_token,
    )
    save_results(results, output_path)
    print(f"\nPass {output_path} to prospect_scorer.py to score and generate brief.")
    return output_path


if __name__ == "__main__":
    main()
