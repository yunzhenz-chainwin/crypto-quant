# -*- coding: utf-8 -*-
"""
export_readme_docx.py — 把 README.md 轉成 Word (.docx) 給主管看。

本機無 pandoc，改用 python-docx 自行轉換；支援：標題、表格、程式碼區塊、
引用、清單、**粗體**、`行內碼`、分隔線。中文用微軟正黑體。

用法（專案根目錄執行）：
  .venv\\Scripts\\python.exe scripts\\export_readme_docx.py
輸出：
  docs/crypto-quant_專案說明.docx
※ 改了 README.md 後重跑本腳本即可同步 Word 版。
"""
import io
import os
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
SRC  = ROOT / "README.md"
OUT  = ROOT / "docs" / "crypto-quant_專案說明.docx"

from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.oxml.ns import qn

ZH_FONT = "微軟正黑體"
MONO    = "Consolas"


def _set_ea(run, latin=None):
    """設定 run 的中英字型（east-asia 用正黑體）。"""
    if latin:
        run.font.name = latin
    rPr = run._element.get_or_add_rPr()
    rf = rPr.rFonts if rPr.rFonts is not None else rPr._add_rFonts()
    rf.set(qn("w:eastAsia"), ZH_FONT)


def _new_doc():
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Microsoft JhengHei"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), ZH_FONT)
    for h, sz in (("Heading 1", 18), ("Heading 2", 14), ("Heading 3", 12)):
        try:
            s = doc.styles[h]
            s.font.name = "Microsoft JhengHei"
            s.font.size = Pt(sz)
            if s.element.rPr is None:
                s.element.get_or_add_rPr()
            rf = (s.element.rPr.rFonts if s.element.rPr.rFonts is not None
                  else s.element.rPr._add_rFonts())
            rf.set(qn("w:eastAsia"), ZH_FONT)
            s.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
        except KeyError:
            pass
    return doc


def add_inline(p, text):
    """行內：先切 `code`，再對非 code 段切 **bold**。"""
    for seg in re.split(r"(`[^`]*`)", text):
        if not seg:
            continue
        if len(seg) >= 2 and seg[0] == "`" and seg[-1] == "`":
            r = p.add_run(seg[1:-1])
            _set_ea(r, MONO)
            r.font.size = Pt(9.5)
            r.font.color.rgb = RGBColor(0xB0, 0x3A, 0x2E)
        else:
            for j, part in enumerate(seg.split("**")):
                if not part:
                    continue
                r = p.add_run(part)
                r.bold = (j % 2 == 1)
                _set_ea(r)


def _cells(line):
    """'| a | b |' → ['a','b']（去頭尾空欄）。"""
    parts = line.strip().split("|")
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [c.strip() for c in parts]


def _is_sep(line):
    """表格分隔列 |---|:--:|。"""
    return bool(re.match(r"^\s*\|?\s*:?-{2,}.*$", line)) and set(line.strip()) <= set("|-: ")


def add_table(doc, rows):
    t = doc.add_table(rows=len(rows), cols=max(len(r) for r in rows))
    t.style = "Table Grid"
    for ri, row in enumerate(rows):
        for ci in range(len(t.columns)):
            cell = t.cell(ri, ci)
            cell.text = ""
            add_inline(cell.paragraphs[0], row[ci] if ci < len(row) else "")
            for run in cell.paragraphs[0].runs:
                run.font.size = Pt(9)
                if ri == 0:
                    run.font.bold = True
    doc.add_paragraph()


def add_code(doc, lines):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.3)
    p.paragraph_format.space_after = Pt(4)
    for k, ln in enumerate(lines):
        if k:
            p.add_run().add_break()
        r = p.add_run(ln)
        _set_ea(r, MONO)
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(0x33, 0x33, 0x33)


def main():
    md = SRC.read_text(encoding="utf-8").splitlines()
    doc = _new_doc()

    i, n = 0, len(md)
    in_code, code_buf = False, []
    while i < n:
        line = md[i]

        # 程式碼區塊
        if line.strip().startswith("```"):
            if in_code:
                add_code(doc, code_buf)
                code_buf, in_code = [], False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # 表格（連續的 | 行）
        if line.strip().startswith("|") and "|" in line.strip()[1:]:
            block = []
            while i < n and md[i].strip().startswith("|"):
                if not _is_sep(md[i]):
                    block.append(_cells(md[i]))
                i += 1
            if block:
                add_table(doc, block)
            continue

        # 標題
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            lvl = min(len(m.group(1)), 3)
            h = doc.add_heading(level=lvl)
            add_inline(h, m.group(2))
            i += 1
            continue

        # 分隔線
        if line.strip() == "---":
            doc.add_paragraph().add_run("─" * 30).font.color.rgb = RGBColor(0xCC, 0xCC, 0xCC)
            i += 1
            continue

        # 引用
        if line.startswith(">"):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.6)
            r0 = p.add_run("▍ ")
            r0.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
            add_inline(p, line.lstrip(">").strip())
            i += 1
            continue

        # 清單
        mb = re.match(r"^\s*[-*]\s+(.*)$", line)
        if mb:
            p = doc.add_paragraph(style="List Bullet")
            add_inline(p, mb.group(1))
            i += 1
            continue

        # 空行
        if not line.strip():
            i += 1
            continue

        # 一般段落
        p = doc.add_paragraph()
        add_inline(p, line)
        i += 1

    doc.save(str(OUT))
    print(f"寫出: {OUT}  ({os.path.getsize(OUT)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
