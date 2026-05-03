"""
Cortex Data Seeder — Generate /data JSON for any ticker using SEC EDGAR (edgartools).

Usage:
    uv run python tools/seed_ticker.py AAPL
    uv run python tools/seed_ticker.py MSFT --quarters 4

Pulls from:
    - 10-K: Annual financials (revenue, EPS, net income)
    - 10-Q: Quarterly financials
    - 8-K:  Material events (used as news/events)
    - Company metadata (industry, SIC, fiscal year end)

Output:
    src/data/{ticker.lower()}.json  — structured JSON matching Cortex schema
    Updates src/data/index.json     — adds the new company to the registry
"""

import json
import logging
import os
import re
import sys
from datetime import datetime

from edgar import Company, set_identity

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [seed] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seed")

set_identity("Cortex Research cortex@research.com")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


# --- 8-K item code descriptions ---
ITEM_DESCRIPTIONS = {
    "1.01": "Entry into a Material Agreement",
    "1.02": "Termination of a Material Agreement",
    "1.03": "Bankruptcy or Receivership",
    "2.01": "Completion of Acquisition or Disposition",
    "2.02": "Results of Operations and Financial Condition",
    "2.03": "Creation of a Direct Financial Obligation",
    "2.04": "Triggering Events That Accelerate Obligations",
    "2.05": "Costs Associated with Exit or Disposal",
    "2.06": "Material Impairments",
    "3.01": "Notice of Delisting",
    "3.02": "Unregistered Sales of Equity Securities",
    "3.03": "Material Modification to Rights of Security Holders",
    "4.01": "Changes in Registrant's Certifying Accountant",
    "4.02": "Non-Reliance on Previously Issued Financials",
    "5.01": "Changes in Control of Registrant",
    "5.02": "Departure/Election of Directors or Officers",
    "5.03": "Amendments to Articles or Bylaws",
    "5.07": "Submission of Matters to a Vote of Security Holders",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}


def get_company(ticker: str) -> Company:
    logger.info("Looking up %s on SEC EDGAR...", ticker)
    c = Company(ticker)
    logger.info("Found: %s (CIK: %s)", c.name, c.cik)
    return c


def extract_financials_from_statement(df, period_col: str) -> dict:
    """Extract revenue, net income, EPS from an income statement dataframe."""
    result = {"revenue": None, "net_income": None, "eps_diluted": None}

    for _, row in df.iterrows():
        if row.get("abstract"):
            continue
        label = str(row.get("label", "")).lower()
        dim = str(row.get("dimension_member_label", ""))
        if dim != "nan":
            continue

        val = row.get(period_col)
        if val is None or (isinstance(val, float) and val != val):  # NaN check
            continue

        if any(k in label for k in ["net sales", "revenue", "total revenue", "net revenue"]) and result["revenue"] is None:
            result["revenue"] = val
        elif label.strip() == "net income" or label.strip() == "net income:":
            result["net_income"] = val
        elif "diluted" in label and "per share" in label and "dollar" in label:
            result["eps_diluted"] = val

    return result


def build_quarterly_filings(company: Company, num_quarters: int) -> list[dict]:
    """Build quarterly transcript-like records from 10-Q filings."""
    logger.info("Fetching 10-Q filings...")
    filings = company.get_filings(form="10-Q")

    quarters = []
    for i, filing in enumerate(filings[:num_quarters]):
        period = str(filing.period_of_report)
        filing_date = str(filing.filing_date)
        logger.info("  Processing 10-Q: %s (period: %s)", filing_date, period)

        # Extract financials from this filing's XBRL
        financials = {"revenue_bn": None, "eps_reported": None}
        try:
            xbrl_data = filing.xbrl()
            inc = xbrl_data.statements.income_statement()
            inc_df = inc.to_dataframe()
            period_cols = [c for c in inc_df.columns if c[0].isdigit()]
            if period_cols:
                data = extract_financials_from_statement(inc_df, period_cols[0])
                if data["revenue"]:
                    financials["revenue_bn"] = round(data["revenue"] / 1e9, 1)
                if data["eps_diluted"]:
                    financials["eps_reported"] = data["eps_diluted"]
                if data["net_income"]:
                    financials["net_income_bn"] = round(data["net_income"] / 1e9, 1)
        except Exception as e:
            logger.warning("  Could not extract financials for %s: %s", period, e)

        # Determine quarter label
        period_date = datetime.strptime(period, "%Y-%m-%d") if period else None
        if period_date:
            month = period_date.month
            if month <= 3:
                q_label = "Q1"
            elif month <= 6:
                q_label = "Q2"
            elif month <= 9:
                q_label = "Q3"
            else:
                q_label = "Q4"
            fy = period_date.year
            quarter_name = f"{q_label} {fy}"
        else:
            quarter_name = f"Filing {filing_date}"

        quarters.append({
            "quarter": quarter_name,
            "fiscal_year": str(fy) if period_date else "",
            "date": filing_date,
            "period_end": period,
            "speakers": [],
            "financials": financials,
            "key_quotes": [],
            "key_themes": [],
            "risks": [],
            "tone": "",
            "source": "SEC 10-Q",
        })

    quarters.reverse()  # oldest first
    return quarters


def build_annual_filings(company: Company, num_years: int = 3) -> list[dict]:
    """Build annual filing records from 10-K."""
    logger.info("Fetching 10-K filings...")
    filings = company.get_filings(form="10-K")

    annuals = []
    for filing in filings[:num_years]:
        period = str(filing.period_of_report)
        filing_date = str(filing.filing_date)
        logger.info("  Processing 10-K: %s (period: %s)", filing_date, period)

        financials = {}
        try:
            xbrl_data = filing.xbrl()
            inc = xbrl_data.statements.income_statement()
            inc_df = inc.to_dataframe()
            period_cols = [c for c in inc_df.columns if c[0].isdigit()]
            if period_cols:
                data = extract_financials_from_statement(inc_df, period_cols[0])
                if data["revenue"]:
                    financials["revenue_bn"] = round(data["revenue"] / 1e9, 1)
                if data["eps_diluted"]:
                    financials["eps_diluted"] = data["eps_diluted"]
                if data["net_income"]:
                    financials["net_income_bn"] = round(data["net_income"] / 1e9, 1)
        except Exception as e:
            logger.warning("  Could not extract 10-K financials: %s", e)

        annuals.append({
            "form": "10-K",
            "filing_date": filing_date,
            "period_end": period,
            "financials": financials,
        })

    annuals.reverse()
    return annuals


def build_events(company: Company, num_events: int = 6) -> list[dict]:
    """Build news/events from 8-K filings."""
    logger.info("Fetching 8-K filings...")
    filings = company.get_filings(form="8-K")

    events = []
    for filing in filings[:num_events]:
        items_raw = str(filing.items) if filing.items else ""
        item_codes = [i.strip() for i in items_raw.split(",") if i.strip()]
        tags = [ITEM_DESCRIPTIONS.get(code, f"Item {code}") for code in item_codes]

        # Build headline from item descriptions
        if tags:
            headline = f"{company.name}: {', '.join(tags)}"
        else:
            headline = f"{company.name}: SEC Filing (8-K)"

        events.append({
            "date": str(filing.filing_date),
            "source": "SEC EDGAR (8-K)",
            "headline": headline,
            "snippet": f"8-K filed on {filing.filing_date}. Items: {items_raw or 'N/A'}.",
            "tags": item_codes + ["8-K", "SEC Filing"],
        })

    return events


def update_index(ticker: str, name: str, sector: str, filename: str, transcript_count: int, news_count: int):
    """Add or update company in index.json."""
    index_path = os.path.join(DATA_DIR, "index.json")
    with open(index_path) as f:
        index = json.load(f)

    # Check if already exists
    for c in index["companies"]:
        if c["ticker"] == ticker:
            c["name"] = name
            c["file"] = filename
            c["transcript_count"] = transcript_count
            c["news_items"] = news_count
            logger.info("Updated existing entry in index.json for %s", ticker)
            with open(index_path, "w") as f:
                json.dump(index, f, indent=2)
            return

    # Add new
    index["companies"].append({
        "name": name,
        "ticker": ticker,
        "file": filename,
        "fiscal_year_note": "",
        "transcripts": [],
        "transcript_count": transcript_count,
        "news_items": news_count,
        "primary_themes": [],
    })

    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)
    logger.info("Added %s to index.json", ticker)


def seed_ticker(ticker: str, num_quarters: int = 8):
    """Main entry: seed data for a ticker."""
    ticker = ticker.upper()
    company = get_company(ticker)

    name = company.name
    industry = company.industry or ""

    logger.info("Company: %s (%s)", name, ticker)
    logger.info("Industry: %s", industry)

    # Build data
    quarters = build_quarterly_filings(company, num_quarters)
    annuals = build_annual_filings(company)
    events = build_events(company)

    # Compose output
    output = {
        "company": name,
        "ticker": ticker,
        "sector": industry,
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "annual_filings": annuals,
        "transcripts": quarters,
        "news": events,
    }

    # Write file
    filename = f"{ticker.lower()}.json"
    filepath = os.path.join(DATA_DIR, filename)
    with open(filepath, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("Wrote %s", filepath)

    # Update index
    update_index(ticker, name, industry, filename, len(quarters), len(events))

    # Summary
    print(f"\n{'='*50}")
    print(f"  Seeded: {name} ({ticker})")
    print(f"  Quarters: {len(quarters)}")
    print(f"  Annual filings: {len(annuals)}")
    print(f"  Events (8-K): {len(events)}")
    print(f"  Output: {filepath}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python tools/seed_ticker.py <TICKER> [--quarters N]")
        print("Example: uv run python tools/seed_ticker.py AAPL")
        print("         uv run python tools/seed_ticker.py MSFT --quarters 4")
        sys.exit(1)

    ticker_arg = sys.argv[1]
    quarters_arg = 8
    if "--quarters" in sys.argv:
        idx = sys.argv.index("--quarters")
        if idx + 1 < len(sys.argv):
            quarters_arg = int(sys.argv[idx + 1])

    seed_ticker(ticker_arg, quarters_arg)
