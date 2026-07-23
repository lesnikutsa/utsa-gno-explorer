#!/usr/bin/env python3
"""Create an atomic PostgreSQL custom-format backup through Docker Compose."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKUP_RE = re.compile(r"^utsa-gno-explorer-\d{8}T\d{6}Z\.dump$")
DEFAULT_BACKUP_DIR = Path("/var/backups/utsa-gno-explorer")
DEFAULT_COMPOSE_FILE = Path("deploy/postgres/compose.yml")
DEFAULT_ENV_FILE = Path("/etc/utsa-gno-explorer/postgres.env")


def backup_filename(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return f"utsa-gno-explorer-{value.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}.dump"


def compose_command(compose_file: Path, env_file: Path, *args: str) -> list[str]:
    return ["docker", "compose", "-f", str(compose_file), "--env-file", str(env_file), *args]


def successful_backups(directory: Path) -> list[Path]:
    backups = []
    for child in directory.iterdir():
        if child.is_file() and not child.is_symlink() and BACKUP_RE.fullmatch(child.name):
            backups.append(child)
    return sorted(backups, key=lambda path: path.name)


def apply_retention(directory: Path, keep: int, newest: Path) -> None:
    if keep <= 0:
        return
    backups = successful_backups(directory)
    victims = backups[: max(0, len(backups) - keep)]
    for victim in victims:
        if victim.resolve() == newest.resolve():
            continue
        victim.unlink()


def run_checked(command: list[str], stdout=None, stdin=None) -> None:
    result = subprocess.run(command, stdout=stdout, stdin=stdin, stderr=None, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}")


def create_backup(backup_dir: Path, compose_file: Path, env_file: Path, retention: int) -> Path:
    if retention < 0:
        raise ValueError("retention must be greater than or equal to 0")
    if not compose_file.is_file():
        raise FileNotFoundError(f"Compose file not found: {compose_file}")
    if not env_file.is_file():
        raise FileNotFoundError(f"Compose env file not found: {env_file}")
    old_umask = os.umask(0o077)
    try:
        backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        final_path = backup_dir / backup_filename()
        part_path = final_path.with_suffix(final_path.suffix + ".part")
        if final_path.exists() or part_path.exists():
            raise RuntimeError(f"Backup path already exists for current timestamp: {final_path.name}")
        try:
            with part_path.open("xb") as output:
                run_checked(compose_command(compose_file, env_file, "exec", "-T", "postgres", "sh", "-c", "pg_dump -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -Fc --no-owner --no-privileges"), stdout=output)
            with part_path.open("rb") as archive:
                run_checked(compose_command(compose_file, env_file, "exec", "-T", "postgres", "pg_restore", "--list"), stdout=subprocess.DEVNULL, stdin=archive)
        except Exception:
            try:
                part_path.unlink()
            except FileNotFoundError:
                pass
            raise
        part_path.replace(final_path)
        apply_retention(backup_dir, retention, final_path)
        return final_path
    finally:
        os.umask(old_umask)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--retention", type=int, default=3, help="Number of successful backups to keep; 0 disables deletion.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        path = create_backup(args.backup_dir, args.compose_file, args.env_file, args.retention)
    except Exception as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1
    print(f"Backup created: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
