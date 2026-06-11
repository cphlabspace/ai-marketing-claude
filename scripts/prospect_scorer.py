#!/usr/bin/env python3
"""
Oprema Prospect Scorer
Reads a research JSON file (from prospect_research.py) and applies the
6-dimension, 18-point Oprema scoring rubric to produce a scored brief.

Scoring is calibrated against Oprema's actual brand portfolio (profit-ranked)
and May item group sales volumes (Access Control: 29k, Fire: 21k, CCTV: ~13k).

Usage:
    python3 prospect_scorer.py research_AcmeSecurity_20260611.json
    python3 prospect_scorer.py research_AcmeSecurity_20260611.json --brief-output PROSPECT-Acme.md
    python3 prospect_scorer.py research_AcmeSecurity_20260611.json --json-output score_acme.json
"""

import sys
import os
import json
import argparse
import re
from datetime import datetime


# ---------------------------------------------------------------------------
# Oprema brand portfolio — ordered by profit (descending)
# Source: Oprema internal sales data
# ---------------------------------------------------------------------------

# Each entry: (brand_name, product_line, profit_tier)
# Tier 1 = top-profit brands; scoring rewards these most
OPREMA_BRANDS = [
    ("Dahua",               "CCTV / IP Video",      1),
    ("Hanwha",              "CCTV / IP Video",      1),
    ("Ernitec",             "CCTV / IP Video",      1),
    ("Paxton",              "Access Control",        1),
    ("Ajax",                "Intruder / Alarm",      1),
    ("Bosch",               "Multi-discipline",      1),
    ("Olix",                "CCTV / IP Video",       2),
    ("Secure Logiq",        "Video Management",      2),
    ("Comelit",             "Access Control",        2),
    ("Apollo",              "Fire Detection",        2),
    ("Advanced Electronics","Fire Detection",        2),
    ("Advanced Fire",       "Fire Detection",        2),
    ("Lanview",             "Networking / Infra",    2),
    ("Intratone",           "Access Control",        2),
    ("STP",                 "Networking / Infra",    3),
    ("ICS",                 "Access Control",        3),
    ("Texecom",             "Intruder / Alarm",      3),
    ("Hochiki",             "Fire Detection",        3),
    ("RGL",                 "Access Control",        3),
    ("CQR",                 "Intruder / Alarm",      3),
    ("Raytec",              "Illumination",          3),
    ("CDVI",                "Access Control",        3),
    ("AMG",                 "Networking / Infra",    3),
    ("Vanderbilt",          "Access Control",        3),
]

# Flat lists for quick matching
BRANDS_TIER1 = [b[0].lower() for b in OPREMA_BRANDS if b[2] == 1]
BRANDS_TIER2 = [b[0].lower() for b in OPREMA_BRANDS if b[2] == 2]
BRANDS_TIER3 = [b[0].lower() for b in OPREMA_BRANDS if b[2] == 3]
ALL_BRANDS   = [b[0].lower() for b in OPREMA_BRANDS]

# Display name → product line lookup
BRAND_TO_LINE = {b[0].lower(): b[1] for b in OPREMA_BRANDS}

# ---------------------------------------------------------------------------
# Oprema item groups — May volume (units sold), maps to product lines
# Used to weight which lines matter most for a prospect's potential
# ---------------------------------------------------------------------------

ITEM_GROUPS = {
    "Access Control":           {"line": "Access Control",        "may_qty": 29041},
    "Fire Detection":           {"line": "Fire Detection",        "may_qty": 20945},
    "Day & Night":              {"line": "CCTV / IP Video",       "may_qty": 7754},
    "Battery":                  {"line": "Accessories / Power",   "may_qty": 7380},
    "Expansion Modules":        {"line": "Intruder / Alarm",      "may_qty": 5090},
    "Brackets":                 {"line": "Accessories / Mounting","may_qty": 4651},
    "Other Surveillance":       {"line": "CCTV / IP Video",       "may_qty": 4409},
    "Accessories":              {"line": "Accessories",           "may_qty": 3278},
    "Cables":                   {"line": "Networking / Infra",    "may_qty": 2954},
    "Central Alarm Equipment":  {"line": "Intruder / Alarm",      "may_qty": 2712},
    "Raw Cables":               {"line": "Networking / Infra",    "may_qty": 1608},
    "Video Mngmt.":             {"line": "Video Management",      "may_qty": 838},
    "Others":                   {"line": "Miscellaneous",         "may_qty": 764},
    "PSU":                      {"line": "Accessories / Power",   "may_qty": 894},
    "Harddisks":                {"line": "Networking / Infra",    "may_qty": 579},
    "IP":                       {"line": "CCTV / IP Video",       "may_qty": 574},
    "Doorstations IP":          {"line": "Access Control",        "may_qty": 557},
    "CONSULTANCY":              {"line": "Services",              "may_qty": 485},
    "22-25\"":                  {"line": "Monitors / Displays",   "may_qty": 264},
    "POE":                      {"line": "Networking / Infra",    "may_qty": 257},
    "White Light":              {"line": "Illumination",          "may_qty": 115},
    "Speakers":                 {"line": "Audio / AV",            "may_qty": 115},
    "IR Light":                 {"line": "Illumination",          "may_qty": 101},
    "Hybrid":                   {"line": "CCTV / IP Video",       "may_qty": 93},
    "Outdoor":                  {"line": "CCTV / IP Video",       "may_qty": 72},
    "Desktop's":                {"line": "Video Management",      "may_qty": 49},
    "Rack Servers":             {"line": "Video Management",      "may_qty": 11},
    "Rack":                     {"line": "Networking / Infra",    "may_qty": 7},
    "Decoder":                  {"line": "Video Management",      "may_qty": 6},
    "52-82\"":                  {"line": "Monitors / Displays",   "may_qty": 23},
    "Audio Conference Accessories": {"line": "Audio / AV",        "may_qty": 24},
    "16-> port":                {"line": "Networking / Infra",    "may_qty": 86},
}

# Product lines ranked by May volume (for evidence labelling in briefs)
LINE_VOLUME_RANK = [
    "Access Control",       # 29,598 units (Access Control + Doorstations IP)
    "Fire Detection",       # 20,945
    "CCTV / IP Video",      # ~12,830 (Day&Night + IP + Other Surv + Hybrid + Outdoor)
    "Intruder / Alarm",     # ~7,802 (Expansion Modules + Central Alarm)
    "Accessories / Power",  # ~8,274 (Battery + PSU)
    "Networking / Infra",   # ~5,512 (Cables + Raw + POE + 16port + Rack + HDD)
    "Video Management",     # 898
    "Illumination",         # 288
]

# ---------------------------------------------------------------------------
# Sector keyword matching (fallback when specific brands not mentioned)
# ---------------------------------------------------------------------------

LINE_KEYWORDS = {
    "CCTV / IP Video": [
        "cctv", "ip camera", "nvr", "dvr", "video surveillance", "video recorder",
        "day & night camera", "day night camera", "ptz", "anpr", "body worn",
        "video analytics", "vms", "hybrid recorder"
    ],
    "Access Control": [
        "access control", "door entry", "intercom", "video intercom", "door controller",
        "key fob", "card reader", "turnstile", "barrier", "door access", "biometric",
        "proximity reader", "electronic lock", "door station", "door phone"
    ],
    "Intruder / Alarm": [
        "intruder alarm", "burglar alarm", "alarm panel", "alarm system",
        "arc monitoring", "alarm receiving", "grade 2", "grade 3",
        "motion detector", "pir detector", "wired alarm", "wireless alarm", "intruder detection"
    ],
    "Fire Detection": [
        "fire alarm", "fire detection", "fire panel", "smoke detector", "heat detector",
        "fire suppression", "bs 5839", "bafe", "fia member", "fire protection",
        "addressable fire", "conventional fire", "fire sprinkler"
    ],
    "Networking / Infra": [
        "structured cabling", "poe switch", "network switch", "fibre", "patch panel",
        "cable installation", "data cabling", "cat6", "cat5", "rack installation"
    ],
    "Illumination": [
        "ir illuminator", "white light", "cctv lighting", "security lighting",
        "infrared light", "covert lighting"
    ],
    "Video Management": [
        "vms", "video management", "milestone", "genetec", "video server",
        "nvr appliance", "recording server"
    ],
}

# ---------------------------------------------------------------------------
# Firmographic / accreditation markers
# ---------------------------------------------------------------------------

SIC_SECURITY = ["43210", "80200", "84250", "71121", "43290"]
ACCREDITATIONS = [
    "ssaib", "nsi nacoss", "nsi gold", "bafe", "niceic",
    "safe contractor", "constructionline", "iso 9001", "iso9001", "nsi acs"
]

# ---------------------------------------------------------------------------
# Buying signals
# ---------------------------------------------------------------------------

BUYING_SIGNAL_STRONG = [
    "procurement coordinator", "stock coordinator", "purchasing manager",
    "procurement manager", "supply chain", "new office", "new branch",
    "acquisition", "acquired", "roll-up", "consolidat", "contract win",
    "framework award", "tender award", "expanding", "new region",
    "opening new", "national contract", "central procurement"
]

BUYING_SIGNAL_MODERATE = [
    "hiring", "vacancy", "recruit", "engineer wanted", "join our team",
    "growing team", "new appointment", "promoted to", "key account manager"
]

# ---------------------------------------------------------------------------
# Incumbent distributors (competitors to Oprema)
# ---------------------------------------------------------------------------

INCUMBENT_CLUES = [
    "rexel", "comark", "adi global", "adi ", "norbain", "videcon",
    "cie group", "cse distributors", "seidor", "azena", "eet europarts",
    "tlc direct", "ajax distributor", "dahua distributor"
]

# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------

TIER_MAP = [
    (15, 18, "HiPo",    "🔴"),
    (11, 14, "Prospect","🟠"),
    (7,  10, "Watch",   "🟡"),
    (0,   6, "Qualify", "⚪"),
]


def get_tier(score: int) -> tuple:
    for low, high, name, emoji in TIER_MAP:
        if low <= score <= high:
            return name, emoji
    return "Qualify", "⚪"


def text_contains(text: str, keywords: list) -> list:
    """Return list of matched keywords found in text (case-insensitive)."""
    t = text.lower()
    return [kw for kw in keywords if kw.lower() in t]


# ---------------------------------------------------------------------------
# Dimension 1: Brand / Line Fit
# ---------------------------------------------------------------------------

def score_brand_fit(text: str) -> tuple:
    """
    Score 3: 1+ Tier 1 Oprema brand VERIFIED, OR 2+ any Oprema brands confirmed
    Score 2: 1+ any Oprema brand found (INFERRED), OR strong sector match in top-3 lines
    Score 1: Sector-adjacent only (generic security/fire/access keywords)
    Score 0: No fit
    """
    t = text.lower()

    matched_t1 = [b for b in BRANDS_TIER1 if b in t]
    matched_t2 = [b for b in BRANDS_TIER2 if b in t]
    matched_t3 = [b for b in BRANDS_TIER3 if b in t]
    all_matched = matched_t1 + matched_t2 + matched_t3

    # Check if any matches are near "VERIFIED" in text
    has_verified_context = "verified" in t or "confirmed" in t or "primary source" in t

    # Sector keywords for top-volume lines
    top_sector_hits = (
        text_contains(text, LINE_KEYWORDS["Access Control"]) +
        text_contains(text, LINE_KEYWORDS["Fire Detection"]) +
        text_contains(text, LINE_KEYWORDS["CCTV / IP Video"])
    )

    if matched_t1 and has_verified_context:
        score, conf = 3, "VERIFIED"
        evidence = f"Tier-1 Oprema brand(s) confirmed: {', '.join(b.title() for b in matched_t1[:3])}"
    elif len(all_matched) >= 2:
        score, conf = 3, "INFERRED"
        display = [b.title() for b in all_matched[:4]]
        evidence = f"Multiple Oprema brands in install mix: {', '.join(display)}"
    elif len(all_matched) == 1:
        score, conf = 2, "INFERRED"
        b = all_matched[0]
        line = BRAND_TO_LINE.get(b, "unknown line")
        evidence = f"{b.title()} ({line}) install likely — UNVERIFIED, confirm on call"
    elif len(top_sector_hits) >= 3:
        score, conf = 2, "INFERRED"
        evidence = f"Strong sector fit: {', '.join(top_sector_hits[:3])} — specific brands UNVERIFIED"
    elif len(top_sector_hits) >= 1:
        score, conf = 1, "INFERRED"
        evidence = f"Sector-adjacent: {', '.join(top_sector_hits[:2])}"
    else:
        score, conf = 0, "VERIFIED"
        evidence = "No security/fire/access install business found in research"

    return score, evidence, conf


# ---------------------------------------------------------------------------
# Dimension 2: Registry / Firmographics
# ---------------------------------------------------------------------------

def score_firmographics(text: str) -> tuple:
    has_ch_number    = bool(re.search(r'\b\d{8}\b', text))
    has_active       = bool(re.search(r'\bactive\b', text, re.IGNORECASE))
    has_director     = bool(re.search(r'director|officer|founder|proprietor|owner', text, re.IGNORECASE))
    has_sic          = any(sic in text for sic in SIC_SECURITY)
    has_accreditation= bool(text_contains(text, ACCREDITATIONS))
    has_address      = bool(re.search(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', text))

    verified_count = sum([has_ch_number, has_active, has_director,
                          has_sic or has_accreditation, has_address])

    if verified_count >= 4:
        score, conf = 3, "VERIFIED"
        evidence = "Companies House verified: entity active, director(s), SIC/accreditations, address"
    elif verified_count >= 2:
        score, conf = 2, "INFERRED"
        parts = []
        if has_ch_number: parts.append("CH no.")
        if has_director: parts.append("director")
        if has_accreditation: parts.append(text_contains(text, ACCREDITATIONS)[0].upper())
        if has_address: parts.append("address")
        evidence = f"Partial verify: {', '.join(parts)}"
    elif verified_count == 1:
        score, conf = 1, "UNVERIFIED"
        evidence = "Minimal firmographic data — trading name only or limited Companies House match"
    else:
        score, conf = 0, "UNVERIFIED"
        evidence = "Cannot verify — no Companies House data or accreditation found"

    return score, evidence, conf


# ---------------------------------------------------------------------------
# Dimension 3: Contact Access
# ---------------------------------------------------------------------------

def score_contact_access(text: str) -> tuple:
    has_md = bool(re.search(
        r'managing director|chief exec|ceo|founder|owner|director\b', text, re.IGNORECASE
    ))
    has_procurement = bool(re.search(
        r'procurement|purchasing|stock manager|supply chain|operations director|ops director|buyer\b',
        text, re.IGNORECASE
    ))
    has_technical = bool(re.search(
        r'technical sales|head of install|installation manager|engineer.*manager|'
        r'technical director|systems designer|pre-sales',
        text, re.IGNORECASE
    ))
    registry_verified = bool(re.search(
        r'companies house.*director|sole director|registered.*officer|registry.verif',
        text, re.IGNORECASE
    ))
    named_contacts = len(re.findall(r'\b[A-Z][a-z]+ [A-Z][a-z]+\b', text))

    if has_md and has_procurement and has_technical:
        score = 3
        conf = "VERIFIED" if registry_verified else "INFERRED"
        evidence = "Deep directory: MD + Procurement/Ops + Technical contact found"
    elif has_md and (has_procurement or has_technical):
        score, conf = 2, "INFERRED"
        evidence = f"MD + {'procurement' if has_procurement else 'technical'} contact found (LinkedIn-sourced)"
    elif has_md or named_contacts >= 3:
        score, conf = 1, "INFERRED"
        evidence = "MD/owner identified — procurement/technical contacts not yet found"
    else:
        score, conf = 0, "UNVERIFIED"
        evidence = "No named contacts identified in research"

    return score, evidence, conf


# ---------------------------------------------------------------------------
# Dimension 4: Opportunity / Buying Signal
# ---------------------------------------------------------------------------

def score_buying_signal(text: str) -> tuple:
    strong  = text_contains(text, BUYING_SIGNAL_STRONG)
    moderate= text_contains(text, BUYING_SIGNAL_MODERATE)
    verified_context = "verified" in text.lower()

    if len(strong) >= 2 or (strong and moderate):
        score = 3
        conf = "VERIFIED" if verified_context else "INFERRED"
        evidence = f"Multiple signals: {', '.join(strong[:2])}{', ' + moderate[0] if moderate else ''}"
    elif len(strong) == 1:
        score, conf = 2, "INFERRED"
        evidence = f"Signal: {strong[0]}"
    elif len(moderate) >= 2:
        score, conf = 2, "INFERRED"
        evidence = f"Growth signals: {', '.join(moderate[:2])}"
    elif len(moderate) == 1:
        score, conf = 1, "INFERRED"
        evidence = f"Weak signal only: {moderate[0]}"
    else:
        score, conf = 0, "UNVERIFIED"
        evidence = "No buying signals found in research"

    return score, evidence, conf


# ---------------------------------------------------------------------------
# Dimension 5: Freshness
# ---------------------------------------------------------------------------

def score_freshness(text: str) -> tuple:
    current_year = str(datetime.now().year)
    last_year    = str(datetime.now().year - 1)

    has_current  = current_year in text
    has_last     = last_year in text
    has_hiring   = bool(re.search(r'hiring|vacanc|recruit|apply now|join us|open position', text, re.IGNORECASE))
    has_news     = bool(re.search(r'announced|launched|opened|won contract|awarded|appointed|joined', text, re.IGNORECASE))
    is_dormant   = bool(re.search(r'dormant|ceased|no recent|inactive|dissolved|struck off|winding', text, re.IGNORECASE))

    if is_dormant:
        return 0, "Dormant or ceased trading — verify before outreach", "VERIFIED"

    if has_current and (has_hiring or has_news):
        score, conf = 3, "VERIFIED"
        evidence = f"Active {current_year}: {'hiring + ' if has_hiring else ''}{'recent news/activity' if has_news else 'current year activity'}"
    elif has_current or (has_last and has_hiring):
        score, conf = 2, "INFERRED"
        evidence = f"Recent activity: {current_year if has_current else last_year}{', hiring' if has_hiring else ''}"
    elif has_last or has_news:
        score, conf = 1, "INFERRED"
        evidence = f"Limited recent signal ({last_year})"
    else:
        score, conf = 1, "UNVERIFIED"
        evidence = "Activity recency unclear — no date-stamped signals in research"

    return score, evidence, conf


# ---------------------------------------------------------------------------
# Dimension 6: Competitive / Incumbent
# ---------------------------------------------------------------------------

def score_competitive(text: str) -> tuple:
    named = text_contains(text, INCUMBENT_CLUES)
    has_window = bool(re.search(
        r'procurement build|centralising|consolidat|reviewing supplier|changing supplier|'
        r'new purchas|multi.site.*supply|group.supply|single.*distributor',
        text, re.IGNORECASE
    ))

    if named and has_window:
        score, conf = 3, "INFERRED"
        evidence = f"Incumbent ({', '.join(n.title() for n in named[:2])}) + displacement window identified"
    elif named:
        score, conf = 2, "INFERRED"
        evidence = f"Incumbent likely: {', '.join(n.title() for n in named[:2])} — no specific window yet"
    elif has_window:
        score, conf = 2, "INFERRED"
        evidence = "Displacement window exists (procurement/consolidation change) — incumbent unknown"
    else:
        score, conf = 1, "UNVERIFIED"
        evidence = "Incumbent situation unknown — ask on discovery: 'Who do you currently buy from?'"

    return score, evidence, conf


# ---------------------------------------------------------------------------
# Honest gaps
# ---------------------------------------------------------------------------

def extract_gaps(research: dict, scores: dict) -> list:
    all_text = " ".join(str(v) for v in research.get("queries", {}).values())
    gaps = []

    if scores["brand_fit"]["score"] < 3:
        gaps.append(
            "BRANDS: Specific manufacturers UNVERIFIED — ask on call: "
            "'Which brands do you install for CCTV/access/fire/intruder?'"
        )
    if scores["firmographics"]["score"] < 3:
        gaps.append("REGISTRY: Companies House data incomplete — verify entity and director before outreach")
    if scores["contacts"]["score"] == 0:
        gaps.append("CONTACTS: No named contacts found — use website/LinkedIn to identify MD before calling")
    elif scores["contacts"]["score"] < 3:
        gaps.append(
            "CONTACTS: Procurement/technical contacts LinkedIn-sourced only — "
            "capture direct email/DDI before outreach (Rule 8)"
        )
    if not text_contains(all_text, INCUMBENT_CLUES + ["distributor", "supplier"]):
        gaps.append(
            "INCUMBENT: Current distributor(s) unknown — ask: "
            "'Who do you currently buy CCTV/access/fire kit from?'"
        )
    if scores["buying_signal"]["score"] < 2:
        gaps.append("BUYING SIGNAL: No verified procurement trigger — qualify opportunity on first call")
    if scores["freshness"]["score"] < 2:
        gaps.append("FRESHNESS: Activity recency low — confirm company is actively trading before outreach")

    return gaps


# ---------------------------------------------------------------------------
# Line fit table helper
# ---------------------------------------------------------------------------

def _assess_line(text: str, line_name: str, brands: list, keywords: list) -> tuple:
    """Returns (fit_label, evidence, conf) for one product line."""
    t = text.lower()
    matched_brands  = [b for b in brands if b.lower() in t]
    matched_keywords= text_contains(text, keywords)

    if matched_brands and ("verified" in t or "confirmed" in t):
        return "**STRONG**", f"{', '.join(b.title() for b in matched_brands[:3])}", "VERIFIED"
    elif matched_brands:
        return "**STRONG**", f"{', '.join(b.title() for b in matched_brands[:3])} (confirm on call)", "INFERRED"
    elif len(matched_keywords) >= 2:
        return "**minor**", f"{', '.join(matched_keywords[:2])}", "INFERRED"
    elif len(matched_keywords) == 1:
        return "minor", matched_keywords[0], "INFERRED"
    else:
        return "none", "No evidence", "VERIFIED"


LINE_DEFINITIONS = [
    {
        "name": "CCTV / IP Video",
        "may_qty": 12830,
        "brands": ["Dahua", "Hanwha", "Ernitec", "Olix", "Secure Logiq", "Bosch"],
        "item_groups": "Day & Night (7.8k), IP (0.6k), Other Surveillance (4.4k)",
        "keywords": LINE_KEYWORDS["CCTV / IP Video"],
    },
    {
        "name": "Access Control",
        "may_qty": 29598,
        "brands": ["Paxton", "Comelit", "Intratone", "ICS", "CDVI", "RGL", "Vanderbilt"],
        "item_groups": "Access Control (29k), Doorstations IP (0.6k)",
        "keywords": LINE_KEYWORDS["Access Control"],
    },
    {
        "name": "Intruder / Alarm",
        "may_qty": 7802,
        "brands": ["Ajax", "Texecom", "CQR", "Bosch"],
        "item_groups": "Expansion Modules (5.1k), Central Alarm Equip (2.7k)",
        "keywords": LINE_KEYWORDS["Intruder / Alarm"],
    },
    {
        "name": "Fire Detection",
        "may_qty": 20945,
        "brands": ["Apollo", "Advanced Electronics", "Advanced Fire", "Hochiki", "Bosch"],
        "item_groups": "Fire Detection (20.9k)",
        "keywords": LINE_KEYWORDS["Fire Detection"],
    },
    {
        "name": "Networking / Infra",
        "may_qty": 5512,
        "brands": ["Lanview", "STP", "AMG"],
        "item_groups": "Cables (3k), Raw Cables (1.6k), POE (0.3k), Harddisks (0.6k)",
        "keywords": LINE_KEYWORDS["Networking / Infra"],
    },
    {
        "name": "Illumination",
        "may_qty": 288,
        "brands": ["Raytec"],
        "item_groups": "IR Light (0.1k), White Light (0.1k)",
        "keywords": LINE_KEYWORDS["Illumination"],
    },
    {
        "name": "Video Management",
        "may_qty": 898,
        "brands": ["Secure Logiq"],
        "item_groups": "Video Mngmt (0.8k), Rack Servers (11)",
        "keywords": LINE_KEYWORDS["Video Management"],
    },
]


def build_line_fit_table(text: str) -> str:
    """Build the Oprema Line Fit markdown table for a brief."""
    rows = ["| Oprema Line | May Vol. | Fit | Oprema Brands | Evidence | Conf. |",
            "|-------------|----------|-----|---------------|----------|-------|"]
    for ld in LINE_DEFINITIONS:
        fit, evidence, conf = _assess_line(text, ld["name"], ld["brands"], ld["keywords"])
        brand_str = ", ".join(ld["brands"][:4])
        rows.append(
            f"| {ld['name']} | {ld['may_qty']:,} | {fit} | {brand_str} | {evidence} | {conf} |"
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Brief generator
# ---------------------------------------------------------------------------

def generate_brief(research: dict, scores: dict, total: int, tier: str, tier_emoji: str) -> str:
    company = research.get("company_name", "Unknown")
    website = research.get("website", "")
    date    = research.get("research_date", datetime.now().strftime("%Y-%m-%d"))
    all_text= " ".join(str(v) for v in research.get("queries", {}).values())

    # Brands actually found in research
    brands_found = [b[0] for b in OPREMA_BRANDS if b[0].lower() in all_text.lower()]

    gaps = extract_gaps(research, scores)

    score_str = (
        f"Brand/line fit **{scores['brand_fit']['score']}** · "
        f"Registry/firmographics **{scores['firmographics']['score']}** · "
        f"Contact access **{scores['contacts']['score']}** · "
        f"Opportunity/buying-signal **{scores['buying_signal']['score']}** · "
        f"Freshness **{scores['freshness']['score']}** · "
        f"Competitive/incumbent **{scores['competitive']['score']}** = "
        f"**{total}/18 — {tier}**"
    )

    lead_line = brands_found[0] if brands_found else "CCTV / Access Control / Fire"
    lead_brands_str = ", ".join(brands_found[:3]) if brands_found else "confirm on call"

    line_fit_table = build_line_fit_table(all_text)

    brief = f"""# Oprema Prospect Brief
**{company}** · UK · {website}
**{total} / 18 — {tier_emoji} {tier.upper()}**

---

## The Play

*(Auto-populated signals below — synthesise into a 2–3 paragraph strategic narrative
for the sales rep: why this company, which Oprema lines fit, what the timing window is,
and how to open the conversation.)*

- **Brand fit:** {scores['brand_fit']['evidence']}
- **Buying signal:** {scores['buying_signal']['evidence']}
- **Competitive angle:** {scores['competitive']['evidence']}
- **Lead line by Oprema volume:** {lead_line} — Oprema's top Access Control line (29k units/month May)
  and Fire Detection (21k units/month May) are the highest-volume attach to this sector

---

## Next Steps

1. **Lead with:** {lead_brands_str} — position Oprema as the consolidated UK supply partner
2. **Entry contact:** {scores['contacts']['evidence']}
3. **Timing window:** {scores['buying_signal']['evidence']}
4. **Verify on call:** Ask which brands they install for CCTV / access / fire / intruder — do not assume
5. **Attach:** Networking/Infra (PoE, Lanview cabling, Harddisks) as natural CCTV upsell;
   Raytec illumination if outdoor CCTV evident
6. **Gap to close first:** {gaps[0] if gaps else 'None critical'}

---

## Who to Call

| Contact | Function | Why / Approach |
|---------|----------|----------------|
| *(MD/Owner — from research)* | Commercial / Decision-maker | Strategic supply conversation; consolidated account across sites |
| *(Ops/Procurement — from research)* | Procurement / category-owner | Kit selection; day-to-day purchasing; who signs off on stock orders |
| *(Head of Installs / Tech Sales)* | Technical | Product mix discovery; brand preferences; volumes |

*(Populate names and direct contacts from research data below — verify emails before outreach)*

---

## Oprema Line Fit

{line_fit_table}

*Volume = Oprema May units sold — indicates revenue potential of each line for this prospect type.*

---

## Brand List

{'**Oprema brands found in research:** ' + ', '.join(brands_found) if brands_found else 'UNVERIFIED — no specific Oprema brands confirmed from primary sources.'}

**Industry-typical for this sector (CONFIRM ON CALL — do not assume):**
- CCTV: Dahua / Hanwha / Ernitec / Olix
- Access: Paxton / Comelit / Intratone / CDVI
- Intruder: Ajax / Texecom / CQR
- Fire: Apollo / Advanced Electronics / Hochiki

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

## Raw Research

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
*Oprema Prospect Brief · {company} · generated {date} · Oprema 6-dimension scoring methodology ·
research via Perplexity API + Apify. Brands ranked by Oprema profit; volumes from May item group data.
Confidence: VERIFIED = primary source · INFERRED = derived · UNVERIFIED = confirm before asserting.*
"""
    return brief


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def score_company(research: dict) -> dict:
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
        "total":  total,
        "tier":   tier,
        "tier_emoji": emoji,
    }


def print_terminal_summary(company: str, website: str, scores: dict, total: int, tier: str, emoji: str):
    bar = lambda s: "█" * s + "░" * (3 - s)
    print(f"\n{'='*55}")
    print(f"=== OPREMA PROSPECT SCORED ===")
    print(f"{'='*55}")
    print(f"\nCompany:  {company}")
    if website:
        print(f"Website:  {website}")
    print(f"Score:    {total}/18 — {emoji} {tier.upper()}")
    print(f"\nDimension Scores:")
    dims = [
        ("Brand/Line Fit         ", "brand_fit"),
        ("Registry/Firmographics ", "firmographics"),
        ("Contact Access         ", "contacts"),
        ("Opportunity/Buying     ", "buying_signal"),
        ("Freshness              ", "freshness"),
        ("Competitive/Incumbent  ", "competitive"),
    ]
    for label, key in dims:
        s = scores[key]
        print(f"  {label} {s['score']}/3  {bar(s['score'])}  {s['conf']}")
        print(f"    → {s['evidence'][:70]}")
    gaps = extract_gaps({"queries": {}}, scores)
    if gaps:
        print(f"\nGaps to Close:")
        for g in gaps[:3]:
            print(f"  ⚠ {g[:72]}")


def main():
    parser = argparse.ArgumentParser(description="Oprema Prospect Scorer")
    parser.add_argument("research_file", nargs="?")
    parser.add_argument("--company")
    parser.add_argument("--website", default="")
    parser.add_argument("--research-text")
    parser.add_argument("--brief-output", "-b")
    parser.add_argument("--json-output", "-j")
    args = parser.parse_args()

    if args.research_file:
        with open(args.research_file, encoding="utf-8") as f:
            research = json.load(f)
    elif args.company and args.research_text:
        research = {
            "company_name": args.company,
            "website": args.website,
            "research_date": datetime.now().strftime("%Y-%m-%d"),
            "queries": {"raw": args.research_text},
        }
    else:
        print("ERROR: Provide a research JSON file or --company + --research-text")
        sys.exit(1)

    scores = score_company(research)
    total  = scores["total"]
    tier   = scores["tier"]
    emoji  = scores["tier_emoji"]

    company = research.get("company_name", "Unknown")
    website = research.get("website", "")

    print_terminal_summary(company, website, scores, total, tier, emoji)

    safe = "".join(c if c.isalnum() else "_" for c in company).strip("_")
    brief_path = args.brief_output or f"PROSPECT-{safe}.md"
    brief = generate_brief(research, scores, total, tier, emoji)

    with open(brief_path, "w", encoding="utf-8") as f:
        f.write(brief)
    print(f"\nBrief saved to: {brief_path}")

    if args.json_output:
        out = {**scores, "company_name": company, "website": website}
        with open(args.json_output, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"Score JSON:     {args.json_output}")

    return scores


if __name__ == "__main__":
    main()
