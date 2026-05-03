"""
Cortex Transcript Fetcher — Pull earnings call transcripts using earningscall-python.

Usage:
    uv run python tools/fetch_transcripts.py AAPL
    uv run python tools/fetch_transcripts.py MSFT --quarters 4

Pulls full earnings call transcripts and:
    - Stores raw full text per quarter
    - Parses speakers from the text
    - Splits into prepared remarks vs Q&A sections
    - Saves structured JSON to src/data/et/{ticker}/

API Key (optional):
    Free tier: full transcript text (no speaker-level breakdown)
    Paid tier: set EARNINGSCALL_API_KEY in .env for speaker-level data

    Get an API key at: https://earningscall.biz/api-pricing
"""

import json
import logging
import os
import re
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [transcript] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("transcript")

# Load .env
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))

import earningscall

# Set API key if available
api_key = os.environ.get("EARNINGSCALL_API_KEY", "")
if api_key:
    earningscall.api_key = api_key
    logger.info("Using EARNINGSCALL_API_KEY (paid tier — speaker-level data available)")
else:
    logger.info("No EARNINGSCALL_API_KEY set — using free tier (full text only)")

ET_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "et")


# --- Common executive title patterns ---
TITLE_PATTERNS = [
    r"(?:Chief Executive Officer|CEO)",
    r"(?:Chief Financial Officer|CFO)",
    r"(?:Chief Operating Officer|COO)",
    r"(?:Chief Technology Officer|CTO)",
    r"(?:President)",
    r"(?:Director of Investor Relations|VP.{0,20}Investor Relations|IR)",
    r"(?:Senior Vice President|SVP|Executive Vice President|EVP)",
    r"(?:Vice President|VP)",
    r"(?:Analyst|Managing Director)",
]


def parse_speakers(text: str) -> list[str]:
    """Extract speaker names from transcript text using common patterns."""
    speakers = set()

    # Pattern: "Name, Title" or "Name — Title" at start of a paragraph
    # or "I'd like to turn the call over to Name"
    # or "Thank you, Name" patterns
    for pattern in [
        r"turn (?:the call|it) over to ([A-Z][a-z]+ [A-Z][a-z]+)",
        r"(?:Thank you|Thanks),? ([A-Z][a-z]+ [A-Z]?[a-z]*)",
    ]:
        for match in re.finditer(pattern, text):
            name = match.group(1).strip()
            if len(name.split()) >= 2 and len(name) < 40:
                speakers.add(name)

    # Look for "Name (Title)" or "Name, Title" patterns near the start
    intro_text = text[:3000]  # Usually speakers are introduced early
    for match in re.finditer(
        r"([A-Z][a-z]+ (?:[A-Z]\. )?[A-Z][a-z]+)(?:,| —| -) (?:" + "|".join(TITLE_PATTERNS) + ")",
        intro_text,
    ):
        name = match.group(1).strip()
        if len(name) < 40:
            speakers.add(name)

    return sorted(speakers)


def split_sections(text: str) -> dict:
    """Split transcript into prepared remarks and Q&A sections."""
    qa_markers = [
        r"(?:we(?:'ll| will) (?:now )?(?:open|begin|take|move to).*(?:question|Q&A|Q & A))",
        r"(?:open (?:the )?(?:call|floor|line).*(?:question|Q&A))",
        r"(?:question.and.answer (?:session|portion|segment))",
        r"(?:Q&A (?:session|portion|segment))",
        r"(?:first question)",
        r"(?:Operator.*(?:first question|question comes from))",
    ]

    qa_pattern = "|".join(qa_markers)
    match = re.search(qa_pattern, text, re.IGNORECASE)

    if match:
        split_pos = match.start()
        prepared_remarks = text[:split_pos].strip()
        qa_section = text[split_pos:].strip()
    else:
        # If no clear split found, treat everything as prepared remarks
        prepared_remarks = text
        qa_section = ""

    return {
        "prepared_remarks": prepared_remarks,
        "questions_and_answers": qa_section,
    }


def extract_key_numbers(text: str) -> dict:
    """Extract mentioned financial figures from transcript text."""
    numbers = {}

    # Revenue patterns
    rev_match = re.search(
        r"revenue of \$?([\d,.]+)\s*(billion|million|B|M)",
        text, re.IGNORECASE,
    )
    if rev_match:
        val = float(rev_match.group(1).replace(",", ""))
        unit = rev_match.group(2).lower()
        if unit in ("billion", "b"):
            numbers["revenue_mentioned"] = f"${val}B"
        elif unit in ("million", "m"):
            numbers["revenue_mentioned"] = f"${val}M"

    # EPS patterns
    eps_match = re.search(
        r"(?:earnings per share|EPS|diluted earnings).*?\$?([\d.]+)",
        text[:5000], re.IGNORECASE,
    )
    if eps_match:
        numbers["eps_mentioned"] = f"${eps_match.group(1)}"

    return numbers


def fetch_transcripts(ticker: str, num_quarters: int = 8):
    """Fetch and save earnings call transcripts for a ticker."""
    ticker = ticker.upper()
    logger.info("Fetching transcripts for %s...", ticker)

    company = earningscall.get_company(ticker.lower())
    if not company:
        logger.error("Company not found: %s", ticker)
        sys.exit(1)

    logger.info("Company: %s", company.name)

    # Get available events
    events = company.events()
    if not events:
        logger.error("No earnings events found for %s", ticker)
        sys.exit(1)

    logger.info("Found %d earnings events, fetching latest %d...", len(events), num_quarters)

    # Create output directory
    ticker_dir = os.path.join(ET_DIR, ticker.lower())
    os.makedirs(ticker_dir, exist_ok=True)

    results = []
    for event in events[:num_quarters]:
        year = event.year
        quarter = event.quarter
        conf_date = str(event.conference_date.date()) if event.conference_date else ""

        logger.info("  Fetching Q%d %d (%s)...", quarter, year, conf_date)

        try:
            transcript = company.get_transcript(year=year, quarter=quarter)
        except Exception as e:
            logger.warning("  Failed to fetch Q%d %d: %s", quarter, year, e)
            continue

        if not transcript or not transcript.text:
            logger.warning("  No transcript available for Q%d %d", quarter, year)
            continue

        text = transcript.text
        logger.info("  Got %d chars", len(text))

        # Use API speaker data if available, otherwise parse
        if transcript.speakers:
            speakers = transcript.speakers
            logger.info("  Speakers (from API): %s", speakers)
        else:
            speakers = parse_speakers(text)
            logger.info("  Speakers (parsed): %s", speakers)

        # Use API sections if available, otherwise split
        if transcript.prepared_remarks and transcript.questions_and_answers:
            sections = {
                "prepared_remarks": transcript.prepared_remarks,
                "questions_and_answers": transcript.questions_and_answers,
            }
            logger.info("  Sections from API (paid tier)")
        else:
            sections = split_sections(text)
            pr_len = len(sections["prepared_remarks"])
            qa_len = len(sections["questions_and_answers"])
            logger.info("  Sections parsed: prepared=%d chars, Q&A=%d chars", pr_len, qa_len)

        # Extract mentioned numbers
        key_numbers = extract_key_numbers(text)
        if key_numbers:
            logger.info("  Key numbers: %s", key_numbers)

        # Build record
        record = {
            "company": company.name,
            "ticker": ticker,
            "year": year,
            "quarter": quarter,
            "quarter_label": f"Q{quarter} {year}",
            "conference_date": conf_date,
            "speakers": speakers,
            "transcript_length": len(text),
            "key_numbers": key_numbers,
            "full_text": text,
            "prepared_remarks": sections["prepared_remarks"],
            "questions_and_answers": sections["questions_and_answers"],
            "fetched_at": datetime.now().isoformat(),
            "source": "earningscall",
        }

        # Save individual quarter file
        filename = f"Q{quarter}_{year}.json"
        filepath = os.path.join(ticker_dir, filename)
        with open(filepath, "w") as f:
            json.dump(record, f, indent=2)
        logger.info("  Saved %s", filepath)

        results.append({
            "quarter_label": record["quarter_label"],
            "conference_date": conf_date,
            "speakers": speakers,
            "transcript_length": len(text),
            "key_numbers": key_numbers,
            "file": filename,
        })

    # Save summary index
    summary = {
        "company": company.name,
        "ticker": ticker,
        "fetched_at": datetime.now().isoformat(),
        "total_transcripts": len(results),
        "transcripts": results,
    }
    summary_path = os.path.join(ticker_dir, "_index.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Print summary
    print(f"\n{'='*55}")
    print(f"  {company.name} ({ticker}) — Transcripts Fetched")
    print(f"{'='*55}")
    print(f"  Total: {len(results)} transcripts")
    print(f"  Output: {ticker_dir}/")
    print()
    for r in results:
        nums = " | ".join(f"{k}: {v}" for k, v in r["key_numbers"].items()) if r["key_numbers"] else ""
        print(f"  {r['quarter_label']:>8}  {r['conference_date']}  {r['transcript_length']:>6} chars  {nums}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python tools/fetch_transcripts.py <TICKER> [--quarters N]")
        print()
        print("Examples:")
        print("  uv run python tools/fetch_transcripts.py AAPL")
        print("  uv run python tools/fetch_transcripts.py MSFT --quarters 4")
        print()
        print("API Key (optional, for speaker-level data):")
        print("  Get one at: https://earningscall.biz/api-pricing")
        print("  Add to .env: EARNINGSCALL_API_KEY=your_key")
        sys.exit(1)

    ticker_arg = sys.argv[1]
    quarters_arg = 8
    if "--quarters" in sys.argv:
        idx = sys.argv.index("--quarters")
        if idx + 1 < len(sys.argv):
            quarters_arg = int(sys.argv[idx + 1])

    fetch_transcripts(ticker_arg, quarters_arg)
