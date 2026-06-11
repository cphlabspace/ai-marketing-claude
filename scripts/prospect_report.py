#!/usr/bin/env python3
"""
Oprema Prospect Batch Report Generator
Reads multiple score JSON files and generates:
  - prospects_scored.csv  — ranked list of all companies
  - PROSPECT-SUMMARY.md   — executive dashboard by tier

Usage:
    python3 prospect_report.py                              # auto-discovers score_*.json files
    python3 prospect_report.py score1.json score2.json ...  # explicit files
    python3 prospect_report.py --output-csv my_list.csv --output-summary SUMMARY.md
"""

import sys
import os
import json
import csv
import glob
import argparse
from datetime import datetime


TIER_ORDER = {"HiPo": 0, "Prospect": 1, "Watch": 2, "Qualify": 3}
TIER_EMOJI = {"HiPo": "🔴", "Prospect": "🟠", "Watch": "🟡", "Qualify": "⚪"}
TIER_ACTION = {
    "HiPo": "Immediate outreach — assign named rep, call within 48 hours",
    "Prospect": "Strong pipeline — outreach within 2 weeks",
    "Watch": "Monitor — set 90-day review, gather more intel",
    "Qualify": "Needs more information or disqualify",
}


def load_scores(file_paths: list) -> list:
    scores = []
    for fp in file_paths:
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
            if "total" in data and "company_name" in data:
                data["_source_file"] = fp
                scores.append(data)
        except Exception as e:
            print(f"  Warning: could not load {fp}: {e}")
    return sorted(scores, key=lambda x: (-x["total"], TIER_ORDER.get(x["tier"], 99)))


def write_csv(scores: list, output_path: str):
    fieldnames = [
        "rank", "company", "website", "score", "tier",
        "brand_fit", "firmographics", "contacts", "buying_signal", "freshness", "competitive",
        "brand_fit_evidence", "buying_signal_evidence", "key_gap",
        "action", "brief_file"
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rank, s in enumerate(scores, 1):
            safe_name = "".join(c if c.isalnum() else "_" for c in s.get("company_name", "")).strip("_")
            writer.writerow({
                "rank": rank,
                "company": s.get("company_name", ""),
                "website": s.get("website", ""),
                "score": f"{s['total']}/18",
                "tier": s["tier"],
                "brand_fit": s.get("brand_fit", {}).get("score", ""),
                "firmographics": s.get("firmographics", {}).get("score", ""),
                "contacts": s.get("contacts", {}).get("score", ""),
                "buying_signal": s.get("buying_signal", {}).get("score", ""),
                "freshness": s.get("freshness", {}).get("score", ""),
                "competitive": s.get("competitive", {}).get("score", ""),
                "brand_fit_evidence": s.get("brand_fit", {}).get("evidence", ""),
                "buying_signal_evidence": s.get("buying_signal", {}).get("evidence", ""),
                "key_gap": _top_gap(s),
                "action": TIER_ACTION.get(s["tier"], ""),
                "brief_file": f"PROSPECT-{safe_name}.md",
            })

    print(f"  CSV saved: {output_path}")


def _top_gap(s: dict) -> str:
    gaps = []
    if s.get("brand_fit", {}).get("score", 0) < 3:
        gaps.append("Brands unverified")
    if s.get("contacts", {}).get("score", 0) < 2:
        gaps.append("Contacts needed")
    if s.get("buying_signal", {}).get("score", 0) < 2:
        gaps.append("No buying signal")
    if s.get("firmographics", {}).get("score", 0) < 2:
        gaps.append("Registry incomplete")
    return "; ".join(gaps[:2]) if gaps else "None critical"


def write_summary(scores: list, output_path: str):
    date = datetime.now().strftime("%Y-%m-%d")
    total_count = len(scores)
    tier_counts = {}
    for s in scores:
        tier_counts[s["tier"]] = tier_counts.get(s["tier"], 0) + 1

    lines = [
        f"# Oprema Prospect Pipeline — Executive Summary",
        f"**Generated:** {date}  |  **Total companies:** {total_count}",
        "",
        "---",
        "",
        "## Pipeline Overview",
        "",
        "| Tier | Count | Action |",
        "|------|-------|--------|",
    ]
    for tier in ["HiPo", "Prospect", "Watch", "Qualify"]:
        count = tier_counts.get(tier, 0)
        emoji = TIER_EMOJI[tier]
        lines.append(f"| {emoji} **{tier}** | {count} | {TIER_ACTION[tier]} |")

    lines += ["", "---", "", "## Full Ranked List", ""]
    lines.append("| Rank | Company | Score | Tier | Brand Fit | Buying Signal | Top Gap | Action |")
    lines.append("|------|---------|-------|------|-----------|---------------|---------|--------|")

    for rank, s in enumerate(scores, 1):
        emoji = TIER_EMOJI.get(s["tier"], "⚪")
        brand_ev = s.get("brand_fit", {}).get("evidence", "")[:40]
        buy_ev = s.get("buying_signal", {}).get("evidence", "")[:40]
        gap = _top_gap(s)
        action = TIER_ACTION.get(s["tier"], "")[:35]
        lines.append(
            f"| {rank} | **{s.get('company_name','')}** | {s['total']}/18 | "
            f"{emoji} {s['tier']} | {brand_ev} | {buy_ev} | {gap} | {action} |"
        )

    # Tier sections
    for tier in ["HiPo", "Prospect", "Watch"]:
        tier_companies = [s for s in scores if s["tier"] == tier]
        if not tier_companies:
            continue
        emoji = TIER_EMOJI[tier]
        lines += ["", "---", "", f"## {emoji} {tier} Companies ({len(tier_companies)})", ""]
        for s in tier_companies:
            safe_name = "".join(c if c.isalnum() else "_" for c in s.get("company_name","")).strip("_")
            lines += [
                f"### {s.get('company_name','')} — {s['total']}/18",
                f"**Website:** {s.get('website','')}  |  **Brief:** [PROSPECT-{safe_name}.md](PROSPECT-{safe_name}.md)",
                "",
                f"| Dimension | Score | Signal |",
                f"|-----------|-------|--------|",
                f"| Brand/Line Fit | {s.get('brand_fit',{}).get('score','')}/3 | {s.get('brand_fit',{}).get('evidence','')[:60]} |",
                f"| Buying Signal | {s.get('buying_signal',{}).get('score','')}/3 | {s.get('buying_signal',{}).get('evidence','')[:60]} |",
                f"| Contacts | {s.get('contacts',{}).get('score','')}/3 | {s.get('contacts',{}).get('evidence','')[:60]} |",
                f"| Firmographics | {s.get('firmographics',{}).get('score','')}/3 | {s.get('firmographics',{}).get('evidence','')[:60]} |",
                "",
                f"**Action:** {TIER_ACTION[tier]}",
                f"**Key gap:** {_top_gap(s)}",
                "",
            ]

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  Summary saved: {output_path}")


def print_batch_terminal(scores: list, tier_counts: dict):
    print(f"\n{'='*55}")
    print(f"=== OPREMA PROSPECT BATCH COMPLETE ===")
    print(f"{'='*55}")
    print(f"\nTotal Processed: {len(scores)}")
    print(f"\n  🔴 HiPo (15–18):      {tier_counts.get('HiPo', 0)} companies")
    print(f"  🟠 Prospect (11–14):  {tier_counts.get('Prospect', 0)} companies")
    print(f"  🟡 Watch (7–10):      {tier_counts.get('Watch', 0)} companies")
    print(f"  ⚪ Qualify (0–6):     {tier_counts.get('Qualify', 0)} companies")
    top5 = scores[:5]
    if top5:
        print(f"\nTop {len(top5)} by Score:")
        for i, s in enumerate(top5, 1):
            print(f"  {i}. {s.get('company_name','')} — {s['total']}/18 {TIER_EMOJI.get(s['tier'],'')} {s['tier']}")


def main():
    parser = argparse.ArgumentParser(description="Oprema Prospect Batch Report")
    parser.add_argument("score_files", nargs="*", help="Score JSON files (default: auto-discover score_*.json)")
    parser.add_argument("--output-csv", default="prospects_scored.csv")
    parser.add_argument("--output-summary", default="PROSPECT-SUMMARY.md")
    args = parser.parse_args()

    file_paths = args.score_files or glob.glob("score_*.json")
    if not file_paths:
        print("No score JSON files found. Run prospect_scorer.py with --json-output first.")
        sys.exit(1)

    print(f"\nLoading {len(file_paths)} score file(s)...")
    scores = load_scores(file_paths)
    print(f"  Loaded {len(scores)} valid records")

    tier_counts = {}
    for s in scores:
        tier_counts[s["tier"]] = tier_counts.get(s["tier"], 0) + 1

    print(f"\nGenerating outputs...")
    write_csv(scores, args.output_csv)
    write_summary(scores, args.output_summary)
    print_batch_terminal(scores, tier_counts)

    print(f"\nFull ranked list:   {args.output_csv}")
    print(f"Executive summary:  {args.output_summary}")
    print(f"Individual briefs:  PROSPECT-*.md")


if __name__ == "__main__":
    main()
