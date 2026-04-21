import logging
from src.llm import call_llm

logger = logging.getLogger("cortex.sentiment")

SYSTEM_PROMPT = """You are a senior market strategist who synthesizes news flow into actionable investment narratives.

Given recent news items for a company, identify the dominant narratives driving market perception.

You MUST respond in the following markdown format exactly:

## Top 3 Narratives

### 1. [Narrative Title]
[2-3 sentences explaining the narrative, what's driving it, and why it matters for the stock]

### 2. [Narrative Title]
[2-3 sentences]

### 3. [Narrative Title]
[2-3 sentences]

## Overall Sentiment
**Rating:** [Bullish / Bearish / Mixed]

**Reasoning:** [2-3 sentences on why — reference specific data points]

## Emerging Risks
- [risk 1 — something the market may not be fully pricing in]
- [risk 2]
- [risk 3]

## 3 Things the Market May Be Missing
1. [insight 1 — a non-consensus or underappreciated angle]
2. [insight 2]
3. [insight 3]

Focus on themes and narrative shifts, not just sentiment scores. Think like a PM constructing a thesis."""


def analyze_sentiment(company_name: str, ticker: str, news: list[dict]) -> str:
    logger.info("Starting sentiment analysis for %s (%s) with %d news items", company_name, ticker, len(news))

    user_prompt = f"# {company_name} ({ticker}) — Recent News Flow\n\n"
    for item in news:
        user_prompt += f"### {item['headline']}\n"
        user_prompt += f"**Date:** {item['date']} | **Source:** {item['source']}\n\n"
        user_prompt += f"{item['snippet']}\n\n"
        user_prompt += f"**Tags:** {', '.join(item['tags'])}\n\n---\n\n"

    result = call_llm(SYSTEM_PROMPT, user_prompt, label="sentiment-narrative")
    logger.info("Sentiment analysis complete (%d chars)", len(result))
    return result
