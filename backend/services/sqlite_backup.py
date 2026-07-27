"""Consistent, atomic backups for SQLite databases, including WAL contents."""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any


_SAFE_LABEL = re.compile(r"^[A-Za-z0-9_-]+$")
_MANAGED_BACKUP = re.compile(
    r"^(?P<label>[A-Za-z0-9_-]+)-\d{8}T\d{12}Z\.sqlite3$"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity_check(connection: sqlite3.Connection) -> None:
    row = connection.execute("PRAGMA quick_check").fetchone()
    if not row or str(row[0]).lower() != "ok":
        detail = str(row[0]) if row else "no result"
        raise sqlite3.DatabaseError(f"SQLite backup integrity check failed: {detail}")


def backup_sqlite_database(
    source: str | Path,
    destination: str | Path,
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Create a transactionally consistent backup with SQLite's online API.

    Copying a ``*.db`` file directly can omit committed rows still stored in a
    WAL file.  ``Connection.backup`` reads a consistent SQLite snapshot.  The
    snapshot is verified in a sibling temporary file and atomically published
    only after ``PRAGMA quick_check`` succeeds.
    """
    source_path = Path(source).expanduser().resolve(strict=True)
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite source is not a file: {source_path}")
    destination_path = Path(destination).expanduser().resolve(strict=False)
    if source_path == destination_path:
        raise ValueError("SQLite backup destination must differ from source")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temp_handle = tempfile.NamedTemporaryFile(
        prefix=f".{destination_path.name}.",
        suffix=".tmp",
        dir=str(destination_path.parent),
        delete=False,
    )
    temp_path = Path(temp_handle.name)
    temp_handle.close()
    try:
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        source_uri = f"{source_path.as_uri()}?mode=ro"
        with closing(sqlite3.connect(
            source_uri,
            uri=True,
            timeout=float(timeout_seconds),
        )) as source_connection:
            source_connection.execute("PRAGMA query_only=ON")
            with closing(sqlite3.connect(
                str(temp_path),
                timeout=float(timeout_seconds),
            )) as backup_connection:
                source_connection.backup(
                    backup_connection,
                    pages=256,
                    sleep=0.01,
                )
                _integrity_check(backup_connection)
                backup_connection.commit()

        with temp_path.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        digest = _sha256(temp_path)
        size_bytes = temp_path.stat().st_size
        os.replace(temp_path, destination_path)
        return {
            "source": str(source_path),
            "destination": str(destination_path),
            "size_bytes": size_bytes,
            "sha256": digest,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "method": "sqlite_online_backup",
            "integrity_check": "ok",
        }
    finally:
        temp_path.unlink(missing_ok=True)


def backup_sqlite_databases(
    sources: Mapping[str, str | Path],
    backup_directory: str | Path,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Back up named databases using collision-resistant managed filenames."""
    if not sources:
        raise ValueError("at least one SQLite source is required")
    backup_root = Path(backup_directory).expanduser().resolve(strict=False)
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = timestamp.strftime("%Y%m%dT%H%M%S%fZ")

    results = []
    for label, source in sources.items():
        normalized = str(label)
        if not _SAFE_LABEL.fullmatch(normalized):
            raise ValueError(f"invalid SQLite backup label: {normalized!r}")
        destination = backup_root / f"{normalized}-{stamp}.sqlite3"
        result = backup_sqlite_database(source, destination)
        result["label"] = normalized
        results.append(result)
    return results


def prune_managed_backups(
    backup_directory: str | Path,
    *,
    keep_per_database: int = 14,
) -> list[str]:
    """Remove only old files created by :func:`backup_sqlite_databases`.

    Unrelated files and temporary/incomplete files are never selected.
    """
    if keep_per_database < 1:
        raise ValueError("keep_per_database must be positive")
    backup_root = Path(backup_directory).expanduser().resolve(strict=False)
    if not backup_root.exists():
        return []

    grouped: dict[str, list[Path]] = {}
    for candidate in backup_root.iterdir():
        if not candidate.is_file():
            continue
        match = _MANAGED_BACKUP.fullmatch(candidate.name)
        if not match:
            continue
        resolved = candidate.resolve(strict=True)
        if resolved.parent != backup_root:
            continue
        grouped.setdefault(match.group("label"), []).append(resolved)

    removed = []
    for files in grouped.values():
        for old_path in sorted(files, key=lambda path: path.name, reverse=True)[keep_per_database:]:
            old_path.unlink()
            removed.append(str(old_path))
    return removed
