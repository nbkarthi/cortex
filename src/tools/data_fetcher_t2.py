#!/usr/bin/env python3
"""
cortex_fetcher_t2.py — Tier 2 Earnings Data Fetcher
====================================================
Fetches full earnings call transcripts from Motley Fool via DuckDuckGo search,
then uses LLM to extract structured data from the actual transcript text.

How it works:
  1. Gets company name/sector from yfinance
  2. Determines the last N quarters to search for
  3. For each quarter: searches DuckDuckGo for Motley Fool transcript page
  4. Fetches the full HTML and extracts the transcript text
  5. Parses speakers, splits prepared remarks vs Q&A
  6. Uses LLM to extract structured financials, key quotes, themes, risks
  7. Saves everything into a single src/data/<ticker>.json file

Usage:
  python data_fetcher_t2.py GOOG
  python data_fetcher_t2.py TSLA --quarters 4
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime

from bs4 import BeautifulSoup

try:
    import yfinance as yf
except ImportError:
    sys.exit("Missing: pip install yfinance")

try:
    from ddgs import DDGS
except ImportError:
    sys.exit("Missing: pip install ddgs")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from llm import call_llm
from config import DEEPSEEK_MODEL

# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_QUARTERS = 8
SEARCH_DELAY_SEC = 2.0
FETCH_TIMEOUT_SEC = 20
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# ── Quarter helpers (reused from Tier 1) ──────────────────────────────────────

FISCAL_YEAR_END_MONTH = {
    "NVDA": 1, "AAPL": 9, "MSFT": 6, "ORCL": 5, "WMT": 1,
}


def prev_quarter(year: int, q: int) -> tuple[int, int]:
    if q == 1:
        return year - 1, 4
    return year, q - 1


def calendar_quarter_for(year: int, q: int, ticker: str) -> str:
    if ticker in FISCAL_YEAR_END_MONTH:
        fy_end_month = FISCAL_YEAR_END_MONTH[ticker]
        fy_start_month = (fy_end_month % 12) + 1
        fy_label = year + 1 if fy_end_month == 1 else year
        return f"Q{q} FY{fy_label}"
    return f"Q{q} {year}"


def get_quarters(ticker: str, num_quarters: int) -> list[dict]:
    today = date.today()
    cur_cal_q = (today.month - 1) // 3 + 1
    year, q = prev_quarter(today.year, cur_cal_q)

    quarters = []
    for _ in range(num_quarters):
        label = calendar_quarter_for(year, q, ticker)
        quarters.append({"year": year, "q": q, "label": label})
        year, q = prev_quarter(year, q)
    return quarters


# ── HTML fetching & parsing ───────────────────────────────────────────────────

def fetch_html(url: str) -> str | None:
    """Fetch HTML from a URL, return None on failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        resp = urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC)
        return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None


def extract_transcript_text(html: str) -> str | None:
    """Extract the transcript body text from a Motley Fool transcript page."""
    soup = BeautifulSoup(html, "html.parser")

    # Motley Fool uses id="article-body-transcript"
    body = soup.find(id="article-body-transcript")
    if not body:
        # Fallback: look for class containing "article-body"
        body = soup.find(class_=re.compile(r"article-body"))
    if not body:
        return None

    # Remove script/style tags
    for tag in body.find_all(["script", "style", "aside", "figure", "img"]):
        tag.decompose()

    # Get text, preserving paragraph breaks
    paragraphs = []
    for el in body.find_all(["p", "h2", "h3"]):
        text = el.get_text(strip=True)
        if text:
            paragraphs.append(text)

    return "\n\n".join(paragraphs) if paragraphs else None


def extract_call_date(html: str) -> str | None:
    """Try to extract the earnings call date from the page."""
    soup = BeautifulSoup(html, "html.parser")
    # Motley Fool format: "DATE Wednesday, July 23, 2025 at 4:30 p.m. ET"
    text = soup.get_text()
    match = re.search(
        r"(?:DATE|Date)[:\s]+\w+day,?\s+(\w+ \d{1,2},?\s+\d{4})",
        text,
    )
    if match:
        try:
            raw = match.group(1).replace(",", "")
            dt = datetime.strptime(raw, "%B %d %Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def parse_speakers_from_transcript(text: str) -> list[str]:
    """Extract speaker names from transcript text."""
    speakers = set()

    # "Call Participants" section often lists them
    participants_match = re.search(
        r"(?:CALL PARTICIPANTS|Call Participants)(.*?)(?:PREPARED REMARKS|Prepared Remarks|KEY|RISKS|TAKEAWAYS|\n\n\n)",
        text, re.DOTALL | re.IGNORECASE,
    )
    if participants_match:
        block = participants_match.group(1)
        # Lines like "Chief Executive Officer — Sundar Pichai" or "Sundar Pichai -- CEO"
        for m in re.finditer(r"(?:—|--|–)\s*([A-Z][a-z]+ (?:[A-Z]\.\s)?[A-Z][a-z]+)", block):
            speakers.add(m.group(1).strip())
        for m in re.finditer(r"([A-Z][a-z]+ (?:[A-Z]\.\s)?[A-Z][a-z]+)\s*(?:—|--|–)", block):
            speakers.add(m.group(1).strip())

    # Also look for "Name -- Title" pattern throughout (Motley Fool uses --)
    for m in re.finditer(
        r"([A-Z][a-z]+ (?:[A-Z]\.\s)?[A-Z][a-z]+)\s*--\s*\w",
        text,
    ):
        name = m.group(1).strip()
        if len(name) < 40:
            speakers.add(name)

    return sorted(speakers)


def split_sections(text: str) -> dict:
    """Split transcript into prepared remarks and Q&A."""
    qa_patterns = [
        r"(?:Questions? (?:and|&) Answers?)",
        r"(?:Q&A Session)",
        r"(?:we(?:'ll| will) (?:now )?(?:open|begin|take).*question)",
        r"(?:Operator.*first question)",
    ]
    pattern = "|".join(qa_patterns)
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        return {
            "prepared_remarks": text[:match.start()].strip(),
            "questions_and_answers": text[match.start():].strip(),
        }
    return {
        "prepared_remarks": text,
        "questions_and_answers": "",
    }


# ── Tier 2 Fetcher ────────────────────────────────────────────────────────────

class Tier2Fetcher:
    """
    Tier 2: Full transcript text from Motley Fool.
    Real quotes, real speaker attribution, full verbatim text.
    """

    def __init__(self):
        self.ddgs = DDGS()

    def get_company_info(self, ticker: str) -> dict:
        try:
            info = yf.Ticker(ticker).info
            return {
                "name": info.get("longName") or info.get("shortName", ticker),
                "sector": info.get("sector", "Unknown"),
                "industry": info.get("industry", "Unknown"),
            }
        except Exception:
            return {"name": ticker, "sector": "Unknown", "industry": "Unknown"}

    def find_transcript_url(self, company: str, ticker: str, label: str,
                            year: int, q: int) -> str | None:
        """Search DuckDuckGo for a Motley Fool transcript URL."""
        # Try multiple search variations to improve hit rate
        queries = [
            f"site:fool.com {company} Q{q} {year} earnings call transcript",
            f"site:fool.com {ticker} Q{q} {year} earnings call transcript",
        ]

        q_patterns = [f"q{q}-{year}", f"q{q} {year}"]

        for query in queries:
            try:
                results = self.ddgs.text(query, max_results=8)
            except Exception:
                continue

            time.sleep(SEARCH_DELAY_SEC)

            for r in results:
                href = r.get("href", "").lower()
                title = r.get("title", "").lower()
                if "fool.com" not in href:
                    continue
                combined = href + " " + title
                if any(p in combined for p in q_patterns):
                    return r["href"]

        return None

    def _parse_json(self, raw: str, fallback):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return fallback

    def _find_financials_chunk(self, text: str) -> str:
        """Find the section of transcript most likely to contain financial numbers."""
        import re
        # Look for CFO's remarks or consolidated revenue section
        markers = [
            r"[Cc]onsolidated [Rr]evenue",
            r"[Tt]otal [Rr]evenue[s]? ",
            r"[Rr]evenue of \$",
            r"earnings per share",
            r"Chief Financial Officer",
        ]
        for pattern in markers:
            match = re.search(pattern, text)
            if match:
                # Grab 3000 chars starting 200 chars before the match
                start = max(0, match.start() - 200)
                return text[start:start + 3000]
        # Fallback: first 3000 chars (summary-style pages)
        return text[:3000]

    def extract_financials(self, ticker: str, label: str, transcript_text: str) -> dict:
        """Focused LLM call to extract just the financial numbers."""
        text_chunk = self._find_financials_chunk(transcript_text)

        raw = call_llm(
            "Extract financial numbers from earnings call text. Return ONLY valid JSON. No markdown fences.",
            f"""Text:
---
{text_chunk}
---

Find these numbers in the text above:
- Consolidated/Total Revenue in billions (e.g. "$102.3 billion" => 102.3)
- Revenue YoY growth percent (e.g. "up 16%" => 16)
- EPS / earnings per share (e.g. "$2.87" => 2.87)

Return: {{"revenue_bn": number or null, "revenue_yoy_pct": number or null, "eps_reported": number or null, "eps_estimate": null}}

Use null if not found. Never use 0 for missing data.""",
            label=f"t2-fin-{ticker}-{label}",
        )
        return self._parse_json(raw, {})

    def extract_structured(self, company: str, ticker: str, label: str,
                           speakers: list[str], transcript_text: str) -> dict:
        """Use LLM to extract structured data from full transcript text."""
        text_chunk = transcript_text[:8000]
        speakers_str = ", ".join(speakers) if speakers else "unknown"

        # 1. Extract financials with a focused call
        financials = self.extract_financials(ticker, label, transcript_text)

        # 2. Extract quotes, themes, risks
        raw = call_llm(
            "You are a financial data extraction assistant for Cortex. "
            "Extract ONLY information present in the text. "
            "Return ONLY valid JSON. No markdown fences.",

            f"""Company: {company} ({ticker})
Quarter: {label}
Known speakers: {speakers_str}

Earnings call transcript text:
---
{text_chunk}
---

Extract this JSON:
{{
  "quarter": "{label}",
  "date": "YYYY-MM-DD of the call or null",
  "speakers": ["Name (Title)"],
  "key_quotes": [
    {{
      "speaker": "Name",
      "theme": "short theme label",
      "text": "exact verbatim quote from transcript"
    }}
  ],
  "key_themes": ["specific theme with numbers if available"],
  "risks": ["specific risk mentioned in call"],
  "tone": "one sentence describing the overall call tone"
}}

For speakers, format as "Name (Title)" from the Call Participants section.
Extract 3-6 key quotes most significant for investment analysis.""",
            label=f"t2-extract-{ticker}-{label}",
        )

        result = self._parse_json(raw, {
            "quarter": label,
            "date": None,
            "speakers": [],
            "key_quotes": [],
            "key_themes": [],
            "risks": [],
            "tone": None,
        })

        # Merge financials into result
        result["financials"] = financials
        return result

    def fetch(self, ticker: str, num_quarters: int = DEFAULT_QUARTERS) -> dict:
        ticker = ticker.upper()

        print(f"\n{'═' * 60}")
        print(f"  CORTEX FETCHER  ·  Tier 2  ·  {ticker}")
        print(f"{'═' * 60}\n")

        # 1. Company info
        print("  Company info...", end="  ", flush=True)
        info = self.get_company_info(ticker)
        company = info["name"]
        print(f"{company} ({info['sector']})\n")

        # 2. Quarters
        quarters = get_quarters(ticker, num_quarters)
        print(f"  Fetching {num_quarters} quarters: "
              f"{quarters[-1]['label']} -> {quarters[0]['label']}\n")

        transcripts = []
        for i, q in enumerate(quarters):
            label = q["label"]
            print(f"  [{i+1:02d}/{num_quarters}] {label}", end="  ", flush=True)

            # Search for transcript URL
            url = self.find_transcript_url(company, ticker, label, q["year"], q["q"])
            if not url:
                print("-- no transcript found")
                continue

            # Fetch HTML
            html = fetch_html(url)
            if not html:
                print("-- fetch failed")
                continue

            # Extract transcript text
            transcript_text = extract_transcript_text(html)
            if not transcript_text or len(transcript_text) < 500:
                print("-- extraction failed")
                continue

            # Parse metadata
            call_date = extract_call_date(html)
            speakers = parse_speakers_from_transcript(transcript_text)
            sections = split_sections(transcript_text)

            # LLM structured extraction
            structured = self.extract_structured(
                company, ticker, label, speakers, transcript_text,
            )

            # Build transcript record matching existing data format
            record = {
                "quarter": structured.get("quarter", label),
                "date": structured.get("date") or call_date,
                "speakers": structured.get("speakers", [f"{s}" for s in speakers]),
                "financials": structured.get("financials", {}),
                "key_quotes": structured.get("key_quotes", []),
                "key_themes": structured.get("key_themes", []),
                "risks": structured.get("risks", []),
                "tone": structured.get("tone"),
                "source_url": url,
            }

            n_quotes = len(record["key_quotes"])
            n_speakers = len(record["speakers"])
            print(f"OK  {len(transcript_text):,} chars  {n_speakers} speakers  {n_quotes} quotes")

            transcripts.append(record)
            time.sleep(2)  # Be polite to Motley Fool and avoid rate limits

        # Assemble single output file
        output = {
            "company": company,
            "ticker": ticker,
            "sector": info["sector"],
            "last_updated": date.today().isoformat(),
            "transcripts": transcripts,
        }

        # Save single file
        os.makedirs(DATA_DIR, exist_ok=True)
        filepath = os.path.join(DATA_DIR, f"{ticker.lower()}.json")
        with open(filepath, "w") as f:
            json.dump(output, f, indent=2)

        # Summary
        print(f"\n{'─' * 60}")
        print(f"  Saved {len(transcripts)} transcripts -> {filepath}")
        print(f"{'─' * 60}\n")

        return output


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Cortex Tier 2 — full transcript fetcher (Motley Fool + LLM)",
    )
    parser.add_argument("ticker", help="Stock ticker (e.g. GOOG, TSLA)")
    parser.add_argument("--quarters", type=int, default=DEFAULT_QUARTERS,
                        help=f"Number of past quarters (default: {DEFAULT_QUARTERS})")
    args = parser.parse_args()

    fetcher = Tier2Fetcher()
    fetcher.fetch(ticker=args.ticker, num_quarters=args.quarters)


if __name__ == "__main__":
    main()
