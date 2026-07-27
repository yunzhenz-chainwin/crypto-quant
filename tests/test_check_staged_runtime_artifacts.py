from scripts import check_staged_runtime_artifacts as guard


def test_runtime_artifact_policy_covers_scheduler_and_replay_outputs():
    generated = [
        "data/clean/BTCUSDT_1d.csv",
        r"data\clean\ETHUSDT_1h.csv",
        "reports/indicators_BTCUSDT_1d.csv",
        "reports/backtest_metrics_BTCUSDT_1d.json",
        "reports/backtest_trades_BTCUSDT_1d.csv",
        "reports/forecast-calibration-replay.json",
        "reports/correlation_heatmap.png",
        "reports/validation_BTCUSDT_1d.txt",
        "reports/crosscheck_BTCUSDT_1d.txt",
    ]

    assert all(guard.is_runtime_artifact(path) for path in generated)


def test_runtime_artifact_policy_keeps_reviewed_sources_trackable():
    reviewed = [
        "README.md",
        "docs/forecast-calibration.md",
        "reports/factor_report.md",
        "tests/fixtures/frozen_market_sample.csv",
        "src/backtest.py",
    ]

    assert not any(guard.is_runtime_artifact(path) for path in reviewed)


def test_find_runtime_artifacts_normalizes_deduplicates_and_sorts():
    paths = [
        "reports/backtest_metrics_ETHUSDT_1d.json",
        r"data\clean\BTCUSDT_1d.csv",
        "./data/clean/BTCUSDT_1d.csv",
        "frontend/src/App.jsx",
    ]

    assert guard.find_runtime_artifacts(paths) == [
        "data/clean/BTCUSDT_1d.csv",
        "reports/backtest_metrics_ETHUSDT_1d.json",
    ]


def test_main_blocks_and_lists_every_staged_artifact(monkeypatch, capsys):
    monkeypatch.setattr(
        guard,
        "read_staged_paths",
        lambda: [
            "frontend/src/App.jsx",
            "reports/backtest_trades_DOGEUSDT_1d.csv",
            "data/clean/ADAUSDT_1d.csv",
        ],
    )

    assert guard.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "BLOCKED" in captured.err
    assert "2 generated runtime artifact(s)" in captured.err
    assert "data/clean/ADAUSDT_1d.csv" in captured.err
    assert "reports/backtest_trades_DOGEUSDT_1d.csv" in captured.err
    assert "never unstages, deletes, or modifies the index" in captured.err


def test_main_passes_when_only_feature_files_are_staged(monkeypatch, capsys):
    monkeypatch.setattr(
        guard,
        "read_staged_paths",
        lambda: ["src/backtest.py", "docs/forecast-calibration.md"],
    )

    assert guard.main() == 0
    captured = capsys.readouterr()
    assert "OK" in captured.out
    assert captured.err == ""
