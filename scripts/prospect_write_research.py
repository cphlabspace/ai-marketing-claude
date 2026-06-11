#!/usr/bin/env python3
"""
prospect_write_research.py
Packages raw research text (gathered by Claude via Apify MCP) into the
standard research JSON format expected by prospect_scorer.py.

Claude runs this after collecting Apify results for a company.

Usage:
    python3 prospect_write_research.py \
        --company "Highcross Security & Electrical" \
        --website "https://www.highcrosssecurity.co.uk" \
        --firmographics "CH 06972003, active, SIC 43210..." \
        --services "Installs CCTV, access control, fire..." \
        --signals "Accounts filed 2025, 5 employees..." \
        --contacts "No named director found..." \
        --crm-json '{"customer_number":"11135","dandb_category":"Gold",...}' \
        --output research_Highcross.json
"""

import sys
import os
import json
import argparse
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Package Apify research into scorer JSON")
    parser.add_argument("--company",        required=True, help="Company name")
    parser.add_argument("--website",        default="",    help="Website URL")
    parser.add_argument("--firmographics",  default="",    help="Companies House / firmographic research text")
    parser.add_argument("--services",       default="",    help="Services, categories and brand research text")
    parser.add_argument("--signals",        default="",    help="Growth signals and buying intelligence text")
    parser.add_argument("--contacts",       default="",    help="Contacts and incumbent distributor text")
    parser.add_argument("--crm-json",       default="{}",  help="JSON string of CRM fields")
    parser.add_argument("--output", "-o",   default="",    help="Output JSON path (auto-generated if blank)")
    args = parser.parse_args()

    crm_data = {}
    try:
        crm_data = json.loads(args.crm_json)
    except json.JSONDecodeError:
        print(f"Warning: could not parse --crm-json, ignoring CRM data", file=sys.stderr)

    safe = "".join(c if c.isalnum() else "_" for c in args.company).strip("_")
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = args.output or f"research_{safe}_{ts}.json"

    result = {
        "company_name":  args.company,
        "website":       args.website,
        "research_date": datetime.now().strftime("%Y-%m-%d"),
        "crm_data":      crm_data,
        "queries": {
            "firmographics":       args.firmographics,
            "brands_services":     args.services,
            "growth_signals":      args.signals,
            "contacts_incumbents": args.contacts,
        }
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(output_path)  # stdout = path, for piping to scorer


if __name__ == "__main__":
    main()
