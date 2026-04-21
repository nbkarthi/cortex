import logging
import os
import time
from datetime import datetime

from src.config import OUTPUT_DIR
from src.data_loader import load_company, get_latest_transcripts, get_news
from src.agents.earnings_analyzer import analyze_earnings
from src.agents.sentiment_narrative import analyze_sentiment
from src.agents.memo_generator import generate_memo

logger = logging.getLogger("cortex.pipeline")


def run_pipeline(company_name: str) -> dict:
    pipeline_start = time.time()
    logger.info("=" * 60)
    logger.info("PIPELINE START: %s", company_name)
    logger.info("=" * 60)

    # Step 1: Load data
    logger.info("[1/4] Loading company data...")
    data = load_company(company_name)
    company = data["company"]
    ticker = data["ticker"]

    transcripts = get_latest_transcripts(data, n=2)
    current = transcripts[0]
    previous = transcripts[1] if len(transcripts) > 1 else None
    news = get_news(data)

    logger.info("Loaded %s (%s) — %d transcripts available, %d news items",
                company, ticker, len(data["transcripts"]), len(news))
    logger.info("Current quarter: %s | Previous: %s",
                current["quarter"], previous["quarter"] if previous else "N/A")

    # Step 2: Earnings Analysis
    logger.info("[2/4] Running Earnings Analyzer Agent...")
    step_start = time.time()
    earnings_analysis = analyze_earnings(current, previous)
    logger.info("[2/4] Earnings analysis done in %.1fs", time.time() - step_start)

    # Step 3: Sentiment & Narrative Analysis
    logger.info("[3/4] Running Sentiment/Narrative Agent...")
    step_start = time.time()
    sentiment_analysis = analyze_sentiment(company, ticker, news)
    logger.info("[3/4] Sentiment analysis done in %.1fs", time.time() - step_start)

    # Step 4: Generate IC Memo
    logger.info("[4/4] Running IC Memo Generator Agent...")
    step_start = time.time()
    ic_memo = generate_memo(company, ticker, earnings_analysis, sentiment_analysis)
    logger.info("[4/4] IC memo generated in %.1fs", time.time() - step_start)

    # Save to file
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{ticker}_memo_{timestamp}.md"
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w") as f:
        f.write(ic_memo)
    logger.info("Memo saved to %s", filepath)

    total_time = time.time() - pipeline_start
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE: %s in %.1fs", company, total_time)
    logger.info("=" * 60)

    return {
        "company": company,
        "ticker": ticker,
        "quarter": current["quarter"],
        "previous_quarter": previous["quarter"] if previous else None,
        "earnings_analysis": earnings_analysis,
        "sentiment_analysis": sentiment_analysis,
        "memo": ic_memo,
        "memo_file": filepath,
        "elapsed_seconds": round(total_time, 1),
    }
