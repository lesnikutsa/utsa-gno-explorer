#!/usr/bin/env python3
"""Apply database/schema.sql to an operator-selected PostgreSQL database."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPO_ROOT / "database" / "schema.sql"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", default=str(SCHEMA), help="Schema SQL file to apply.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required; value is intentionally not printed", file=sys.stderr)
        return 1
    schema = Path(args.schema)
    if not schema.is_file():
        print(f"Schema file not found: {schema}", file=sys.stderr)
        return 1
    command = ["psql", database_url, "--set", "ON_ERROR_STOP=1", "--file", str(schema)]
    result = subprocess.run(command, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
