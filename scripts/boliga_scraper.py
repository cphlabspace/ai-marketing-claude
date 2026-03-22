#!/usr/bin/env python3
"""
Boliga Scraper — Utility script for AI Marketing Claude Code Skills
Scrapes sold property data from Boliga.dk for Danish real estate market analysis.
Based on the krose/boliga R package.
"""

import sys
import json
import re
import time
import random
import urllib.request
import urllib.error
import ssl
from html.parser import HTMLParser
from datetime import datetime, timedelta
from statistics import mean, median


BASE_URL = "https://www.boliga.dk/salg/resultater"

PROPERTY_TYPES = {
    "villa": "Villa",
    "ejerlejlighed": "Ejerlejlighed",
    "rækkehus": "Rækkehus",
    "fritidshus": "Fritidshus",
    "landejendom": "Landejendom",
    "andel": "Andel",
    "alle": "",
}


class BoligaSalesParser(HTMLParser):
    """Parse Boliga sold property results page."""

    def __init__(self):
        super().__init__()
        self.sales = []
        self._in_table = False
        self._in_thead = False
        self._in_tbody = False
        self._in_row = False
        self._in_cell = False
        self._current_row = []
        self._current_text = ""
        self._table_found = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        classes = attrs_dict.get("class", "")

        if tag == "table":
            self._in_table = True
            self._table_found = True
        elif tag == "thead" and self._in_table:
            self._in_thead = True
        elif tag == "tbody" and self._in_table:
            self._in_tbody = True
        elif tag == "tr" and self._in_tbody:
            self._in_row = True
            self._current_row = []
        elif tag in ("td", "th") and (self._in_row or self._in_thead):
            self._in_cell = True
            self._current_text = ""
        elif tag == "a" and self._in_cell:
            # Capture link text as part of cell
            pass

    def handle_endtag(self, tag):
        if tag == "table" and self._in_table:
            self._in_table = False
            self._in_tbody = False
            self._in_thead = False
        elif tag == "thead":
            self._in_thead = False
        elif tag == "tbody":
            self._in_tbody = False
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if self._current_row and len(self._current_row) >= 5:
                sale = self._parse_row(self._current_row)
                if sale:
                    self.sales.append(sale)
        elif tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            self._current_row.append(self._current_text.strip())

    def handle_data(self, data):
        if self._in_cell:
            self._current_text += data

    def _parse_row(self, cells):
        """Parse a table row into a sale record."""
        try:
            # Boliga table columns vary but typically include:
            # Address, Price, Price/sqm, Rooms, Type, Sqm, Year, Discount, Date, Sale type
            sale = {}

            if len(cells) >= 1:
                sale["address"] = cells[0].strip()
            if len(cells) >= 2:
                sale["price"] = self._parse_number(cells[1])
                sale["price_formatted"] = cells[1].strip()
            if len(cells) >= 3:
                sale["price_per_sqm"] = self._parse_number(cells[2])
            if len(cells) >= 4:
                sale["rooms"] = self._parse_number(cells[3])
            if len(cells) >= 5:
                sale["property_type"] = cells[4].strip()
            if len(cells) >= 6:
                sale["sqm"] = self._parse_number(cells[5])
            if len(cells) >= 7:
                sale["year_built"] = self._parse_number(cells[6])
            if len(cells) >= 8:
                sale["discount_pct"] = self._parse_float(cells[7])
            if len(cells) >= 9:
                sale["sale_date"] = cells[8].strip()
            if len(cells) >= 10:
                sale["sale_type"] = cells[9].strip()

            # Only return if we have at minimum an address and price
            if sale.get("address") and sale.get("price"):
                return sale
        except (ValueError, IndexError):
            pass
        return None

    def _parse_number(self, text):
        """Parse a number from text, removing dots and spaces."""
        cleaned = re.sub(r"[^\d]", "", text)
        if cleaned:
            return int(cleaned)
        return None

    def _parse_float(self, text):
        """Parse a float/percentage from text."""
        cleaned = text.replace(",", ".").replace("%", "").strip()
        match = re.search(r"-?\d+\.?\d*", cleaned)
        if match:
            return float(match.group())
        return None

    def get_results(self):
        return self.sales


class BoligaResultCountParser(HTMLParser):
    """Parse the total result count from Boliga search results."""

    def __init__(self):
        super().__init__()
        self.result_count = 0
        self._capture = False
        self._text = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        classes = attrs_dict.get("class", "")
        if "search-result" in classes or "result" in classes:
            self._capture = True
            self._text = ""

    def handle_data(self, data):
        if self._capture:
            self._text += data
        # Look for result count patterns anywhere
        match = re.search(r"(\d[\d.]*)\s*(?:resultat|bolig|salg)", data.lower())
        if match:
            count_str = match.group(1).replace(".", "")
            try:
                self.result_count = int(count_str)
            except ValueError:
                pass

    def handle_endtag(self, tag):
        if self._capture:
            self._capture = False
            match = re.search(r"(\d[\d.]*)", self._text)
            if match:
                count_str = match.group(1).replace(".", "")
                try:
                    self.result_count = int(count_str)
                except ValueError:
                    pass


def build_url(postal_code, min_date=None, max_date=None, property_type=None, page=1):
    """Build Boliga search URL for sold properties."""
    params = [
        f"so=1",
        f"sort=omregnings_dato-d",
    ]

    if postal_code:
        params.append(f"iPostnr={postal_code}")

    if min_date:
        params.append(f"minsaledate={min_date}")

    if max_date:
        params.append(f"maxsaledate={max_date}")

    if property_type and property_type.lower() != "alle":
        # Map to Boliga's type parameter
        type_val = PROPERTY_TYPES.get(property_type.lower(), property_type)
        params.append(f"type={type_val}")

    if page > 1:
        params.append(f"p={page}")

    return f"{BASE_URL}?{'&'.join(params)}"


def fetch_page(url):
    """Fetch a webpage from Boliga."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "da-DK,da;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(req, timeout=20, context=ctx)
        return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Fetch error: {e}", file=sys.stderr)
        return None


def try_api(postal_code, min_date=None, max_date=None, property_type=None, page=1):
    """Try the Boliga JSON API (v2) first, which is simpler to parse."""
    api_url = "https://api.boliga.dk/api/v2/sold/search/results"
    params = [f"pageSize=50", f"page={page}", f"sort=date-d"]

    if postal_code:
        params.append(f"zipcodeFrom={postal_code}")
        params.append(f"zipcodeTo={postal_code}")

    if min_date:
        params.append(f"salesDateMin={min_date}")
    if max_date:
        params.append(f"salesDateMax={max_date}")

    if property_type and property_type.lower() != "alle":
        type_map = {
            "villa": 1,
            "ejerlejlighed": 2,
            "rækkehus": 3,
            "fritidshus": 4,
            "landejendom": 5,
            "andel": 6,
        }
        type_id = type_map.get(property_type.lower())
        if type_id:
            params.append(f"propertyType={type_id}")

    url = f"{api_url}?{'&'.join(params)}"

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(req, timeout=20, context=ctx)
        data = json.loads(response.read().decode("utf-8", errors="replace"))
        return data
    except Exception:
        return None


def parse_api_results(api_data):
    """Parse results from the Boliga JSON API."""
    sales = []
    results = api_data.get("results", [])
    for r in results:
        sale = {
            "address": r.get("address", ""),
            "price": r.get("price"),
            "price_formatted": f"{r.get('price', 0):,} kr.".replace(",", ".") if r.get("price") else None,
            "price_per_sqm": r.get("sqmPrice"),
            "rooms": r.get("rooms"),
            "property_type": r.get("propertyType", ""),
            "sqm": r.get("size"),
            "year_built": r.get("buildYear"),
            "discount_pct": r.get("change"),
            "sale_date": r.get("soldDate", ""),
            "sale_type": r.get("saleType", ""),
            "postal_code": r.get("zipCode"),
            "city": r.get("city", ""),
            "latitude": r.get("latitude"),
            "longitude": r.get("longitude"),
        }
        if sale["address"] and sale["price"]:
            sales.append(sale)
    total_count = api_data.get("totalCount", len(sales))
    return sales, total_count


def scrape_sold(postal_code, min_date=None, max_date=None, property_type=None, max_pages=10):
    """Scrape sold property data from Boliga."""
    all_sales = []

    # Try API first
    api_data = try_api(postal_code, min_date, max_date, property_type, page=1)
    if api_data and api_data.get("results"):
        sales, total_count = parse_api_results(api_data)
        all_sales.extend(sales)
        total_pages = min((total_count + 49) // 50, max_pages)
        print(f"Found {total_count} results via API (fetching up to {total_pages} pages)", file=sys.stderr)

        for page in range(2, total_pages + 1):
            # Polite delay
            time.sleep(random.gammavariate(3, 0.3))
            api_data = try_api(postal_code, min_date, max_date, property_type, page=page)
            if api_data and api_data.get("results"):
                sales, _ = parse_api_results(api_data)
                all_sales.extend(sales)
                print(f"  Page {page}/{total_pages}: {len(sales)} results", file=sys.stderr)
            else:
                break

        return all_sales

    # Fall back to HTML scraping
    print("API unavailable, falling back to HTML scraping", file=sys.stderr)
    url = build_url(postal_code, min_date, max_date, property_type, page=1)
    html = fetch_page(url)
    if not html:
        return all_sales

    # Get result count
    count_parser = BoligaResultCountParser()
    try:
        count_parser.feed(html)
    except Exception:
        pass

    total_count = count_parser.result_count or 0
    total_pages = min((total_count + 49) // 50, max_pages) if total_count > 0 else 1
    print(f"Found approximately {total_count} results (fetching up to {total_pages} pages)", file=sys.stderr)

    # Parse first page
    parser = BoligaSalesParser()
    try:
        parser.feed(html)
        all_sales.extend(parser.get_results())
    except Exception:
        pass

    # Fetch remaining pages
    for page in range(2, total_pages + 1):
        time.sleep(random.gammavariate(3, 0.3))
        url = build_url(postal_code, min_date, max_date, property_type, page=page)
        html = fetch_page(url)
        if not html:
            break

        parser = BoligaSalesParser()
        try:
            parser.feed(html)
            results = parser.get_results()
            if not results:
                break
            all_sales.extend(results)
            print(f"  Page {page}/{total_pages}: {len(results)} results", file=sys.stderr)
        except Exception:
            break

    return all_sales


def compute_stats(sales):
    """Compute market statistics from sales data."""
    if not sales:
        return {"total_sales": 0, "message": "No sales data available"}

    stats = {"total_sales": len(sales)}

    # Price statistics
    prices = [s["price"] for s in sales if s.get("price")]
    if prices:
        stats["price"] = {
            "mean": round(mean(prices)),
            "median": round(median(prices)),
            "min": min(prices),
            "max": max(prices),
        }

    # Price per sqm statistics
    price_per_sqm = [s["price_per_sqm"] for s in sales if s.get("price_per_sqm")]
    if price_per_sqm:
        stats["price_per_sqm"] = {
            "mean": round(mean(price_per_sqm)),
            "median": round(median(price_per_sqm)),
            "min": min(price_per_sqm),
            "max": max(price_per_sqm),
        }

    # Size statistics
    sizes = [s["sqm"] for s in sales if s.get("sqm")]
    if sizes:
        stats["size_sqm"] = {
            "mean": round(mean(sizes)),
            "median": round(median(sizes)),
            "min": min(sizes),
            "max": max(sizes),
        }

    # Discount statistics
    discounts = [s["discount_pct"] for s in sales if s.get("discount_pct") is not None]
    if discounts:
        stats["discount_pct"] = {
            "mean": round(mean(discounts), 1),
            "median": round(median(discounts), 1),
            "min": round(min(discounts), 1),
            "max": round(max(discounts), 1),
        }

    # Breakdown by property type
    type_counts = {}
    type_prices = {}
    for s in sales:
        ptype = s.get("property_type", "Unknown")
        type_counts[ptype] = type_counts.get(ptype, 0) + 1
        if s.get("price"):
            type_prices.setdefault(ptype, []).append(s["price"])

    stats["by_type"] = {}
    for ptype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        entry = {"count": count}
        if ptype in type_prices and type_prices[ptype]:
            entry["avg_price"] = round(mean(type_prices[ptype]))
            entry["median_price"] = round(median(type_prices[ptype]))
        stats["by_type"][ptype] = entry

    # Breakdown by month
    month_counts = {}
    month_prices = {}
    for s in sales:
        date_str = s.get("sale_date", "")
        if date_str and len(date_str) >= 7:
            month = date_str[:7]  # YYYY-MM
            month_counts[month] = month_counts.get(month, 0) + 1
            if s.get("price"):
                month_prices.setdefault(month, []).append(s["price"])

    stats["by_month"] = {}
    for month in sorted(month_counts.keys()):
        entry = {"count": month_counts[month]}
        if month in month_prices and month_prices[month]:
            entry["avg_price"] = round(mean(month_prices[month]))
            entry["median_price"] = round(median(month_prices[month]))
        stats["by_month"][month] = entry

    # Rooms breakdown
    room_counts = {}
    for s in sales:
        rooms = s.get("rooms")
        if rooms:
            room_counts[rooms] = room_counts.get(rooms, 0) + 1
    if room_counts:
        stats["by_rooms"] = dict(sorted(room_counts.items()))

    return stats


def print_usage():
    """Print usage information."""
    print(json.dumps({
        "usage": "python3 boliga_scraper.py --postal <code> [options]",
        "options": {
            "--postal": "Postal code (required, e.g., 2100)",
            "--from": "Min sale date (YYYY-MM-DD, default: 12 months ago)",
            "--to": "Max sale date (YYYY-MM-DD, default: today)",
            "--type": "Property type: Villa, Ejerlejlighed, Rækkehus, Fritidshus, Landejendom, Andel, Alle (default: Alle)",
            "--max-pages": "Max pages to fetch (default: 10, max 50 results per page)",
            "--output": "Output format: json (default), stats",
        },
        "examples": [
            "python3 boliga_scraper.py --postal 2100",
            "python3 boliga_scraper.py --postal 4500 --from 2024-01-01 --to 2024-12-31 --type Fritidshus",
            "python3 boliga_scraper.py --postal 2100 --output stats",
        ],
        "description": "Scrapes sold property data from Boliga.dk for Danish real estate market analysis",
    }, indent=2))


def parse_args(argv):
    """Parse command-line arguments."""
    args = {
        "postal_code": None,
        "min_date": None,
        "max_date": None,
        "property_type": None,
        "max_pages": 10,
        "output": "json",
    }

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--postal" and i + 1 < len(argv):
            args["postal_code"] = argv[i + 1]
            i += 2
        elif arg == "--from" and i + 1 < len(argv):
            args["min_date"] = argv[i + 1]
            i += 2
        elif arg == "--to" and i + 1 < len(argv):
            args["max_date"] = argv[i + 1]
            i += 2
        elif arg == "--type" and i + 1 < len(argv):
            args["property_type"] = argv[i + 1]
            i += 2
        elif arg == "--max-pages" and i + 1 < len(argv):
            args["max_pages"] = int(argv[i + 1])
            i += 2
        elif arg == "--output" and i + 1 < len(argv):
            args["output"] = argv[i + 1]
            i += 2
        elif arg in ("--help", "-h"):
            print_usage()
            sys.exit(0)
        else:
            # Treat bare argument as postal code if not set
            if not args["postal_code"] and arg.isdigit():
                args["postal_code"] = arg
            i += 1

    # Defaults for dates
    if not args["max_date"]:
        args["max_date"] = datetime.now().strftime("%Y-%m-%d")
    if not args["min_date"]:
        one_year_ago = datetime.now() - timedelta(days=365)
        args["min_date"] = one_year_ago.strftime("%Y-%m-%d")

    return args


def main():
    if len(sys.argv) < 2:
        print_usage()
        return

    args = parse_args(sys.argv[1:])

    if not args["postal_code"]:
        print(json.dumps({"error": "Postal code is required. Use --postal <code>"}), file=sys.stderr)
        sys.exit(1)

    print(f"Scraping Boliga.dk for postal code {args['postal_code']} "
          f"({args['min_date']} to {args['max_date']})", file=sys.stderr)

    sales = scrape_sold(
        postal_code=args["postal_code"],
        min_date=args["min_date"],
        max_date=args["max_date"],
        property_type=args["property_type"],
        max_pages=args["max_pages"],
    )

    stats = compute_stats(sales)

    if args["output"] == "stats":
        print(json.dumps(stats, indent=2, default=str, ensure_ascii=False))
    else:
        output = {
            "postal_code": args["postal_code"],
            "date_range": {"from": args["min_date"], "to": args["max_date"]},
            "property_type_filter": args["property_type"] or "Alle",
            "stats": stats,
            "sales": sales,
        }
        print(json.dumps(output, indent=2, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
