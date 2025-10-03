#!/usr/bin/env python
"""Placeholder utility to export interaction metrics from Verba logs.

Implementations should:
- Query the Verba backend `/api/admin/interactions` endpoint (or database) for the pilot date range.
- Aggregate counts of solved vs. escalated questions.
- Surface top intents with low confidence for review meetings.
"""

import sys


def main() -> None:
    sys.exit("export_metrics is not yet implemented. Track this in the PoC backlog.")


if __name__ == "__main__":
    main()
