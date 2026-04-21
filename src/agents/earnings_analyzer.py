import json
import logging
from src.llm import call_llm

logger = logging.getLogger("cortex.earnings")

SYSTEM_PROMPT = """You are an elite buy-side equity research analyst specializing in earnings transcript analysis.

Your job is to analyze earnings call transcripts and produce institutional-quality research output.

You MUST respond in the following markdown format exactly:

## Key Themes
- [theme 1]
- [theme 2]
- ...

## Key Financial Metrics
| Metric | Value | vs Estimate | Reaction |
|--------|-------|-------------|----------|
| ... | ... | ... | ... |

## Management Tone & Messaging
[1-2 sentences on tone shift, confidence level, language changes]

## Risks
- [risk 1]
- [risk 2]
- ...

## What Changed vs Last Quarter
- [change 1 — be specific about what shifted in narrative, guidance, or emphasis]
- [change 2]
- ...

## Notable Quotes
> "[quote]" — [speaker], on [topic]

Be specific, quantitative where possible, and focus on what matters for investment decisions.
If comparing quarters, highlight narrative shifts — not just number changes."""


def analyze_earnings(current_transcript: dict, previous_transcript: dict | None = None) -> str:
    logger.info("Starting earnings analysis for %s", current_transcript["quarter"])
    if previous_transcript:
        logger.info("Comparing against previous quarter: %s", previous_transcript["quarter"])

    user_prompt = f"## Current Quarter: {current_transcript['quarter']} ({current_transcript['date']})\n\n"
    user_prompt += f"**Speakers:** {', '.join(current_transcript['speakers'])}\n\n"
    user_prompt += f"**Financials:** {json.dumps(current_transcript['financials'], indent=2)}\n\n"
    user_prompt += f"**Tone:** {current_transcript['tone']}\n\n"
    user_prompt += "**Key Themes:**\n"
    for theme in current_transcript["key_themes"]:
        user_prompt += f"- {theme}\n"
    user_prompt += "\n**Key Quotes:**\n"
    for quote in current_transcript["key_quotes"]:
        user_prompt += f'- {quote["speaker"]} ({quote["theme"]}): "{quote["text"]}"\n'
    user_prompt += "\n**Risks:**\n"
    for risk in current_transcript["risks"]:
        user_prompt += f"- {risk}\n"

    if previous_transcript:
        user_prompt += f"\n---\n\n## Previous Quarter: {previous_transcript['quarter']} ({previous_transcript['date']})\n\n"
        user_prompt += f"**Financials:** {json.dumps(previous_transcript['financials'], indent=2)}\n\n"
        user_prompt += f"**Tone:** {previous_transcript['tone']}\n\n"
        user_prompt += "**Key Themes:**\n"
        for theme in previous_transcript["key_themes"]:
            user_prompt += f"- {theme}\n"
        user_prompt += "\n**Risks:**\n"
        for risk in previous_transcript["risks"]:
            user_prompt += f"- {risk}\n"
        user_prompt += "\n**Key Quotes:**\n"
        for quote in previous_transcript["key_quotes"]:
            user_prompt += f'- {quote["speaker"]} ({quote["theme"]}): "{quote["text"]}"\n'

    result = call_llm(SYSTEM_PROMPT, user_prompt, label="earnings-analyzer")
    logger.info("Earnings analysis complete (%d chars)", len(result))
    return result
