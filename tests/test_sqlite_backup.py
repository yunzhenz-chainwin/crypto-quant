from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

import pytest

from backend import scheduler
from backend.services.sqlite_backup import (
    backup_sqlite_database,
    backup_sqlite_databases,
    prune_managed_backups,
)


@pytest.fixture()
def backup_workspace():
    root = Path(__file__).parent / f".sqlite_backup_test_{uuid4().hex}"
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root)


def _create_database(path: Path, value: str = "seed") -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample(value) VALUES (?)", (value,))
        connection.commit()


def test_online_backup_contains_committed_rows_still_in_wal(backup_workspace):
    source = backup_workspace / "source.db"
    destination = backup_workspace / "backup.sqlite3"
    writer = sqlite3.connect(source)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        writer.commit()
        writer.execute("INSERT INTO sample(value) VALUES ('committed-in-wal')")
        writer.commit()
        assert Path(f"{source}-wal").exists()

        result = backup_sqlite_database(source, destination)
        assert result["method"] == "sqlite_online_backup"
        assert result["integrity_check"] == "ok"
        assert len(result["sha256"]) == 64

        with closing(sqlite3.connect(destination)) as restored:
            assert restored.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            assert restored.execute("SELECT value FROM sample").fetchall() == [
                ("committed-in-wal",),
            ]
    finally:
        writer.close()


def test_failed_backup_does_not_replace_existing_destination(backup_workspace):
    source = backup_workspace / "corrupt.db"
    destination = backup_workspace / "existing.sqlite3"
    source.write_bytes(b"not a sqlite database")
    destination.write_bytes(b"known-good-existing-backup")

    with pytest.raises(sqlite3.DatabaseError):
        backup_sqlite_database(source, destination)

    assert destination.read_bytes() == b"known-good-existing-backup"
    assert not list(backup_workspace.glob(".*.tmp"))


def test_missing_source_never_creates_destination(backup_workspace):
    destination = backup_workspace / "never-created.sqlite3"
    with pytest.raises(FileNotFoundError):
        backup_sqlite_database(backup_workspace / "missing.db", destination)
    assert not destination.exists()


def test_bundle_naming_and_pruning_only_touch_managed_files(backup_workspace):
    source = backup_workspace / "source.db"
    backup_root = backup_workspace / "backups"
    _create_database(source)
    unrelated = backup_root / "keep-me.txt"
    backup_root.mkdir()
    unrelated.write_text("unrelated", encoding="utf-8")

    for second in (1, 2, 3):
        result = backup_sqlite_databases(
            {"app": source},
            backup_root,
            now=datetime(2026, 7, 24, 1, 2, second, tzinfo=timezone.utc),
        )
        assert result[0]["label"] == "app"

    removed = prune_managed_backups(backup_root, keep_per_database=2)
    assert len(removed) == 1
    assert len(list(backup_root.glob("app-*.sqlite3"))) == 2
    assert unrelated.read_text(encoding="utf-8") == "unrelated"


def test_scheduler_registers_non_overlapping_daily_backup(monkeypatch):
    class FakeScheduler:
        def __init__(self):
            self.jobs = []
            self.started = False

        def add_job(self, function, trigger, **kwargs):
            self.jobs.append((function, trigger, kwargs))

        def start(self):
            self.started = True

    fake = FakeScheduler()
    monkeypatch.setattr(scheduler, "BackgroundScheduler", lambda: fake)
    result = scheduler.start_scheduler()
    backup_jobs = [job for job in fake.jobs if job[2].get("id") == "sqlite_backup"]

    assert result is fake
    assert fake.started is True
    assert len(backup_jobs) == 1
    function, trigger, options = backup_jobs[0]
    assert function is scheduler.run_sqlite_backup
    assert trigger == "cron"
    assert options["hour"] == 3
    assert options["minute"] == 30
    assert options["max_instances"] == 1
    assert options["coalesce"] is True
