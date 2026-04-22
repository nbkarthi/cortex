import logging
import sys
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

from pipeline import run_pipeline
from data_loader import list_companies


def main():
    if len(sys.argv) < 2:
        print("Usage: python src/main.py <company_name>")
        print(f"Available: {', '.join(list_companies())}")
        sys.exit(1)

    company = sys.argv[1]
    result = run_pipeline(company)

    print(f"\n{'='*60}")
    print(f"  IC MEMO: {result['company']} ({result['ticker']})")
    print(f"  Time: {result['elapsed_seconds']}s")
    print(f"{'='*60}\n")
    print(result["memo"])
    print(f"\n  Saved to: {result['memo_file']}")


if __name__ == "__main__":
    main()
