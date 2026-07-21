"""Regression tests for inclusive date ranges in the central DB reader."""

import sqlite3

from backend.services.reader import _range_clause


def _selected_timestamps(interval: str) -> list[str]:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE samples (ts TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO samples(ts) VALUES (?)",
        [
            ("2026-07-18 23:00:00",),
            ("2026-07-19 00:00:00",),
            ("2026-07-19 12:00:00",),
            ("2026-07-19 23:59:59",),
            ("2026-07-20 00:00:00",),
        ],
    )
    tail, params, reverse = _range_clause(
        None,
        "2026-07-19",
        "2026-07-19",
        interval=interval,
    )
    assert reverse is False
    rows = conn.execute("SELECT ts FROM samples WHERE 1=1" + tail, params).fetchall()
    conn.close()
    return [row[0] for row in rows]


def test_daily_range_includes_end_date_but_not_next_date():
    assert _selected_timestamps("1d") == [
        "2026-07-19 00:00:00",
        "2026-07-19 12:00:00",
        "2026-07-19 23:59:59",
    ]


def test_hourly_range_includes_end_date_but_not_next_date():
    assert _selected_timestamps("1h") == [
        "2026-07-19 00:00:00",
        "2026-07-19 12:00:00",
        "2026-07-19 23:59:59",
    ]
