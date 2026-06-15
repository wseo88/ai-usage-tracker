"""CLI entry point for the sync package.

Usage:
    python -m src.sync --days 7
    python -m src.sync --days 30
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.sync.anthropic import AnthropicSyncError, sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync AI usage data from Anthropic")
    parser.add_argument(
        "--days", type=int, default=7, help="Number of days of history to sync (default: 7)"
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic"],
        default="anthropic",
        help="Provider to sync (default: anthropic)",
    )
    args = parser.parse_args()

    try:
        if args.provider == "anthropic":
            result = sync(days=args.days)
            logger.info("Sync result: %s", result)
            print(f"\nSync complete: {result['records_inserted']} records synced")
        else:
            logger.error("Unknown provider: %s", args.provider)
            sys.exit(1)
    except AnthropicSyncError as e:
        logger.error("Sync failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
