# -*- coding: utf-8 -*-
"""
merge_docx.py — 把 docs/ 下的 5 份 .docx 合併成「一份合集」給主管一次看完。

用 docxcompose（保留每份原有的表格 / 標題 / 樣式），每份之間插入分頁，
最前面加一頁封面 + 目錄。

用法（專案根目錄）：
  .venv\\Scripts\\python.exe scripts\\merge_docx.py
輸出：
  docs/crypto-quant_文件合集.docx
※ 任一來源 .docx 更新後，重跑本腳本即可同步合集。
  (crypto-quant_專案說明.docx 來自 README → export_readme_docx.py；
   AI機器人固定問答範本.docx 來自 canned_qa → export_qa_docs.py)
"""
import io
import os
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT  = DOCS / "crypto-quant_文件合集.docx"

from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn
from docxcompose.composer import Composer

ZH = "微軟正黑體"

# 合併順序：總覽 → 兩份前瞻計畫（增準 → ML，ML 依賴增準）→ 兩份內容審核範本
SECTIONS = [
    ("crypto-quant_專案說明.docx",   "壹、專案說明（README）"),
    ("訊號增準計畫.docx",            "貳、訊號增準計畫（規則式）"),
    ("ML訊號研究計畫.docx",          "參、ML 訊號研究計畫"),
    ("AI機器人固定問答範本.docx",     "肆、AI 機器人固定問答庫"),
    ("情緒詞庫範本.docx",            "伍、情緒詞庫範本"),
]


def _ea(run, size=None, bold=False, color=None):
    run.font.name = "Microsoft JhengHei"
    if size:
        run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = color
    rPr = run._element.get_or_add_rPr()
    rf = rPr.rFonts if rPr.rFonts is not None else rPr._add_rFonts()
    rf.set(qn("w:eastAsia"), ZH)


def main():
    missing = [fn for fn, _ in SECTIONS if not (DOCS / fn).exists()]
    if missing:
        raise SystemExit(f"缺少來源檔：{missing}")

    # 封面（空白 master + 中文字型）
    master = Document()
    st = master.styles["Normal"]
    st.font.name = "Microsoft JhengHei"
    st.font.size = Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), ZH)

    _ea(master.add_paragraph().add_run("crypto-quant 文件合集"), size=26, bold=True,
        color=RGBColor(0x1F, 0x3A, 0x5F))
    _ea(master.add_paragraph().add_run("加密貨幣量化分析平台 — 文件包（合併 5 份）"),
        size=12, color=RGBColor(0x66, 0x66, 0x66))
    master.add_paragraph()
    _ea(master.add_paragraph().add_run("內容"), size=14, bold=True)
    for i, (_, title) in enumerate(SECTIONS, 1):
        _ea(master.add_paragraph().add_run(f"{i}. {title}"), size=11)
    _ea(master.add_paragraph().add_run(
        "（各份保留原始格式；每份自第二頁起、以分頁分隔。要調整內容請改各來源檔後重跑 merge_docx.py）"),
        size=9, color=RGBColor(0x88, 0x88, 0x88))

    # 依序附加，每份前插分頁
    composer = Composer(master)
    for fn, _ in SECTIONS:
        master.add_page_break()
        composer.append(Document(str(DOCS / fn)))

    composer.save(str(OUT))
    print(f"寫出: {OUT}  ({os.path.getsize(OUT) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
