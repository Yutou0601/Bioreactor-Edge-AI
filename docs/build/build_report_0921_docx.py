# -*- coding: utf-8 -*-
"""把 2026-09-21 分析報告轉成 Word（含全部分析圖）。

樣式沿用既有日報／週報：標楷體 + Times New Roman、行高 16pt。
Markdown 來源為單一事實來源，本檔只負責排版；改內容請改 .md。

  python docs/build/build_report_0921_docx.py
"""
import os
import re
import sys

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, 'docs', 'reports',
                   '分析報告_2026-09-21_氫氣流失與壓降歸因.md')
OUT = os.path.join(REPO, 'docs', 'reports',
                   '分析報告_2026-09-21_氫氣流失與壓降歸因_李承育.docx')

CN, EN = '標楷體', 'Times New Roman'
FIGW = Mm(160)              # 直式 A4 扣邊界後的可用寬度
INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x55, 0x55, 0x55)
ACCENT = RGBColor(0xB0, 0x30, 0x30)

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def style_run(r, size=11, bold=False, color=INK):
    r.font.size = Pt(size)
    r.bold = bold
    r.font.name = EN
    r.font.color.rgb = color
    r._element.rPr.rFonts.set(qn('w:eastAsia'), CN)


# 行內標記：**粗體**、`等寬`
TOKEN = re.compile(r'(\*\*.+?\*\*|`.+?`)')


def add_rich(p, text, size=11, base_bold=False, color=INK):
    """處理行內的 **粗體** 與 `程式碼`。其餘原樣輸出。"""
    for part in TOKEN.split(text):
        if not part:
            continue
        if part.startswith('**') and part.endswith('**'):
            style_run(p.add_run(part[2:-2]), size, True, color)
        elif part.startswith('`') and part.endswith('`'):
            r = p.add_run(part[1:-1])
            style_run(r, size - 0.5, False, MUTED)
            r.font.name = 'Consolas'
        else:
            style_run(p.add_run(part), size, base_bold, color)


def para(doc, text='', size=11, bold=False, before=0, after=3, indent=0,
         align=None, color=INK):
    p = doc.add_paragraph()
    if text:
        add_rich(p, text, size, bold, color)
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.left_indent = Mm(indent)
    pf.line_spacing = Pt(16)
    if align is not None:
        p.alignment = align
    return p


def borders(tbl, sz=4):
    el = tbl._tbl.tblPr
    b = OxmlElement('w:tblBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        e = OxmlElement('w:' + edge)
        e.set(qn('w:val'), 'single')
        e.set(qn('w:sz'), str(sz))
        e.set(qn('w:color'), 'BFBFBF')
        b.append(e)
    el.append(b)


def shade(cell, hexcolor):
    el = OxmlElement('w:shd')
    el.set(qn('w:val'), 'clear')
    el.set(qn('w:fill'), hexcolor)
    cell._tc.get_or_add_tcPr().append(el)


def split_row(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def add_table(doc, rows, fs=9.5):
    """rows[0] 為表頭；含 --- 的分隔列已在呼叫端移除。"""
    ncol = max(len(r) for r in rows)
    tbl = doc.add_table(rows=len(rows), cols=ncol)
    borders(tbl)
    for i, row in enumerate(rows):
        for j in range(ncol):
            cell = tbl.cell(i, j)
            cell.paragraphs[0].paragraph_format.space_after = Pt(0)
            cell.paragraphs[0].paragraph_format.line_spacing = Pt(13)
            txt = row[j] if j < len(row) else ''
            add_rich(cell.paragraphs[0], txt, fs, i == 0)
            if i == 0:
                shade(cell, 'EFEFEF')
    doc.add_paragraph().paragraph_format.space_after = Pt(4)
    return tbl


def add_figure(doc, path, caption):
    if not os.path.isfile(path):
        raise SystemExit('找不到圖檔：%s\n請先執行對應的繪圖程式。' % path)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(path, width=FIGW)
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_rich(c, caption, 9, False, MUTED)
    c.paragraph_format.space_after = Pt(10)
    c.paragraph_format.line_spacing = Pt(13)


def main():
    text = open(SRC, encoding='utf-8').read().split('\n')
    doc = Document()
    s = doc.sections[0]
    s.page_width, s.page_height = Mm(210), Mm(297)
    s.left_margin = s.right_margin = Mm(25)
    s.top_margin = s.bottom_margin = Mm(20)

    i, n_fig, n_tbl = 0, 0, 0
    while i < len(text):
        ln = text[i].rstrip()

        # 水平線 -> 分節（跳過表格分隔用的 ---|---）
        if ln.strip() == '---':
            i += 1
            continue

        # 圖片
        m = re.match(r'^!\[.*?\]\((.+?)\)\s*$', ln)
        if m:
            rel = m.group(1)
            path = os.path.normpath(os.path.join(os.path.dirname(SRC), rel))
            cap = ''
            j = i + 1
            while j < len(text) and not text[j].strip():
                j += 1
            if j < len(text) and text[j].strip().startswith('*') \
                    and not text[j].strip().startswith('**'):
                cap = text[j].strip().strip('*')
                i = j
            add_figure(doc, path, cap)
            n_fig += 1
            i += 1
            continue

        # 標題
        if ln.startswith('#'):
            lvl = len(ln) - len(ln.lstrip('#'))
            t = ln.lstrip('#').strip()
            sizes = {1: 16, 2: 13.5, 3: 12}
            para(doc, t, sizes.get(lvl, 11.5), True,
                 before=(0 if lvl == 1 else 14), after=6,
                 align=WD_ALIGN_PARAGRAPH.CENTER if lvl == 1 else None,
                 color=INK if lvl <= 2 else ACCENT)
            i += 1
            continue

        # 表格
        if ln.startswith('|'):
            rows = []
            while i < len(text) and text[i].strip().startswith('|'):
                r = split_row(text[i])
                if not all(set(c) <= set('-: ') for c in r if c):
                    rows.append(r)
                i += 1
            if rows:
                add_table(doc, rows)
                n_tbl += 1
            continue

        # 引言區塊
        if ln.startswith('>'):
            buf = []
            while i < len(text) and text[i].lstrip().startswith('>'):
                buf.append(text[i].lstrip().lstrip('>').strip())
                i += 1
            para(doc, ' '.join(x for x in buf if x), 10.5, False,
                 before=4, after=6, indent=6, color=MUTED)
            continue

        # 條列
        m = re.match(r'^(\s*)([-*]|\d+\.)\s+(.*)$', ln)
        if m:
            depth = len(m.group(1)) // 2
            bullet = '‧ ' if m.group(2) in ('-', '*') else m.group(2) + ' '
            body = m.group(3)
            # 續行（縮排且非新條列）
            i += 1
            while (i < len(text) and text[i].strip()
                   and text[i].startswith(' ')
                   and not re.match(r'^\s*([-*]|\d+\.)\s', text[i])
                   and not text[i].strip().startswith('|')):
                body += text[i].strip()
                i += 1
            para(doc, bullet + body, 11, indent=6 + depth * 6, after=2)
            continue

        # 空行
        if not ln.strip():
            i += 1
            continue

        # 一般段落：合併到下一個空行為止
        buf = [ln]
        i += 1
        while (i < len(text) and text[i].strip()
               and not text[i].startswith(('#', '|', '>', '!'))
               and not re.match(r'^\s*([-*]|\d+\.)\s', text[i])
               and text[i].strip() != '---'):
            buf.append(text[i].strip())
            i += 1
        para(doc, ''.join(buf), 11, after=5)

    doc.save(OUT)
    print('已輸出 %s' % os.path.relpath(OUT, REPO))
    print('共 %d 張圖、%d 個表格' % (n_fig, n_tbl))


if __name__ == '__main__':
    main()
