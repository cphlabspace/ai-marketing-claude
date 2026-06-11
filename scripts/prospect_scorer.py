#!/usr/bin/env python3
"""
Oprema Prospect Scorer
Reads research JSON and applies the 6-dimension, 18-point Oprema rubric.

SCORING PHILOSOPHY
==================
Category is the qualifier. Brand is the sales intelligence.

A company installing Hikvision CCTV + Honeywell access control scores the
same on Category Fit as one already using Dahua + Paxton. Both are in the
right buying categories — the sales conversation simply starts differently.
Oprema brands found in research are recorded as supporting evidence and
sales intelligence, NOT as the scoring gate.

Dimension 1 is "Category Fit" (not brand fit):
  Score 3 = installs in 2+ Oprema categories (CCTV, access, fire, intruder)
  Score 2 = installs in 1 high-volume category with good evidence
  Score 1 = sector-adjacent or single minor category
  Score 0 = no fit

Usage:
    python3 prospect_scorer.py research_AcmeSecurity.json
    python3 prospect_scorer.py research_AcmeSecurity.json --brief-output PROSPECT-Acme.md
    python3 prospect_scorer.py research_AcmeSecurity.json --json-output score_acme.json
"""

import sys
import os
import json
import argparse
import re
from datetime import datetime


# ---------------------------------------------------------------------------
# Oprema brand portfolio — profit-ranked
# Used as SUPPORTING EVIDENCE within category scoring, not as the gate.
# ---------------------------------------------------------------------------

OPREMA_BRANDS = [
    # (brand, category, profit_tier)
    ("Dahua",               "CCTV / IP Video",    1),
    ("Hanwha",              "CCTV / IP Video",    1),
    ("Ernitec",             "CCTV / IP Video",    1),
    ("Paxton",              "Access Control",      1),
    ("Ajax",                "Intruder / Alarm",    1),
    ("Bosch",               "Multi-discipline",    1),
    ("Olix",                "CCTV / IP Video",     2),
    ("Secure Logiq",        "Video Management",    2),
    ("Comelit",             "Access Control",      2),
    ("Apollo",              "Fire Detection",      2),
    ("Advanced Electronics","Fire Detection",      2),
    ("Advanced Fire",       "Fire Detection",      2),
    ("Lanview",             "Networking / Infra",  2),
    ("Intratone",           "Access Control",      2),
    ("STP",                 "Networking / Infra",  3),
    ("ICS",                 "Access Control",      3),
    ("Texecom",             "Intruder / Alarm",    3),
    ("Hochiki",             "Fire Detection",      3),
    ("RGL",                 "Access Control",      3),
    ("CQR",                 "Intruder / Alarm",    3),
    ("Raytec",              "Illumination",        3),
    ("CDVI",                "Access Control",      3),
    ("AMG",                 "Networking / Infra",  3),
    ("Vanderbilt",          "Access Control",      3),
]

BRAND_TO_LINE  = {b[0].lower(): b[1] for b in OPREMA_BRANDS}
BRAND_NAMES_LC = [b[0].lower() for b in OPREMA_BRANDS]

# Brands NOT in Oprema portfolio but common in the industry.
# Finding these signals category fit even without Oprema brand alignment.
NON_OPREMA_CATEGORY_BRANDS = {
    "CCTV / IP Video":   ["hikvision", "axis", "avigilon", "genetec", "milestone",
                           "mobotix", "uniview", "cp plus", "provision isr"],
    "Access Control":    ["hid", "salto", "lenel", "ccure", "allegion", "dormakaba",
                           "honeywell access", "assa abloy", "gallagher", "inner range"],
    "Fire Detection":    ["notifier", "gent", "simplex", "kentec", "c-tec", "nittan",
                           "fike", "fenwal", "siemens fire", "cerberus"],
    "Intruder / Alarm":  ["pyronix", "honeywell security", "paradox", "risco", "dsc",
                           "crow", "optex", "visonic", "napco", "bentel"],
    "Networking / Infra":["ubiquiti", "tp-link", "cisco", "netgear", "zyxel",
                           "ruckus", "meraki", "planet networking"],
}

# ---------------------------------------------------------------------------
# Oprema product categories — ordered by May sales volume
# These are the categories we score against, regardless of which brand
# ---------------------------------------------------------------------------

OPREMA_CATEGORIES = {
    "Access Control": {
        "may_qty": 29598,
        "oprema_brands": ["Paxton", "Comelit", "Intratone", "ICS", "CDVI", "RGL", "Vanderbilt"],
        "keywords": [
            "access control", "door entry", "intercom", "video intercom", "door controller",
            "key fob", "card reader", "turnstile", "barrier", "door access", "biometric entry",
            "proximity reader", "electronic lock", "door station", "door phone",
            "door hardware", "gate controller", "barrier system", "fob entry"
        ],
    },
    "Fire Detection": {
        "may_qty": 20945,
        "oprema_brands": ["Apollo", "Advanced Electronics", "Advanced Fire", "Hochiki", "Bosch"],
        "keywords": [
            "fire alarm", "fire detection", "fire panel", "smoke detector", "heat detector",
            "fire suppression", "bs 5839", "bafe", "fia", "fire protection",
            "addressable fire", "conventional fire", "fire sprinkler", "fire system",
            "fire maintenance", "fire service"
        ],
    },
    "CCTV / IP Video": {
        "may_qty": 12830,
        "oprema_brands": ["Dahua", "Hanwha", "Ernitec", "Olix", "Secure Logiq"],
        "keywords": [
            "cctv", "ip camera", "nvr", "dvr", "video surveillance", "surveillance camera",
            "video recorder", "day & night", "ptz", "anpr", "body worn",
            "video analytics", "vms", "hybrid recorder", "ip video", "security camera"
        ],
    },
    "Intruder / Alarm": {
        "may_qty": 7802,
        "oprema_brands": ["Ajax", "Texecom", "CQR", "Bosch"],
        "keywords": [
            "intruder alarm", "burglar alarm", "alarm panel", "alarm system",
            "arc monitoring", "alarm receiving", "grade 2", "grade 3",
            "motion detector", "pir", "wired alarm", "wireless alarm",
            "intruder detection", "security alarm", "perimeter detection"
        ],
    },
    "Networking / Infra": {
        "may_qty": 5512,
        "oprema_brands": ["Lanview", "STP", "AMG"],
        "keywords": [
            "structured cabling", "poe switch", "network switch", "fibre", "fibre optic",
            "patch panel", "cable installation", "data cabling", "cat6", "cat5",
            "rack installation", "network infrastructure"
        ],
    },
    "Illumination": {
        "may_qty": 288,
        "oprema_brands": ["Raytec"],
        "keywords": [
            "ir illuminator", "white light illuminator", "cctv lighting",
            "security lighting", "infrared light", "covert lighting"
        ],
    },
}

# ---------------------------------------------------------------------------
# Firmographic markers
# ---------------------------------------------------------------------------

SIC_SECURITY     = ["43210", "80200", "84250", "71121", "43290"]
ACCREDITATIONS   = ["ssaib", "nsi nacoss", "nsi gold", "bafe", "niceic",
                    "safe contractor", "constructionline", "iso 9001", "iso9001", "nsi acs"]

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
# Incumbent distributors
# ---------------------------------------------------------------------------

INCUMBENT_CLUES = [
    "rexel", "comark", "adi global", "adi ", "norbain", "videcon",
    "cie group", "cse distributors", "seidor", "azena", "eet europarts",
    "tlc direct", "snap av", "external distributor"
]

# ---------------------------------------------------------------------------
# Tier map
# ---------------------------------------------------------------------------

TIER_MAP = [
    (15, 18, "HiPo",     "🔴"),
    (11, 14, "Prospect", "🟠"),
    (7,  10, "Watch",    "🟡"),
    (0,   6, "Qualify",  "⚪"),
]


def get_tier(score: int):
    for low, high, name, emoji in TIER_MAP:
        if low <= score <= high:
            return name, emoji
    return "Qualify", "⚪"


_NEGATION_PATTERN = re.compile(
    r'\b(no|not|none|without|never|doesn\'t|does not|cannot|can\'t|'
    r'no evidence|not found|not identified|unverified|n/a)\b',
    re.IGNORECASE,
)

def text_contains(text: str, keywords: list) -> list:
    """Match keywords, skipping matches preceded by negation within 50 chars."""
    t = text.lower()
    matched = []
    for kw in keywords:
        kw_lc = kw.lower()
        pos = 0
        found = False
        while True:
            idx = t.find(kw_lc, pos)
            if idx == -1:
                break
            # Check 50 chars before the match for negation
            window = t[max(0, idx - 50): idx]
            if not _NEGATION_PATTERN.search(window):
                found = True
                break
            pos = idx + 1
        if found:
            matched.append(kw)
    return matched


# ---------------------------------------------------------------------------
# Dimension 1: Category Fit (0–3)
# Score on which CATEGORIES the company installs in, regardless of brand.
# Brand findings are secondary evidence, stored for the brief.
# ---------------------------------------------------------------------------

def score_category_fit(text: str) -> tuple:
    """
    Score 3: Operates in 2+ Oprema categories — ideal multi-line opportunity
    Score 2: Strong fit in 1 high-volume category (Access/Fire/CCTV/Intruder)
    Score 1: Single lower-volume category or weak/inferred evidence
    Score 0: No security/fire/access install business found
    """
    t = text.lower()

    # Assess each category
    category_hits = {}
    for cat_name, cat_data in OPREMA_CATEGORIES.items():
        kw_matches    = text_contains(text, cat_data["keywords"])
        # Oprema brands found for this category
        opr_matches   = [b for b in cat_data["oprema_brands"] if b.lower() in t]
        # Non-Oprema brands in the same category (still proves category fit)
        non_opr = NON_OPREMA_CATEGORY_BRANDS.get(cat_name, [])
        non_opr_matches = [b for b in non_opr if b in t]

        if kw_matches or opr_matches or non_opr_matches:
            category_hits[cat_name] = {
                "keywords": kw_matches[:3],
                "oprema_brands": opr_matches,
                "other_brands": non_opr_matches[:3],
            }

    high_value_cats = [c for c in category_hits
                       if c in ("Access Control", "Fire Detection",
                                "CCTV / IP Video", "Intruder / Alarm")]

    if len(high_value_cats) >= 2:
        score, conf = 3, "INFERRED"
        cats_str = " + ".join(high_value_cats[:3])
        evidence = f"Multi-line fit: {cats_str}"
    elif len(high_value_cats) == 1:
        cat = high_value_cats[0]
        h = category_hits[cat]
        score, conf = 2, "INFERRED"
        brand_note = ""
        if h["oprema_brands"]:
            brand_note = f" — Oprema brands: {', '.join(h['oprema_brands'][:2])}"
        elif h["other_brands"]:
            brand_note = f" — installs {', '.join(h['other_brands'][:2])} (non-Oprema, Oprema can pitch alternative)"
        evidence = f"Fits {cat} (Oprema: {OPREMA_CATEGORIES[cat]['may_qty']:,}/mo){brand_note}"
    elif category_hits:
        cat = list(category_hits.keys())[0]
        score, conf = 1, "INFERRED"
        evidence = f"Partial fit: {cat} (lower-volume line)"
    else:
        score, conf = 0, "VERIFIED"
        evidence = "No security/fire/access/intruder install category found"

    return score, evidence, conf, category_hits


# ---------------------------------------------------------------------------
# Dimension 2: Registry / Firmographics (0–3)
# ---------------------------------------------------------------------------

def score_firmographics(text: str, crm_data: dict = None) -> tuple:
    has_ch_number    = bool(re.search(r'\b\d{8}\b', text))
    has_active       = bool(re.search(r'\bactive\b', text, re.IGNORECASE))
    has_director     = bool(re.search(r'director|officer|founder|proprietor|owner', text, re.IGNORECASE))
    has_sic          = any(sic in text for sic in SIC_SECURITY)
    has_accreditation= bool(text_contains(text, ACCREDITATIONS))
    has_address      = bool(re.search(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', text))

    verified_count = sum([has_ch_number, has_active, has_director,
                          has_sic or has_accreditation, has_address])

    # Boost from CRM DUNS data if present
    crm_boost = ""
    if crm_data:
        if crm_data.get("dandb_category") in ("Gold", "Silver"):
            verified_count = min(verified_count + 1, 5)
            crm_boost = f" · D&B: {crm_data['dandb_category']}"
        if crm_data.get("revenue_duns"):
            crm_boost += f" · Revenue: £{int(float(str(crm_data['revenue_duns']).replace(',','.'))):,}"
        if crm_data.get("employees_duns"):
            crm_boost += f" · {crm_data['employees_duns']} employees"

    if verified_count >= 4:
        score, conf = 3, "VERIFIED"
        evidence = f"Companies House verified: entity, director(s), SIC/accreditations, address{crm_boost}"
    elif verified_count >= 2:
        score, conf = 2, "INFERRED"
        parts = []
        if has_ch_number: parts.append("CH no.")
        if has_director: parts.append("director")
        if has_accreditation:
            found = text_contains(text, ACCREDITATIONS)
            if found: parts.append(found[0].upper())
        if has_address: parts.append("address")
        evidence = f"Partial: {', '.join(parts)}{crm_boost}"
    elif verified_count == 1 or crm_boost:
        score, conf = 1, "UNVERIFIED"
        evidence = f"Minimal data — trading name only{crm_boost}"
    else:
        score, conf = 0, "UNVERIFIED"
        evidence = "Cannot verify — no Companies House data found"

    return score, evidence, conf


# ---------------------------------------------------------------------------
# Dimension 3: Contact Access (0–3)
# ---------------------------------------------------------------------------

def score_contact_access(text: str) -> tuple:
    has_md = bool(re.search(
        r'managing director|chief exec|ceo|founder|owner|director\b', text, re.IGNORECASE
    ))
    has_procurement = bool(re.search(
        r'procurement|purchasing|stock manager|supply chain|operations director|buyer\b',
        text, re.IGNORECASE
    ))
    has_technical = bool(re.search(
        r'technical sales|head of install|installation manager|engineer.*manager|'
        r'technical director|systems designer|pre-sales',
        text, re.IGNORECASE
    ))
    registry_verified = bool(re.search(
        r'companies house.*director|sole director|registered.*officer',
        text, re.IGNORECASE
    ))

    if has_md and has_procurement and has_technical:
        score = 3
        conf = "VERIFIED" if registry_verified else "INFERRED"
        evidence = "Deep directory: MD + Procurement/Ops + Technical contact found"
    elif has_md and (has_procurement or has_technical):
        score, conf = 2, "INFERRED"
        evidence = f"MD + {'procurement' if has_procurement else 'technical'} contact found"
    elif has_md:
        score, conf = 1, "INFERRED"
        evidence = "MD/owner identified — procurement/technical not yet found"
    else:
        score, conf = 0, "UNVERIFIED"
        evidence = "No named contacts identified"

    return score, evidence, conf


# ---------------------------------------------------------------------------
# Dimension 4: Opportunity / Buying Signal (0–3)
# ---------------------------------------------------------------------------

def score_buying_signal(text: str, crm_data: dict = None) -> tuple:
    strong   = text_contains(text, BUYING_SIGNAL_STRONG)
    moderate = text_contains(text, BUYING_SIGNAL_MODERATE)
    verified = "verified" in text.lower()

    # CRM data boosts: HIPO flag or D&B Gold are strong signals
    crm_signal = ""
    if crm_data:
        if str(crm_data.get("hipo_eval", "")).lower() == "yes":
            strong.append("HIPO-flagged by Oprema")
            crm_signal = " (HIPO flagged)"
        if crm_data.get("dandb_category") == "Gold" and not strong:
            moderate.append("D&B Gold category")
            crm_signal = " (D&B Gold)"

    if len(strong) >= 2 or (strong and moderate):
        score = 3
        conf = "VERIFIED" if verified else "INFERRED"
        evidence = f"Multiple signals: {', '.join(strong[:2])}{', ' + moderate[0] if moderate else ''}{crm_signal}"
    elif len(strong) == 1:
        score, conf = 2, "INFERRED"
        evidence = f"Signal: {strong[0]}{crm_signal}"
    elif len(moderate) >= 2:
        score, conf = 2, "INFERRED"
        evidence = f"Growth signals: {', '.join(moderate[:2])}{crm_signal}"
    elif len(moderate) == 1:
        score, conf = 1, "INFERRED"
        evidence = f"Weak signal: {moderate[0]}{crm_signal}"
    else:
        score, conf = 0, "UNVERIFIED"
        evidence = "No buying signals found in research"

    return score, evidence, conf


# ---------------------------------------------------------------------------
# Dimension 5: Freshness (0–3)
# ---------------------------------------------------------------------------

def score_freshness(text: str) -> tuple:
    cy = str(datetime.now().year)
    ly = str(datetime.now().year - 1)

    has_current = cy in text
    has_last    = ly in text
    has_hiring  = bool(re.search(r'hiring|vacanc|recruit|apply now|join us|open position', text, re.IGNORECASE))
    has_news    = bool(re.search(r'announced|launched|opened|won contract|awarded|appointed', text, re.IGNORECASE))
    is_dormant  = bool(re.search(r'dormant|ceased|no recent|inactive|dissolved|struck off', text, re.IGNORECASE))

    if is_dormant:
        return 0, "Dormant or ceased trading — verify before outreach", "VERIFIED"

    if has_current and (has_hiring or has_news):
        return 3, f"Active {cy}: {'hiring + ' if has_hiring else ''}recent activity", "VERIFIED"
    elif has_current or (has_last and has_hiring):
        return 2, f"Recent activity: {cy if has_current else ly}{', hiring' if has_hiring else ''}", "INFERRED"
    elif has_last or has_news:
        return 1, f"Limited recent signal ({ly})", "INFERRED"
    else:
        return 1, "Activity recency unclear — no date-stamped signals", "UNVERIFIED"


# ---------------------------------------------------------------------------
# Dimension 6: Competitive / Incumbent (0–3)
# ---------------------------------------------------------------------------

def score_competitive(text: str) -> tuple:
    named = text_contains(text, INCUMBENT_CLUES)
    has_window = bool(re.search(
        r'procurement build|centralising|consolidat|reviewing supplier|'
        r'changing supplier|new purchas|multi.site.*supply|group.supply|'
        r'single.*distributor',
        text, re.IGNORECASE
    ))

    if named and has_window:
        return 3, f"Incumbent ({', '.join(n.title() for n in named[:2])}) + displacement window", "INFERRED"
    elif named:
        return 2, f"Incumbent likely: {', '.join(n.title() for n in named[:2])} — no window yet", "INFERRED"
    elif has_window:
        return 2, "Displacement window exists — incumbent unknown", "INFERRED"
    else:
        return 1, "Incumbent unknown — ask: 'Who do you currently buy from?'", "UNVERIFIED"


# ---------------------------------------------------------------------------
# Honest gaps
# ---------------------------------------------------------------------------

def extract_gaps(research: dict, scores: dict, category_hits: dict) -> list:
    all_text = " ".join(str(v) for v in research.get("queries", {}).values())
    gaps = []

    # Gap 1: categories found but specific brands unconfirmed
    cats_without_brands = [
        cat for cat, data in category_hits.items()
        if not data.get("oprema_brands") and not data.get("other_brands")
    ]
    if cats_without_brands:
        gaps.append(
            f"BRANDS: Category fit found for {', '.join(cats_without_brands)} but specific brands UNVERIFIED"
            f" — ask: 'Which brands do you install for {cats_without_brands[0]}?'"
        )

    # Gap 2: non-Oprema brands found — sales intelligence
    non_oprema_found = []
    for cat, data in category_hits.items():
        if data.get("other_brands"):
            non_oprema_found.extend(data["other_brands"])
    if non_oprema_found:
        gaps.append(
            f"NON-OPREMA BRANDS: Installs {', '.join(set(non_oprema_found[:3]))} — "
            f"Oprema can pitch category alternatives or complementary lines"
        )

    if scores["firmographics"]["score"] < 3:
        gaps.append("REGISTRY: Companies House data incomplete — verify entity and director before outreach")
    if scores["contacts"]["score"] < 2:
        gaps.append("CONTACTS: Limited contacts found — identify MD/procurement before calling")
    elif scores["contacts"]["score"] == 2:
        gaps.append("CONTACTS: LinkedIn-sourced only — capture direct email/DDI before outreach")
    if not text_contains(all_text, INCUMBENT_CLUES + ["distributor", "supplier"]):
        gaps.append(
            "INCUMBENT: Current distributor(s) unknown — ask: "
            "'Who do you currently buy from for [category]?'"
        )
    if scores["buying_signal"]["score"] < 2:
        gaps.append("BUYING SIGNAL: No trigger identified — qualify opportunity size on first call")

    return gaps


# ---------------------------------------------------------------------------
# Line fit table
# ---------------------------------------------------------------------------

def build_line_fit_table(text: str, category_hits: dict) -> str:
    rows = [
        "| Oprema Line | May Vol. | Fit | Evidence | Oprema Brands | Other Brands Found |",
        "|-------------|----------|-----|----------|---------------|--------------------|",
    ]
    for cat_name, cat_data in OPREMA_CATEGORIES.items():
        hit = category_hits.get(cat_name)
        if hit:
            opr = ", ".join(hit["oprema_brands"]) or "—"
            other = ", ".join(hit["other_brands"]) or "—"
            kw = ", ".join(hit["keywords"][:2]) or ""
            fit = "**STRONG**" if cat_name in ("Access Control","Fire Detection","CCTV / IP Video","Intruder / Alarm") else "minor"
            evidence = f"{kw}" if kw else "sector match"
        else:
            fit, evidence = "none", "no signals"
            opr, other = "—", "—"
        rows.append(
            f"| {cat_name} | {cat_data['may_qty']:,} | {fit} | {evidence[:40]} | {opr} | {other} |"
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Brief generator
# ---------------------------------------------------------------------------

def generate_brief(research: dict, scores: dict, total: int, tier: str,
                   tier_emoji: str, category_hits: dict, crm_data: dict = None) -> str:

    company = research.get("company_name", "Unknown")
    website = research.get("website", "")
    date    = research.get("research_date", datetime.now().strftime("%Y-%m-%d"))
    all_text= " ".join(str(v) for v in research.get("queries", {}).values())

    # Oprema brands found (for brief)
    oprema_brands_found = [b[0] for b in OPREMA_BRANDS if b[0].lower() in all_text.lower()]

    # Non-Oprema brands found (sales intelligence — these are the pitch)
    non_oprema_found = {}
    for cat, hit in category_hits.items():
        if hit.get("other_brands"):
            non_oprema_found[cat] = hit["other_brands"]

    gaps = extract_gaps(research, scores, category_hits)

    # CRM block
    crm_block = ""
    if crm_data and any(crm_data.values()):
        crm_block = f"""
| CRM Field | Value |
|-----------|-------|
| Customer No. | {crm_data.get('customer_number', '—')} |
| Account Manager | {crm_data.get('primary_responsible', '—')} |
| Category (Calculated) | {crm_data.get('category_calculated', '—')} |
| D&B Category | {crm_data.get('dandb_category', '—')} |
| Category (Override) | {crm_data.get('category_override', '—')} |
| Revenue (DUNS) | {('£' + f"{int(float(str(crm_data.get('revenue_duns','0')).replace(',','.'))):,}") if crm_data.get('revenue_duns') else '—'} |
| Employees (DUNS) | {crm_data.get('employees_duns', '—')} |
| HIPO Flag | {crm_data.get('hipo_eval', '—')} ({crm_data.get('hipo_date', '—')}) |
| Business Unit | {crm_data.get('business_unit', '—')} |
"""

    # Lead categories for the play
    matched_cats = list(category_hits.keys())
    lead_cat = matched_cats[0] if matched_cats else "confirm on call"

    # Build non-Oprema brand pitch angles
    pitch_angles = []
    for cat, brands in non_oprema_found.items():
        pitch_angles.append(
            f"Installs {', '.join(brands[:2])} for {cat} — "
            f"Oprema can offer {', '.join(OPREMA_CATEGORIES[cat]['oprema_brands'][:2])} as alternatives/supplements"
        )

    score_str = (
        f"Category fit **{scores['category_fit']['score']}** · "
        f"Registry/firmographics **{scores['firmographics']['score']}** · "
        f"Contact access **{scores['contacts']['score']}** · "
        f"Opportunity/buying-signal **{scores['buying_signal']['score']}** · "
        f"Freshness **{scores['freshness']['score']}** · "
        f"Competitive/incumbent **{scores['competitive']['score']}** = "
        f"**{total}/18 — {tier}**"
    )

    line_fit_table = build_line_fit_table(all_text, category_hits)

    brief = f"""# Oprema Prospect Brief
**{company}** · UK · {website}
**{total} / 18 — {tier_emoji} {tier.upper()}**

---
{crm_block}
---

## The Play

*(Synthesise into a 2–3 paragraph narrative: why this company, which Oprema lines fit,
what the approach is, and what the timing window looks like.)*

**Category signals:** {scores['category_fit']['evidence']}
**Buying signal:** {scores['buying_signal']['evidence']}
**Competitive angle:** {scores['competitive']['evidence']}

{('**Pitch angles from non-Oprema brands found:**' + chr(10) + chr(10).join('- ' + p for p in pitch_angles)) if pitch_angles else ''}

---

## Next Steps

1. **Lead category:** {lead_cat} — Oprema's top line by volume ({OPREMA_CATEGORIES.get(lead_cat, {}).get('may_qty', 0):,} units/month)
2. **Entry contact:** {scores['contacts']['evidence']}
3. **Timing window:** {scores['buying_signal']['evidence']}
4. **Confirm on call:** Which brands do they currently install for {' / '.join(matched_cats[:3])}?
5. **If non-Oprema brands confirmed:** Position Oprema's equivalent — {', '.join(OPREMA_CATEGORIES.get(lead_cat, {}).get('oprema_brands', [])[:3]) or 'see line fit table'}
6. **Attach:** {('Networking/Infra (PoE, cabling) as natural CCTV attach' if 'CCTV / IP Video' in category_hits else 'Accessories, power, cabling as attach')}
7. **Gap to close:** {gaps[0] if gaps else 'None critical'}

---

## Who to Call

| Contact | Function | Why / Approach |
|---------|----------|----------------|
| *(MD/Owner — from research)* | Commercial / Decision-maker | Strategic supply conversation |
| *(Ops/Procurement — from research)* | Procurement | Day-to-day purchasing; who signs off on stock |
| *(Technical/Install Manager)* | Technical | Category mix discovery; brand preferences; volume |

*(Populate from research below — verify direct emails before outreach)*

---

## Oprema Line Fit

{line_fit_table}

*"Other Brands Found" = non-Oprema brands the prospect installs — same category, Oprema pitch angle.*
*May Volume = Oprema monthly units — indicates revenue potential per line.*

---

## Installed Brand Intelligence

{'**Oprema brands already in their mix:** ' + ', '.join(oprema_brands_found) if oprema_brands_found else '**No Oprema brands confirmed** — prospect installs alternative brands (see line fit table). Oprema can pitch category equivalents.'}

{('**Non-Oprema brands found (pitch angles):**' + chr(10) + chr(10).join('- ' + p for p in pitch_angles)) if pitch_angles else ''}

**Confirm on first call** — never assert a brand without primary source confirmation.

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
| Headcount | {crm_data.get('employees_duns', '*(from research)*') if crm_data else '*(from research)*'} | {'DUNS' if crm_data and crm_data.get('employees_duns') else ''} |
| Revenue | {('£' + f"{int(float(str(crm_data.get('revenue_duns','0')).replace(',','.'))):,}") if crm_data and crm_data.get('revenue_duns') else '*(from research)*'} | {'DUNS' if crm_data and crm_data.get('revenue_duns') else ''} |
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
<summary>Services & Brands (Category Research)</summary>

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
*Oprema Prospect Brief · {company} · generated {date} · Oprema 6-dimension methodology ·
Category-first scoring: fit = what categories they operate in, brands = sales intelligence.
Research via Perplexity API + Apify. Confidence: VERIFIED = primary source · INFERRED = derived · UNVERIFIED = confirm on call.*
"""
    return brief


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def score_company(research: dict, crm_data: dict = None) -> tuple:
    """Returns (scores_dict, category_hits_dict)."""
    all_text = " ".join(str(v) for v in research.get("queries", {}).values())

    cat_score, cat_ev, cat_conf, category_hits = score_category_fit(all_text)
    fi_score,  fi_ev,  fi_conf  = score_firmographics(all_text, crm_data)
    ca_score,  ca_ev,  ca_conf  = score_contact_access(all_text)
    bs_score,  bs_ev,  bs_conf  = score_buying_signal(all_text, crm_data)
    fr_score,  fr_ev,  fr_conf  = score_freshness(all_text)
    co_score,  co_ev,  co_conf  = score_competitive(all_text)

    total = cat_score + fi_score + ca_score + bs_score + fr_score + co_score
    tier, emoji = get_tier(total)

    scores = {
        "category_fit":  {"score": cat_score, "evidence": cat_ev, "conf": cat_conf},
        "firmographics": {"score": fi_score,  "evidence": fi_ev,  "conf": fi_conf},
        "contacts":      {"score": ca_score,  "evidence": ca_ev,  "conf": ca_conf},
        "buying_signal": {"score": bs_score,  "evidence": bs_ev,  "conf": bs_conf},
        "freshness":     {"score": fr_score,  "evidence": fr_ev,  "conf": fr_conf},
        "competitive":   {"score": co_score,  "evidence": co_ev,  "conf": co_conf},
        "total":         total,
        "tier":          tier,
        "tier_emoji":    emoji,
    }
    return scores, category_hits


def print_terminal_summary(company: str, website: str, scores: dict,
                           total: int, tier: str, emoji: str, category_hits: dict):
    bar = lambda s: "█" * s + "░" * (3 - s)
    print(f"\n{'='*58}")
    print(f"=== OPREMA PROSPECT SCORED ===")
    print(f"{'='*58}")
    print(f"\nCompany:  {company}")
    if website: print(f"Website:  {website}")
    print(f"Score:    {total}/18 — {emoji} {tier.upper()}")

    print(f"\nCategories matched:")
    for cat, hit in category_hits.items():
        opr   = f"Oprema: {', '.join(hit['oprema_brands'])}" if hit['oprema_brands'] else ""
        other = f"Other: {', '.join(hit['other_brands'])}"   if hit['other_brands']  else ""
        brand_note = " | ".join(filter(None, [opr, other]))
        print(f"  ✓ {cat:<25} {brand_note}")
    if not category_hits:
        print("  — No category matches found")

    print(f"\nDimension Scores:")
    dims = [
        ("Category Fit          ", "category_fit"),
        ("Registry/Firmographics", "firmographics"),
        ("Contact Access        ", "contacts"),
        ("Opportunity/Buying    ", "buying_signal"),
        ("Freshness             ", "freshness"),
        ("Competitive/Incumbent ", "competitive"),
    ]
    for label, key in dims:
        s = scores[key]
        print(f"  {label}  {s['score']}/3  {bar(s['score'])}  {s['conf']}")
        print(f"    → {s['evidence'][:70]}")

    gaps = extract_gaps({"queries": {}}, scores, category_hits)
    if gaps:
        print(f"\nGaps to Close:")
        for g in gaps[:3]:
            print(f"  ⚠ {g[:74]}")


def main():
    parser = argparse.ArgumentParser(description="Oprema Prospect Scorer")
    parser.add_argument("research_file", nargs="?")
    parser.add_argument("--company", default="")
    parser.add_argument("--website", default="")
    parser.add_argument("--research-text", default="")
    parser.add_argument("--crm-json", help="JSON string of CRM fields")
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

    crm_data = json.loads(args.crm_json) if args.crm_json else research.get("crm_data")

    scores, category_hits = score_company(research, crm_data)
    total = scores["total"]
    tier  = scores["tier"]
    emoji = scores["tier_emoji"]

    company = research.get("company_name", "Unknown")
    website = research.get("website", "")

    print_terminal_summary(company, website, scores, total, tier, emoji, category_hits)

    safe = "".join(c if c.isalnum() else "_" for c in company).strip("_")
    brief_path = args.brief_output or f"PROSPECT-{safe}.md"
    brief = generate_brief(research, scores, total, tier, emoji, category_hits, crm_data)

    with open(brief_path, "w", encoding="utf-8") as f:
        f.write(brief)
    print(f"\nBrief saved to: {brief_path}")

    if args.json_output:
        out = {**scores, "company_name": company, "website": website,
               "categories": list(category_hits.keys())}
        with open(args.json_output, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"Score JSON:     {args.json_output}")

    return scores


if __name__ == "__main__":
    main()
