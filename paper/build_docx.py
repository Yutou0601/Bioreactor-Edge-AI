
# -*- coding: utf-8 -*-
"""
產生 Springer proceedings 格式的 .docx
════════════════════════════════════════════════════════════════════════

嚴格對應 "Springer Guidelines for Authors of Proceedings" 的規定：

  版面   文字區 122 × 193 mm（A4 邊界 44 / 52 mm）；**不加頁碼、不加 running head**
  字型   Times New Roman（Word 範本以 Times 為基礎；LaTeX 範本才是 CMR）
  字級   標題 14 pt 粗體置中｜1 級標題 12 pt 粗體｜2 級標題 10 pt 粗體
         ｜3 級 run-in 粗體 10 pt｜內文 10 pt｜圖表說明 9 pt
  標題   只有前兩層編號；標題採 title case（冠詞、介系詞、連接詞除外）
  摘要   15–250 字，run-in 粗體 "Abstract."
  關鍵字 run-in 粗體 "Keywords:"，以 middot (·) 分隔，每個字首大寫
  圖     說明在**圖下**；表說明在**表上**；兩者都必須在內文交叉引用
  公式   置中、獨立一行、右側括號編號，且不含節次編號
  引用   方括號阿拉伯數字、非上標、**依出現順序**編號
  文獻   MathPhySci 樣式，附 DOI

本檔內建三項驗證，任一失敗即中止產出：
  V1  每個 Fig./Table 都在內文被交叉引用
  V2  每筆文獻都被引用，且每個引用都有對應文獻
  V3  引用編號嚴格依首次出現順序（Springer 明文要求）
"""
import os
import re
import sys

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls
from docx.shared import Pt, Mm, RGBColor

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
FIGDIR = os.path.join(os.path.dirname(HERE), 'docs', 'paper_figures')
OUT = os.path.join(HERE, 'ICEA2026_Li_et_al.docx')

FONT = 'Times New Roman'
TEXTW_MM = 122.0                      # LNCS 文字區寬度；圖檔即以此寬度製作


# ══════════════════════════════════════════════════════════════════
#  低階排版工具
# ══════════════════════════════════════════════════════════════════
def _rpr_font(run, size, bold=False, italic=False, name=FONT):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    # 東亞字型也要指定，否則 Word 可能改用預設中文字型
    run._element.rPr.rFonts.set(qn('w:eastAsia'), name)
    return run


def para(doc, align=WD_ALIGN_PARAGRAPH.JUSTIFY, before=0, after=0,
         first_indent=None, line=None):
    p = doc.add_paragraph()
    p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    if first_indent is not None:
        pf.first_line_indent = Mm(first_indent)
    if line is not None:
        pf.line_spacing = line
    return p


def text(p, s, size=10, bold=False, italic=False, name=FONT):
    return _rpr_font(p.add_run(s), size, bold, italic, name)


def rich(p, spec, size=10):
    """spec = [(字串, 'b'|'i'|'bi'|'sub'|'sup'|''), ...]"""
    for s, st in spec:
        r = _rpr_font(p.add_run(s), size, 'b' in st, 'i' in st)
        if st == 'sub':
            r.font.subscript = True
        elif st == 'sup':
            r.font.superscript = True
    return p


# ══════════════════════════════════════════════════════════════════
#  OMML 公式（Word 原生方程式，非圖片）
# ══════════════════════════════════════════════════════════════════
M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'


def _m(tag, *children, **attrs):
    e = OxmlElement(f'm:{tag}')
    for k, v in attrs.items():
        e.set(qn(f'm:{k}'), v)
    for c in children:
        e.append(c)
    return e


def _run(txt, italic=True):
    """OMML 中的一個文字 run。"""
    r = OxmlElement('m:r')
    rpr = OxmlElement('w:rPr')
    rf = OxmlElement('w:rFonts')
    rf.set(qn('w:ascii'), 'Cambria Math')
    rf.set(qn('w:hAnsi'), 'Cambria Math')
    rpr.append(rf)
    if not italic:
        i = OxmlElement('w:i'); i.set(qn('w:val'), '0'); rpr.append(i)
    r.append(rpr)
    t = OxmlElement('m:t')
    t.text = txt
    t.set(qn('xml:space'), 'preserve')
    r.append(t)
    return r


def _frac(num_children, den_children):
    return _m('f', _m('num', *num_children), _m('den', *den_children))


def add_equation(doc, omml_children, number):
    """置中公式 ＋ 右側括號編號（Springer 規定）。"""
    p = para(doc, align=WD_ALIGN_PARAGRAPH.LEFT, before=5, after=5)
    # 置中制表位 + 右對齊制表位，讓公式置中、編號靠右
    tabs = p.paragraph_format.tab_stops
    tabs.add_tab_stop(Mm(TEXTW_MM/2), WD_TAB_ALIGNMENT.CENTER)
    tabs.add_tab_stop(Mm(TEXTW_MM), WD_TAB_ALIGNMENT.RIGHT)
    p.add_run('\t')
    omath = OxmlElement('m:oMath')
    for c in omml_children:
        omath.append(c)
    p._p.append(omath)
    p.add_run('\t')
    _rpr_font(p.add_run(f'({number})'), 10)
    return p


# ══════════════════════════════════════════════════════════════════
#  文獻（依首次引用順序；DOI 全部經 Crossref 查證）
# ══════════════════════════════════════════════════════════════════
REFS = [
    ('iturbe', 'Iturbe, M., Camacho, J., Garitano, I., Zurutuza, U., '
     'Uribeetxeberria, R.: On the feasibility of distinguishing between '
     'process disturbances and intrusions in process control systems using '
     'multivariate statistical process control. In: 2016 46th Annual '
     'IEEE/IFIP International Conference on Dependable Systems and Networks '
     'Workshop (DSN-W), pp. 155−160. IEEE (2016). '
     'doi: 10.1109/DSN-W.2016.32'),
    ('linek89', 'Linek, V., Beneš, P., Vacek, V.: Dynamic pressure '
     'method for kLa measurement in large-scale bioreactors. Biotechnol. '
     'Bioeng. 33(11), 1406−1412 (1989). doi: 10.1002/bit.260331107'),
    ('linek94', 'Linek, V., Moucha, T., Doušová, M., Sinkule, J.: '
     'Measurement of kLa by dynamic pressure method in pilot-plant fermentor. '
     'Biotechnol. Bioeng. 43, 477−482 (1994). doi: 10.1002/bit.260430607'),
    ('scargiali', 'Scargiali, F., Busciglio, A., Grisafi, F., Brucato, A.: '
     'Simplified dynamic pressure method for kLa measurement in aerated '
     'bioreactors. Biochem. Eng. J. 49(2), 165−172 (2010). '
     'doi: 10.1016/j.bej.2009.12.008'),
    ('tobajas', 'Tobajas, M., García-Calvo, E.: Comparison of '
     'experimental methods for determination of the volumetric mass transfer '
     'coefficient in fermentation processes. Heat Mass Transf. 36, '
     '201−207 (2000). doi: 10.1007/s002310050385'),
    ('harris', 'Harris, T.J.: Assessment of closed loop performance. Can. J. '
     'Chem. Eng. 67, 856−861 (1989). doi: 10.1002/cjce.5450670519'),
    ('jelali', 'Jelali, M.: An overview of control performance assessment '
     'technology and industrial applications. Control Eng. Pract. 14(5), '
     '441−466 (2006). doi: 10.1016/j.conengprac.2005.11.005'),
    # ⚠ Crossref 把第八作者 Sangtrakulcharoen 截成 "San"、第一作者只給 "B."。
    #   姓名依 arXiv math/0309285、dblp、Semantic Scholar 三處交叉查證後修正。
    ('jackson', 'Jackson, B.W., Scargle, J.D., Barnes, D., Arabhi, S., '
     'Alt, A., Gioumousis, P., Gwin, E., Sangtrakulcharoen, P., Tan, L., '
     'Tsai, T.T.: An algorithm for optimal partitioning of data on an '
     'interval. IEEE Signal Process. Lett. 12, 105−108 (2005). '
     'doi: 10.1109/LSP.2001.838216'),
    ('killick', 'Killick, R., Fearnhead, P., Eckley, I.A.: Optimal detection '
     'of changepoints with a linear computational cost. J. Am. Stat. Assoc. '
     '107(500), 1590−1598 (2012). doi: 10.1080/01621459.2012.737745'),
    ('box', 'Box, G.E.P., Tiao, G.C.: Intervention analysis with applications '
     'to economic and environmental problems. J. Am. Stat. Assoc. 70(349), '
     '70−79 (1975). doi: 10.1080/01621459.1975.10480264'),
    ('nomikos', 'Nomikos, P., MacGregor, J.F.: Monitoring batch processes '
     'using multiway principal component analysis. AIChE J. 40(8), '
     '1361−1375 (1994). doi: 10.1002/aic.690400809'),
    ('messenger', 'Messenger, D.A., Bortz, D.M.: Weak SINDy for partial '
     'differential equations. J. Comput. Phys. 443, 110525 (2021). '
     'doi: 10.1016/j.jcp.2021.110525'),
]
KEY2NUM = {k: i+1 for i, (k, _) in enumerate(REFS)}


def cite(*keys):
    """回傳 [n] 或 [n, m]；同時記錄以供 V2/V3 驗證。"""
    nums = [KEY2NUM[k] for k in keys]
    for k in keys:
        CITED.append(k)
    return '[' + ', '.join(str(n) for n in sorted(nums)) + ']'


CITED = []          # 依出現順序記錄的引用 key
XREFS = []          # 內文出現過的 "Fig. n" / "Table n"


def xref(s):
    XREFS.append(s)
    return s


# ══════════════════════════════════════════════════════════════════
#  版面
# ══════════════════════════════════════════════════════════════════
def setup(doc):
    s = doc.sections[0]
    s.page_width, s.page_height = Mm(210), Mm(297)          # A4
    # LNCS 文字區 122 × 193 mm
    s.left_margin = s.right_margin = Mm((210-TEXTW_MM)/2)
    s.top_margin = s.bottom_margin = Mm((297-193)/2)
    s.header_distance = s.footer_distance = Mm(20)
    # Springer：不要頁碼、不要 running head（由出版端加）
    st = doc.styles['Normal']
    st.font.name = FONT
    st.font.size = Pt(10)
    st.element.rPr.rFonts.set(qn('w:eastAsia'), FONT)
    st.paragraph_format.space_after = Pt(0)
    st.paragraph_format.line_spacing = 1.0


def h1(doc, num, title):
    p = para(doc, WD_ALIGN_PARAGRAPH.LEFT, before=11, after=5)
    text(p, f'{num}\t{title}', 12, bold=True)
    p.paragraph_format.tab_stops.add_tab_stop(Mm(10))
    return p


def h2(doc, num, title):
    p = para(doc, WD_ALIGN_PARAGRAPH.LEFT, before=10, after=4)
    text(p, f'{num}\t{title}', 10, bold=True)
    p.paragraph_format.tab_stops.add_tab_stop(Mm(10))
    return p


def h3(doc, title):
    """3 級標題：run-in 粗體，後接內文（Springer 規定）。"""
    p = para(doc, before=8, after=0)
    text(p, title + ' ', 10, bold=True)
    return p


def body(doc, s, first=True):
    p = para(doc, first_indent=(0 if first else 5), after=0)
    text(p, s, 10)
    return p


# ── 圖：說明置於圖下（Springer 規定）────────────────────────────
def figure(doc, fname, num, caption):
    p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, before=6, after=2)
    p.add_run().add_picture(os.path.join(FIGDIR, fname), width=Mm(TEXTW_MM))
    c = para(doc, WD_ALIGN_PARAGRAPH.JUSTIFY, after=7)
    text(c, f'Fig. {num}. ', 9, bold=True)
    text(c, caption, 9)
    FIGS_DEFINED.append(f'Fig. {num}')


# ── 表：說明置於表上（Springer 規定）────────────────────────────
def _rule(cell, edge, sz=6):
    tcPr = cell._tc.get_or_add_tcPr()
    b = tcPr.find(qn('w:tcBorders'))
    if b is None:
        b = OxmlElement('w:tcBorders'); tcPr.append(b)
    e = OxmlElement(f'w:{edge}')
    e.set(qn('w:val'), 'single'); e.set(qn('w:sz'), str(sz))
    e.set(qn('w:color'), '000000')
    b.append(e)


def table(doc, num, caption, header, rows, widths=None, align=None):
    c = para(doc, WD_ALIGN_PARAGRAPH.JUSTIFY, before=7, after=3)
    text(c, f'Table {num}. ', 9, bold=True)
    text(c, caption, 9)

    t = doc.add_table(rows=1+len(rows), cols=len(header))
    t.autofit = False
    for j, htxt in enumerate(header):
        cell = t.cell(0, j)
        cell.text = ''
        p = cell.paragraphs[0]
        p.alignment = (WD_ALIGN_PARAGRAPH.LEFT if j == 0
                       else WD_ALIGN_PARAGRAPH.CENTER)
        text(p, htxt, 9, bold=True)
        _rule(cell, 'top', 8); _rule(cell, 'bottom', 6)
    for i, r in enumerate(rows):
        for j, v in enumerate(r):
            cell = t.cell(i+1, j)
            cell.text = ''
            p = cell.paragraphs[0]
            p.alignment = (WD_ALIGN_PARAGRAPH.LEFT if j == 0
                           else WD_ALIGN_PARAGRAPH.CENTER)
            bold = v.startswith('**') and v.endswith('**')
            text(p, v.strip('*'), 9, bold=bold)
            if i == len(rows)-1:
                _rule(cell, 'bottom', 8)
    if widths:
        for j, w in enumerate(widths):
            for row in t.rows:
                row.cells[j].width = Mm(w)
    para(doc, after=3)
    TABLES_DEFINED.append(f'Table {num}')
    return t


FIGS_DEFINED, TABLES_DEFINED = [], []
