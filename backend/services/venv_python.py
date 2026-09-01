"""venv_python.py — 決定要用哪一支 Python 去跑 src/ 底下的腳本。

排程（scheduler.py）與後台「新增幣種」（app_db.fetch_and_ingest_symbol）都會用
subprocess 呼叫 src/fetch_binance.py、src/indicators.py，必須跑虛擬環境裡的 Python
才能拿到一致的套件版本。

原本兩處各自寫死 Windows 的 venv 版面（.venv/Scripts/python.exe）。macOS / Linux 的
venv 是 .venv/bin/python，那條路徑不存在 —— subprocess 會直接丟 FileNotFoundError，
每日 09:00、每小時 :06 的抓取與後台新增幣種全部失敗，而且只會出現在排程 log 裡，
前台只看得到「資料沒更新」。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def venv_python(root: Path) -> str:
    """回傳 root/.venv 裡的 Python 路徑；找不到就退回當前行程的直譯器。

    退回 sys.executable 是安全的：呼叫端本來就跑在 uvicorn 裡，而 uvicorn 是用
    專案的 Python 啟動的，套件一定齊全（例如用 conda 或把相依直接裝進系統
    Python、沒有 .venv 目錄的情況）。
    """
    candidate = (
        root / ".venv" / "Scripts" / "python.exe"
        if os.name == "nt"
        else root / ".venv" / "bin" / "python"
    )
    return str(candidate) if candidate.exists() else sys.executable
