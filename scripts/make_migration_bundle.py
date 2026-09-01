"""make_migration_bundle.py — 打包「不會跟著 git 走」的東西，給換機器時帶走。

git 只帶程式碼。下面這些是 .gitignore 排除、但新機器要它才算「同一套系統」：

  secrets.local.sh   後台帳密（由 Windows 的 secrets.local.cmd 轉出）
  data/app.db        工作項目追蹤、後台設定、AI 金鑰與用量、使用紀錄、市場資料
  data/news.db       新聞與情緒歷史
  data/clean/*.csv   已清洗的 K 線（沒帶也行，排程會重抓，但要等）
  data/raw/          原始下載檔
  reports/           指標／回測／驗證產出

用法（在 repo 根目錄）：
    python scripts/make_migration_bundle.py                 # 產生到 ../crypto-quant-migration/
    python scripts/make_migration_bundle.py --no-secrets    # 不含帳密，另外用安全管道傳
    python scripts/make_migration_bundle.py --out D:/tmp

新機器上還原（zip 內路徑相對於 repo 根目錄，直接解開覆蓋即可）：
    unzip -o crypto-quant-migration-YYYYMMDD.zip -d ~/crypto-quant

DB 用 sqlite3 的線上備份 API 複製，不是直接 copy 檔案 —— 後端是 WAL 模式且排程
還在寫入，直接複製 .db 會漏掉還在 -wal 裡的交易，甚至拿到壞掉的快照。
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_FILES = ["data/app.db", "data/news.db"]
DIR_TREES = ["data/clean", "data/raw", "reports"]


def convert_secrets(cmd_path: Path) -> str | None:
    """把 Windows 的 `set KEY=VALUE` 轉成 POSIX 的 `export KEY=VALUE`（值原樣保留）。"""
    if not cmd_path.exists():
        return None
    lines = [
        "#!/usr/bin/env bash",
        "# 由 scripts/make_migration_bundle.py 從 secrets.local.cmd 轉出（值未更動）。",
        "# 這個檔已被 .gitignore 排除（*.local.sh），不要提交、不要放進雲端硬碟公開資料夾。",
    ]
    for raw in cmd_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        m = re.match(r'^\s*set\s+"?([A-Za-z_][A-Za-z0-9_]*)=(.*?)"?\s*$', raw)
        if m:
            key, value = m.group(1), m.group(2)
            lines.append(f"export {key}='{value}'" if value else f"export {key}=")
    return "\n".join(lines) + "\n"


def snapshot_db(src: Path, dst: Path) -> None:
    """用線上備份 API 取得一致的快照（含尚未 checkpoint 的 WAL 內容）。"""
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as source, sqlite3.connect(dst) as target:
        source.backup(target)
    with sqlite3.connect(dst) as check:
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise RuntimeError(f"{src.name} 備份完整性檢查失敗：{result}")


def main() -> int:
    parser = argparse.ArgumentParser(description="打包換機器要帶走的非版控檔案")
    parser.add_argument("--out", default=str(ROOT.parent / "crypto-quant-migration"),
                        help="輸出目錄（預設 repo 隔壁的 crypto-quant-migration/，刻意放在 repo 外避免被誤提交）")
    parser.add_argument("--no-secrets", action="store_true", help="不要把後台帳密放進 zip")
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"crypto-quant-migration-{date.today():%Y%m%d}.zip"

    total = 0
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(
        zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6
    ) as bundle:
        # 1. 帳密
        if not args.no_secrets:
            converted = convert_secrets(ROOT / "secrets.local.cmd")
            if converted:
                bundle.writestr("secrets.local.sh", converted)
                print("  + secrets.local.sh（由 secrets.local.cmd 轉出）")
            else:
                print("  ! 找不到 secrets.local.cmd，跳過帳密")

        # 2. 資料庫快照
        for rel in DB_FILES:
            src = ROOT / rel
            if not src.exists():
                print(f"  ! 找不到 {rel}，跳過")
                continue
            snap = Path(tmp) / Path(rel).name
            snapshot_db(src, snap)
            bundle.write(snap, rel)
            size = snap.stat().st_size
            total += size
            print(f"  + {rel}  {size / 1048576:.1f} MB（線上備份快照，完整性檢查通過）")

        # 3. 執行期資料與報表
        for rel in DIR_TREES:
            base = ROOT / rel
            if not base.exists():
                continue
            count = 0
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(ROOT).as_posix())
                    total += path.stat().st_size
                    count += 1
            print(f"  + {rel}/  {count} 個檔案")

    print(f"\n完成：{zip_path}")
    print(f"  壓縮後 {zip_path.stat().st_size / 1048576:.1f} MB（原始 {total / 1048576:.1f} MB）")
    if not args.no_secrets:
        print("  ⚠ 內含後台帳密，請用私人管道傳（AirDrop／隨身碟），不要丟公開連結。")
    print("\n新機器上還原：")
    print(f"  unzip -o {zip_path.name} -d ~/crypto-quant")
    return 0


if __name__ == "__main__":
    sys.exit(main())
