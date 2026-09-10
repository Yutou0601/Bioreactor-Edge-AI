
# -*- coding: utf-8 -*-
"""
main.tex → Springer 格式 .docx（含 Algorithm 欄位與**向量**圖）
════════════════════════════════════════════════════════════════════════

**為什麼是轉換而不是重打**：先前版本的 docx 內容是另外用 Python 字串寫的，
與 main.tex 是兩份獨立來源，改一邊忘另一邊就會不一致。本檔改成
**單一來源**：正文只存在於 main.tex，docx 由它產生。

Springer LNCS 規格（依 template 量測）：
  · 文字區 122 × 193 mm
  · Times New Roman；標題 14 pt、節標題 12 pt、內文 10 pt、圖說 9 pt
  · 圖說在圖**下**、表說在表**上**
  · 圖至少 800 dpi（本檔內嵌向量 SVG，另附 1200 dpi PNG 後備）

向量圖：Word 的向量格式是 EMF，本機無工具可產；改用 SVG（Word 2016+ 原生），
由 `svg_docx.add_vector_picture()` 內嵌，PNG 為後備。詳見該檔說明。
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
from docx.shared import Mm, Pt, RGBColor

from svg_docx import add_vector_picture                            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIGDIR = os.path.join(ROOT, 'docs', 'paper_figures')
TEX = os.path.join(HERE, 'main.tex')
# 檔案在 Word 開著時會 PermissionError；給一個覆寫出口，
# 這樣量頁數不必先請使用者關檔。
OUT = os.environ.get('ICEA_OUT') or os.path.join(HERE, 'ICEA2026_Li_et_al.docx')

FONT = 'Times New Roman'
SZ_TITLE, SZ_SEC, SZ_SUB, SZ_BODY, SZ_CAP = 14, 12, 10, 10, 9
# 演算法欄位專用級數。範本 §2.8 規定 program listings 用打字機字體，
# 未規定級數；圖說 9 pt 是明文規定，故兩者分開，不可共用 SZ_CAP。
# 7.5 pt：為壓進 11 頁而降半級。範本 §2.8 只規定 program listings 用
# 打字機字體，未規定級數；圖說 9 pt 是明文規定，不受影響。
SZ_ALG = 7.5

# 版心相依的兩個量，抽成模組層級好讓 acm_docx.py 覆寫：
# LNCS 單欄版心 122 mm；ACM 雙欄跨欄可到 178 mm。
FIGW = Mm(86)      # emit_figure 的預設圖寬
# 逐圖覆寫（鍵為檔名去副檔名）。相片與向量圖的合理寬度不同：
# 向量圖放多大都清晰，相片受像素數限制，超過就是放大軟掉的像素。
FIGW_OVERRIDE = {}
CAP_BOLD = False   # Springer 圖說不粗體；ACM 明訂 9pt bold
FIG_WORD = 'Fig.'  # ACM 要求 Figure／Table 全字拼出
COLW = 122.0       # 公式編號靠右的定位點（mm）

# ── 巨集與符號展開 ──────────────────────────────────────────────
MACROS = [
    # ⚠ 巨集在正文有**帶 `{}` 與不帶** 兩種寫法（`\rb{}` 與 `\rb\,t`）。
    #   只比對帶 `{}` 的版本，不帶的就會被後面「刪除未知指令」那條吃掉——
    #   摘要裡的 `P(t)=P_eq+Ae^{-kt}-\rb t` 就這樣掉了 r_b 變成「− t」。
    #   `(?:\{\})?` 讓兩種寫法都吃得到。
    #   下標一律輸出 ⟦base|sub⟧ 標記，交給 rich_para() 排成 **Word 真下標**；
    #   不要用 Unicode 近似字元——**Unicode 沒有下標 b**，先前輸出的 `ᵇ`
    #   其實是 U+1D47「上標 b」，與 Eq. (1) 的真下標長得完全不同。
    # ⚠ 單位不可用 Unicode `²`。稽核發現全文有**兩種排法**並存：9 個 run
    #   是 Unicode ²、5 個是 Word 真上標（來自摘要手寫的 \textsuperscript
    #   與公式的 ^{2}）。兩者字級與基線都不同，並排看得出來。一律輸出
    #   ⟦m^2⟧ 標記，交給 rich_runs() 排成真上標。
    #   MACROS 只展開成 LaTeX 形式 `cm^{2}`，**不可自己包 ⟦⟧**——後面的
    #   _sup() 會再包一次，結果是 ⟦⟦m²⟧⟧。包標記的地方只能有一處。
    (r'\\ratu(?:\{\})?', 'kg/cm^{2}/hr'),
    (r'\\pu(?:\{\})?', 'kg/cm^{2}'),
    (r'\\invh(?:\{\})?', '/hr'),
    (r'\\rbh(?:\{\})?', '\u27e6r\u0302|b\u27e7'),
    (r'\\rb(?:\{\})?', '\u27e6r|b\u27e7'),
    (r'\\kh(?:\{\})?', 'k\u0302'),
    (r'P_\{eq\}', '\u27e6P|eq\u27e7'), (r'P_\{?eq\}?', '\u27e6P|eq\u27e7'),
    (r'\\ce\{H2\}', 'H\u2082'), (r'\\ce\{CO2\}', 'CO\u2082'),
    (r'\\ce\{CH4\}', 'CH\u2084'), (r'\\ce\{H2O\}', 'H\u2082O'),
    (r'\\times', '\u00d7'), (r'\\pm', '\u00b1'), (r'\\approx', '\u2248'),
    (r'\\rightarrow', '\u2192'), (r'\\Rightarrow', '\u21d2'),
    (r'\\le\b', '\u2264'), (r'\\ge\b', '\u2265'), (r'\\neq', '\u2260'),
    (r'\\quad', '  '), (r'\\;', ' '), (r'\\,', '\u2009'),
    # LaTeX \u7684\u8df3\u812b\u7a7a\u683c `\ `\uff08\u7528\u5728 "syst.\ " \u9019\u7a2e\u975e\u53e5\u672b\u7e2e\u5beb\u5f8c\uff09\u3002
    # \u6c92\u6709\u9019\u689d\u5c31\u6703\u7559\u4e0b\u4e00\u500b\u88f8\u53cd\u659c\u7dda\u5728\u6210\u54c1\u88e1\u3002
    (r'\\ ', ' '),
    (r'\\emph\{([^{}]*)\}', r'\1'), (r'\\textbf\{([^{}]*)\}', r'\1'),
    (r'\\mathrm\{([^{}]*)\}', r'\1'), (r'\\text\{([^{}]*)\}', r'\1'),
    # ⚠ 取代字串不可用 raw string——r'\1\u0302' 裡的 \u 會被 re 當成
    #   轉義序列而報 bad escape。要用一般字串讓 \u0302 先變成真正的字元。
    (r'\\hat\{([^{}]*)\}', '\\1\u0302'),
    # ⚠ 2026-08-24：以下七個原本全部缺席，被「刪除未知指令」那條吃掉且
    #   不報錯，成品在數學上是錯的：
    #     \dot{P}=…      印成 P=…        微分方程看起來像代數式
    #     r_b \equiv 0   印成 r_b 0      「恆等於零」整個消失
    #     \lVert…\rVert  印成 …          範數沒有豎線
    #     \arg\min_{k\in K}  印成 argminₖ K   集合關係消失
    #   合成字元用組合附加符號 U+0307（點）接在字母後面。
    (r'\\dot\{([^{}]*)\}', '\\1\u0307'),
    (r'\\lVert\s*', '\u2016'), (r'\\rVert', '\u2016'),
    (r'\\lvert', '|'), (r'\\rvert', '|'),
    (r'\\equiv', '\u2261'), (r'\\in\b\s*', '\u2208'),
    # \sqrt{x} → √(x)。括號不可省：√kD 會被讀成「根號 k 再乘 D」。
    (r'\\sqrt\{([^{}]*)\}', '\u221a(\\1)'),
    (r'\\notin', '\u2209'), (r'\\mathbf\{([^{}]*)\}', r'\1'),
    (r'\\arg\\min', 'argmin'), (r'\\exists', '\u2203'),
    (r'\\varepsilon', '\u03b5'), (r'\\varphi', '\u03c6'),
    (r'\\sigma', '\u03c3'), (r'\\rho', '\u03c1'), (r'\\gets', '\u2190'),
    # \u26a0 \u5e0c\u81d8\u5b57\u6bcd\u7f3a\u4e00\u500b\u5c31\u6703\u88ab\u300c\u522a\u9664\u672a\u77e5\u6307\u4ee4\u300d\u90a3\u689d**\u6574\u500b\u5403\u6389**\uff0c\u800c\u4e14\u4e0d\u5831\u932f\u3002
    #   \u00a75.2 \u7684 `\beta` \u5c31\u9019\u6a23\u6d88\u5931\uff0c`$\beta=0.30$` \u5370\u6210\u300c=0.30\u300d\u3002
    #   \u51e1\u662f\u6b63\u6587\u7528\u5f97\u5230\u7684\u90fd\u8981\u5217\u9032\u4f86\u3002
    (r'\\chi', '\u03c7'),
    (r'\\alpha', '\u03b1'), (r'\\beta', '\u03b2'), (r'\\gamma', '\u03b3'),
    (r'\\delta', '\u03b4'), (r'\\Delta', '\u0394'), (r'\\lambda', '\u03bb'),
    (r'\\mu\b', '\u03bc'), (r'\\tau\b', '\u03c4'), (r'\\theta', '\u03b8'),
    (r'\\eta\b', '\u03b7'), (r'\\phi\b', '\u03d5'), (r'\\omega', '\u03c9'),
    (r'\\mathcal\{F\}', 'F'), (r'\\max\b', 'max'), (r'\\min\b', 'min'),
    (r'\\bigl', ''), (r'\\bigr', ''), (r'\\big', ''),
    (r'\\left', ''), (r'\\right', ''), (r'\\!', ''),
    (r'\\%', '%'), (r'\\&', '&'), (r'\\_', '_'),
    # ⚠ LaTeX 的跳脫大括號 `\{` `\}`。先前沒處理：後面「剝大括號」那條
    #   把 `{`/`}` 拿掉，只剩下反斜線留在成品裡（Listing 3 圖說踩到）。
    (r'\\\{', '{'), (r'\\\}', '}'),
    (r"\\'\{e\}", '\u00e9'), (r"\\'\{i\}", '\u00ed'),
    (r'\\"\{u\}', '\u00fc'),
    # ⚠ 土耳其姓氏 Yörüklü / Köroğlu 需要 ö 與 ğ。先前只有 ü，於是 \"{o}
    #   的反斜線原封不動留在成品的參考文獻裡，\u{g} 則整個被吃掉。
    (r'\\"\{o\}', '\u00f6'), (r'\\u\{g\}', '\u011f'),
    (r'\\"\{O\}', '\u00d6'), (r'\\c\{c\}', '\u00e7'),
    (r'\\v\{s\}', '\u0161'),
    (r'\\v\{c\}', '\u010d'), (r'\\v\{e\}', '\u011b'),
    (r'\\~\{n\}', '\u00f1'), (r'\\^\{o\}', '\u00f4'),
]
# \u26a0 \u53ea\u653e**\u771f\u7684\u5b58\u5728\u4e0b\u6a19\u5f62\u5f0f**\u7684\u5b57\u5143\u3002\u539f\u672c\u628a b \u5c0d\u5230 U+1D47 '\u1d47'\u2014\u2014\u90a3\u662f
#   **\u4e0a\u6a19** b\uff0c\u5167\u6587\u65bc\u662f\u5370\u51fa\u300cr\u1d47\u300d\u800c Eq.(1) \u662f\u771f\u4e0b\u6a19\uff0c\u5169\u8655\u9577\u5f97\u5b8c\u5168\u4e0d\u540c\u3002
#   Unicode \u6c92\u6709\u4e0b\u6a19 b/q/d/\u2026\uff0c\u51e1\u662f\u9019\u985e\u90fd\u6539\u8d70 \u27e6base|sub\u27e7 \u6a19\u8a18\u8207\u771f\u4e0b\u6a19\u3002
SUBOK = set('0123456789+-=()aeoxkLmn')
SUBSCR = str.maketrans('0123456789+-=()aeoxkLmn',
                       '\u2080\u2081\u2082\u2083\u2084\u2085\u2086\u2087'
                       '\u2088\u2089\u208a\u208b\u208c\u208d\u208e'
                       '\u2090\u2091\u2092\u2093\u2096\u2097'
                       '\u2098\u2099')
# \u26a0 \u5148\u524d\u53ea\u8655\u7406 ^2\uff0c\u5176\u9918\u4e0a\u6a19\u4e00\u5f8b\u88ab\u300c\u525d\u6389\u5927\u62ec\u865f\u300d\uff0c\u65bc\u662f e^{-kt} \u8b8a\u6210\u5b57\u9762\u7684
#   e^-kt\uff0c\u8b80\u8005\u770b\u4e0d\u51fa\u90a3\u662f\u6b21\u65b9\u3002\u4e0a\u6a19\u5fc5\u9808\u6709\u81ea\u5df1\u7684\u5b57\u5143\u5c0d\u61c9\u3002
SUPSCR = str.maketrans('0123456789+-=()aeoxbktinm',
                       '\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077'
                       '\u2078\u2079\u207a\u207b\u207c\u207d\u207e'
                       '\u1d43\u1d49\u1d52\u02e3\u1d47\u1d4f\u1d57'
                       '\u2071\u207f\u1d50')


# 式號表：依 \begin{equation} 在 main.tex 的出現順序編。
# ⚠ 先前寫死成 '(1)'，於是所有 \eqref 都印成 (1)——曲率式該是 (2)、
#   定版速率該是 (3)。式號不可寫死。
EQNO = {}


def build_eqno(tex):
    EQNO.clear()
    i = 0
    for m in re.finditer(r'\\begin\{equation\}(.*?)\\end\{equation\}',
                         tex, re.S):
        i += 1
        lab = re.search(r'\\label\{([^}]*)\}', m.group(1))
        if lab:
            EQNO[lab.group(1)] = '(%d)' % i


def detex(s):
    """把 LaTeX 片段轉成可讀純文字。"""
    s = re.sub(r'(?<!\\)%.*', '', s)
    for pat, rep in MACROS:
        s = re.sub(pat, rep, s)
    # ⚠ 環境標記與 \label 必須在「剝大括號」之前清掉，否則環境名與
    #   標籤名會變成裸文字留在成品裡——PDF 實證：貢獻列表末印出
    #   「enumerate」，兩個小節標題下印出 sec:null、sec:endpoint。
    s = re.sub(r'\\(?:begin|end)\{[a-zA-Z*]+\}', '', s)
    s = re.sub(r'\\label\{[^}]*\}', '', s)
    s = re.sub(r'\\item\b', '', s)
    s = re.sub(r'\\eqref\{([^}]*)\}', lambda m: EQNO.get(m.group(1), '(?)'), s)
    s = re.sub(r'\\Comment\{([^{}]*)\}', r'   // \1', s)
    s = re.sub(r'\\(State|Require|Ensure|If|EndIf|For|EndFor)\b', '', s)
    s = re.sub(r'\\frac\{([^{}]*)\}\{([^{}]*)\}', r'(\1)/(\2)', s)
    # ⚠ 內文的數學變數要**斜體**（Springer 慣例；函數名與單位維持正體）。
    #   先前只是把 $ 剝掉，變數與一般文字混在同一個 run 裡，全部變成正體。
    #   改成標記成 ⟨…⟩，由 rich_runs() 排成斜體。
    s = re.sub(r'\$([^$]*)\$', lambda m: '⟨'+m.group(1)+'⟩', s)
    s = re.sub(r'\\[a-zA-Z]+\{([^{}]*)\}', r'\1', s)
    s = re.sub(r'\\[a-zA-Z]+', '', s)
    # \u26a0 \u4e0a\u4e0b\u6a19\u5fc5\u9808\u5728**\u525d\u6389\u5927\u62ec\u865f\u4e4b\u524d**\u8655\u7406\u3002\u521d\u7248\u5148 replace('{','') \u518d\u53ea\u8f49
    #   ^2\uff0c\u65bc\u662f e^{-kt} \u8b8a\u6210\u5b57\u9762\u7684 e^-kt\u2014\u2014\u8b80\u8005\u770b\u4e0d\u51fa\u90a3\u662f\u6b21\u65b9\u3002
    # 上標同理：SUPSCR 蓋不全就走 ⟦base^sup⟧ 標記排成 Word 真上標。
    def _sup(m):
        base, up = m.group(1), m.group(2)
        # ⚠ 不可「能轉 Unicode 就轉」。MACROS 產生的 ⟦m^2⟧ 標記會在
        #   這裡被重新匹配、換回 Unicode ²，於是全文又出現兩種
        #   排法。一律輸出標記，由 rich_runs() 排成 Word 真上標。
        return '⟦' + base + '↑' + up + '⟧'
    s = re.sub(r'([A-Za-z0-9\)])\^\{([^{}]+)\}', _sup, s)
    s = re.sub(r'\^\{([^{}]+)\}', lambda m: m.group(1).translate(SUPSCR), s)
    s = re.sub(r'([A-Za-z0-9\)])\^([a-zA-Z0-9])', _sup, s)
    s = re.sub(r'\^([a-zA-Z0-9])', lambda m: m.group(1).translate(SUPSCR), s)
    # ⚠ 下標不可無條件套 translate：SUBSCR 蓋不到的字元會**原樣留下**，
    #   於是 `k_{med}` 印成 `kₘₑd`——m、e 是真下標而 d 是正常大小的字，
    #   同一個下標裡混兩種高度。凡是蓋不全的，改走 ⟦base|sub⟧ 標記交給
    #   rich_runs() 排成 Word 真下標。
    def _sub(m):
        base, sub = m.group(1), m.group(2)
        # 同上：下標也一律走真下標，不用 Unicode 近似字元。
        return '⟦' + base + '|' + sub + '⟧'
    s = re.sub(r'([A-Za-z0-9̂])_\{([^{}]+)\}', _sub, s)
    s = re.sub(r'_\{([^{}]+)\}', lambda m: m.group(1).translate(SUBSCR), s)
    s = re.sub(r'([A-Za-z0-9̂])_([a-zA-Z0-9])', _sub, s)
    s = re.sub(r'_([a-zA-Z0-9])', lambda m: m.group(1).translate(SUBSCR), s)
    s = s.replace('{', '').replace('}', '').replace('~', '\u00a0')
    # \u26a0 \u7834\u6298\u865f\u8981**\u5148\u9577\u5f8c\u77ed**\u3002\u53ea\u5beb `--` \u7684\u8a71\uff0cLaTeX \u7684 em dash `---`
    #   \u6703\u88ab\u5403\u6389\u524d\u5169\u500b\u8b8a\u6210\u300c\u2013-\u300d\uff08\u534a\u5f62\u9023\u5b57\u865f\u9ecf\u5728 en dash \u5f8c\u9762\uff09\u3002
    s = re.sub(r'---', '\u2014', s)
    s = re.sub(r'--', '\u2013', s)
    s = re.sub(r'``|\'\'', '"', s)
    # \u26a0 \u9019\u88e1\u539f\u672c\u5beb [ \t]+\uff0c**\u6c92\u6709\u6536\u5408\u63db\u884c**\u3002\u65bc\u662f main.tex \u6bcf\u500b\u539f\u59cb\u78bc\u63db\u884c\u90fd
    #   \u8b8a\u6210 Word \u7684\u786c\u65b7\u884c\uff1a\u6b63\u6587\u6bb5\u843d\u51fa\u73fe 14 \u500b run\u3001\u6a19\u984c 3 \u500b\uff0c\u6587\u5b57\u7121\u6cd5\u6d41\u52d5
    #   \u4e5f\u7121\u6cd5\u5de6\u53f3\u5c0d\u9f4a\uff0c\u770b\u8d77\u4f86\u5c31\u662f\u300c\u5b57\u9ad4\u5168\u90e8\u8dd1\u6389\u300d\uff0c\u800c\u4e14\u786c\u65b7\u884c\u704c\u7206\u884c\u6578\u2014\u2014
    #   \u90a3\u624d\u662f\u9801\u6578\u8b8a\u6210 12 \u7684\u771f\u6b63\u539f\u56e0\u3002\u5fc5\u9808\u7528 \s+ \u628a\u63db\u884c\u4e00\u8d77\u6536\u6389\u3002
    return re.sub(r'\s+', ' ', s).strip()


def setup(doc):
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = Mm((210-122)/2)
    sec.top_margin = sec.bottom_margin = Mm((297-193)/2)
    st = doc.styles['Normal']
    st.font.name = FONT
    st.font.size = Pt(SZ_BODY)
    st.element.rPr.rFonts.set(qn('w:eastAsia'), FONT)
    pf = st.paragraph_format
    pf.space_before = pf.space_after = Pt(0)
    pf.line_spacing = 1.0


def para(doc, text, size=None, bold=False, italic=False,
         align=None, before=0, after=0, indent=None, mono=False):
    p = doc.add_paragraph()
    if size is None:
        size = SZ_BODY
    pf = p.paragraph_format
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    if align is not None:
        p.alignment = align
    if indent is not None:
        pf.left_indent = Mm(indent)
    r = p.add_run(text)
    r.font.name = 'Courier New' if mono else FONT
    r.font.size = Pt(size)
    r.bold, r.italic = bold, italic
    return p


def math_runs(p, latex, size=None):
    """顯示公式：用 Word **真正的上下標**（w:vertAlign），不用 Unicode 近似。
    if size is None:
        size = SZ_BODY

    Unicode 上標只涵蓋部分字元（例如沒有 ˡ、ᵍ 的完整集合），且字級不隨
    內文縮放；顯示公式是全篇最該正確排版的地方，值得逐段送 run。
    """
    # ⚠ 巨集要在**切詞之前**展開成帶 `_` 的形式，否則 \rb 會走 detex_plain
    #   的 Unicode 對應，而 Unicode **沒有下標 b**——會被換成 U+1D47 'ᵇ'，
    #   那其實是上標。展開後 `_b` 才能走下面真正的 Word 下標。
    for name, rep in (('rbh', 'r̂_b'), ('rb', 'r_b'), ('kh', 'k̂'),
                      ('ratu', 'kg/cm^{2}/hr'), ('pu', 'kg/cm^{2}'),
                      ('peq', 'P_eq')):
        latex = re.sub(r'\\'+name+r'(?:\{\})?(?![a-zA-Z])', rep, latex)
    toks = re.findall(r'\^\{[^{}]*\}|_\{[^{}]*\}|\^.|_.|[^_^]+', latex)
    for tk in toks:
        if tk[0] in '^_':
            body = tk[2:-1] if tk[1] == '{' else tk[1:]
            r = p.add_run(detex_plain(body))
            # python-docx 沒有 vertAlign 列舉，上下標是 font 上的布林屬性。
            if tk[0] == '^':
                r.font.superscript = True
            else:
                r.font.subscript = True
            r.font.size = Pt(size)
        else:
            r = p.add_run(detex_plain(tk))
            r.font.size = Pt(size)
        r.font.name = FONT
        r.italic = bool(re.fullmatch(r'[A-Za-z]+', r.text or ''))
    return p


def detex_plain(s):
    r"""只做符號展開，不碰上下標（那由 math_runs 處理）。

    ⚠ 兩個實際踩到的坑：
      1. 巨集在正文寫成 `\\rb\\,t`（**沒有** `{}`），而 MACROS 只比對
         `\\rb\{\}`，於是比對失敗、接著被「刪除未知指令」那條整個吃掉，
         公式變成 `P(t)=Peq+A e-kt- t`——r_b 消失了。
      2. `\\frac{a}{b}` 沒展開，分數被壓成 `y(0)-y(T/2)y(0)-y(T)`。
    """
    s = re.sub(r'\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}', r'(\1) / (\2)', s)
    for pat, rep in MACROS:
        s = re.sub(pat, rep, s)
    # 不帶 {} 的巨集用法（\rb\,t 這種）——必須在刪除未知指令之前處理。
    for name, rep in (('rbh', 'r̂_b'), ('rb', 'r_b'), ('kh', 'k̂'),
                      ('ratu', 'kg/cm²/hr'), ('pu', 'kg/cm²'),
                      ('invh', '/hr')):
        s = re.sub(r'\\'+name+r'(?![a-zA-Z])', rep, s)
    s = re.sub(r'\\[a-zA-Z]+\{([^{}]*)\}', r'\1', s)
    s = re.sub(r'\\[a-zA-Z]+', '', s)

    # NOTE 2026-08-24: subscripts must be handled BEFORE braces are
    # stripped. Once `_{k in K}` becomes `_k in K` there is no way to
    # tell where the subscript ended, so \arg\min_{k\in K} printed as
    # a subscripted k followed by a full-size 'in K'.
    # Nor may translate(SUBSCR) be applied unconditionally: that table
    # covers only 0-9 +-=() a e o x k L m n, and every other character
    # survives at full size, mixing two heights inside one subscript
    # (`k_{med}` printed with a full-size d). Anything the table cannot
    # cover goes through the base|sub marker instead, which rich_runs()
    # renders as a real Word subscript.
    def _sub_plain(m):
        base, sub = m.group(1), m.group(2)
        if sub and all(c in SUBOK for c in sub):
            return base + sub.translate(SUBSCR)
        return '⟦' + base + '|' + sub + '⟧'

    s = re.sub(r'([A-Za-z0-9\u0302\u0307])_\{([^{}]*)\}',
               _sub_plain, s)
    s = re.sub(r'([A-Za-z0-9\u0302\u0307])_([a-zA-Z0-9])',
               _sub_plain, s)
    s = s.replace('{', '').replace('}', '').replace('$', '')
    # ⚠ `~`（不斷行空格）與破折號只在 detex() 裡處理過，公式走的是這條
    #   路徑，於是 Eq. (3) 印出字面的 `~`：「0.0116]~kg/cm²/hr」。
    s = s.replace('~', ' ')
    s = re.sub(r'---', '—', s)
    s = re.sub(r'--', '–', s)
    return s


def add_hyperlink(p, url, text, size=None, name=None):
    """在段落 p 裡插入一段可點擊的超連結。

    python-docx 沒有這個 API：要先在 document part 建一個 external
    relationship 拿到 r:id，再手工組 w:hyperlink 節點。用 Word 內建的
    Hyperlink 字元樣式（藍色加底線），這樣即使換範本也跟著走。
    """
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    r_id = p.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement('w:hyperlink')
    link.set(qn('r:id'), r_id)
    run = OxmlElement('w:r')
    rPr = OxmlElement('w:rPr')
    st = OxmlElement('w:rStyle')
    st.set(qn('w:val'), 'Hyperlink')
    rPr.append(st)
    if name:
        rf = OxmlElement('w:rFonts')
        for a in ('w:ascii', 'w:hAnsi', 'w:cs'):
            rf.set(qn(a), name)
        rPr.append(rf)
    if size is not None:
        sz = OxmlElement('w:sz')
        sz.set(qn('w:val'), str(int(size * 2)))
        rPr.append(sz)
    run.append(rPr)
    t = OxmlElement('w:t')
    t.text = text
    t.set(qn('xml:space'), 'preserve')
    run.append(t)
    link.append(run)
    p._p.append(link)
    return link

def rich_runs(p, text, size=None, bold=False):
    """把 detex 產出的 ⟦base|sub⟧ 標記排成 **Word 真下標**。
    if size is None:
        size = SZ_BODY

    Unicode 的下標集合不完整（沒有 b、q、eq…），用近似字元會出現
    「上標 b 冒充下標 b」這種錯誤。內文與 Eq. (1) 必須是同一種排法。
    """
    # ⟨…⟩ 為行內數學（整段斜體），⟦base|sub⟧ 為帶真下標的符號。
    # 兩者會巢狀（數學段裡含 ⟦⟧），故先切 ⟨⟩ 再切 ⟦⟧。
    def emit(seg, ital):
        for tk in re.split(r'(⟦[^⟦⟧]*⟧)', seg):
            if not tk:
                continue
            if tk.startswith('⟦'):
                # `|` 為下標、`^` 為上標。上標分支是後補的：SUPSCR 蓋不到
                # 的字元（例如 β）原本會原樣留下，`(k/k_med)^β` 於是印成
                # `(k/k_med)β`，看起來像乘法而不是次方。
                body = tk[1:-1]
                if '↑' in body:
                    base, _, up = body.partition('↑')
                    sup = True
                else:
                    base, _, up = body.partition('|')
                    sup = False
                r = p.add_run(base)
                r.font.name = FONT; r.font.size = Pt(size)
                r.italic = True; r.bold = bold
                r2 = p.add_run(up)
                r2.font.name = FONT; r2.font.size = Pt(size)
                if sup:
                    r2.font.superscript = True
                else:
                    r2.font.subscript = True
                r2.italic = True; r2.bold = bold
            else:
                r = p.add_run(tk)
                r.font.name = FONT; r.font.size = Pt(size)
                r.bold = bold; r.italic = ital

    for part in re.split(r'(⟨[^⟨⟩]*⟩)', text):
        if not part:
            continue
        if part.startswith('⟨'):
            emit(part[1:-1], True)     # 行內數學：斜體
        else:
            emit(part, False)
    return p


def rich_para(doc, text, size=None, align=None, after=0, before=0,
              indent=None, bold=False):
    p = doc.add_paragraph()
    if size is None:
        size = SZ_BODY
    pf = p.paragraph_format
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    if align is not None:
        p.alignment = align
    if indent is not None:
        pf.left_indent = Mm(indent)
    rich_runs(p, text, size, bold)
    return p


def cell_border(cell, top=None, bottom=None):
    """儲存格框線（w:tcBorders）。

    ⚠ 不可用**段落**框線畫表格橫線：每個儲存格各畫一段，中間被儲存格
      間距斷開，看起來是斷線。儲存格框線在相鄰格之間會接起來，才是
      範例 Table 1 那種連續的橫線。
    """
    tcPr = cell._tc.get_or_add_tcPr()
    for old in tcPr.findall(qn('w:tcBorders')):
        tcPr.remove(old)
    b = OxmlElement('w:tcBorders')
    for edge, sz in (('top', top), ('bottom', bottom)):
        if sz is None:
            continue
        e = OxmlElement(f'w:{edge}')
        e.set(qn('w:val'), 'single'); e.set(qn('w:sz'), str(sz))
        e.set(qn('w:space'), '0'); e.set(qn('w:color'), '000000')
        b.append(e)
    tcPr.append(b)


def shade(p, hexcolor='F2F2F2'):
    el = OxmlElement('w:shd')
    el.set(qn('w:val'), 'clear'); el.set(qn('w:fill'), hexcolor)
    p._p.get_or_add_pPr().append(el)


def border(p, edges=('top', 'bottom', 'left', 'right'), sz=6):
    pbdr = OxmlElement('w:pBdr')
    for e in edges:
        b = OxmlElement(f'w:{e}')
        b.set(qn('w:val'), 'single'); b.set(qn('w:sz'), str(sz))
        b.set(qn('w:space'), '4'); b.set(qn('w:color'), '808080')
        pbdr.append(b)
    p._p.get_or_add_pPr().append(pbdr)


# ── 解析 main.tex ───────────────────────────────────────────────
def parse(tex):
    """回傳 (blocks, cites, bib)。blocks 是 (kind, payload) 串列。"""
    build_eqno(tex)
    body = tex.split(r'\maketitle', 1)[1]
    body = body.split(r'\begin{thebibliography}')[0]

    bib = []
    # ⚠ 最後一筆的終止條件不可以只用 \Z：那會把 \end{thebibliography} 與
    #   \end{document} 一起吃進來，detex 剝掉指令名後在成品最末筆參考文獻
    #   後面留下字面的「thebibliography document」。
    for m in re.finditer(r'\\bibitem\{([^}]*)\}(.*?)'
                         r'(?=\\bibitem|\\end\{thebibliography\}|\Z)',
                         tex.split(r'\begin{thebibliography}')[1], re.S):
        bib.append((m.group(1), detex(' '.join(m.group(2).split()))))
    order = [k for k, _ in bib]                    # 依字母序編號（LNCS 慣例）
    num = {k: i+1 for i, k in enumerate(order)}

    # 圖／表／演算法的編號
    labels, fig_i, tab_i, alg_i = {}, 0, 0, 0
    # ⚠ 必須**逐環境**比對。原本寫 \begin{figure}.*?\label{...}，非貪婪的
    #   .*? 會跨越環境邊界：四個演算法列表也是 figure 環境但沒有 \label，
    #   於是它們一路吃到下一張真圖的 label，編號整個錯位——內文寫
    #   「Fig. 5」而圖說是「Fig. 4」就是這樣來的。
    # ⚠ 星號版本（figure*／table*）也要吃：ACM 的跨欄浮動體就是它，
    #   漏掉會讓整個環境被靜默丟棄，圖號還會跟著錯位。
    for m in re.finditer(r'\\begin\{(figure\*?|table\*?|algorithm)\}(.*?)'
                         r'\\end\{\1\}', body, re.S):
        kind, inner = m.group(1).rstrip('*'), m.group(2)
        lab = re.search(r'\\label\{([^}]*)\}', inner)
        if kind == 'figure':
            # 只有含 \includegraphics 的才算「圖」；列表另以 Listing 編號。
            if '\\includegraphics' not in inner:
                continue
            fig_i += 1
            if lab:
                labels[lab.group(1)] = f'Fig. {fig_i}'
        elif kind == 'table':
            tab_i += 1
            if lab:
                labels[lab.group(1)] = f'Table {tab_i}'
        else:
            alg_i += 1
            if lab:
                labels[lab.group(1)] = f'Algorithm {alg_i}'
    # 節號**動態**編出來，不要寫死。
    # ⚠ 原本是一個手打的字典 {'sec:intro':'1', ...}，只收 \section 的標籤：
    #   1) \subsection 的標籤（如 sec:endpoint）查不到 → 印成 'Sect. ?'
    #   2) 章節一搬動，寫死的號碼就與實際不符，而且不會報錯
    #   兩個問題這次都踩到了。改成掃過本文依序編號，含 x.y 層。
    secno = {}
    si = sj = 0
    for m in re.finditer(r'\\(section|subsection)\{[^}]*\}'
                         r'(?:\s*\\label\{([^}]*)\})?', body):
        if m.group(1) == 'section':
            si += 1; sj = 0; cur = str(si)
        else:
            sj += 1; cur = f'{si}.{sj}'
        if m.group(2):
            secno[m.group(2)] = cur
    labels.setdefault('eq:le', '(1)')

    # 解不掉的交叉引用要吵，不能默默印成 '?'——sec:endpoint 就是這樣
    # 一路混到成品裡的。
    unresolved = []

    def refs(s):
        s = re.sub(r'\\cite\{([^}]*)\}',
                   lambda m: '[' + ', '.join(
                       str(num.get(k.strip(), '?'))
                       for k in m.group(1).split(',')) + ']', s)
        s = re.sub(r'(Sect\.|Sects\.)~\\ref\{([^}]*)\}',
                   lambda m: m.group(1) + '\u00a0' +
                   secno.get(m.group(2), '?'), s)
        def one(m):
            v = labels.get(m.group(1))
            if v is None:
                unresolved.append(m.group(1))
                return '?'
            return v
        s = re.sub(r'(?:Algorithms|Algorithm|Figure|Fig\.|Table)?~?'
                   r'\\ref\{([^}]*)\}', one, s)
        return s

    blocks, pos = [], 0
    # ⚠ equation 必須也在這裡抽出來。它在 main.tex 裡是**嵌在段落中間**的
    #   （前面沒有空行），而 text_blocks 只在段落開頭偵測 \begin{equation}，
    #   結果公式一個都沒被認出來（產出顯示「公式 0」）。
    envs = re.compile(r'\\begin\{(figure\*?|table\*?|algorithm|equation)\}(.*?)'
                      r'\\end\{\1\}', re.S)
    for m in envs.finditer(body):
        blocks += text_blocks(body[pos:m.start()], refs)
        # ⚠ 區塊種類要去掉星號，否則 main() 的 kind == 'figure' 比不到，
        #   figure* 會被當成未知種類而**靜默丟棄**（figG 就是這樣消失的）。
        blocks.append((m.group(1).rstrip('*'), refs(m.group(2))))
        pos = m.end()
    blocks += text_blocks(body[pos:], refs)
    return blocks, bib, num


def text_blocks(chunk, refs):
    out = []
    chunk = re.sub(r'(?<!\\)%.*', '', chunk)
    for raw in re.split(r'\n\s*\n', chunk):
        raw = raw.strip()
        if not raw or raw.startswith(r'\end{document}'):
            continue
        m = re.match(r'\\section\{(.*?)\}', raw, re.S)
        if m:
            out.append(('sec', detex(m.group(1))))
            rest = raw[m.end():].strip()
            rest = re.sub(r'^\\label\{[^}]*\}', '', rest).strip()
            if rest:
                out.append(('p', detex(refs(rest))))
            continue
        m = re.match(r'\\subsection\{(.*?)\}', raw, re.S)
        if m:
            out.append(('sub', detex(m.group(1))))
            rest = raw[m.end():].strip()
            if rest:
                out.append(('p', detex(refs(rest))))
            continue
        m = re.match(r'\\subsubsection\{(.*?)\}', raw, re.S)
        if m:
            out.append(('run', detex(m.group(1)),
                        detex(refs(raw[m.end():].strip()))))
            continue
        if raw.startswith(r'\begin{equation}'):
            e = re.search(r'\\begin\{equation\}(.*?)\\end\{equation\}',
                          raw, re.S)
            if e:
                out.append(('eq', detex(re.sub(r'\\label\{[^}]*\}', '',
                                               e.group(1)))))
            continue
        if raw.startswith(r'\begin{enumerate}'):
            for it in re.findall(r'\\item\s+(.*?)(?=\\item|\Z)',
                                 raw, re.S):
                out.append(('li', detex(refs(it))))
            continue
        if raw.startswith('\\'):
            continue
        out.append(('p', detex(refs(raw))))
    return out


# ── 產生 ─────────────────────────────────────────────────────────
def emit_algorithm(doc, payload, n):
    cap = re.search(r'\\caption\{(.*?)\}\s*\\label', payload, re.S)
    lines = re.findall(r'\\(?:State|Require|Ensure|If|EndIf|For|EndFor|'
                       r'ElsIf|Else)\b(.*)', payload)
    head = re.search(r'\\Require(.*)', payload)
    tail = re.search(r'\\Ensure(.*?)(?=\\end)', payload, re.S)
    p = para(doc, f'Algorithm {n}. '+detex(cap.group(1) if cap else ''),
             size=SZ_CAP, bold=True, before=6, after=2)
    border(p, edges=('top',))
    if head:
        para(doc, 'Input: '+detex(head.group(1)), size=SZ_CAP, italic=True,
             indent=2)
    i = 0
    for ln in lines:
        t = detex(ln)
        if not t or t.startswith('Input:'):
            continue
        if head and detex(head.group(1)).startswith(t[:20]):
            continue
        if tail and t and detex(tail.group(1)).startswith(t[:20]):
            continue
        i += 1
        para(doc, f'{i:>2}.  {t}', size=SZ_CAP, indent=3, mono=True)
    if tail:
        p2 = para(doc, 'Output: '+detex(tail.group(1)), size=SZ_CAP,
                  italic=True, indent=2, after=6)
        border(p2, edges=('bottom',))


def caption(doc, text, before=3, after=8):
    """範本規則：圖說 9 pt；短的置中，超過一行的左右對齊；
    非完整句子不加句點。"""
    long = len(text) > 92
    p = rich_para(doc, text, size=SZ_CAP, before=before, after=after,
                  bold=CAP_BOLD,
                  align=(WD_ALIGN_PARAGRAPH.JUSTIFY if long
                         else WD_ALIGN_PARAGRAPH.CENTER))
    return p


def emit_listing(doc, payload, n):
    """verbatim 區塊 → 打字機字體（範本 §2.8：program listings 用
    typewriter font）。"""
    vb = re.search(r'\\begin\{verbatim\}\n(.*?)\\end\{verbatim\}',
                   payload, re.S)
    if not vb:
        return False
    # ── 經典 algorithm 浮動框版式（依使用者提供的範例圖）────────
    #     ────────────────────────────
    #     Algorithm n  Title              ← 粗體標頭，上下各一條橫線
    #     ────────────────────────────
    #      1: code                 ▷ note ← 行號；註解靠右、加 ▷
    #     ────────────────────────────
    #   內容仍是可執行的 NumPy（範本 §2.8 要求 typewriter font），
    #   只是外框改成前沿論文慣用的版式。
    # ⚠ 標記格式由 `\textbf{Listing N.}` 改成 `\textbf{Algorithm N  名稱}`
    #   之後，這條正規式沒跟著改，比對失敗就給空字串——Word 的兩條線之間
    #   只剩「Algorithm 1」而名稱整個不見。名稱現在在大括號**裡面**。
    # ⚠ 2026-08-24：標題搬到 verbatim **之前**之後，原本單一個 (.*)
    #   會把整段程式碼一起吞進去當說明文字，於是程式碼被重複輸出成
    #   一段流水文字，k_fit 在那裡被斷成「k＋下標 f」＋「it」。
    #   說明文字改為只在 verbatim 的前段或後段各自搜，不跨過程式碼。
    _head = payload.partition('\\begin{verbatim}')[0]
    _tail = payload.partition('\\end{verbatim}')[2]
    _pat = r'\\textbf\{Algorithm\s*(\d+)\s+([^}]*)\}(.*)'
    cap = (re.search(_pat, _head, re.S) or re.search(_pat, _tail, re.S))
    if cap:
        title = detex(cap.group(2)).strip()
        full = detex(cap.group(3)).strip()
    else:                                   # 舊格式的後備
        old = re.search(r'\\textbf\{Listing \d+\.\}(.*)', payload, re.S)
        full = detex(old.group(1)) if old else ''
        title = full.split('.')[0].strip() if full else ''

    # ── 標頭：橫線 ＋「Algorithm n  標題」──────────────
    lead = doc.add_paragraph()
    lead.paragraph_format.space_before = Pt(8)
    lead.paragraph_format.space_after = Pt(1)
    lead.paragraph_format.keep_with_next = True
    r = lead.add_run(f'Algorithm {n} ')
    r.font.name = FONT; r.font.size = Pt(SZ_ALG); r.bold = True
    r2 = lead.add_run(title)
    r2.font.name = FONT; r2.font.size = Pt(SZ_ALG); r2.bold = True
    lead.paragraph_format.left_indent = Mm(0)
    # 範例圖在標題**上下各一條**線；先前只畫了上面那條。
    border(lead, edges=('top', 'bottom'), sz=10)

    # \u2500\u2500 \u8a18\u865f\u7d71\u4e00 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    #   \u6253\u5b57\u6a5f\u5b57\u9ad4\uff08\u7bc4\u672c \u00a72.8\uff09\u4f46\u7b26\u865f\u8981\u56b4\u8b39\uff1a`X^` \u4e0a\u52a0\u6291\u63da\u7b26\u6210 X\u0302\uff0c
    #   `_abc` \u6392\u6210**\u771f\u4e0b\u6a19**\uff0c`^2` \u6392\u6210**\u771f\u4e0a\u6a19**\uff0c\u7bad\u982d\u8207\u4e0d\u7b49\u865f\u7528\u771f\u7b26\u865f\u3002
    # \u26a0 \u6f14\u7b97\u6cd5\u5340\u584a**\u4e0d\u4f7f\u7528\u7d44\u5408\u6291\u63da\u7b26**\uff08U+0302\uff09\u3002\u7b49\u5bec\u5b57\u578b\u5c0d\u7d44\u5408\u9644\u52a0\u7b26\u865f\u7684
    #   \u652f\u63f4\u5f88\u5dee\uff0c`k\u0302` \u7684\u5e3d\u5b50\u6703\u6d6e\u6389\u6216\u932f\u4f4d\uff1b\u800c\u4e14\u53ea\u6709 \u00c2\u3001\u015d \u6709\u9810\u7d44\u5b57\u5143\uff0c
    #   k\u0302\uff0fP\u0302\uff0fr\u0302\uff0ff\u0302 \u6c92\u6709\uff0c\u4e00\u5b9a\u6703\u4e0d\u4e00\u81f4\u3002\u4f30\u8a08\u91cf\u6539\u7528\u6587\u5b57\u8aaa\u660e\uff08\u898b input \u884c\u7684
    #   "fitted"\uff0f"estimates"\uff09\uff0c\u5e3d\u5b50\u53ea\u7559\u5728\u5167\u6587\u8207\u516c\u5f0f\uff08Times \u6392\u5f97\u6f02\u4eae\uff09\u3002
    SYM = [(r'<-', '\u2190'), (r'!=', '\u2260'), (r'\|\|', '\u2016'),
           (r'\brho\b', '\u03c1'), (r'\bsigma\b', '\u03c3'), (r'\bphi\b', '\u03c6'),
           (r'\bin\b', '\u2208'), (r'\.\.\.', '\u2026'),
           # \u26a0 \u53d6\u4ee3\u5b57\u4e32\u4e0d\u53ef\u7528 raw string\u2014\u2014'\1 \u00d7 \2' \u88e1\u7684 \u \u6703\u88ab re
           #   \u7576\u6210\u8f49\u7fa9\u5e8f\u5217\u800c\u5831 bad escape\uff0c\u6574\u500b\u5efa\u7f6e\u6703\u639b\u6389\u3002
           (r'(\d) x (\d)', '\\1 \u00d7 \\2')]
    # \u6f14\u7b97\u6cd5\u7248\u5f0f\uff08\u4f9d\u7bc4\u4f8b\u5716\uff09\uff1a\u95dc\u9375\u5b57\u7c97\u9ad4\u3001**\u8b8a\u6578\u659c\u9ad4\u3001\u51fd\u6578\u540d\u6b63\u9ad4**\u3002
    # \u5224\u5b9a\u898f\u5247\uff1a\u8b58\u5225\u5b57\u5f8c\u9762\u63a5 '(' \u8005\u70ba\u51fd\u6578\uff08\u6b63\u9ad4\uff09\uff0c\u5176\u9918\u8b58\u5225\u5b57\u70ba\u8b8a\u6578\uff08\u659c\u9ad4\uff09\u3002
    KW = {'for', 'do', 'end', 'while', 'if', 'then', 'else', 'return',
          'to', 'each', 'repeat', 'until'}

    def emit_code_line(q, text, sz=8):
        """\u4e00\u884c\u7a0b\u5f0f\u78bc \u2192 \u591a\u500b run\uff1a\u95dc\u9375\u5b57\u7c97\u9ad4\u3001**\u8b8a\u6578\u659c\u9ad4\u3001\u51fd\u6578\u540d\u6b63\u9ad4**\u3002

        \u5224\u5b9a\u898f\u5247\uff08\u8207\u7bc4\u4f8b\u5716\u4e00\u81f4\uff09\uff1a\u8b58\u5225\u5b57\u5f8c\u63a5 '(' \u8005\u70ba\u51fd\u6578\uff08\u6b63\u9ad4\uff09\uff0c
        \u5176\u9918\u8b58\u5225\u5b57\u70ba\u8b8a\u6578\uff08\u659c\u9ad4\uff09\uff1bKW \u5167\u8005\u70ba\u95dc\u9375\u5b57\uff08\u7c97\u9ad4\u6b63\u9ad4\uff09\u3002
        """
        for pat, rep in SYM:
            text = re.sub(pat, rep, text)
        # \u26a0 \u5e3d\u5b50\u5fc5\u9808**\u5148\u4f75\u9032\u5b57\u6bcd**\u518d\u5207\u8a5e\u3002\u539f\u672c\u628a `[A-Za-z]\^` \u7576\u6210\u4e00\u500b
        #   token\uff0c\u4f46\u6392\u5728\u5b83\u524d\u9762\u7684\u8caa\u5a6a\u4e00\u822c\u5b57\u5143\u7d44\u5df2\u7d93\u5148\u628a\u5b57\u6bcd\u5403\u6389\uff0c\u65bc\u662f
        #   `k^` \u6c92\u5408\u6210 k\u0302\uff1b\u843d\u55ae\u7684 `^` \u53c8\u8d70\u9032\u4e0a\u6a19\u5206\u652f\uff0c\u7522\u751f\u7a7a\u7684\u4e0a\u6a19 run\u3002
        text = re.sub(r'([A-Za-z])\^', '\\1\u0302', text)
        # \u26a0 \u4e0b\u6a19\u539f\u672c\u5beb\u6210 `_[A-Za-z0-9,]+`\uff0c\u5c0d\u9017\u865f**\u8caa\u5a6a**\uff0c\u628a\u5217\u8868\u7684\u5206\u9694\u9017\u865f
        #   \u4e00\u8d77\u541e\u9032\u4e0b\u6a19\uff1a`{k^_i, A^_i}` \u8b8a\u6210\u4e0b\u6a19\u300ci,\u300d\u3001`Spearman(r^_b, k^)`
        #   \u751a\u81f3\u51fa\u73fe\u53ea\u542b\u4e00\u500b\u9017\u865f\u7684\u4e0b\u6a19\u3002`eq,i`\uff0f`b,i` \u9700\u8981**\u5167\u90e8**\u9017\u865f\uff0c
        #   \u4f46**\u7d50\u5c3e**\u7684\u9017\u865f\u662f\u5206\u9694\u7b26 \u2014\u2014 \u7528 (?:,\w+)* \u5141\u8a31\u5167\u90e8\u3001\u7981\u6b62\u7d50\u5c3e\u3002
        # 切成識別字／下標／上標／其他，逐段決定字體樣式
        for tk in re.finditer(
                r'(?P<sub>_[A-Za-z0-9]+(?:,[A-Za-z0-9]+)*)'
                r'|(?P<sup>\^[0-9]+)'
                r'|(?P<word>[A-Za-z][A-Za-z0-9]*)'
                r'|(?P<other>.)', text):
            g, s = tk.lastgroup, tk.group()
            if g == 'sub':
                r1 = q.add_run(s[1:])
                r1.font.subscript = True; r1.italic = True
                r1.font.name = FONT
            elif g == 'sup':
                r1 = q.add_run(s[1:])
                r1.font.superscript = True; r1.font.name = FONT
            elif g == 'word':
                r1 = q.add_run(s); r1.font.name = FONT
                if s.lower() in KW:
                    r1.bold = True                      # 關鍵字：粗體
                elif text[tk.end():tk.end()+1] == '(':
                    pass                                # 函數名：正體
                else:
                    r1.italic = True                    # 變數：斜體
            else:
                r1 = q.add_run(s); r1.font.name = FONT
            r1.font.size = Pt(sz)

    # ── 標頭區塊：Input / Parameter / Output（標籤粗體）────
    lines = vb.group(1).rstrip('\n').split('\n')
    head, body_lines, in_head = [], [], True
    for ln in lines:
        if in_head and (re.match(r'\s*(Input|Parameter|Output)\s*:', ln)
                        or (head and ln.startswith('    ')
                            and not re.match(r'\s*(for|if|while)', ln))):
            head.append(ln)
        else:
            in_head = False
            body_lines.append(ln)

    for ln in head:
        q = doc.add_paragraph()
        pf = q.paragraph_format
        pf.space_before = pf.space_after = Pt(0)
        pf.line_spacing = 1.0; pf.left_indent = Mm(0)
        m2 = re.match(r'\s*(Input|Parameter|Output)\s*:(.*)', ln)
        if m2:
            rr = q.add_run(m2.group(1)+': ')
            rr.font.name = FONT; rr.font.size = Pt(SZ_ALG); rr.bold = True
            emit_code_line(q, m2.group(2).strip(), SZ_ALG)
        else:
            pf.left_indent = Mm(6)
            emit_code_line(q, ln.strip(), SZ_ALG)
    # ⚠ Input/Parameter/Output 下方**不畫線**——標頭與編號行連成一片，
    #   整個框只有三條：頂、標題下、最底。

    # ── 主體：行號、縮排、關鍵字粗體 ────────────────────
    i = 0
    for ln in body_lines:
        if not ln.strip():
            continue
        i += 1
        q = doc.add_paragraph()
        pf = q.paragraph_format
        pf.space_before = pf.space_after = Pt(0)
        pf.line_spacing = 1.0; pf.left_indent = Mm(0)
        pf.tab_stops.add_tab_stop(Mm(8), WD_TAB_ALIGNMENT.LEFT)
        rn = q.add_run(f'{i:2d}:\t')
        rn.font.name = FONT; rn.font.size = Pt(SZ_ALG)
        ind = len(ln)-len(ln.lstrip())
        if ind:
            rs = q.add_run('\u00a0'*(ind+1))
            rs.font.name = FONT; rs.font.size = Pt(SZ_ALG)
        emit_code_line(q, ln.strip(), SZ_ALG)
    if body_lines:
        border(doc.paragraphs[-1], edges=('bottom',), sz=10)

    # 範本 §2.8 的程式碼區塊底下配一行方括號說明，不用框線。
    if full:
        p2 = rich_para(doc, '['+full.rstrip('.')+']', size=SZ_CAP,
                       before=2, after=8, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
        p2.paragraph_format.left_indent = Mm(4)
    return True


def emit_figure(doc, payload, n):
    inc = re.search(r'\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}', payload)
    cap = re.search(r'\\caption\{(.*)\}\s*\\label', payload, re.S)
    if inc:
        stem = os.path.splitext(inc.group(1))[0]
        svg = os.path.join(FIGDIR, stem+'.svg')
        png = os.path.join(FIGDIR, stem+'.png')
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(8)
        # 圖寬由 122 mm（滿版）收到 112 mm：高度等比縮 8 %，四張合計省
        # 約 18 mm。左右留白置中，Springer 允許且常見。
        add_vector_picture(p.add_run(), svg, png,
                           width=FIGW_OVERRIDE.get(stem, FIGW))
    if cap:
        caption(doc, f'{FIG_WORD} {n}. '+detex(cap.group(1)))


def emit_table(doc, payload, n):
    cap = re.search(r'\\caption\{(.*?)\}\s*\\label', payload, re.S)
    # 範本：表說在表**上**（與圖說相反）
    caption(doc, f'Table {n}. '+detex(cap.group(1) if cap else ''),
            before=8, after=3)
    tb = re.search(r'\\begin\{tabular\}\{[^}]*\}(.*?)\\end\{tabular\}',
                   payload, re.S)
    if not tb:
        return
    rows = []
    for line in tb.group(1).split(r'\\'):
        line = re.sub(r'\\(top|mid|bottom)rule', '', line).strip()
        if not line:
            continue
        rows.append([detex(c) for c in line.split('&')])
    if not rows:
        return
    t = doc.add_table(rows=len(rows), cols=max(len(r) for r in rows))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            c = t.cell(i, j)
            c.text = ''
            pr = c.paragraphs[0]
            if j > 0:
                pr.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            rich_runs(pr, cell, SZ_CAP, bold=(i == 0))
        # 範例 Table 1：標頭列用**上下兩條等長的線**夾起來，
        # 表格最底再一條；三條都必須是連續的（故用儲存格框線）。
        for j in range(len(t.columns)):
            if i == 0:
                cell_border(t.cell(i, j), top=8, bottom=8)
            elif i == len(rows)-1:
                cell_border(t.cell(i, j), bottom=8)
    para(doc, '', size=SZ_CAP, after=6)


def main():
    with open(TEX, encoding='utf-8') as fh:
        tex = fh.read()
    blocks, bib, num = parse(tex)

    doc = Document()
    setup(doc)

    title = re.search(r'\\title\{(.*?)\}\s*\n\s*\\titlerunning', tex, re.S)
    para(doc, detex(title.group(1)), size=SZ_TITLE, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, after=10)
    # ── 作者欄，嚴格照範本第 1 頁 ───────────────────────
    #   First Author¹*, Second Author¹, Third Author², and Fourth Author²
    #   單位編號與 * 都是**上標**；最後一位作者前要有 "and"；
    #   通訊作者以 * 標示（範本：「place an envelope icon (or any other
    #   pointer) next to the name of the corresponding author」）；
    #   email **另起一行、緊接在對應單位下方**。
    def sup(p, txt):
        r = p.add_run(txt)
        r.font.name = FONT; r.font.size = Pt(SZ_BODY)
        r.font.superscript = True

    def plain(p, txt, size=SZ_BODY):
        r = p.add_run(txt)
        r.font.name = FONT; r.font.size = Pt(size)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(6)
    authors = [('Cheng-Yu Li', '1', True), ('Chun-Hao Chen', '1', False),
               ('Cheng-Yuan Hung', '2', False),
               ('Yen-Jie Huang', '2', False)]
    for i, (name, aff, corr) in enumerate(authors):
        if i:
            plain(p, ', and ' if i == len(authors)-1 else ', ')
        plain(p, name)
        sup(p, aff+('*' if corr else ''))

    aff1 = para(doc, '', size=SZ_CAP, align=WD_ALIGN_PARAGRAPH.CENTER)
    r = aff1.add_run('1'); r.font.name = FONT; r.font.size = Pt(SZ_CAP)
    r.font.superscript = True
    plain(aff1, 'Department of Computer Science and Information '
          'Engineering, National Kaohsiung University of Science and '
          'Technology, Kaohsiung, Taiwan', SZ_CAP)
    para(doc, 'lkkyb555@gmail.com', size=SZ_CAP,
         align=WD_ALIGN_PARAGRAPH.CENTER)
    aff2 = para(doc, '', size=SZ_CAP, align=WD_ALIGN_PARAGRAPH.CENTER,
                after=10)
    r = aff2.add_run('2'); r.font.name = FONT; r.font.size = Pt(SZ_CAP)
    r.font.superscript = True
    plain(aff2, 'Opto-Electronics Technology Section, Energy and '
          'Agile System Department, Metal Industries Research & '
          'Development Centre, Kaohsiung, Taiwan', SZ_CAP)

    abst = re.search(r'\\begin\{abstract\}(.*?)\\keywords', tex, re.S)
    kw = re.search(r'\\keywords\{(.*?)\}', tex, re.S)
    p = para(doc, 'Abstract. ', size=SZ_CAP, bold=True)
    rich_runs(p, detex(abst.group(1)) if abst else '', SZ_CAP)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.left_indent = Mm(8)
    p.paragraph_format.right_indent = Mm(8)
    if kw:
        # \u7bc4\u672c\uff1a`Keywords:` \u6a19\u7c64\u672c\u8eab\u8981\u7c97\u9ad4\uff0c\u5f8c\u9762\u7684\u95dc\u9375\u8a5e\u4e0d\u7c97\u3002
        pk = para(doc, '', size=SZ_CAP, before=4, after=10)
        rk = pk.add_run('Keywords: ')
        rk.font.name = FONT; rk.font.size = Pt(SZ_CAP); rk.bold = True
        rich_runs(pk, detex(kw.group(1)).replace('and ', '\u00b7 '),
                  size=SZ_CAP)
        pk.paragraph_format.left_indent = Mm(8)
        pk.paragraph_format.right_indent = Mm(8)

    nsec = nfig = ntab = nlst = neq = 0
    for b in blocks:
        kind = b[0]
        if kind == 'sec':
            nsec += 1
            para(doc, f'{nsec}   {b[1]}', size=SZ_SEC, bold=True,
                 before=10, after=4)
        elif kind == 'sub':
            para(doc, b[1], size=SZ_SUB, bold=True, before=6, after=3)
        elif kind == 'run':
            p = para(doc, b[1]+'  ', size=SZ_BODY, bold=True, before=4)
            rich_runs(p, b[2], SZ_BODY)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        elif kind == 'p':
            rich_para(doc, b[1], align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=3)
        elif kind == 'li':
            rich_para(doc, '\u2022  '+b[1],
                      align=WD_ALIGN_PARAGRAPH.JUSTIFY, indent=5, after=3)
        elif kind == 'eq':
            # 範本 §2.6：公式置中、另起一行、上下留半行，編號加括號並
            # **靠右邊界**。靠右用定位停駐點，不是空白字元。
            neq += 1
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.space_before = pf.space_after = Pt(5)
            tabs = pf.tab_stops
            tabs.add_tab_stop(Mm(COLW/2), WD_TAB_ALIGNMENT.CENTER)
            tabs.add_tab_stop(Mm(COLW), WD_TAB_ALIGNMENT.RIGHT)
            r = p.add_run('\t'+b[1])
            r.font.name = FONT; r.font.size = Pt(SZ_BODY); r.italic = True
            r2 = p.add_run(f'\t({neq})')
            r2.font.name = FONT; r2.font.size = Pt(SZ_BODY)
        elif kind == 'equation':
            neq += 1
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.space_before = pf.space_after = Pt(5)
            pf.tab_stops.add_tab_stop(Mm(COLW/2), WD_TAB_ALIGNMENT.CENTER)
            pf.tab_stops.add_tab_stop(Mm(COLW), WD_TAB_ALIGNMENT.RIGHT)
            body = re.sub(r'\\label\{[^}]*\}', '', b[1])
            body = re.sub(r'\s+', ' ', body).strip().rstrip(',').strip()
            p.add_run('\t')
            math_runs(p, body, SZ_BODY)
            r2 = p.add_run(f'\t({neq})')
            r2.font.name = FONT; r2.font.size = Pt(SZ_BODY)
        elif kind == 'figure':
            if emit_listing(doc, b[1], nlst+1):
                nlst += 1
            else:
                nfig += 1; emit_figure(doc, b[1], nfig)
        elif kind == 'table':
            ntab += 1; emit_table(doc, b[1], ntab)

    para(doc, 'References', size=SZ_SEC, bold=True, before=10, after=4)
    for i, (key, txt) in enumerate(bib, 1):
        # DOI 切出來單獨排成超連結；其餘照舊走 rich_para（要保留下標）。
        head_txt, url = txt, ''
        m_doi = re.search(r'(https?://\S+)', txt)
        if m_doi:
            url = m_doi.group(1).rstrip('.')
            head_txt = txt[:m_doi.start()]
        p = rich_para(doc, f'{i}.  {head_txt}', size=SZ_CAP,
                      align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=2)
        if url:
            add_hyperlink(p, url, url, size=SZ_CAP, name=FONT)
        p.paragraph_format.left_indent = Mm(6)
        p.paragraph_format.first_line_indent = Mm(-6)

    doc.save(OUT)
    print(f'   ✓ {os.path.basename(OUT)}')
    print(f'     節 {nsec}   圖 {nfig}   表 {ntab}   程式列表 {nlst}   '
          f'公式 {neq}   參考文獻 {len(bib)}')


if __name__ == '__main__':
    print('══ main.tex → .docx ══\n')
    main()
