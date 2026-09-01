# -*- coding: utf-8 -*-
"""
md2docx.py — 通用 Markdown → Word(.docx) 轉換引擎（本機無 pandoc 用）。

2026-09-01 樣式改版：對齊 iFare 文件的專業排版（C:/sites/ifare-website 同款主題）——
深藍標題階層＋底線、表格深藍表頭白字＋隔行網底、程式碼盒、引言左側邊條、
每個「# 章」從新頁開始（首個 # 為文件標題）、頁尾「第 X 頁／共 Y 頁」、2cm 邊界。
樣式常數集中在 THEME，要換配色改那裡即可。

支援：標題、表格、程式碼區塊、引用、清單、**粗體**、`行內碼`、[連結](url)、分隔線、
本地圖片 ![說明](相對路徑)，以及 ```mermaid 圖（本機 mermaid-cli via npx 渲染成 PNG 嵌入，
渲染失敗自動退回「見線上版」文字註記）。中文用微軟正黑體。

需求：node + npx（渲染 mermaid 用；首次自動下載 @mermaid-js/mermaid-cli）。

用法（專案根目錄）：
  .venv\\Scripts\\python.exe scripts\\md2docx.py          # 轉換下方 JOBS 全部
其他腳本可： from md2docx import convert; convert(md_path, out_path)

JOBS（來源 .md → docs/*.docx，共 7 份）：
  docs/主管摘要.md、README.md（→ crypto-quant_專案說明.docx）、
  docs/archive/ 的 部署與運維／API規格／成果匯報／訊號增準計畫／研究預測評估。
※ 任一來源 .md 改動後重跑本腳本；再跑 merge_docx.py 同步合集。
"""
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent

from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT

ZH_FONT = "微軟正黑體"
MONO    = "Consolas"

# ── 配色主題（同 iFare convert-docs.mjs）────────────────────────────────────
THEME = {
    "accent":      "1F4E79",  # 標題與表頭：深藍
    "accent_soft": "2E6DA4",  # 次級標題
    "text":        "333333",
    "muted":       "595959",
    "table_border":"C9D6E4",
    "table_band":  "F2F6FA",  # 表格隔行網底
    "code_bg":     "F7F8FA",
    "code_border": "E1E4E8",
    "code_ink":    "EFF1F4",  # 行內 code 底色
    "quote_bg":    "F7FAFC",
    "rule":        "D0D7DE",
    "link":        "0563C1",
    "h4":          "2D3748",
}


def _rgb(key):
    return RGBColor.from_string(THEME[key])


JOBS = [
    (ROOT / "docs" / "主管摘要.md",                ROOT / "docs" / "主管摘要.docx"),
    (ROOT / "README.md",                          ROOT / "docs" / "crypto-quant_專案說明.docx"),
    (ROOT / "docs" / "archive" / "部署與運維.md",    ROOT / "docs" / "部署與運維.docx"),
    (ROOT / "docs" / "archive" / "API規格.md",       ROOT / "docs" / "API規格.docx"),
    (ROOT / "docs" / "archive" / "成果匯報.md",       ROOT / "docs" / "成果匯報.docx"),
    (ROOT / "docs" / "archive" / "訊號增準計畫.md",  ROOT / "docs" / "訊號增準計畫.docx"),
    (ROOT / "docs" / "archive" / "研究預測評估.md",  ROOT / "docs" / "研究預測評估.docx"),
]


# ── 低階 XML 小工具 ──────────────────────────────────────────────────────────
def _set_ea(run, latin=None):
    if latin:
        run.font.name = latin
    rPr = run._element.get_or_add_rPr()
    rf = rPr.rFonts if rPr.rFonts is not None else rPr._add_rFonts()
    rf.set(qn("w:eastAsia"), ZH_FONT)


def _run_shd(run, fill):
    """行內底色（行內 code 用）。"""
    rPr = run._element.get_or_add_rPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill)
    rPr.append(shd)


def _para_shd(p, fill):
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill)
    pPr.append(shd)


def _para_border(p, edges):
    """edges = {"bottom": (size, color, space), "left": (...)}；size 為 1/8 pt。"""
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    for edge, (size, color, space) in edges.items():
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(size))
        el.set(qn("w:color"), color)
        el.set(qn("w:space"), str(space))
        pBdr.append(el)
    pPr.append(pBdr)


def _cell_shd(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def _cell_margins(cell, top=80, bottom=80, left=120, right=120):
    tcPr = cell._tc.get_or_add_tcPr()
    mar = OxmlElement("w:tcMar")
    for tag, v in (("top", top), ("bottom", bottom), ("start", left), ("end", right)):
        el = OxmlElement(f"w:{tag}")
        el.set(qn("w:w"), str(v))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tcPr.append(mar)


def _table_theme(t):
    """全寬、細框線（同 iFare tableBorders）。"""
    tblPr = t._tbl.tblPr
    w = OxmlElement("w:tblW")
    w.set(qn("w:w"), "5000")
    w.set(qn("w:type"), "pct")
    tblPr.append(w)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:color"), THEME["table_border"])
        borders.append(el)
    tblPr.append(borders)


def _add_field(p, instr, size=8):
    """頁碼欄位（PAGE / NUMPAGES）。"""
    for kind, text in (("begin", None), (None, instr), ("end", None)):
        r = p.add_run()
        _set_ea(r)
        r.font.size = Pt(size)
        r.font.color.rgb = _rgb("muted")
        if kind:
            fld = OxmlElement("w:fldChar")
            fld.set(qn("w:fldCharType"), kind)
            r._r.append(fld)
        else:
            it = OxmlElement("w:instrText")
            it.set(qn("xml:space"), "preserve")
            it.text = f" {text} "
            r._r.append(it)


# ── 文件骨架 ────────────────────────────────────────────────────────────────
def _new_doc():
    doc = Document()
    for s in doc.sections:
        s.top_margin = s.bottom_margin = Cm(2)
        s.left_margin = s.right_margin = Cm(2.2)
    st = doc.styles["Normal"]
    st.font.name = "Microsoft JhengHei"
    st.font.size = Pt(10.5)
    st.font.color.rgb = _rgb("text")
    st.element.rPr.rFonts.set(qn("w:eastAsia"), ZH_FONT)
    st.paragraph_format.space_after = Pt(6)
    # 標題階層：16 深藍 / 14 深藍 / 13 次藍 / 11.5 深灰
    for h, sz, colkey, before, after in (
        ("Heading 1", 16, "accent", 12, 10),
        ("Heading 2", 14, "accent", 14, 7),
        ("Heading 3", 13, "accent_soft", 13, 6),
        ("Heading 4", 11.5, "h4", 10, 5),
    ):
        try:
            s = doc.styles[h]
            s.font.name = "Microsoft JhengHei"
            s.font.size = Pt(sz)
            s.font.bold = True
            s.font.color.rgb = _rgb(colkey)
            if s.element.rPr is None:
                s.element.get_or_add_rPr()
            rf = (s.element.rPr.rFonts if s.element.rPr.rFonts is not None
                  else s.element.rPr._add_rFonts())
            rf.set(qn("w:eastAsia"), ZH_FONT)
            s.paragraph_format.space_before = Pt(before)
            s.paragraph_format.space_after = Pt(after)
            s.paragraph_format.keep_with_next = True
        except KeyError:
            pass
    return doc


def add_footer(doc, title):
    """頁尾：細頂線＋「標題 · 第 X 頁／共 Y 頁」置中。"""
    footer = doc.sections[0].footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _para_border(p, {"top": (4, THEME["rule"], 4)})
    r = p.add_run(f"{title}　·　第 ")
    _set_ea(r)
    r.font.size = Pt(8)
    r.font.color.rgb = _rgb("muted")
    _add_field(p, "PAGE")
    r = p.add_run(" 頁／共 ")
    _set_ea(r)
    r.font.size = Pt(8)
    r.font.color.rgb = _rgb("muted")
    _add_field(p, "NUMPAGES")
    r = p.add_run(" 頁")
    _set_ea(r)
    r.font.size = Pt(8)
    r.font.color.rgb = _rgb("muted")


# ── 行內語法：`code`、[連結](url)、**粗體** ─────────────────────────────────
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _emit_bold_aware(p, text, color=None, base_size=None):
    for j, part in enumerate(text.split("**")):
        if not part:
            continue
        r = p.add_run(part)
        r.bold = (j % 2 == 1)
        _set_ea(r)
        if color is not None:
            r.font.color.rgb = color
        if base_size is not None:
            r.font.size = Pt(base_size)


def add_inline(p, text, color=None, base_size=None):
    for seg in re.split(r"(`[^`]*`)", text):
        if not seg:
            continue
        if len(seg) >= 2 and seg[0] == "`" and seg[-1] == "`":
            r = p.add_run(seg[1:-1])
            _set_ea(r, MONO)
            r.font.size = Pt(9.5)
            if color is None:  # 深色表頭上不上灰底
                r.font.color.rgb = RGBColor.from_string("24292F")
                _run_shd(r, THEME["code_ink"])
            else:
                r.font.color.rgb = color
            continue
        # 連結：只留文字、上藍色底線（目標路徑對 Word 讀者無意義）
        pos = 0
        for m in _LINK_RE.finditer(seg):
            if m.start() > pos:
                _emit_bold_aware(p, seg[pos:m.start()], color, base_size)
            r = p.add_run(m.group(1).replace("**", ""))
            _set_ea(r)
            r.font.color.rgb = _rgb("link")
            r.underline = True
            if base_size is not None:
                r.font.size = Pt(base_size)
            pos = m.end()
        if pos < len(seg):
            _emit_bold_aware(p, seg[pos:], color, base_size)


# ── 區塊 ────────────────────────────────────────────────────────────────────
def _cells(line):
    parts = line.strip().split("|")
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [c.strip() for c in parts]


def _is_sep(line):
    return bool(re.match(r"^\s*\|?\s*:?-{2,}.*$", line)) and set(line.strip()) <= set("|-: ")


def add_table(doc, rows):
    t = doc.add_table(rows=len(rows), cols=max(len(r) for r in rows))
    _table_theme(t)
    for ri, row in enumerate(rows):
        for ci in range(len(t.columns)):
            cell = t.cell(ri, ci)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            _cell_margins(cell)
            cell.text = ""
            para = cell.paragraphs[0]
            para.paragraph_format.space_after = Pt(0)
            txt = row[ci] if ci < len(row) else ""
            if ri == 0:
                _cell_shd(cell, THEME["accent"])
                add_inline(para, txt, color=RGBColor.from_string("FFFFFF"), base_size=9.5)
                for run in para.runs:
                    run.font.bold = True
                    if run.font.size is None:
                        run.font.size = Pt(9.5)
            else:
                if ri % 2 == 0:  # 隔行網底（ri 含表頭列，偶數列＝第 2、4…資料列）
                    _cell_shd(cell, THEME["table_band"])
                add_inline(para, txt, base_size=9)
                for run in para.runs:
                    if run.font.size is None:
                        run.font.size = Pt(9)
    doc.add_paragraph()


def add_code(doc, lines):
    """程式碼盒：單格表格、淺底細框、等寬 9pt。"""
    t = doc.add_table(rows=1, cols=1)
    tblPr = t._tbl.tblPr
    w = OxmlElement("w:tblW")
    w.set(qn("w:w"), "5000")
    w.set(qn("w:type"), "pct")
    tblPr.append(w)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:color"), THEME["code_border"])
        borders.append(el)
    tblPr.append(borders)
    cell = t.cell(0, 0)
    _cell_shd(cell, THEME["code_bg"])
    _cell_margins(cell, top=120, bottom=120, left=160, right=160)
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    for k, ln in enumerate(lines):
        if k:
            p.add_run().add_break()
        r = p.add_run(ln if ln else " ")
        _set_ea(r, MONO)
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor.from_string("24292F")
    doc.add_paragraph()


def add_quote(doc, text):
    """引言：左側深藍邊條＋淺底＋縮排。"""
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.4)
    p.paragraph_format.space_after = Pt(2)
    _para_border(p, {"left": (18, THEME["accent"], 8)})
    _para_shd(p, THEME["quote_bg"])
    add_inline(p, text, color=RGBColor.from_string("404040"))
    return p


def add_bullet(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.7)
    p.paragraph_format.first_line_indent = Cm(-0.35)
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run("•  ")
    _set_ea(r)
    r.font.color.rgb = _rgb("accent")
    r.bold = True
    add_inline(p, text)


def add_hr(doc):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(12)
    _para_border(p, {"bottom": (6, THEME["rule"], 1)})


def add_diagram_note(doc, label="流程圖"):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.3)
    r = p.add_run(f"〔{label}：請於 GitHub 線上版檢視渲染後的圖表〕")
    _set_ea(r)
    r.italic = True
    r.font.size = Pt(9.5)
    r.font.color.rgb = RGBColor.from_string("888888")


# ── Mermaid → PNG（本機 mermaid-cli via npx；失敗回 None）─────────────────────
_MMDC_DEAD = False


def _png_size(path):
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
    except Exception:
        pass
    return None


def _render_mermaid(src, idx, tmp: Path):
    global _MMDC_DEAD
    if _MMDC_DEAD:
        return None
    mmd = tmp / f"d{idx}.mmd"
    png = tmp / f"d{idx}.png"
    mmd.write_text(src, encoding="utf-8")
    pconf = tmp / "pconf.json"
    if not pconf.exists():
        pconf.write_text('{"args":["--no-sandbox"]}', encoding="utf-8")
    cmd = (f'npx -y @mermaid-js/mermaid-cli -i "{mmd}" -o "{png}" '
           f'-b white -s 3 -p "{pconf}"')
    try:
        subprocess.run(cmd, shell=True, capture_output=True, timeout=180)
    except Exception:
        _MMDC_DEAD = True
        return None
    if not png.exists():
        if idx == 1:
            _MMDC_DEAD = True
        return None
    return png


def _add_centered_picture(doc, img_path):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    sz = _png_size(img_path)
    if sz and sz[1] > sz[0] * 1.35:
        run.add_picture(str(img_path), height=Cm(18))
    else:
        run.add_picture(str(img_path), width=Cm(15.8))


def add_diagram(doc, src, idx, tmp):
    png = _render_mermaid(src, idx, tmp)
    if not png:
        add_diagram_note(doc)
        return False
    _add_centered_picture(doc, png)
    return True


# ── 主轉換 ──────────────────────────────────────────────────────────────────
def convert(src: Path, out: Path):
    """把單一 .md 轉成 .docx（含 mermaid 渲染）。回傳 (mermaid總數, 成功渲染數)。"""
    md = Path(src).read_text(encoding="utf-8").splitlines()
    doc = _new_doc()
    tmp = Path(tempfile.mkdtemp(prefix="mmd_"))
    mermaid_n = rendered = 0
    h1_seen = 0
    doc_title = Path(src).stem
    i, n = 0, len(md)
    in_code, code_buf, code_lang = False, [], ""
    try:
        while i < n:
            line = md[i]
            if line.strip().startswith("```"):
                if in_code:
                    if code_lang == "mermaid":
                        mermaid_n += 1
                        if add_diagram(doc, "\n".join(code_buf), mermaid_n, tmp):
                            rendered += 1
                    else:
                        add_code(doc, code_buf)
                    code_buf, in_code, code_lang = [], False, ""
                else:
                    in_code = True
                    code_lang = line.strip()[3:].strip().lower()
                i += 1
                continue
            if in_code:
                code_buf.append(line)
                i += 1
                continue
            if line.strip().startswith("|") and "|" in line.strip()[1:]:
                block = []
                while i < n and md[i].strip().startswith("|"):
                    if not _is_sep(md[i]):
                        block.append(_cells(md[i]))
                    i += 1
                if block:
                    add_table(doc, block)
                continue
            mi = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", line.strip())
            if mi:
                img_path = (Path(src).resolve().parent / mi.group(2)).resolve()
                if img_path.exists():
                    _add_centered_picture(doc, img_path)
                    if mi.group(1):
                        cap = doc.add_paragraph()
                        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        r = cap.add_run(mi.group(1))
                        _set_ea(r)
                        r.italic = True
                        r.font.size = Pt(9)
                        r.font.color.rgb = _rgb("muted")
                else:
                    add_diagram_note(doc, label=f"圖：{mi.group(1) or mi.group(2)}（本機檔案未找到）")
                i += 1
                continue
            m = re.match(r"^(#{1,6})\s+(.*)$", line)
            if m:
                depth = len(m.group(1))
                if depth == 1:
                    h1_seen += 1
                    if h1_seen == 1:
                        # 首個 # ＝文件標題：22pt 深藍＋粗底線
                        doc_title = re.sub(r"[*`]", "", m.group(2)).strip()
                        p = doc.add_paragraph()
                        p.paragraph_format.space_before = Pt(6)
                        p.paragraph_format.space_after = Pt(12)
                        _para_border(p, {"bottom": (12, THEME["accent"], 6)})
                        add_inline(p, m.group(2), color=_rgb("accent"), base_size=22)
                        for run in p.runs:
                            run.bold = True
                            if run.font.size is None:
                                run.font.size = Pt(22)
                    else:
                        # 之後的每個 # 章：新頁開始＋章底線
                        h = doc.add_heading(level=1)
                        h.paragraph_format.page_break_before = True
                        _para_border(h, {"bottom": (8, THEME["accent"], 4)})
                        add_inline(h, m.group(2), color=_rgb("accent"))
                else:
                    add_inline(doc.add_heading(level=min(depth, 4)), m.group(2))
                i += 1
                continue
            if line.strip() == "---":
                add_hr(doc)
                i += 1
                continue
            if line.startswith(">"):
                add_quote(doc, line.lstrip(">").strip())
                i += 1
                continue
            mb = re.match(r"^\s*[-*]\s+(.*)$", line)
            if mb:
                add_bullet(doc, mb.group(1))
                i += 1
                continue
            if not line.strip():
                i += 1
                continue
            add_inline(doc.add_paragraph(), line)
            i += 1
        add_footer(doc, doc_title)
        doc.save(str(out))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return mermaid_n, rendered


def main():
    for src, out in JOBS:
        if not src.exists():
            print(f"跳過（來源不存在）：{src}")
            continue
        mn, rn = convert(src, out)
        tag = f"（{rn}/{mn} 圖）" if mn else ""
        if mn and rn == 0:
            tag += " ⚠️ 渲染失敗，退回文字註記"
        print(f"寫出: {out.name}  ({os.path.getsize(out)/1024:.0f} KB) {tag}")


if __name__ == "__main__":
    main()
