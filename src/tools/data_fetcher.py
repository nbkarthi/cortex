#!/usr/bin/env python3
"""
cortex_fetcher.py — Tier 1 Earnings Data Fetcher
=================================================
Fetches earnings transcript highlights + recent news for any stock ticker
using web search (DuckDuckGo, no API key required) + LLM extraction.

How it works:
  1. Gets company name/sector from yfinance
  2. Determines the last N quarters to search for
  3. For each quarter: searches DuckDuckGo → feeds snippets to LLM → extracts structured JSON
  4. Searches for recent news and extracts structured news items
  5. Saves everything to data/<TICKER>.json matching the Cortex schema

Usage:
  python cortex_fetcher.py NVDA
  python cortex_fetcher.py TSLA --quarters 4
  python cortex_fetcher.py AMZN --quarters 8 --output ./my_data

Requirements:
  pip install yfinance duckduckgo-search
  Set DEEPSEEK_API_KEY env var
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date

# ── Third-party ────────────────────────────────────────────────────────────────
try:
    import yfinance as yf
except ImportError:
    sys.exit("Missing: pip install yfinance")

try:
    from ddgs import DDGS
except ImportError:
    sys.exit("Missing: pip install ddgs")

# Add parent dir to path so we can import from src
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from llm import call_llm
from config import DEEPSEEK_MODEL


# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_QUARTERS = 8
DEFAULT_OUTPUT_DIR = "data"
SEARCH_DELAY_SEC = 1.5      # Pause between DuckDuckGo calls to avoid rate limits

# Companies whose fiscal year does NOT end in December.
# Value = calendar month the fiscal year ENDS (1=Jan, 6=Jun, 9=Sep, etc.)
FISCAL_YEAR_END_MONTH = {
    "NVDA": 1,   # Nvidia FY ends January  → Q1 FY starts February
    "AAPL": 9,   # Apple  FY ends September
    "MSFT": 6,   # Microsoft FY ends June
    "ORCL": 5,   # Oracle    FY ends May
    "WMT":  1,   # Walmart   FY ends January
}


# ── Helper: quarter arithmetic ─────────────────────────────────────────────────

def prev_quarter(year: int, q: int) -> tuple[int, int]:
    """Return the previous (year, quarter) given current (year, quarter)."""
    if q == 1:
        return year - 1, 4
    return year, q - 1


def calendar_quarter_for(year: int, q: int, ticker: str) -> str:
    """
    Returns a human-readable quarter label for search purposes.
    For standard tickers this is just "Q1 2024".
    For Nvidia we also append the fiscal year label, e.g. "Q1 FY2025 (May 2024)".
    """
    if ticker in FISCAL_YEAR_END_MONTH:
        # Determine the fiscal year label
        fy_end_month = FISCAL_YEAR_END_MONTH[ticker]
        # Fiscal quarter: if FY ends in month M, FY starts in month M+1
        fy_start_month = (fy_end_month % 12) + 1
        # Calendar month roughly in the middle of fiscal quarter q
        mid_month = ((fy_start_month - 1 + (q - 1) * 3 + 1) % 12) + 1
        cal_year = year if mid_month >= fy_start_month else year - 1
        # Fiscal year label: the year in which the FY ends
        fy_label = year + 1 if fy_end_month == 1 else year
        return f"Q{q} FY{fy_label}"
    return f"Q{q} {year}"


def get_quarters(ticker: str, num_quarters: int) -> list[dict]:
    """
    Generate the last N completed quarters (calendar year + quarter number).
    Returns list of dicts with 'year', 'q', 'label', 'approx_report_month'.
    """
    today = date.today()
    cur_year = today.year
    cur_month = today.month

    # Start from the last *completed* calendar quarter
    cur_cal_q = (cur_month - 1) // 3 + 1
    year, q = prev_quarter(cur_year, cur_cal_q)

    quarters = []
    for _ in range(num_quarters):
        label = calendar_quarter_for(year, q, ticker)
        # Approximate month the earnings were reported (1-2 months after quarter end)
        quarter_end_month = q * 3
        report_month = (quarter_end_month % 12) + 1
        report_year = year if quarter_end_month < 12 else year + 1

        quarters.append({
            "year": year,
            "q": q,
            "label": label,
            "report_year": report_year,
            "report_month": report_month,
        })
        year, q = prev_quarter(year, q)

    return quarters


# ── CortexFetcher class ────────────────────────────────────────────────────────

class CortexFetcher:
    """
    Tier 1 fetcher: DuckDuckGo web search + Claude LLM extraction.

    No paid search API required. Accuracy is "news-summary" level —
    good for prototyping Cortex modules; use Tier 2/3 for production IC memos.
    """

    def __init__(self):
        self.ddgs = DDGS()

    # ── Company info ─────────────────────────────────────────────────────────

    def get_company_info(self, ticker: str) -> dict:
        """Pull basic company metadata from yfinance."""
        try:
            info = yf.Ticker(ticker).info
            return {
                "name": info.get("longName") or info.get("shortName", ticker),
                "sector": info.get("sector", "Unknown"),
                "industry": info.get("industry", "Unknown"),
            }
        except Exception as e:
            print(f"  ⚠ yfinance error: {e} — using ticker as name")
            return {"name": ticker, "sector": "Unknown", "industry": "Unknown"}

    # ── Search ───────────────────────────────────────────────────────────────

    def _search(self, query: str, max_results: int = 6) -> str:
        """Run a DuckDuckGo text search and return concatenated snippets."""
        try:
            results = self.ddgs.text(query, max_results=max_results)
            lines = []
            for r in results:
                lines.append(f"SOURCE: {r.get('href', '')}")
                lines.append(f"TITLE:  {r.get('title', '')}")
                lines.append(f"BODY:   {r.get('body', '')}")
                lines.append("")
            return "\n".join(lines)
        except Exception as e:
            return f"[Search failed: {e}]"

    def search_transcript(self, company: str, ticker: str, label: str) -> str:
        """Search for a single quarter's earnings call highlights."""
        query = f"{company} {ticker} {label} earnings call transcript highlights key quotes"
        raw = self._search(query)
        time.sleep(SEARCH_DELAY_SEC)
        return raw

    def search_news(self, company: str, ticker: str) -> str:
        """Search for recent news about the company."""
        year = date.today().year
        query = f"{company} {ticker} news {year}"
        raw = self._search(query, max_results=8)
        time.sleep(SEARCH_DELAY_SEC)
        return raw

    # ── LLM extraction ───────────────────────────────────────────────────────

    def _llm(self, system: str, user: str, label: str = "fetcher") -> str:
        """Call LLM via the shared call_llm helper."""
        return call_llm(system, user, label=label)

    def _parse_json(self, raw: str, fallback):
        """Strip markdown fences and parse JSON; return fallback on failure."""
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return fallback

    def extract_transcript(self, company: str, ticker: str, label: str, snippets: str) -> dict:
        """
        Feed raw search snippets to LLM and extract a structured transcript object.
        LLM is instructed to use ONLY what's in the snippets — no hallucination.
        """
        system = "You are a financial data extraction assistant for an investment research system called Cortex. Extract ONLY information present in the provided snippets. Do NOT invent, guess, or hallucinate any numbers, quotes, or facts. Return ONLY valid JSON. No markdown fences. No explanation."

        user = f"""Company: {company} ({ticker})
Quarter: {label}

Below are raw web search snippets about this earnings call:
---
{snippets[:4000]}
---

Extract a JSON object. If a field has no evidence in the snippets, use null or an empty array.

Return this exact JSON schema:
{{
  "quarter": "{label}",
  "date": "YYYY-MM-DD or null",
  "speakers": ["Name (Title)"],
  "financials": {{
    "revenue_bn": null,
    "revenue_yoy_pct": null,
    "eps_reported": null,
    "eps_estimate": null
  }},
  "key_quotes": [
    {{
      "speaker": "Name",
      "theme": "short theme label",
      "text": "quote text from snippets"
    }}
  ],
  "key_themes": ["theme 1", "theme 2"],
  "risks": ["risk 1", "risk 2"],
  "tone": "one sentence describing the overall call tone",
  "data_quality": "high | medium | low — how much source text was found"
}}"""

        raw = self._llm(system, user, label=f"transcript-{ticker}-{label}")
        result = self._parse_json(raw, {
            "quarter": label,
            "date": None,
            "speakers": [],
            "financials": {},
            "key_quotes": [],
            "key_themes": [],
            "risks": [],
            "tone": None,
            "data_quality": "low",
            "error": "LLM parse failed",
        })
        return result

    def extract_news(self, company: str, ticker: str, snippets: str) -> list:
        """Extract structured news items from raw search snippets."""
        system = "You are a financial data extraction assistant. Extract ONLY information from the provided text. Do NOT invent anything. Return ONLY a valid JSON array. No markdown. No explanation."

        user = f"""Company: {company} ({ticker})

Raw news search results:
---
{snippets[:3000]}
---

Extract a JSON array of news items. Max 6 items.

[
  {{
    "date": "YYYY-MM-DD or null",
    "source": "publication name",
    "headline": "headline text",
    "snippet": "1-2 sentence summary",
    "tags": ["tag1", "tag2"]
  }}
]"""

        raw = self._llm(system, user, label=f"news-{ticker}")
        result = self._parse_json(raw, [])
        return result if isinstance(result, list) else []

    # ── Main fetch ───────────────────────────────────────────────────────────

    def fetch(
        self,
        ticker: str,
        num_quarters: int = DEFAULT_QUARTERS,
        output_dir: str = DEFAULT_OUTPUT_DIR,
    ) -> dict:
        """
        Full pipeline for one ticker:
          company info → quarter list → transcript search+extract → news → save JSON
        """
        ticker = ticker.upper()

        print(f"\n{'═' * 58}")
        print(f"  CORTEX FETCHER  ·  Tier 1  ·  {ticker}")
        print(f"{'═' * 58}\n")

        # ── 1. Company info
        print("▸ Company info...")
        info = self.get_company_info(ticker)
        company = info["name"]
        print(f"  Name:   {company}")
        print(f"  Sector: {info['sector']}\n")

        # ── 2. Quarter list
        quarters = get_quarters(ticker, num_quarters)
        print(f"▸ Fetching {num_quarters} quarters: "
              f"{quarters[-1]['label']} → {quarters[0]['label']}\n")

        # ── 3. Transcripts
        transcripts = []
        for i, q in enumerate(quarters):
            label = q["label"]
            print(f"  [{i+1:02d}/{num_quarters}] {label}", end="  ", flush=True)

            snippets = self.search_transcript(company, ticker, label)

            if not snippets.strip() or "[Search failed" in snippets:
                print("⚠ no results")
                continue

            structured = self.extract_transcript(company, ticker, label, snippets)
            transcripts.append(structured)

            n_quotes = len(structured.get("key_quotes", []))
            n_themes = len(structured.get("key_themes", []))
            quality  = structured.get("data_quality", "?")
            print(f"✓  {n_quotes} quotes  {n_themes} themes  [{quality}]")

        # ── 4. News
        print(f"\n▸ Fetching recent news...")
        news_snippets = self.search_news(company, ticker)
        news = self.extract_news(company, ticker, news_snippets)
        print(f"  ✓ {len(news)} news items\n")

        # ── 5. Assemble
        output = {
            "company": company,
            "ticker": ticker,
            "sector": info["sector"],
            "industry": info["industry"],
            "last_updated": date.today().isoformat(),
            "fetcher": {
                "tier": 1,
                "method": "duckduckgo_search + llm_extraction",
                "model": DEEPSEEK_MODEL,
                "note": (
                    "Data sourced from news article snippets. "
                    "Quotes may be paraphrased. "
                    "Verify financials against official IR filings before use in IC memos."
                ),
            },
            "transcripts": transcripts,
            "news": news,
        }

        # ── 6. Save
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"{ticker.lower()}.json")
        with open(path, "w") as f:
            json.dump(output, f, indent=2)

        print(f"{'─' * 58}")
        print(f"  ✓ Saved  →  {path}")
        print(f"  {len(transcripts)} transcripts  ·  {len(news)} news items")
        print(f"{'─' * 58}\n")

        return output


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Cortex Tier 1 — earnings transcript fetcher (web search + LLM)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cortex_fetcher.py NVDA
  python cortex_fetcher.py TSLA --quarters 4
  python cortex_fetcher.py MSFT --quarters 8 --output ./research_data
        """,
    )
    parser.add_argument("ticker",      help="Stock ticker (e.g. NVDA, TSLA, AMZN)")
    parser.add_argument("--quarters",  type=int, default=DEFAULT_QUARTERS,
                        help=f"Number of past quarters to fetch (default: {DEFAULT_QUARTERS})")
    parser.add_argument("--output",    default=DEFAULT_OUTPUT_DIR,
                        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR}/)")
    args = parser.parse_args()

    fetcher = CortexFetcher()
    fetcher.fetch(
        ticker=args.ticker,
        num_quarters=args.quarters,
        output_dir=args.output,
    )


if __name__ == "__main__":
    main()