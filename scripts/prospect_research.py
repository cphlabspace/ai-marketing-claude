#!/usr/bin/env python3
"""
Oprema Prospect Research — Perplexity API Module
Queries Perplexity to gather Companies House data, news, buying signals,
and brand intelligence for a given UK security installer/integrator.

Usage:
    python3 prospect_research.py "Acme Security Ltd" "acmesecurity.co.uk"
    python3 prospect_research.py "Acme Security Ltd" "acmesecurity.co.uk" --output acme.json

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
PERPLEXITY_MODEL = "llama-3.1-sonar-large-128k-online"

# Oprema brand portfolio in profit order (Tier 1 = highest profit)
OPREMA_BRANDS_BY_PROFIT = [
    # Tier 1 — top profit
    "Dahua", "Hanwha", "Ernitec", "Paxton", "Ajax", "Bosch",
    # Tier 2
    "Olix", "Secure Logiq", "Comelit", "Apollo", "Advanced Electronics",
    "Lanview", "Intratone",
    # Tier 3
    "STP", "ICS", "Texecom", "Hochiki", "RGL", "CQR", "Raytec",
    "CDVI", "AMG", "Vanderbilt",
]

# Oprema item groups with May QTY (used to contextualise line value in queries)
OPREMA_TOP_LINES = {
    "Access Control":  29041,   # Paxton, Comelit, Intratone, ICS, CDVI, RGL, Vanderbilt
    "Fire Detection":  20945,   # Apollo, Advanced Electronics, Hochiki, Bosch
    "CCTV / IP Video": 12830,   # Dahua, Hanwha, Ernitec, Olix, Secure Logiq
    "Intruder / Alarm": 7802,   # Ajax, Texecom, CQR, Bosch
    "Networking / Infra": 5512, # Lanview, STP, AMG
}


def perplexity_query(api_key: str, prompt: str, system_prompt: str = None) -> str:
    """Send a single query to Perplexity and return the response text."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
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


def research_company(company_name: str, website: str, api_key: str) -> dict:
    """Run all research queries for one company. Returns structured research dict."""

    system = (
        "You are a B2B sales intelligence analyst researching UK security industry companies "
        "for Oprema, a UK security products distributor. Be factual and cite sources. "
        "Distinguish clearly between VERIFIED facts (primary sources) and INFERRED signals. "
        "Focus on commercially relevant intelligence for sales prospecting."
    )

    results = {
        "company_name": company_name,
        "website": website,
        "research_date": datetime.now().strftime("%Y-%m-%d"),
        "queries": {}
    }

    # --- Query 1: Companies House & Firmographics ---
    q1 = f"""Research the UK company "{company_name}" (website: {website}).

Find and report:
1. Legal entity name on Companies House (exact match or parent group)
2. Companies House number
3. Incorporation date and status (active/dissolved)
4. SIC code(s) and description
5. Registered office address
6. Current directors / officers (name, role, appointment date)
7. Any parent company or group structure
8. Any subsidiary or acquired companies
9. Filed accounts summary (turnover band if available)
10. Industry accreditations: SSAIB, NSI NACOSS, NSI Gold, BAFE, NICEIC, Safe Contractor, ISO 9001

Format as structured data. Label each fact as VERIFIED (from Companies House / official register) or INFERRED."""

    print(f"  [1/4] Researching Companies House & firmographics for {company_name}...")
    try:
        results["queries"]["firmographics"] = perplexity_query(api_key, q1, system)
    except Exception as e:
        results["queries"]["firmographics"] = f"ERROR: {e}"

    # --- Query 2: Products, Brands & Services ---
    brand_list = ", ".join(OPREMA_BRANDS_BY_PROFIT)
    q2 = f"""Research the security installation company "{company_name}" ({website}).

Find and report:
1. Exact services offered: CCTV, intruder alarms, fire alarms, access control, networking, PA systems, other
2. Specific product brands/manufacturers they install or are certified for.
   Oprema distributes these brands — check specifically for each:
   TIER 1 (highest value): {", ".join(OPREMA_BRANDS_BY_PROFIT[:6])}
   TIER 2: {", ".join(OPREMA_BRANDS_BY_PROFIT[6:13])}
   TIER 3: {", ".join(OPREMA_BRANDS_BY_PROFIT[13:])}
3. Any partner/brand certifications listed on their website or manufacturer websites
4. Market segments served: residential, commercial, industrial, retail, healthcare, education
5. Geographic coverage area
6. Size signals: number of engineers, project scale, typical contract values if known

Label each finding as VERIFIED (found on company website/manufacturer's partner page) or INFERRED."""

    print(f"  [2/4] Researching products, brands & services...")
    try:
        results["queries"]["brands_services"] = perplexity_query(api_key, q2, system)
    except Exception as e:
        results["queries"]["brands_services"] = f"ERROR: {e}"

    # --- Query 3: News, Growth & Buying Signals ---
    q3 = f"""Search for recent news and commercial intelligence about "{company_name}" ({website}).

Find and report:
1. Any acquisitions made or being acquired (last 3 years)
2. New office openings or relocations
3. Recent contract wins or tender awards
4. Current job vacancies (especially: procurement coordinator, stock manager, engineers, sales)
5. Management changes or new hires at senior level
6. Any press releases, trade press coverage (IFSEC International, PSI Magazine, CCTV Image, SecurityNewsDesk)
7. Awards, accreditations gained recently
8. LinkedIn company page activity: recent posts, follower count, hiring posts
9. Any signals of financial difficulty, restructuring or cessation

Focus on the last 12 months. Label: VERIFIED (direct source URL) or INFERRED."""

    print(f"  [3/4] Researching news, growth signals & buying intelligence...")
    try:
        results["queries"]["growth_signals"] = perplexity_query(api_key, q3, system)
    except Exception as e:
        results["queries"]["growth_signals"] = f"ERROR: {e}"

    # --- Query 4: Contacts & Incumbent Distributors ---
    q4 = f"""Research key personnel and supply chain intelligence for "{company_name}" ({website}).

Find and report:
1. Key contacts with names and titles:
   - Managing Director / CEO / Owner
   - Operations Director / General Manager
   - Procurement Manager / Stock Manager / Purchasing
   - Head of Installations / Installation Manager
   - Technical Sales Manager / Sales Director
2. Any mentions of their current distributors or suppliers
   (look for: Rexel, Comark, ADI Global, EET Europarts, CIE Group, Norbain, Videcon, Oprema mentions)
3. Any distributor relationships evident from manufacturer partner listings
4. Any dealer/installer registration pages from manufacturers that list this company

For contacts: note if REGISTRY-VERIFIED (Companies House officers list) or LINKEDIN-SOURCED or WEBSITE-SOURCED.
For incumbent distributors: VERIFIED (explicitly stated) or INFERRED (derived from brand fit + region)."""

    print(f"  [4/4] Researching contacts & incumbent distributor intelligence...")
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
    parser = argparse.ArgumentParser(description="Oprema Prospect Research via Perplexity API")
    parser.add_argument("company_name", help="Company name to research")
    parser.add_argument("website", help="Company website URL")
    parser.add_argument("--output", "-o", help="Output JSON file path (default: auto-generated)")
    parser.add_argument("--api-key", help="Perplexity API key (or set PERPLEXITY_API_KEY env var)")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        print("ERROR: Perplexity API key required. Set PERPLEXITY_API_KEY or use --api-key")
        sys.exit(1)

    safe_name = "".join(c if c.isalnum() else "_" for c in args.company_name).strip("_")
    output_path = args.output or f"research_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    print(f"\nOprema Prospect Research")
    print(f"{'='*50}")
    print(f"Company: {args.company_name}")
    print(f"Website: {args.website}")
    print(f"Output:  {output_path}\n")

    results = research_company(args.company_name, args.website, api_key)
    save_results(results, output_path)

    print(f"\nDone. Pass {output_path} to prospect_scorer.py to generate score and brief.")
    return output_path


if __name__ == "__main__":
    main()
