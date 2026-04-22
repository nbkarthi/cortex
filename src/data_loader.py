import json
import logging
import os
from config import DATA_DIR

logger = logging.getLogger("cortex.data")


def _load_index() -> dict:
    index_path = os.path.join(DATA_DIR, "index.json")
    with open(index_path) as f:
        return json.load(f)


def load_company(name: str) -> dict:
    """Load company data by name or ticker (case-insensitive)."""
    index = _load_index()
    for company in index["companies"]:
        if company["name"].lower() == name.lower() or company["ticker"].lower() == name.lower():
            file_path = os.path.join(DATA_DIR, company["file"])
            logger.info("Loading company data from %s", file_path)
            with open(file_path) as f:
                return json.load(f)

    available = [c["name"] for c in index["companies"]]
    raise ValueError(f"Company '{name}' not found. Available: {available}")


def get_latest_transcripts(data: dict, n: int = 2) -> list[dict]:
    """Return the last n transcripts (most recent first)."""
    return list(reversed(data["transcripts"][-n:]))


def get_news(data: dict) -> list[dict]:
    """Return all news items."""
    return data.get("news", [])


def list_companies() -> list[str]:
    """Return list of available company names."""
    index = _load_index()
    return [c["name"] for c in index["companies"]]


def list_companies_detail() -> list[dict]:
    """Return detailed company list for the sidebar."""
    index = _load_index()
    result = []
    for c in index["companies"]:
        file_path = os.path.join(DATA_DIR, c["file"])
        with open(file_path) as f:
            data = json.load(f)
        result.append({
            "name": data["company"],
            "ticker": data["ticker"],
            "sector": data.get("sector", ""),
            "transcript_count": len(data.get("transcripts", [])),
            "news_count": len(data.get("news", [])),
        })
    return result
