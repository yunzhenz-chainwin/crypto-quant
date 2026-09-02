# -*- coding: utf-8 -*-
"""
build_docs.py — 一鍵重生兩份 Word 交接文件（docs/src/*.md → docs/*.docx）。

  docs/src/crypto-quant_系統規格書.md → docs/crypto-quant_系統規格書.docx
  docs/src/crypto-quant_交接手冊.md   → docs/crypto-quant_交接手冊.docx

步驟：
  1. md2docx.convert()：Markdown → docx（含 mermaid 圖以本機 npx 渲染成 PNG 嵌入）。
  2. 有 Microsoft Word 的機器：以 COM 開啟 docx、更新目錄與頁碼欄位後存檔
     （scripts/update_docx_fields.ps1），交接手冊的「目錄（章節與頁碼）」因此帶真實頁碼。
     沒有 Word（例如 macOS 開發機）：在 docx 設 updateFields，Word 開啟時會自動更新目錄。

用法（專案根目錄）：
  .venv\\Scripts\\python.exe scripts\\build_docs.py            # 全部
  .venv\\Scripts\\python.exe scripts\\build_docs.py 交接手冊     # 只建含關鍵字的那份
  .venv\\Scripts\\python.exe scripts\\build_docs.py --no-word   # 跳過 Word 更新欄位
"""
import io
import os
import platform
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from md2docx import JOBS, convert, mark_update_fields  # noqa: E402

PS1 = HERE / "update_docx_fields.ps1"
PS1_RELEASE = HERE / "word_release_docx.ps1"


def _ps(script: Path, *args) -> tuple[int, str]:
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:  # noqa: BLE001
        return 1, str(e)
    return r.returncode, (r.stdout or r.stderr or "").strip()


def _is_locked(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with open(path, "r+b"):
            return False
    except OSError:
        return True


def release_from_word(docx: Path) -> bool:
    """輸出檔若被使用者開著的 Word 鎖住：只在該文件沒有未存檔變更時關閉它，回傳是否有關閉。"""
    if platform.system() != "Windows" or not _is_locked(docx):
        return False
    code, msg = _ps(PS1_RELEASE, "-Path", str(docx), "-Action", "close")
    print(f"  {docx.name} 正被 Word 開啟：{msg}")
    if code == 2:
        raise SystemExit(f"{docx.name} 在 Word 中有未存檔的變更，請先存檔或關閉後再執行。")
    return "closed" in msg


def reopen_in_word(docx: Path):
    code, msg = _ps(PS1_RELEASE, "-Path", str(docx), "-Action", "reopen")
    print(f"  {msg}")


def update_fields_with_word(docx: Path) -> bool:
    """用 Word COM 更新欄位；成功回 True。非 Windows 或無 Word 一律回 False。"""
    if platform.system() != "Windows":
        return False
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", str(PS1), "-Path", str(docx)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception as e:  # noqa: BLE001
        print(f"  Word 更新欄位失敗（{e}）")
        return False
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        print(f"  Word 更新欄位失敗：{msg[-1] if msg else '未知錯誤'}")
        return False
    print(f"  {r.stdout.strip()}")
    return True


def main(argv):
    use_word = "--no-word" not in argv
    keys = [a for a in argv if not a.startswith("--")]
    for src, out in JOBS:
        if keys and not any(k in src.name for k in keys):
            continue
        if not src.exists():
            print(f"跳過（來源不存在）：{src}")
            continue
        print(f"轉換 {src.name} …")
        reopened_needed = release_from_word(out)
        mn, rn, has_toc = convert(src, out)
        tag = f"（{rn}/{mn} 圖）" if mn else ""
        if mn and rn == 0:
            tag += " ⚠️ mermaid 渲染失敗，已退回文字註記（需 node/npx）"
        print(f"  寫出 {out.name}  ({os.path.getsize(out)/1024:.0f} KB){tag}")
        ok = use_word and update_fields_with_word(out)
        if not ok and has_toc:
            mark_update_fields(out)
            print("  已設 updateFields：Word 開啟時會自動更新目錄頁碼")
        if reopened_needed:
            reopen_in_word(out)
    print("完成。")


if __name__ == "__main__":
    main(sys.argv[1:])
