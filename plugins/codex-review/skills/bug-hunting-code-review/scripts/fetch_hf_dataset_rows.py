#!/usr/bin/env python3
"""Fetch rows from the Hugging Face Dataset Viewer API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


BASE_URL = "https://datasets-server.huggingface.co/rows"


def fetch_rows(dataset: str, config: str, split: str, offset: int, length: int) -> dict:
    query = urlencode(
        {
            "dataset": dataset,
            "config": config,
            "split": split,
            "offset": offset,
            "length": length,
        }
    )
    url = f"{BASE_URL}?{query}"
    with urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch rows from a Hugging Face dataset via the Dataset Viewer API.")
    parser.add_argument("--dataset", required=True, help="Dataset repo id, e.g. SWE-bench/SWE-bench_Verified")
    parser.add_argument("--config", default="default", help="Dataset config name")
    parser.add_argument("--split", default="test", help="Dataset split")
    parser.add_argument("--offset", type=int, default=0, help="0-based row offset")
    parser.add_argument("--length", type=int, default=5, help="Number of rows to fetch")
    parser.add_argument("--output", help="Optional file path to write JSON output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = fetch_rows(args.dataset, args.config, args.split, args.offset, args.length)
    rendered = json.dumps(payload, indent=2)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
