
# -*- coding: utf-8 -*-
"""main.tex → ACM SIG Proceedings 版式的 .docx。

大會（ICEA 2026）投稿頁所附之官方模板為 `pubform.docx`，內文首句即
「describe the formatting guidelines for ACM SIG Proceedings」。本檔依
該模板的明文規格排版，規格逐條列於 SPEC。

為什麼做 .docx 而不只做 LaTeX：本機無 LaTeX toolchain，acmart 版
（main_acm.tex）必須上 Overleaf 才編得出來；而頁數是投稿前最需要
確認的數字，Word 開起來就能數。兩條路並存，不互相取代。

⚠ 解析與排版的機器一律沿用 tex_to_docx.py，本檔只換版面：
  覆寫其模組層級常數（字級、圖寬、定位點）後呼叫同一組 emit_*。
  如此 main.tex 一改，兩個版式同步跟上，不會各自漂移。

⚠ 雙欄中要讓浮動體跨欄，Word 的作法是**前後各插一個連續分節符**，
  中間那節設成單欄。python-docx 沒有現成 API，見 span()。
"""
import os
import re
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Mm, Pt

import tex_to_docx as T                                        # noqa: E402
from refs_acm import acm_entries                            # noqa: E402
from tex_to_docx import (caption, detex, emit_figure, emit_listing,  # noqa
                         emit_table, math_runs, para, parse, rich_para,
                         rich_runs)

HERE = os.path.dirname(os.path.abspath(__file__))
TEX = os.path.join(HERE, 'main.tex')
OUT = (os.environ.get('ICEA_ACM_OUT')
       or os.path.join(HERE, 'ICEA2026_Li_et_al_ACM.docx'))

# ── 規格（pubform.docx 明文，勿憑印象改）──────────────────────
SPEC = """
紙張 US Letter 8.5x11；版心 7" x 9.25"；上 0.75" 下 1" 左右各 0.75"
雙欄各 3.33"，欄距 0.33"；內文 9pt Times Roman，左右對齊
標題 Helvetica 18pt bold；作者 12pt；單位 10pt；三者跨欄滿版
章節 Times 12pt bold 全大寫、編號、靠左，上方 6pt
二級 Times 12pt bold 首字母大寫；三級 Times 11pt italic
圖說 Times 9pt bold，圖在下、表在上；圖可跨欄最寬 7"
不得有頁首、頁尾、頁碼
"""

SERIF = 'Times New Roman'
# 模板寫 Helvetica。Windows 沒有該字型，Word 一律代換為 Arial（度量相同），
# 故直接寫 Arial，避免在別台機器上落到不可預期的代換字型。
SANS = 'Arial'

COL_W_TW = 4795          # 3.33" 欄寬（twip），僅供備查
GUTTER_TW = 475          # 0.33" 欄距（twip）

# ⚠ 每個跨欄浮動體都要前後各切一個連續分節符。Word 若塞不下就把整塊
#   推到次頁，並在原處留下大片空白——實測那是把 8 頁撐成 12 頁的主因。
#   凡是塞得進 3.33" 單欄的，一律留在文字流裡，不切分節符。
COL_IN = 3.33
# 相片、單一直方圖、單一時間序列——都不需要跨欄的 6.89
INLINE_FIGS = {'equipment', 'figH_null', 'figD_device_pipeline',
               'figE_cascade_narrow', 'figF_method_flow',
               'figB_matched_baseline'}
# ⚠ 表 2 原本跨欄。每個跨欄區塊要前後各切一個連續分節符，Word 一旦
#   塞不下就把整塊推到次頁、在原處留下大片空白——實測全篇 1.16 頁的
#   留白就來自僅存的兩個跨欄區塊。表 2 只有三欄、每格都短，收進 3.33"
#   單欄只會多折幾行，遠比留白划算。
INLINE_TABLES = {'tab:params', 'tab:rate'}


def set_cols(section, num, space=GUTTER_TW):
    """設定該節的欄數。python-docx 無此 API，直接改 w:cols。"""
    sectPr = section._sectPr
    cols = sectPr.find(qn('w:cols'))
    if cols is None:
        cols = OxmlElement('w:cols')
        sectPr.append(cols)
    cols.set(qn('w:num'), str(num))
    cols.set(qn('w:space'), str(space))
    cols.set(qn('w:equalWidth'), '1')


def span(doc, num):
    """插入連續分節符並設欄數，用來讓浮動體跨欄後再回到雙欄。"""
    sec = doc.add_section(WD_SECTION.CONTINUOUS)
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    sec.top_margin = Inches(0.75)
    sec.bottom_margin = Inches(1.0)
    sec.left_margin = sec.right_margin = Inches(0.75)
    set_cols(sec, num)
    return sec


def setup(doc):
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    sec.top_margin = Inches(0.75)
    sec.bottom_margin = Inches(1.0)
    sec.left_margin = sec.right_margin = Inches(0.75)
    set_cols(sec, 1)                      # 抬頭區單欄
    st = doc.styles['Normal']
    st.font.name = SERIF
    st.font.size = Pt(9)
    st.element.rPr.rFonts.set(qn('w:eastAsia'), SERIF)
    pf = st.paragraph_format
    pf.space_before = pf.space_after = Pt(0)
    pf.line_spacing = 1.0


def sans(p, txt, size, bold=False):
    r = p.add_run(txt)
    r.font.name = SANS
    r.font.size = Pt(size)
    r.bold = bold
    return r


def no_border(tbl):
    b = OxmlElement('w:tblBorders')
    for e in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement('w:' + e)
        el.set(qn('w:val'), 'none')
        b.append(el)
    tbl._tbl.tblPr.append(b)


def topmatter(doc, tex):
    """標題與作者跨欄滿版。模板以三欄並排三位作者，並註明
    「For more than three authors, you may have to improvise」。

    四位作者排成**一列四欄**的無框表格，與 acmart 的
    \\settopmatter{authorsperrow=4} 對齊，兩個版式外觀才一致。
    每欄 1.75"，單位名稱會折成數行——模板自己的範例每位作者也是
    「affiliation／1st line／2nd line」多行，屬正常。"""
    m = re.search(r'\\title\{(.*?)\}\s*\n\s*\\titlerunning', tex, re.S)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(10)
    sans(p, detex(m.group(1)), 18, bold=True)

    # ⚠ 系／部門那一層不可省。main_acm.tex 的 \affiliation 是有寫的，
    #   兩個輸出同屬 ACM 版式，作者欄不一致會被看出來。
    NKUST = ('Department of Computer Science and Information Engineering\n'
             'National Kaohsiung University of Science and Technology\n'
             'Kaohsiung, Taiwan')
    MIRDC = ('Opto-Electronics Technology Section\n'
             'Energy and Agile System Department\n'
             'Metal Industries Research & Development Centre\n'
             'Kaohsiung, Taiwan')
    people = [('Cheng-Yu Li', NKUST, 'lkkyb555@gmail.com'),
              ('Chun-Hao Chen', NKUST, ''),
              ('Cheng-Yuan Hung', MIRDC, ''),
              ('Yen-Jie Huang', MIRDC, '')]

    tbl = doc.add_table(rows=1, cols=4)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    no_border(tbl)
    for i, (name, aff, mail) in enumerate(people):
        cell = tbl.cell(0, i)
        cell.text = ''
        q = cell.paragraphs[0]
        q.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sans(q, name, 12)
        for line in aff.split('\n'):
            r = cell.add_paragraph()
            r.alignment = WD_ALIGN_PARAGRAPH.CENTER
            sans(r, line, 10)
        if mail:
            r = cell.add_paragraph()
            r.alignment = WD_ALIGN_PARAGRAPH.CENTER
            sans(r, mail, 12)
    para(doc, '', size=9, after=6)


def head(doc, text, size=12, bold=True, italic=False, before=4, after=1):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    r = p.add_run(text)
    r.font.name = SERIF
    r.font.size = Pt(size)
    r.bold, r.italic = bold, italic
    return p


def main():
    with open(TEX, encoding='utf-8') as fh:
        tex = fh.read()
    blocks, bib, _num = parse(tex)

    # ── 覆寫 tex_to_docx 的版心相依常數 ──────────────────────
    T.SZ_BODY = T.SZ_CAP = 9
    T.SZ_SEC = T.SZ_SUB = 12
    # 演算法改走單欄（3.33"）：虛擬碼已寫緊到最長 50 字元，
    # 7.5 pt Courier 每字 4.5 pt，50 字元約 3.0"，放得下。
    # 9 pt 需要 3.75"，會溢出欄外。
    T.SZ_ALG = 7.5
    # 圖說：ACM 明訂 9pt **bold**，且 Figure／Table 要全字拼出
    #（"please note that the word for Table and Figure are spelled out"）。
    T.CAP_BOLD = True
    T.FIG_WORD = 'Figure'
    T.FIGW = Mm(175)          # 7" = 177.8 mm，留一點餘裕
    # ⚠ 實機照片只有 1425 px 寬。175 mm 下僅 207 dpi，低於送印慣例的
    #   300 dpi；120 mm（4.72"）恰好回到 302 dpi，是這個檔案能維持
    #   清晰的最大尺寸，再大只是放大軟掉的像素。高度也由 5.17" 收到
    #   3.55"，不再佔去版心的一半。
    # figH_null 是單一直方圖：跨欄拉到 175 mm 只會顯得空洞，
    # 而且它本來就是照單欄尺寸畫的。
    # 三張都在單欄流裡，寬度一律 83 mm。先前照片留著 120 mm 的覆寫值，
    # 而 FIGW_OVERRIDE 的優先權蓋過單欄設定，結果圖比欄還寬、溢出欄外。
    # 83 mm 下相片為 1425/3.27 = 436 dpi，品質反而更好。
    T.FIGW_OVERRIDE = {'equipment': Mm(83), 'figH_null': Mm(83),
                       'figD_device_pipeline': Mm(83),
                       'figE_cascade_narrow': Mm(83),
                       'figF_method_flow': Mm(83),
                       'figB_matched_baseline': Mm(83)}
    T.COLW = 84.6             # 單欄 3.33"，公式編號靠右用

    doc = Document()
    setup(doc)
    topmatter(doc, tex)
    span(doc, 2)                            # 之後全部雙欄

    # ── 摘要、CCS、關鍵字（在雙欄流內，同模板第 1 頁）──────
    abst = re.search(r'\\begin\{abstract\}(.*?)\\keywords', tex, re.S)
    kw = re.search(r'\\keywords\{(.*?)\}', tex, re.S)
    head(doc, 'ABSTRACT', before=0)
    rich_para(doc, detex(abst.group(1)) if abst else '',
              align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=3)

    head(doc, 'CCS Concepts')
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    for line in ['\u2022 Information systems \u2192 Data mining',
                 '\u2022 Computing methodologies \u2192 Model verification '
                 'and validation',
                 '\u2022 Mathematics of computing \u2192 Time series '
                 'analysis',
                 '\u2022 Applied computing \u2192 Physical sciences and '
                 'engineering']:
        r = p.add_run(line + '  ')
        r.font.name = SERIF
        r.font.size = Pt(9)
        r.bold = True

    head(doc, 'Keywords')
    # 模板明載「separated by semicolons」。
    # ⚠ 必須**先切 \and 再 detex**：detex 會把未知指令整個刪掉，
    #   先 detex 的話 \and 連同分隔資訊一起消失，只剩空白。
    if kw:
        parts = [detex(x).strip()
                 for x in re.split(r'\\and\b', kw.group(1)) if x.strip()]
        rich_para(doc, '; '.join(parts),
                  align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=3)

    # ── 正文 ────────────────────────────────────────────────
    nsec = nsub = nfig = ntab = nlst = neq = 0
    for b in blocks:
        kind = b[0]
        if kind == 'sec':
            nsec += 1
            nsub = 0
            head(doc, f'{nsec}. {detex(b[1]).upper()}', before=4)
        elif kind == 'sub':
            nsub += 1
            head(doc, f'{nsec}.{nsub} {b[1]}', before=4)
        elif kind == 'run':
            p = para(doc, b[1] + '  ', size=9, bold=True, before=4)
            rich_runs(p, b[2], 9)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        elif kind == 'p':
            rich_para(doc, b[1], align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=3)
        elif kind == 'li':
            rich_para(doc, '\u2022  ' + b[1],
                      align=WD_ALIGN_PARAGRAPH.JUSTIFY, indent=5, after=3)
        elif kind in ('eq', 'equation'):
            neq += 1
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.space_before = pf.space_after = Pt(4)
            pf.tab_stops.add_tab_stop(Mm(T.COLW / 2),
                                      WD_TAB_ALIGNMENT.CENTER)
            pf.tab_stops.add_tab_stop(Mm(T.COLW), WD_TAB_ALIGNMENT.RIGHT)
            p.add_run('\t')
            if kind == 'eq':
                r = p.add_run(b[1])
                r.font.name = SERIF
                r.font.size = Pt(9)
                r.italic = True
            else:
                body = re.sub(r'\\label\{[^}]*\}', '', b[1])
                body = re.sub(r'\s+', ' ', body).strip().rstrip(',').strip()
                math_runs(p, body, 9)
            r2 = p.add_run(f'\t({neq})')
            r2.font.name = SERIF
            r2.font.size = Pt(9)
        elif kind == 'figure':
            m = re.search(r'\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}',
                          b[1])
            stem = os.path.splitext(m.group(1))[0] if m else ''
            # 虛擬碼已寫緊到最長 50 字元；7.5 pt Courier 下為 3.0"，
            # 塞得進 3.33" 單欄。三段演算法因此不必再跨欄。
            inline = stem in INLINE_FIGS or '\\begin{verbatim}' in b[1]
            if inline:
                # 單欄：直接排進文字流，不切分節符，也就沒有留白
                T.FIGW = Mm(COL_IN * 25.4 - 2)
            else:
                span(doc, 1)
            if emit_listing(doc, b[1], nlst + 1):
                nlst += 1
            else:
                nfig += 1
                emit_figure(doc, b[1], nfig)
            if inline:
                T.FIGW = Mm(175)
            else:
                span(doc, 2)
        elif kind == 'table':
            m = re.search(r'\\label\{([^}]*)\}', b[1])
            inline = (m.group(1) if m else '') in INLINE_TABLES
            if not inline:
                span(doc, 1)
            ntab += 1
            emit_table(doc, b[1], ntab)
            if not inline:
                span(doc, 2)

    # ── 參考文獻：ACM Reference Format ─────────────────────
    # 由 refs.bib 的欄位重建（見 refs_acm.py），但**鍵序沿用
    # thebibliography**——內文的 [n] 是照那個順序編的。
    # 模板 §3.5：references 一節為 9pt、ragged right（不左右對齊）。
    head(doc, f'{nsec + 1}. REFERENCES', before=4)
    entries, missing = acm_entries([k for k, _ in bib])
    for i, (_key, segs) in enumerate(entries, 1):
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_after = Pt(0)   # 21 筆共省 42pt
        pf.left_indent = Mm(7)
        pf.first_line_indent = Mm(-7)
        r = p.add_run(f'[{i}]  ')
        r.font.name = SERIF
        r.font.size = Pt(9)
        for txt, ital in segs:
            # refs_acm 把 DOI 的網址切成獨立片段，這裡排成可點擊的連結。
            if txt.startswith('http'):
                T.add_hyperlink(p, txt, txt, size=9, name=SERIF)
                continue
            r = p.add_run(txt)
            r.font.name = SERIF
            r.font.size = Pt(9)
            r.italic = ital
    if missing:
        print('     ⚠ refs.bib 缺這些鍵：%s' % ', '.join(missing))

    doc.save(OUT)
    print(f'   \u2713 {os.path.basename(OUT)}')
    print(f'     節 {nsec}   圖 {nfig}   表 {ntab}   程式列表 {nlst}   '
          f'公式 {neq}   參考文獻 {len(bib)}')
    print('     ⚠ 頁數請在 Word 實測；上限 10 頁含表圖與參考文獻。')
    print('     ⚠ 第一頁左欄底部需留 1.5" 版權區，須人工調整。')


if __name__ == '__main__':
    print('══ main.tex → ACM .docx ══\n')
    main()
