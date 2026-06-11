#!/usr/bin/env python3
"""
Oprema Prospect Batch Runner
Reads a CSV of companies, runs research + scoring for each, generates all outputs.

Input CSV format (one of):
  company_name,website
  company_name,website,notes
  company_name,website,notes,region

Usage:
    python3 prospect_batch.py prospects.csv
    python3 prospect_batch.py prospects.csv --skip-research   # score only (needs existing research files)
    python3 prospect_batch.py prospects.csv --limit 5         # process first 5 only

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


def load_input(csv_path: str) -> list[dict]:
    companies = []
    with open(csv_path, encoding="utf-8") as f:
        # Handle with or without header
        sample = f.read(256)
        f.seek(0)
        has_header = not sample.strip().split("\n")[0][0].isdigit()
        reader = csv.DictReader(f) if has_header else csv.reader(f)

        if has_header:
            for row in reader:
                name = row.get("company_name") or row.get("name") or row.get("company") or ""
                website = row.get("website") or row.get("url") or row.get("domain") or ""
                notes = row.get("notes") or row.get("note") or ""
                region = row.get("region") or row.get("location") or ""
                if name.strip():
                    companies.append({"name": name.strip(), "website": website.strip(),
                                       "notes": notes.strip(), "region": region.strip()})
        else:
            for row in reader:
                if row:
                    name = row[0].strip()
                    website = row[1].strip() if len(row) > 1 else ""
                    notes = row[2].strip() if len(row) > 2 else ""
                    region = row[3].strip() if len(row) > 3 else ""
                    if name:
                        companies.append({"name": name, "website": website,
                                           "notes": notes, "region": region})
    return companies


def safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_")


def run_research(company: dict, api_key: str) -> str | None:
    """Run prospect_research.py for one company. Returns output JSON path."""
    safe = safe_filename(company["name"])
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = f"research_{safe}_{ts}.json"

    cmd = [
        sys.executable, "scripts/prospect_research.py",
        company["name"], company.get("website", ""),
        "--output", output,
        "--api-key", api_key,
    ]

    print(f"\n  Researching: {company['name']} ({company.get('website','')})...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  ERROR researching {company['name']}: {result.stderr[:200]}")
        return None

    print(result.stdout[-300:] if result.stdout else "  (no output)")
    return output if os.path.exists(output) else None


def run_scoring(research_file: str) -> str | None:
    """Run prospect_scorer.py on a research file. Returns score JSON path."""
    base = research_file.replace("research_", "score_").replace(".json", "_scored.json")
    cmd = [
        sys.executable, "scripts/prospect_scorer.py",
        research_file,
        "--json-output", base,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout[-400:] if result.stdout else "")

    if result.returncode != 0:
        print(f"  ERROR scoring {research_file}: {result.stderr[:200]}")
        return None

    return base if os.path.exists(base) else None


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
    parser.add_argument("input_csv", help="CSV file with company_name,website columns")
    parser.add_argument("--skip-research", action="store_true",
                         help="Skip Perplexity research, use existing research_*.json files")
    parser.add_argument("--limit", type=int, help="Process first N companies only")
    parser.add_argument("--delay", type=float, default=2.0,
                         help="Seconds between API calls (default: 2)")
    parser.add_argument("--output-csv", default="prospects_scored.csv")
    parser.add_argument("--output-summary", default="PROSPECT-SUMMARY.md")
    parser.add_argument("--api-key", help="Perplexity API key (or set PERPLEXITY_API_KEY)")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("PERPLEXITY_API_KEY")
    if not api_key and not args.skip_research:
        print("ERROR: PERPLEXITY_API_KEY required for research. Set env var or use --api-key")
        sys.exit(1)

    companies = load_input(args.input_csv)
    if args.limit:
        companies = companies[:args.limit]

    print(f"\nOprema Prospect Batch Runner")
    print(f"{'='*50}")
    print(f"Input:      {args.input_csv}")
    print(f"Companies:  {len(companies)}")
    print(f"Research:   {'SKIP (using existing files)' if args.skip_research else 'Perplexity API'}")
    print(f"Output CSV: {args.output_csv}")
    print(f"Summary:    {args.output_summary}\n")

    score_files = []
    failed = []

    if args.skip_research:
        # Use existing research files
        existing = glob.glob("research_*.json")
        if not existing:
            print("No research_*.json files found. Run without --skip-research first.")
            sys.exit(1)
        print(f"Using {len(existing)} existing research files...")
        for rf in existing:
            sf = run_scoring(rf)
            if sf:
                score_files.append(sf)
            time.sleep(0.5)
    else:
        for i, company in enumerate(companies, 1):
            print(f"\n[{i}/{len(companies)}] {company['name']}")

            rf = run_research(company, api_key)
            if not rf:
                failed.append(company["name"])
                continue

            time.sleep(args.delay)

            sf = run_scoring(rf)
            if sf:
                score_files.append(sf)
            else:
                failed.append(company["name"])

            # Brief delay between companies to avoid API rate limits
            if i < len(companies):
                time.sleep(args.delay)

    if score_files:
        print(f"\n\nGenerating batch report from {len(score_files)} scored companies...")
        run_batch_report(score_files, args.output_csv, args.output_summary)

    if failed:
        print(f"\nFailed ({len(failed)}): {', '.join(failed)}")

    print(f"\nDone. {len(score_files)} companies scored, {len(failed)} failed.")


if __name__ == "__main__":
    main()
