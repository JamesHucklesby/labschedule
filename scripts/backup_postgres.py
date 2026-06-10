#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "backups"
MIN_BACKUP_SPACING_HOURS = 24


def parse_env_file(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_setting(name: str, env_values: dict[str, str], default: str) -> str:
    return os.getenv(name) or env_values.get(name) or default


def run_pg_dump_to_file(
    db_host: str,
    db_port: str,
    db_user: str,
    db_name: str,
    db_password: str,
    output_sql_path: Path,
) -> None:
    command = [
        "pg_dump",
        "--host",
        db_host,
        "--port",
        db_port,
        "--username",
        db_user,
        "--dbname",
        db_name,
        "--format=plain",
        "--no-owner",
        "--no-privileges",
    ]

    env = os.environ.copy()
    env["PGPASSWORD"] = db_password

    with output_sql_path.open("wb") as sql_file:
        proc = subprocess.run(
            command,
            stdout=sql_file,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"pg_dump failed with exit code {proc.returncode}: {stderr}")


def compress_sql_dump(sql_path: Path, zip_path: Path) -> None:
    with ZipFile(zip_path, mode="w", compression=ZIP_DEFLATED, compresslevel=9) as zip_file:
        zip_file.write(sql_path, arcname=sql_path.name)


def prune_old_backups(backup_dir: Path, retention_days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = 0

    for backup_file in backup_dir.glob("*.zip"):
        modified = datetime.fromtimestamp(backup_file.stat().st_mtime, tz=timezone.utc)
        if modified < cutoff:
            backup_file.unlink(missing_ok=True)
            deleted += 1

    return deleted


def list_backup_files_newest_first(backup_dir: Path) -> list[Path]:
    return sorted(
        backup_dir.glob("*.zip"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def get_latest_backup_time(backup_dir: Path) -> datetime | None:
    backups = list_backup_files_newest_first(backup_dir)
    if not backups:
        return None
    return datetime.fromtimestamp(backups[0].stat().st_mtime, tz=timezone.utc)


def prune_dense_backups(backup_dir: Path, min_spacing_hours: float) -> int:
    backups = list_backup_files_newest_first(backup_dir)
    if len(backups) <= 1:
        return 0

    spacing_seconds = min_spacing_hours * 3600.0
    kept_timestamps: list[float] = []
    deleted = 0

    for backup_file in backups:
        modified_ts = backup_file.stat().st_mtime
        if any((kept_ts - modified_ts) < spacing_seconds for kept_ts in kept_timestamps):
            backup_file.unlink(missing_ok=True)
            deleted += 1
            continue
        kept_timestamps.append(modified_ts)

    return deleted


def perform_backup(
    backup_dir: Path,
    db_host: str,
    db_port: str,
    db_user: str,
    db_name: str,
    db_password: str,
    retention_days: int,
    min_spacing_hours: float = MIN_BACKUP_SPACING_HOURS,
) -> Path | None:
    backup_dir.mkdir(parents=True, exist_ok=True)

    latest_backup_time = get_latest_backup_time(backup_dir)
    now = datetime.now(timezone.utc)
    if latest_backup_time is not None:
        elapsed = now - latest_backup_time
        if elapsed < timedelta(hours=min_spacing_hours):
            dense_deleted_count = prune_dense_backups(backup_dir=backup_dir, min_spacing_hours=min_spacing_hours)
            old_deleted_count = prune_old_backups(backup_dir=backup_dir, retention_days=retention_days)
            print(
                f"[{now.isoformat()}] Backup skipped: most recent backup is {elapsed} old"
                f" (< {min_spacing_hours:g}h)"
                f" | dense backups removed: {dense_deleted_count}"
                f" | old backups removed: {old_deleted_count}",
                flush=True,
            )
            return None

    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    sql_filename = f"{db_name}_{timestamp}.sql"
    zip_filename = f"{db_name}_{timestamp}.zip"
    zip_path = backup_dir / zip_filename

    with tempfile.TemporaryDirectory(prefix="labschedule-backup-") as temp_dir:
        sql_path = Path(temp_dir) / sql_filename
        run_pg_dump_to_file(
            db_host=db_host,
            db_port=db_port,
            db_user=db_user,
            db_name=db_name,
            db_password=db_password,
            output_sql_path=sql_path,
        )
        compress_sql_dump(sql_path=sql_path, zip_path=zip_path)

    dense_deleted_count = prune_dense_backups(backup_dir=backup_dir, min_spacing_hours=min_spacing_hours)
    old_deleted_count = prune_old_backups(backup_dir=backup_dir, retention_days=retention_days)
    print(
        f"[{datetime.now(timezone.utc).isoformat()}] Backup complete: {zip_path}"
        f" | dense backups removed: {dense_deleted_count}"
        f" | old backups removed: {old_deleted_count}",
        flush=True,
    )
    return zip_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create full PostgreSQL backups using pg_dump over network, "
            "compress each dump to zip, and prune backups older than retention policy."
        )
    )
    parser.add_argument(
        "--backup-dir",
        default=str(DEFAULT_BACKUP_DIR),
        help="Directory where zipped backups are written (default: ./backups).",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help="Path to .env file used for POSTGRES settings defaults.",
    )
    parser.add_argument(
        "--db-host",
        default=None,
        help="PostgreSQL host (default: POSTGRES_HOST env/.env or 'localhost').",
    )
    parser.add_argument(
        "--db-port",
        default=None,
        help="PostgreSQL port (default: POSTGRES_PORT env/.env or '5432').",
    )
    parser.add_argument(
        "--interval-hours",
        type=float,
        default=24.0,
        help="Hours between backup runs in scheduler mode (default: 24).",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=30,
        help="Delete .zip backups older than this many days (default: 30).",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run one backup immediately and exit.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.interval_hours <= 0:
        print("interval-hours must be greater than 0", file=sys.stderr)
        return 2
    if args.retention_days < 1:
        print("retention-days must be at least 1", file=sys.stderr)
        return 2

    env_values = parse_env_file(Path(args.env_file))
    db_host = args.db_host or resolve_setting("POSTGRES_HOST", env_values, "localhost")
    db_port = args.db_port or resolve_setting("POSTGRES_PORT", env_values, "5432")
    db_user = resolve_setting("POSTGRES_USER", env_values, "calendar")
    db_name = resolve_setting("POSTGRES_DB", env_values, "calendar")
    db_password = resolve_setting("POSTGRES_PASSWORD", env_values, "change-me")

    backup_dir = Path(args.backup_dir).expanduser().resolve()

    while True:
        try:
            perform_backup(
                backup_dir=backup_dir,
                db_host=db_host,
                db_port=db_port,
                db_user=db_user,
                db_name=db_name,
                db_password=db_password,
                retention_days=args.retention_days,
            )
        except Exception as exc:
            print(f"Backup run failed: {exc}", file=sys.stderr, flush=True)

        if args.run_once:
            return 0

        sleep_seconds = int(args.interval_hours * 3600)
        next_run = datetime.now(timezone.utc) + timedelta(seconds=sleep_seconds)
        print(f"Next backup scheduled for {next_run.isoformat()}", flush=True)
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
