# -*- coding: utf-8 -*-
"""
export_readme_docx.py — 把 README.md 轉成 Word (docs/crypto-quant_專案說明.docx)。

轉換引擎已抽到 md2docx.py（通用 md→docx + mermaid 渲染）；本檔是「只轉 README」
的便捷入口，維持既有流程：改完 README → 重跑本腳本 → 再跑 merge_docx.py 同步合集。
要一次重產所有 .docx（README + 增準 + ML），改跑 md2docx.py。

用法（專案根目錄）：
  .venv\\Scripts\\python.exe scripts\\export_readme_docx.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from md2docx import convert  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "README.md"
OUT = ROOT / "docs" / "crypto-quant_專案說明.docx"

if __name__ == "__main__":
    mn, rn = convert(SRC, OUT)
    tag = f"（{rn}/{mn} 張 mermaid 圖已渲染）" if mn else ""
    print(f"寫出: {OUT}  {tag}")
