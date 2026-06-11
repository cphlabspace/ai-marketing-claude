#!/usr/bin/env python3
"""
Oprema Prospect Batch Runner
Reads a CRM export CSV, runs research + scoring for each company,
and generates all output files.

Supported CSV formats:
  1. Oprema CRM export (tab or comma separated):
     Account Name | Customer Number | Primary Responsible | Category (Calculated) |
     Customer Category (D&B Potential) | Category (Manual Override) |
     Financial Revenue (DUNS) | Number Of Employees (DUNS) |
     HIPO evaluation | HIPO evaluation date | Owning Business Unit | Website

  2. Simple format:
     company_name,website
     company_name,website,notes

Usage:
    python3 prospect_batch.py crm_export.csv
    python3 prospect_batch.py crm_export.csv --limit 5
    python3 prospect_batch.py crm_export.csv --skip-research   # re-score existing research files

Requires: PERPLEXITY_API_KEY environment variable
"""

import sys
import os
import csv
import json
import time
import glob
import argparse
import subprocess
from datetime import datetime
from pathlib import Path


def load_env_file():
    for candidate in [Path(__file__).parent.parent / ".env", Path(".env")]:
        if candidate.exists():
            with open(candidate) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, val = line.partition("=")
                        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
            break


load_env_file()


# Column name aliases for the Oprema CRM export format
CRM_COLUMN_MAP = {
    "company_name":         ["Account Name", "account_name", "company_name", "name", "company"],
    "customer_number":      ["Customer Number", "customer_number", "customer_id"],
    "primary_responsible":  ["Primary Responsible", "primary_responsible", "account_manager", "rep"],
    "category_calculated":  ["Category (Calculated)", "category_calculated"],
    "dandb_category":       ["Customer Category (D&B Potential)", "dandb_category", "db_category"],
    "category_override":    ["Category (Manual Override)", "category_override"],
    "revenue_duns":         ["Financial Revenue (DUNS) (DUNS)", "Financial Revenue (DUNS)", "revenue_duns", "revenue"],
    "employees_duns":       ["Number Of Employees (DUNS) (DUNS)", "Number Of Employees (DUNS)", "employees_duns", "employees"],
    "hipo_eval":            ["HIPO evaluation", "hipo_eval", "hipo"],
    "hipo_date":            ["HIPO evaluation date", "hipo_date"],
    "business_unit":        ["Owning Business Unit", "business_unit"],
    "website":              ["Website", "website", "url", "domain"],
    "notes":                ["notes", "note", "comment"],
    "region":               ["region", "location", "area"],
}


def find_column(headers: list, field_key: str) -> str | None:
    """Find the actual column header matching a logical field name."""
    aliases = CRM_COLUMN_MAP.get(field_key, [field_key])
    for alias in aliases:
        for h in headers:
            if h.strip().lower() == alias.strip().lower():
                return h
    return None


def parse_crm_row(row: dict, headers: list) -> dict:
    """Extract standardised fields from a CRM row."""
    result = {}
    for field_key in CRM_COLUMN_MAP:
        col = find_column(headers, field_key)
        result[field_key] = row.get(col, "").strip() if col else ""
    return result


def detect_delimiter(filepath: str) -> str:
    """Detect if the file is tab or comma separated."""
    with open(filepath, encoding="utf-8-sig") as f:
        sample = f.read(512)
    tab_count   = sample.count("\t")
    comma_count = sample.count(",")
    return "\t" if tab_count > comma_count else ","


def load_crm_csv(csv_path: str) -> list:
    """Load CRM export CSV. Returns list of standardised company dicts."""
    delimiter = detect_delimiter(csv_path)
    companies = []

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        headers = reader.fieldnames or []

        # Check if this looks like a CRM export or a simple CSV
        is_crm_format = any(
            find_column(headers, k) for k in ["customer_number", "dandb_category", "revenue_duns"]
        )

        for row in reader:
            if is_crm_format:
                data = parse_crm_row(row, headers)
            else:
                # Simple format fallback
                data = {
                    "company_name": (row.get("company_name") or row.get("name") or
                                     row.get("Account Name") or "").strip(),
                    "website":      (row.get("website") or row.get("url") or "").strip(),
                    "notes":        (row.get("notes") or "").strip(),
                    "region":       (row.get("region") or "").strip(),
                    "customer_number": "", "primary_responsible": "",
                    "category_calculated": "", "dandb_category": "",
                    "category_override": "", "revenue_duns": "",
                    "employees_duns": "", "hipo_eval": "",
                    "hipo_date": "", "business_unit": "",
                }

            if data.get("company_name"):
                companies.append(data)

    return companies


def safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_")


def run_research(company: dict, api_key: str) -> str | None:
    """Run prospect_research.py for one company. Returns output JSON path."""
    safe  = safe_filename(company["company_name"])
    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    output= f"research_{safe}_{ts}.json"

    # Pass CRM data as JSON so it gets embedded in the research file
    crm_payload = {
        k: v for k, v in company.items()
        if k not in ("company_name", "website") and v
    }

    cmd = [
        sys.executable, "scripts/prospect_research.py",
        company["company_name"],
        company.get("website", ""),
        "--output", output,
        "--api-key", api_key,
    ]
    if crm_payload:
        cmd += ["--crm-json", json.dumps(crm_payload)]

    print(f"\n  Researching: {company['company_name']}"
          f" | Revenue: {company.get('revenue_duns','—')}"
          f" | Employees: {company.get('employees_duns','—')}"
          f" | D&B: {company.get('dandb_category','—')}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        # Show last few lines (progress output)
        lines = result.stdout.strip().split("\n")
        for line in lines[-4:]:
            print(f"    {line}")

    if result.returncode != 0:
        print(f"  ERROR: {result.stderr[:200]}")
        return None

    return output if os.path.exists(output) else None


def run_scoring(research_file: str) -> str | None:
    """Run prospect_scorer.py. Returns score JSON path."""
    score_file = research_file.replace("research_", "score_")
    brief_base = research_file.replace("research_", "PROSPECT-").replace(".json", "")
    # Load company name for brief filename
    try:
        with open(research_file, encoding="utf-8") as f:
            data = json.load(f)
        safe = safe_filename(data.get("company_name", "unknown"))
        brief_file = f"PROSPECT-{safe}.md"
    except Exception:
        brief_file = brief_base + ".md"

    cmd = [
        sys.executable, "scripts/prospect_scorer.py",
        research_file,
        "--json-output", score_file,
        "--brief-output", brief_file,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        lines = result.stdout.strip().split("\n")
        for line in lines[-6:]:
            print(f"    {line}")

    if result.returncode != 0:
        print(f"  ERROR scoring: {result.stderr[:200]}")
        return None

    return score_file if os.path.exists(score_file) else None


def run_batch_report(score_files: list, output_csv: str, output_summary: str):
    cmd = [
        sys.executable, "scripts/prospect_report.py",
        *score_files,
        "--output-csv", output_csv,
        "--output-summary", output_summary,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f"  ERROR in batch report: {result.stderr[:200]}")


def main():
    parser = argparse.ArgumentParser(description="Oprema Prospect Batch Runner")
    parser.add_argument("input_csv",
                        help="CRM export CSV (Oprema format) or simple company_name,website CSV")
    parser.add_argument("--skip-research", action="store_true",
                        help="Skip Perplexity research, re-score existing research_*.json files")
    parser.add_argument("--limit",  type=int, help="Process first N companies only")
    parser.add_argument("--delay",  type=float, default=2.5,
                        help="Seconds between API calls (default: 2.5)")
    parser.add_argument("--output-csv",     default="prospects_scored.csv")
    parser.add_argument("--output-summary", default="PROSPECT-SUMMARY.md")
    parser.add_argument("--api-key",
                        help="Perplexity API key (or set PERPLEXITY_API_KEY env var)")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("PERPLEXITY_API_KEY")
    if not api_key and not args.skip_research:
        print("ERROR: PERPLEXITY_API_KEY required. Set env var or use --api-key")
        sys.exit(1)

    companies = load_crm_csv(args.input_csv)
    if not companies:
        print(f"No companies found in {args.input_csv}")
        sys.exit(1)

    if args.limit:
        companies = companies[:args.limit]

    print(f"\nOprema Prospect Batch Runner")
    print(f"{'='*55}")
    print(f"Input:      {args.input_csv}")
    print(f"Companies:  {len(companies)}")
    print(f"Research:   {'SKIP — using existing files' if args.skip_research else 'Perplexity API'}")
    print(f"Output CSV: {args.output_csv}")
    print(f"Summary:    {args.output_summary}")

    # Show D&B category distribution if available
    dnb_counts = {}
    for c in companies:
        cat = c.get("dandb_category") or c.get("category_calculated") or "Unknown"
        dnb_counts[cat] = dnb_counts.get(cat, 0) + 1
    if len(dnb_counts) > 1:
        print(f"\nD&B Categories in input:")
        for cat, count in sorted(dnb_counts.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count}")

    score_files = []
    failed = []

    if args.skip_research:
        existing = glob.glob("research_*.json")
        if not existing:
            print("\nNo research_*.json files found. Run without --skip-research first.")
            sys.exit(1)
        print(f"\nUsing {len(existing)} existing research files...")
        for rf in existing:
            sf = run_scoring(rf)
            if sf:
                score_files.append(sf)
            time.sleep(0.3)
    else:
        for i, company in enumerate(companies, 1):
            print(f"\n[{i}/{len(companies)}] {company['company_name']}")
            rf = run_research(company, api_key)
            if not rf:
                failed.append(company["company_name"])
                continue

            time.sleep(args.delay)

            sf = run_scoring(rf)
            if sf:
                score_files.append(sf)
            else:
                failed.append(company["company_name"])

            if i < len(companies):
                time.sleep(args.delay)

    if score_files:
        print(f"\n\nGenerating batch report from {len(score_files)} scored companies...")
        run_batch_report(score_files, args.output_csv, args.output_summary)

    if failed:
        print(f"\nFailed ({len(failed)}): {', '.join(failed)}")

    print(f"\nDone. {len(score_files)} scored, {len(failed)} failed.")
    print(f"  Ranked CSV:  {args.output_csv}")
    print(f"  Summary:     {args.output_summary}")
    print(f"  Briefs:      PROSPECT-*.md")


if __name__ == "__main__":
    main()
