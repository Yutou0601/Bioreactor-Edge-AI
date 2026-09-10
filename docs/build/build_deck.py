
# -*- coding: utf-8 -*-
"""報告簡報產生器（依定版論文重建，22 頁）。

版式沿用 8 月報告簡報的模板，逐項對齊：
  · 標題置中、黑色粗體標楷體，下方一條青色細線
  · 底部藍色色帶，右下白色頁碼
  · 表格藍底白字表頭 + 淺藍交錯列，全欄置中
  · 內文以「•」起首，關鍵詞紅色、次要術語藍色（模板的重點標示法）
  · 中文標楷體、西文 Times New Roman —— 兩者都是襯線體，清晰且嚴謹

內容原則（與模板無關，屬本次改版）：
  · 每頁一個主張，標題就是結論
  · 表格用於「對照」，項目符號用於「並列」
  · 需要保留的界線（不宣稱什麼）放進頁尾淺藍框，與正文分開

⚠ 一律用檔案寫入產生，不走 shell heredoc——heredoc 會吃掉反斜線與引號。
"""
import os
import re
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Cm, Pt

# ⚠ 2026-09-10 本檔從 docs/ 搬到 docs/build/。HERE 仍然要指 docs/，
#   否則產生的文件會掉進 build/ 裡。
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIG = os.path.join(HERE, 'paper_figures')
OUT = os.path.join(HERE, 'decks', '報告簡報_2026-08-14_定版論文.pptx')

# 模板字型：中文標楷體、西文 Times New Roman
CN, EN = '標楷體', 'Times New Roman'

INK = RGBColor(0x00, 0x00, 0x00)          # 標題與內文
RED = RGBColor(0xFF, 0x00, 0x00)          # 模板的重點紅
BLUE = RGBColor(0x1F, 0x6F, 0xB5)         # 模板的術語藍
GREY = RGBColor(0x59, 0x59, 0x59)
BAR = RGBColor(0x2E, 0x8B, 0xC0)          # 底部色帶
RULE = RGBColor(0x2A, 0xB6, 0xD8)         # 標題下細線
THEAD = RGBColor(0x2E, 0x9B, 0xD6)        # 表頭
TROW1 = RGBColor(0xDB, 0xE9, 0xF6)        # 表格奇數列
TROW2 = RGBColor(0xEA, 0xF2, 0xFA)        # 表格偶數列
BOXBG = RGBColor(0xF2, 0xF7, 0xFC)        # 頁尾保留框
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

W, H = Cm(33.87), Cm(19.05)               # 16:9
BAR_H = Cm(0.85)                          # 底部色帶高度
TOP = Cm(3.0)                             # 內容起始 y


def _font(run, size, bold=False, color=INK, italic=False):
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.italic = italic
    f.color.rgb = color
    f.name = EN
    # ⚠ 只設 name 會讓中文回退成新細明體，必須另設 eastAsia
    rPr = run._r.get_or_add_rPr()
    ea = rPr.makeelement(
        '{http://schemas.openxmlformats.org/drawingml/2006/main}ea', {})
    ea.set('typeface', CN)
    rPr.append(ea)


def textbox(slide, x, y, w, h, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Cm(0)
    tf.margin_top = tf.margin_bottom = Cm(0)
    return tf


def para(tf, first=False, space_after=6, align=PP_ALIGN.LEFT, level=0):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.space_after = Pt(space_after)
    p.alignment = align
    p.level = level
    return p


# ── 數學排版 ────────────────────────────────────────────────
# 下標／上標寫成 _{...} 與 ^{...}，例如：
#     'P(t) = P_{eq} + A e^{−kt} − r_{b} t'
#     'kg/cm^{2}'　'CO_{2} + 4H_{2} → CH_{4} + 2H_{2}O'
# 產生的是 DrawingML 的 baseline 屬性——真正的上下標，不是縮小的字。
SUB, SUP = -25000, 30000
GREEK = 'αβγδεζηθικλμνξοπρστυφχψωΓΔΘΛΞΠΣΦΨΩ'
_SCRIPT = re.compile(r'([_^])\{([^}]*)\}')
_WORD = re.compile('[A-Za-z]+|[' + GREEK + ']')


def _segments(text):
    """拆成 (文字, baseline) 序列。"""
    out, i = [], 0
    for m in _SCRIPT.finditer(text):
        if m.start() > i:
            out.append((text[i:m.start()], 0))
        out.append((m.group(2), SUB if m.group(1) == '_' else SUP))
        i = m.end()
    if i < len(text):
        out.append((text[i:], 0))
    return out or [(text, 0)]


def _add(p, text, size, bold, color, italic, base):
    if not text:
        return
    r = p.add_run()
    _font(r, 1)                        # 佔位，避免空段
    r.text = text
    _font(r, size, bold, color, italic)
    if base:
        r._r.get_or_add_rPr().set('baseline', str(base))


# 上下標裡維持正體的標籤（它們是名稱，不是變數的乘積）
LABELS = {'eq', 'max', 'min', 'tot', 'obs', 'perm', 'La', 'bio'}
# 散文裡出現的多字母變數乘積，仍要斜體
VARS = {'kt', 'kT'}
# 單一字母但其實是名稱，維持正體。⚠ 本簡報的 C 專指「資料集 C」；
# 若日後 C 被用來表示濃度，要把它從這裡拿掉。
NAMES = {'C'}


def emit(p, text, size, bold=False, color=INK, italic=False):
    """把一段文字放進段落，自動處理上下標與變數斜體。

    斜體判準（與論文一致：變數斜體、函數與標籤正體）：

    基線文字
      · 單一拉丁或希臘字母 → 斜體：k、c、p、N、β、ρ
      · 兩字母以上 → 正體：PT、ORP、AUC、cm、hr、pH
      · 後面緊接數字 → 正體，那是編號：V1、V4
      · 自然對數的底 e → 正體（常數）
      · ⚠ 緊鄰「純數字下標」者 → 正體，那是化學元素不是變數：
        H_{2}、H_{2}O 的 H 與 O 必須正體，否則會被讀成兩個變數相乘

    上下標內容
      · 純數字 → 正體：cm^{2}、H_{2}
      · LABELS 內的名稱 → 正體：P_{eq}
      · 其餘 → 斜體：r_{b} 的 b、e^{−kt} 的 k 與 t
    """
    segs = _segments(text)
    for n, (seg, base) in enumerate(segs):
        if base:                                   # 上標／下標
            up = seg.isdigit() or seg in LABELS
            _add(p, seg, size, bold, color, italic or not up, base)
            continue
        prev_num = n and segs[n - 1][1] and segs[n - 1][0].isdigit()
        next_num = (n + 1 < len(segs) and segs[n + 1][1]
                    and segs[n + 1][0].isdigit())
        pos = 0
        for m in _WORD.finditer(seg):
            if m.start() > pos:
                _add(p, seg[pos:m.start()], size, bold, color, italic,
                     base)
            tok, nxt = m.group(0), seg[m.end():m.end() + 1]
            chem = ((next_num and m.end() == len(seg))     # H_{2}
                    or (prev_num and m.start() == 0))      # H_{2}O 的 O
            var = (tok in VARS or
                   (len(tok) == 1 and tok != 'e' and tok not in NAMES
                    and not nxt.isdigit() and not chem))
            _add(p, tok, size, bold, color, italic or var, base)
            pos = m.end()
        _add(p, seg[pos:], size, bold, color, italic, base)


def put(tf, chunks, first=False, space_after=6, align=PP_ALIGN.LEFT,
        level=0):
    """chunks = [(文字, 級數, 粗體, 顏色), ...] 同一段內混排。"""
    p = para(tf, first, space_after, align, level)
    for c in chunks:
        emit(p, c[0], c[1], c[2] if len(c) > 2 else False,
             c[3] if len(c) > 3 else INK)
    return p


def rect(slide, x, y, w, h, color):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    s.fill.solid()
    s.fill.fore_color.rgb = color
    s.line.fill.background()
    s.shadow.inherit = False
    return s


def chrome(slide, n=None):
    """模板的頁面外框：底部藍色色帶 + 右下白色頁碼。"""
    rect(slide, Cm(0), H - BAR_H, W, BAR_H, BAR)
    if n is not None:
        tf = textbox(slide, W - Cm(2.4), H - Cm(0.78), Cm(1.6), Cm(0.6))
        put(tf, [(str(n), 11, False, WHITE)], first=True,
            align=PP_ALIGN.RIGHT)


PAGE_NO = [1]                             # 封面為第 1 頁但不印頁碼


def nextno():
    """依序取下一個頁碼。

    ⚠ 沒有走 page() 的版面（謝詞、附錄封面）以前是手打頁碼或乾脆不印，
      結果 PAGE_NO 沒有遞增，後面每一頁都往前偏。一律改用這個函式。
    """
    PAGE_NO[0] += 1
    return PAGE_NO[0]


def page(prs, title, sub=None, n=None):
    """一頁的骨架：置中標題、青色細線、底部色帶、頁碼。

    ⚠ 頁碼一律由 PAGE_NO 依序指派，呼叫端傳入的 n 只作閱讀用而不生效——
      這樣在中間插入或抽掉投影片時，不必回頭改後面每一頁的編號。
    """
    s = prs.slides.add_slide(prs.slide_layouts[6])
    PAGE_NO[0] += 1
    n = PAGE_NO[0]
    tf = textbox(s, Cm(1.2), Cm(0.5), W - Cm(2.4), Cm(1.5))
    put(tf, [(title, 28, True, INK)], first=True, space_after=0,
        align=PP_ALIGN.CENTER)
    rect(s, Cm(0.6), Cm(2.12), W - Cm(1.2), Cm(0.05), RULE)
    if sub:
        t2 = textbox(s, Cm(1.4), Cm(2.34), W - Cm(2.8), Cm(0.7))
        put(t2, [(sub, 13, False, GREY)], first=True,
            align=PP_ALIGN.CENTER)
    chrome(s, n)
    return s


def table(slide, x, y, w, rows, widths=None, fs=13, hi_rows=(),
          hi_col=None):
    """模板表格：藍底白字表頭、淺藍交錯列、全欄置中。

    hi_rows 以紅色粗體強調；給 hi_col 則只強調該欄。
    """
    nr, nc = len(rows), len(rows[0])
    gt = slide.shapes.add_table(nr, nc, x, y, w, Cm(0.95 * nr)).table
    gt.first_row = False                 # 關掉 PPT 內建樣式，改自己上色
    gt.horz_banding = False
    if widths:
        for j, ww in enumerate(widths):
            gt.columns[j].width = ww
    for i, row in enumerate(rows):
        gt.rows[i].height = Cm(1.05 if i == 0 else 0.92)
        for j, val in enumerate(row):
            cell = gt.cell(i, j)
            cell.margin_left = cell.margin_right = Cm(0.2)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = (
                THEAD if i == 0 else (TROW1 if i % 2 else TROW2))
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            emph = i and (i in hi_rows) and (hi_col is None or j == hi_col)
            emit(p, str(val), fs, bold=(i == 0 or emph),
                 color=(WHITE if i == 0 else (RED if emph else INK)))
    return gt


def note(slide, text, y=None, color=RED, fs=13):
    """頁尾保留框：講界線、講不宣稱什麼。與正文分開。"""
    y = y or (H - Cm(3.6))
    h = Cm(2.4)
    box = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(1.2), y,
                                 W - Cm(2.4), h)
    box.fill.solid()
    box.fill.fore_color.rgb = BOXBG
    box.line.color.rgb = RULE
    box.line.width = Pt(0.75)
    box.shadow.inherit = False
    tf = textbox(slide, Cm(1.7), y + Cm(0.3), W - Cm(3.4), h - Cm(0.6),
                 anchor=MSO_ANCHOR.MIDDLE)
    put(tf, [(text, fs, False, color)], first=True)


FIG_NO = [0]


def caption(slide, x, y, w, no, text, fs=11.5):
    """圖說。每一張嵌圖都要有，格式為「圖 N.　說明」。

    ⚠ 圖號同頁碼，一律由 FIG_NO 依序指派——手動編號我已經編錯過一次
      （兩張圖同時是「圖 5」）。呼叫端傳入的 no 只作閱讀用。
    """
    FIG_NO[0] += 1
    tf = textbox(slide, x, y, w, Cm(0.7))
    put(tf, [('圖 %d.　' % FIG_NO[0], fs, True, BLUE),
             (text, fs, False, GREY)],
        first=True, align=PP_ALIGN.CENTER)
    return tf


def bullets(tf, items, fs=16, first=True, gap=10):
    """模板以「•」起首。items 可為字串或 chunk 串列。"""
    for k, it in enumerate(items):
        chunks = it if isinstance(it, list) else [('• ' + it, fs)]
        put(tf, chunks, first=(first and k == 0), space_after=gap)


def pic(slide, name, x, y, w):
    p = os.path.join(FIG, name)
    if os.path.exists(p):
        return slide.shapes.add_picture(p, x, y, width=w)
    return None
