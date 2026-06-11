#!/usr/bin/env python3
"""
Oprema Prospect Scorer
Reads a research JSON file (from prospect_research.py) and applies the
6-dimension, 18-point Oprema scoring rubric to produce a scored brief.

Usage:
    python3 prospect_scorer.py research_AcmeSecurity_20260611.json
    python3 prospect_scorer.py research_AcmeSecurity_20260611.json --brief-output PROSPECT-Acme.md
    python3 prospect_scorer.py research_AcmeSecurity_20260611.json --json-output score_acme.json

Can also accept raw company data as arguments for a quick score:
    python3 prospect_scorer.py --company "Acme Security" --website acme.co.uk --research-text "..."
"""

import sys
import os
import json
import argparse
import re
from datetime import datetime


# --- Scoring keywords ---

BRAND_FIT_STRONG = [
    "dahua", "ajax", "texecom", "paxton", "advanced electronics", "advanced fire",
    "apollo", "hochiki", "honeywell", "milestone", "secure logiq", "videx",
    "pyronix", "hikvision", "hanwha", "hid", "salto", "notifier", "kentec",
    "gent", "c-tec", "bosch security", "gallagher", "inner range"
]

BRAND_FIT_SECTOR = [
    "cctv", "ip camera", "nvr", "dvr", "intruder alarm", "burglar alarm",
    "fire alarm", "fire detection", "access control", "door entry", "intercom",
    "video surveillance", "security system", "alarm system", "fire panel"
]

SIC_SECURITY = ["43210", "80200", "84250", "71121", "43290"]
ACCREDITATIONS = ["ssaib", "nsi nacoss", "nsi gold", "bafe", "niceic",
                   "safe contractor", "constructionline", "iso 9001", "iso9001"]

BUYING_SIGNAL_STRONG = [
    "procurement coordinator", "stock coordinator", "purchasing manager",
    "procurement manager", "supply chain", "new office", "new branch",
    "acquisition", "acquired", "roll-up", "consolidat", "contract win",
    "framework award", "tender award", "expanding", "new region"
]

BUYING_SIGNAL_MODERATE = [
    "hiring", "vacancy", "recruit", "engineer wanted", "join our team",
    "growing team", "new appointment", "promoted to", "key account"
]

FRESHNESS_STRONG = [
    "this month", "last month", "this week", "recent", "2025", "2026",
    "currently hiring", "live vacancy", "just announced", "just opened"
]

INCUMBENT_CLUES = [
    "rexel", "comark", "adi global", "adi ", "norbain", "videcon",
    "cie group", "cse distributors", "seidor", "azena"
]

TIER_MAP = {
    (15, 18): ("HiPo", "🔴"),
    (11, 14): ("Prospect", "🟠"),
    (7, 10): ("Watch", "🟡"),
    (0, 6): ("Qualify", "⚪"),
}


def get_tier(score: int) -> tuple[str, str]:
    for (low, high), (name, emoji) in TIER_MAP.items():
        if low <= score <= high:
            return name, emoji
    return "Qualify", "⚪"


def text_contains(text: str, keywords: list) -> list:
    """Return list of matched keywords found in text (case-insensitive)."""
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]


def score_brand_fit(research_text: str) -> tuple[int, str, str]:
    """Score dimension 1: Brand/Line Fit (0-3)."""
    matched_brands = text_contains(research_text, BRAND_FIT_STRONG)
    matched_sector = text_contains(research_text, BRAND_FIT_SECTOR)

    verified_signals = [b for b in matched_brands
                         if re.search(rf'\b{re.escape(b)}\b.*verif|verif.*\b{re.escape(b)}\b',
                                       research_text, re.IGNORECASE)]

    if len(matched_brands) >= 3 or (matched_brands and "VERIFIED" in research_text.upper()):
        score, conf = 3, "VERIFIED"
        evidence = f"Installs: {', '.join(matched_brands[:5])}"
    elif len(matched_brands) >= 1 or len(matched_sector) >= 3:
        score, conf = 2, "INFERRED"
        evidence = f"Sector fit: {', '.join((matched_brands + matched_sector)[:5])}"
    elif len(matched_sector) >= 1:
        score, conf = 1, "INFERRED"
        evidence = f"Sector-adjacent: {', '.join(matched_sector[:3])}"
    else:
        score, conf = 0, "VERIFIED"
        evidence = "No security/fire/access install business found"

    return score, evidence, conf


def score_firmographics(research_text: str) -> tuple[int, str, str]:
    """Score dimension 2: Registry/Firmographics (0-3)."""
    has_ch_number = bool(re.search(r'\b\d{8}\b', research_text))
    has_active = bool(re.search(r'\bactive\b', research_text, re.IGNORECASE))
    has_director = bool(re.search(r'director|officer|founder|proprietor', research_text, re.IGNORECASE))
    has_sic = any(sic in research_text for sic in SIC_SECURITY)
    has_accreditation = bool(text_contains(research_text, ACCREDITATIONS))
    has_address = bool(re.search(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', research_text))  # UK postcode

    verified_count = sum([has_ch_number, has_active, has_director, has_sic or has_accreditation, has_address])

    if verified_count >= 4:
        score, conf = 3, "VERIFIED"
        evidence = "Companies House verified: entity, director(s), SIC/accreditations, address"
    elif verified_count >= 2:
        score, conf = 2, "INFERRED"
        evidence = f"Partial: CH number {'found' if has_ch_number else 'missing'}, director {'found' if has_director else 'missing'}, accreditations {'found' if has_accreditation else 'missing'}"
    elif verified_count >= 1:
        score, conf = 1, "UNVERIFIED"
        evidence = "Minimal firmographic data — trading name only or limited Companies House data"
    else:
        score, conf = 0, "UNVERIFIED"
        evidence = "Cannot verify — no Companies House data found"

    return score, evidence, conf


def score_contact_access(research_text: str) -> tuple[int, str, str]:
    """Score dimension 3: Contact Access (0-3)."""
    has_md = bool(re.search(
        r'managing director|chief exec|ceo|founder|owner|director\b',
        research_text, re.IGNORECASE
    ))
    has_procurement = bool(re.search(
        r'procurement|purchasing|stock manager|supply|operations director|ops director',
        research_text, re.IGNORECASE
    ))
    has_technical = bool(re.search(
        r'technical sales|head of install|installation manager|engineer.*manager|technical director',
        research_text, re.IGNORECASE
    ))
    registry_verified = bool(re.search(r'registry.verif|companies house.*director|sole director', research_text, re.IGNORECASE))
    multiple_named = len(re.findall(r'[A-Z][a-z]+ [A-Z][a-z]+\s*—', research_text)) >= 3

    if (has_md and has_procurement and has_technical) or (multiple_named and registry_verified):
        score, conf = 3, "VERIFIED" if registry_verified else "INFERRED"
        evidence = "Deep directory: MD + Procurement/Ops + Technical contact found"
    elif has_md and (has_procurement or has_technical):
        score, conf = 2, "INFERRED"
        evidence = f"MD + {'procurement' if has_procurement else 'technical'} contact found"
    elif has_md:
        score, conf = 1, "INFERRED"
        evidence = "MD/owner identified only"
    else:
        score, conf = 0, "UNVERIFIED"
        evidence = "No named contacts found"

    return score, evidence, conf


def score_buying_signal(research_text: str) -> tuple[int, str, str]:
    """Score dimension 4: Opportunity/Buying Signal (0-3)."""
    strong_signals = text_contains(research_text, BUYING_SIGNAL_STRONG)
    moderate_signals = text_contains(research_text, BUYING_SIGNAL_MODERATE)

    verified = "VERIFIED" in research_text.upper() and (strong_signals or moderate_signals)

    if len(strong_signals) >= 2 or (strong_signals and moderate_signals):
        score, conf = 3, "VERIFIED" if verified else "INFERRED"
        evidence = f"Strong signals: {', '.join(strong_signals[:3])}"
    elif len(strong_signals) >= 1:
        score, conf = 2, "INFERRED"
        evidence = f"Signal: {strong_signals[0]}"
    elif len(moderate_signals) >= 2:
        score, conf = 2, "INFERRED"
        evidence = f"Growth signals: {', '.join(moderate_signals[:2])}"
    elif len(moderate_signals) >= 1:
        score, conf = 1, "INFERRED"
        evidence = f"Weak signal: {moderate_signals[0]}"
    else:
        score, conf = 0, "UNVERIFIED"
        evidence = "No buying signals found"

    return score, evidence, conf


def score_freshness(research_text: str) -> tuple[int, str, str]:
    """Score dimension 5: Freshness (0-3)."""
    current_year = str(datetime.now().year)
    last_year = str(datetime.now().year - 1)

    has_current_year = current_year in research_text
    has_last_year = last_year in research_text
    has_hiring = bool(re.search(r'hiring|vacanc|recruit|apply now|join us', research_text, re.IGNORECASE))
    has_recent_news = bool(re.search(r'announced|launched|opened|won|awarded|appointed', research_text, re.IGNORECASE))
    has_social = bool(re.search(r'linkedin|posted|followers|engaged', research_text, re.IGNORECASE))
    is_dormant = bool(re.search(r'dormant|ceased|no recent|inactive|dissolved|struck off', research_text, re.IGNORECASE))

    if is_dormant:
        return 0, "Dormant or ceased trading signals", "VERIFIED"

    if has_current_year and (has_hiring or has_recent_news):
        score, conf = 3, "VERIFIED"
        evidence = f"Active in {current_year}: hiring + recent news/activity"
    elif has_current_year or (has_last_year and has_hiring):
        score, conf = 2, "INFERRED"
        evidence = f"Active: {current_year if has_current_year else last_year} activity, {'hiring' if has_hiring else 'news'}"
    elif has_last_year or has_recent_news:
        score, conf = 1, "INFERRED"
        evidence = f"Limited recent activity ({last_year})"
    else:
        score, conf = 1, "UNVERIFIED"
        evidence = "Activity recency unclear — no date-stamped signals found"

    return score, evidence, conf


def score_competitive(research_text: str) -> tuple[int, str, str]:
    """Score dimension 6: Competitive/Incumbent (0-3)."""
    named_incumbents = text_contains(research_text, INCUMBENT_CLUES)
    has_displacement_window = bool(re.search(
        r'procurement build|centralising|consolidat|new purchas|reviewing supplier|changing supplier',
        research_text, re.IGNORECASE
    ))
    has_incumbent_unknown = bool(re.search(
        r'incumbent unknown|supplier unknown|distributor unknown|unverified.*supply',
        research_text, re.IGNORECASE
    ))

    if named_incumbents and has_displacement_window:
        score, conf = 3, "INFERRED"
        evidence = f"Incumbent ({', '.join(named_incumbents)}) + displacement window identified"
    elif named_incumbents:
        score, conf = 2, "INFERRED"
        evidence = f"Incumbent identified: {', '.join(named_incumbents)} — no specific window yet"
    elif has_displacement_window:
        score, conf = 2, "INFERRED"
        evidence = "Displacement window exists (procurement change) — incumbent unknown"
    elif has_incumbent_unknown:
        score, conf = 1, "UNVERIFIED"
        evidence = "Incumbent likely but unidentified — ask on discovery call"
    else:
        score, conf = 1, "UNVERIFIED"
        evidence = "Competitive/incumbent situation unknown"

    return score, evidence, conf


def extract_gaps(research: dict, scores: dict) -> list:
    """Generate honest gaps list from scores and research content."""
    gaps = []
    all_text = " ".join(str(v) for v in research.get("queries", {}).values())

    if scores["brand_fit"]["score"] < 3:
        gaps.append("BRANDS: Specific CCTV/alarm/access/fire manufacturers UNVERIFIED — confirm on first call")
    if scores["firmographics"]["score"] < 3:
        gaps.append("REGISTRY: Companies House data incomplete — verify entity, director and SIC before outreach")
    if scores["contacts"]["score"] < 2:
        gaps.append("CONTACTS: No procurement/technical contacts identified — use MD as entry point")
    if scores["contacts"]["score"] == 2:
        gaps.append("CONTACTS: Procurement/technical contacts LinkedIn-sourced — verify direct email/DDI before outreach")
    if not text_contains(all_text, ["incumbent", "distributor", "supplier", "rexel", "adi", "norbain"]):
        gaps.append("INCUMBENT: Current distributor(s) unknown — ask on discovery call: 'Who do you currently buy CCTV/alarm/access kit from?'")
    if scores["buying_signal"]["score"] < 2:
        gaps.append("BUYING SIGNAL: No verified procurement trigger identified — qualify opportunity on first call")
    if scores["freshness"]["score"] < 2:
        gaps.append("FRESHNESS: Activity recency unconfirmed — verify company is actively trading before outreach")

    return gaps


def generate_brief(research: dict, scores: dict, total: int, tier: str, tier_emoji: str) -> str:
    """Generate the full Markdown prospect brief."""
    company = research.get("company_name", "Unknown")
    website = research.get("website", "")
    date = research.get("research_date", datetime.now().strftime("%Y-%m-%d"))
    all_text = " ".join(str(v) for v in research.get("queries", {}).values())

    brands_mentioned = text_contains(all_text, [
        "Dahua", "Ajax", "Texecom", "Paxton", "Advanced", "Apollo", "Hochiki",
        "Honeywell", "Milestone", "Secure Logiq", "Videx", "Pyronix",
        "Hikvision", "Hanwha", "HID", "Notifier", "Kentec", "Gent"
    ])

    gaps = extract_gaps(research, scores)

    # Score breakdown string
    score_str = (
        f"Brand/line fit **{scores['brand_fit']['score']}** · "
        f"Registry/firmographics **{scores['firmographics']['score']}** · "
        f"Contact access **{scores['contacts']['score']}** · "
        f"Opportunity/buying-signal **{scores['buying_signal']['score']}** · "
        f"Freshness **{scores['freshness']['score']}** · "
        f"Competitive/incumbent **{scores['competitive']['score']}** = "
        f"**{total}/18 — {tier}**"
    )

    brief = f"""# Oprema Prospect Brief
**{company}** · UK · {website}
**{total} / 18 — {tier_emoji} {tier.upper()}**

---

## The Play

*(Synthesise from research below — replace this placeholder with a 2–3 paragraph strategic summary
explaining why {company} is an Oprema prospect, what product lines fit, what the timing window is,
and what the entry approach should be.)*

Key signals from research:
- Brand fit: {scores['brand_fit']['evidence']}
- Buying signal: {scores['buying_signal']['evidence']}
- Competitive angle: {scores['competitive']['evidence']}

---

## Next Steps

1. **Lead product line**: {', '.join(brands_mentioned[:3]) if brands_mentioned else 'CCTV / Intruder / Fire — confirm on call'} — position Oprema as consolidated supply partner
2. **Entry contact**: {scores['contacts']['evidence']}
3. **Timing window**: {scores['buying_signal']['evidence']}
4. **Brand verify on call**: Ask which CCTV/alarm/access/fire manufacturers they currently install — do not assume
5. **Attach opportunities**: Storage/Network (PoE switches, surveillance HDD) as CCTV attach; ProAV if PA/AV installs evident
6. **Data gaps to close**: {gaps[0] if gaps else 'None critical'}

---

## Who to Call

| Contact | Function | Why / Approach |
|---------|----------|----------------|
| *(MD/Owner — from research)* | Commercial / Decision-maker | Entry point for strategic supply conversation |
| *(Procurement/Ops — from research)* | Procurement / category-owner | Kit selection and day-to-day purchasing |
| *(Technical Sales/Head of Installs)* | Technical | Product mix discovery and brand conversation |

*(Populate from research data — see Contact Access notes below)*

---

## Oprema Line Fit

| Oprema Line | Fit | Evidence | Conf. |
|-------------|-----|----------|-------|
| CCTV / IP Video | {_line_fit(all_text, "cctv ip camera nvr surveillance dahua hikvision hanwha milestone secure logiq")} |
| Intruder / Alarm | {_line_fit(all_text, "intruder alarm burglar alarm texecom ajax pyronix honeywell")} |
| Fire | {_line_fit(all_text, "fire alarm fire detection advanced apollo hochiki notifier kentec")} |
| Access Control | {_line_fit(all_text, "access control door entry paxton videx hid salto intercom")} |
| Networking / Storage | {_line_fit(all_text, "poe switch cabling nvr storage surveillance hdd")} |
| ProAV | {_line_fit(all_text, "public address pa system audiovisual digital signage")} |

---

## Brand List

{'**Brands found in research:** ' + ', '.join(brands_mentioned) if brands_mentioned else 'UNVERIFIED — no specific manufacturer brands confirmed from primary sources.'}

**Inferred industry-typical brands for this sector (CONFIRM ON CALL, do not assume):**
- CCTV: Dahua / Hikvision / Hanwha
- Intruder: Texecom / Ajax / Pyronix / Honeywell
- Access: Paxton / Videx / HID
- Fire: Advanced Electronics / Apollo / Hochiki

---

## Company Snapshot

| Field | Value | Conf. |
|-------|-------|-------|
| Trading name | {company} | |
| Legal entity | *(from research)* | |
| Companies House no. | *(from research)* | |
| Status | *(from research)* | |
| Director(s) | *(from research)* | |
| SIC / nature | *(from research)* | |
| Registered office | *(from research)* | |
| Operating sites | *(from research)* | |
| Accreditations | *(from research)* | |
| Headcount signal | *(from research)* | |
| Buying signal | {scores['buying_signal']['evidence']} | {scores['buying_signal']['conf']} |

---

## Score Breakdown & Honest Gaps

{score_str}

**Honest Gaps:**
{chr(10).join('• ' + g for g in gaps) if gaps else '• No critical gaps identified'}

---

## Raw Research Data

<details>
<summary>Firmographics (Companies House)</summary>

{research.get('queries', {}).get('firmographics', 'Not available')}

</details>

<details>
<summary>Brands & Services</summary>

{research.get('queries', {}).get('brands_services', 'Not available')}

</details>

<details>
<summary>Growth Signals & News</summary>

{research.get('queries', {}).get('growth_signals', 'Not available')}

</details>

<details>
<summary>Contacts & Incumbent Distributors</summary>

{research.get('queries', {}).get('contacts_incumbents', 'Not available')}

</details>

---
*Oprema Prospect Brief · {company} · generated {date} · Oprema 6-dimension scoring methodology · research via Perplexity API + Apify (website/LinkedIn/Google Places). Confidence: VERIFIED = primary source · INFERRED = derived · UNVERIFIED = confirm before asserting.*
"""
    return brief


def _line_fit(text: str, keywords_str: str) -> str:
    """Quick inline fit assessment for a product line."""
    keywords = keywords_str.split()
    matches = [kw for kw in keywords if kw.lower() in text.lower()]
    if len(matches) >= 2:
        return f"**minor** | Signals: {', '.join(matches[:2])} | INFERRED |"
    elif len(matches) == 1:
        return f"**minor** | Signal: {matches[0]} | INFERRED |"
    else:
        return "**none** | No evidence found | VERIFIED |"


def score_company(research: dict) -> dict:
    """Apply full scoring rubric to research data. Returns scores dict."""
    all_text = " ".join(str(v) for v in research.get("queries", {}).values())

    bf_score, bf_ev, bf_conf = score_brand_fit(all_text)
    fi_score, fi_ev, fi_conf = score_firmographics(all_text)
    ca_score, ca_ev, ca_conf = score_contact_access(all_text)
    bs_score, bs_ev, bs_conf = score_buying_signal(all_text)
    fr_score, fr_ev, fr_conf = score_freshness(all_text)
    co_score, co_ev, co_conf = score_competitive(all_text)

    total = bf_score + fi_score + ca_score + bs_score + fr_score + co_score
    tier, emoji = get_tier(total)

    return {
        "brand_fit":     {"score": bf_score, "evidence": bf_ev, "conf": bf_conf},
        "firmographics": {"score": fi_score, "evidence": fi_ev, "conf": fi_conf},
        "contacts":      {"score": ca_score, "evidence": ca_ev, "conf": ca_conf},
        "buying_signal": {"score": bs_score, "evidence": bs_ev, "conf": bs_conf},
        "freshness":     {"score": fr_score, "evidence": fr_ev, "conf": fr_conf},
        "competitive":   {"score": co_score, "evidence": co_ev, "conf": co_conf},
        "total":         total,
        "tier":          tier,
        "tier_emoji":    emoji,
    }


def print_terminal_summary(company: str, website: str, scores: dict, total: int, tier: str, emoji: str):
    bar = lambda s: "█" * s + "░" * (3 - s)
    print(f"\n{'='*55}")
    print(f"=== OPREMA PROSPECT SCORED ===")
    print(f"{'='*55}")
    print(f"\nCompany:  {company} ({website})")
    print(f"Score:    {total}/18 — {emoji} {tier.upper()}")
    print(f"\nDimension Scores:")
    print(f"  Brand/Line Fit:          {scores['brand_fit']['score']}/3  {bar(scores['brand_fit']['score'])}  {scores['brand_fit']['conf']}")
    print(f"  Registry/Firmographics:  {scores['firmographics']['score']}/3  {bar(scores['firmographics']['score'])}  {scores['firmographics']['conf']}")
    print(f"  Contact Access:          {scores['contacts']['score']}/3  {bar(scores['contacts']['score'])}  {scores['contacts']['conf']}")
    print(f"  Opportunity/Buying:      {scores['buying_signal']['score']}/3  {bar(scores['buying_signal']['score'])}  {scores['buying_signal']['conf']}")
    print(f"  Freshness:               {scores['freshness']['score']}/3  {bar(scores['freshness']['score'])}  {scores['freshness']['conf']}")
    print(f"  Competitive/Incumbent:   {scores['competitive']['score']}/3  {bar(scores['competitive']['score'])}  {scores['competitive']['conf']}")
    gaps = extract_gaps({"queries": {}}, scores)
    if gaps:
        print(f"\nGaps to Close:")
        for g in gaps[:3]:
            print(f"  ⚠ {g[:70]}...")


def main():
    parser = argparse.ArgumentParser(description="Oprema Prospect Scorer")
    parser.add_argument("research_file", nargs="?", help="Research JSON file from prospect_research.py")
    parser.add_argument("--company", help="Company name (if not using research file)")
    parser.add_argument("--website", help="Website (if not using research file)")
    parser.add_argument("--research-text", help="Raw research text (if not using research file)")
    parser.add_argument("--brief-output", "-b", help="Output path for Markdown brief")
    parser.add_argument("--json-output", "-j", help="Output path for score JSON")
    args = parser.parse_args()

    if args.research_file:
        with open(args.research_file, encoding="utf-8") as f:
            research = json.load(f)
    elif args.company and args.research_text:
        research = {
            "company_name": args.company,
            "website": args.website or "",
            "research_date": datetime.now().strftime("%Y-%m-%d"),
            "queries": {"raw": args.research_text}
        }
    else:
        print("ERROR: Provide a research JSON file or --company + --research-text")
        sys.exit(1)

    scores = score_company(research)
    total = scores["total"]
    tier = scores["tier"]
    emoji = scores["tier_emoji"]

    company = research.get("company_name", "Unknown")
    website = research.get("website", "")

    print_terminal_summary(company, website, scores, total, tier, emoji)

    safe_name = "".join(c if c.isalnum() else "_" for c in company).strip("_")
    brief_path = args.brief_output or f"PROSPECT-{safe_name}.md"
    brief = generate_brief(research, scores, total, tier, emoji)

    with open(brief_path, "w", encoding="utf-8") as f:
        f.write(brief)
    print(f"\nBrief saved to: {brief_path}")

    if args.json_output:
        scores["company_name"] = company
        scores["website"] = website
        with open(args.json_output, "w", encoding="utf-8") as f:
            json.dump(scores, f, indent=2)
        print(f"Score JSON saved to: {args.json_output}")

    return scores


if __name__ == "__main__":
    main()
