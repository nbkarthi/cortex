import json
import os
from src.config import DATA_DIR


def load_company(name: str) -> dict:
    """Load company data by name (case-insensitive)."""
    index_path = os.path.join(DATA_DIR, "index.json")
    with open(index_path) as f:
        index = json.load(f)

    for company in index["companies"]:
        if company["name"].lower() == name.lower() or company["ticker"].lower() == name.lower():
            file_path = os.path.join(DATA_DIR, company["file"])
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
    index_path = os.path.join(DATA_DIR, "index.json")
    with open(index_path) as f:
        index = json.load(f)
    return [c["name"] for c in index["companies"]]
