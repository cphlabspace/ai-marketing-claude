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


PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL   = "llama-3.1-sonar-large-128k-online"

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


def perplexity_query(api_key: str, prompt: str, system: str = None) -> str:
    """Send a query to Perplexity and return response text."""
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

    req = urllib.request.Request(
        PERPLEXITY_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Perplexity API error {e.code}: {body}")


def research_company(company_name: str, website: str, api_key: str,
                     crm_data: dict = None) -> dict:
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
        results["queries"]["firmographics"] = perplexity_query(api_key, q1, system)
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
        results["queries"]["brands_services"] = perplexity_query(api_key, q2, system)
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
        results["queries"]["growth_signals"] = perplexity_query(api_key, q3, system)
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
        results["queries"]["contacts_incumbents"] = perplexity_query(api_key, q4, system)
    except Exception as e:
        results["queries"]["contacts_incumbents"] = f"ERROR: {e}"

    return results


def save_results(results: dict, output_path: str):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  Research saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Oprema Prospect Research via Perplexity")
    parser.add_argument("company_name", help="Company name")
    parser.add_argument("website", nargs="?", default="", help="Website URL (optional)")
    parser.add_argument("--output", "-o", help="Output JSON path")
    parser.add_argument("--api-key", help="Perplexity API key (or PERPLEXITY_API_KEY env var)")
    parser.add_argument("--crm-json", help="JSON string of CRM fields to embed in output")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        print("ERROR: PERPLEXITY_API_KEY required")
        sys.exit(1)

    crm_data = json.loads(args.crm_json) if args.crm_json else None

    safe = "".join(c if c.isalnum() else "_" for c in args.company_name).strip("_")
    output_path = args.output or f"research_{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    print(f"\nOprema Prospect Research")
    print(f"{'='*50}")
    print(f"Company: {args.company_name}")
    print(f"Website: {args.website or '(will search)'}")
    if crm_data:
        print(f"CRM:     Revenue={crm_data.get('revenue_duns','—')}  "
              f"Employees={crm_data.get('employees_duns','—')}  "
              f"D&B={crm_data.get('dandb_category','—')}")
    print(f"Output:  {output_path}\n")

    results = research_company(args.company_name, args.website, api_key, crm_data)
    save_results(results, output_path)
    print(f"\nPass {output_path} to prospect_scorer.py to score and generate brief.")
    return output_path


if __name__ == "__main__":
    main()
