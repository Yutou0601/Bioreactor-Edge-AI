
# -*- coding: utf-8 -*-
"""週報 markdown → Word（依 2026-07-27 日報之版式）。

版式要點（自範本 PDF 量測）：
  · 抬頭表 4 欄：標題列跨欄、時間／學生同列、地點跨欄、內容與過程註記跨欄
  · 全文置於外框內（以單欄表格承載，取得四周框線）
  · 中文標楷體、西文 Times New Roman、內文 12 pt、行距固定 20 pt
  · 內文表格用三線式，標頭列加粗

⚠ 中文字型必須同時設 w:eastAsia，只設 ascii 會讓中文回退成新細明體。
"""
import os
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

# ⚠ 2026-09-10 本檔從 docs/ 搬到 docs/build/。HERE 仍然要指 docs/，
#   否則產生的文件會掉進 build/ 裡。
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, 'reports', '週報_2026-08-12_李承育.docx')
CN, EN = '標楷體', 'Times New Roman'


def style_run(r, size=12, bold=False):
    r.font.size = Pt(size)
    r.bold = bold
    r.font.name = EN
    r._element.rPr.rFonts.set(qn('w:eastAsia'), CN)


def para(container, text='', size=12, bold=False, align=None,
         before=0, after=0, indent=0, line=20):
    p = container.add_paragraph()
    if text:
        style_run(p.add_run(text), size, bold)
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.left_indent = Mm(indent)
    pf.line_spacing = Pt(line)
    if align is not None:
        p.alignment = align
    return p


def borders(tbl, sz=8):
    tblPr = tbl._tbl.tblPr
    b = OxmlElement('w:tblBorders')
    for e in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement('w:' + e)
        el.set(qn('w:val'), 'single'); el.set(qn('w:sz'), str(sz))
        el.set(qn('w:color'), '000000')
        b.append(el)
    tblPr.append(b)


def cell_text(c, text, size=12, bold=False, center=True):
    c.text = ''
    p = c.paragraphs[0]
    style_run(p.add_run(text), size, bold)
    p.paragraph_format.line_spacing = Pt(18)
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def header_table(doc, period='2026/08/06 – 2026/08/12',
                 place='金屬中心（歷史資料分析、方法驗證與論文撰寫）'):
    """報表抬頭。

    ⚠ 2026-09-11 把期間與地點改成參數（預設值＝原本寫死的值，既有的
      build_weekly.py 行為不變）。原本是寫死的，每週都要複製一份版式函式
      才能改日期——而複製品會漂移，本週已經在別處踩過一次同樣的問題。
    """
    t = doc.add_table(rows=4, cols=4)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    borders(t)
    a = t.cell(0, 0).merge(t.cell(0, 3))
    cell_text(a, '國立高雄科技大學_金屬中心_週報', 14, True)
    cell_text(t.cell(1, 0), '時間')
    cell_text(t.cell(1, 1), period)
    cell_text(t.cell(1, 2), '學生')
    cell_text(t.cell(1, 3), '李承育')
    cell_text(t.cell(2, 0), '地點')
    cell_text(t.cell(2, 1).merge(t.cell(2, 3)), place)
    cell_text(t.cell(3, 0).merge(t.cell(3, 3)), '內容與過程註記')
    for r in t.rows:
        r.cells[0].width = Mm(22)
    return t


def data_table(doc, head, rows, widths=None):
    t = doc.add_table(rows=len(rows)+1, cols=len(head))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    borders(t, 6)
    for j, h in enumerate(head):
        cell_text(t.cell(0, j), h, 11, True)
    for i, row in enumerate(rows, 1):
        for j, v in enumerate(row):
            cell_text(t.cell(i, j), v, 11, False,
                      center=(len(v) < 16))
    if widths:
        for r in t.rows:
            for j, w in enumerate(widths):
                r.cells[j].width = Mm(w)
    para(doc, '', 6)
    return t
