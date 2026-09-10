
# -*- coding: utf-8 -*-
"""把論文用到的四張圖打包成一份 PPT 交給陳老師（可編輯）。

每張圖一頁，優先插入 **SVG**：PowerPoint 2016 以後可以在圖上按右鍵
→「轉換成圖形」，把 SVG 拆成可個別編輯的方框與文字。若 python-pptx
這一版不吃 SVG，就退回 1200 dpi 的 PNG，並在頁面上標明向量原始檔
的位置，老師可以自行插入再轉換。

⚠ 圖 1(a) 是實機照片，本來就是點陣圖，轉成圖形後仍是一張影像。
"""
import os
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.util import Cm, Pt

import build_deck as B
from build_deck import BLUE, GREY, INK, W, chrome, page, put, textbox

FIG = B.FIG
OUT = os.path.join(B.HERE, 'decks', '論文圖檔_可編輯_2026-08-17.pptx')

# (論文圖號, 檔名主幹, 標題, 產生器)
FIGS = [
    ('Fig. 1', 'fig1_equipment', '設備照片與階梯式分壓架構',
     'docs/build/build_figpack.py 內組版；(b) 由 edge_backend/'
     'fig_cascade_narrow.py 產生'),
    ('Fig. 2', 'figD_device_pipeline', '壓力軌跡與挖掘流程',
     'edge_backend/fig_device_pipeline.py'),
    ('Fig. 3', 'figF_method_flow', '方法流程圖（含三個演算法的涵蓋範圍）',
     'edge_backend/fig_method_flow.py'),
    ('Fig. 4', 'figB_matched_baseline', '配對基準與偏誤分解',
     'edge_backend/degeneracy_invert.py'),
]


def put_fig(prs, no, stem, title, src):
    s = page(prs, '%s　%s' % (no, title), None)
    svg = os.path.join(FIG, stem + '.svg')
    png = os.path.join(FIG, stem + '.png')
    if not os.path.exists(png):
        png = os.path.join(B.HERE, '..', 'paper', stem + '.png')
    kind = 'PNG'
    try:                                     # 先試 SVG（可轉換成圖形）
        if os.path.exists(svg):
            pic = s.shapes.add_picture(svg, Cm(1.6), Cm(3.4),
                                       width=W - Cm(3.2))
            kind = 'SVG'
        else:
            raise FileNotFoundError
    except Exception:
        pic = s.shapes.add_picture(png, Cm(1.6), Cm(3.4),
                                   width=W - Cm(3.2))
    # 圖太高就改以高度為準重放
    if pic.top + pic.height > B.H - Cm(3.4):
        s.shapes._spTree.remove(pic._element)
        h = B.H - Cm(3.4) - Cm(3.4)
        src_img = svg if kind == 'SVG' else png
        pic = s.shapes.add_picture(src_img, Cm(1.6), Cm(3.4), height=h)
        pic.left = int((W - pic.width) / 2)
    tf = textbox(s, Cm(1.6), B.H - Cm(2.6), W - Cm(3.2), Cm(1.6))
    put(tf, [('原始程式：', 12, True, INK), (src, 12, False, GREY)],
        first=True, space_after=4)
    put(tf, [('向量檔：', 12, True, INK),
             ('docs/paper_figures/%s.svg（與 .pdf）' % stem, 12, False,
              GREY),
             ('　　本頁插入的是 %s' % kind, 12, False, BLUE)])


def cover(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tf = textbox(s, Cm(2.0), Cm(6.0), W - Cm(4.0), Cm(6.5))
    put(tf, [('ICEA 2026 論文圖檔', 34, True, INK)], first=True,
        space_after=12, align=PP_ALIGN.CENTER)
    put(tf, [('四張圖的可編輯原始檔', 20, False, INK)], space_after=16,
        align=PP_ALIGN.CENTER)
    put(tf, [('每張圖一頁。PowerPoint 2016 以後可在圖上按右鍵 →'
              '「轉換成圖形」，把向量圖拆成可個別編輯的方框與文字。',
              13, False, GREY)], space_after=8, align=PP_ALIGN.CENTER)
    put(tf, [('所有圖都由程式產生，改內容請改程式後重跑，'
              '不要只改 PPT —— 否則論文與簡報會不一致。', 13, False,
              BLUE)], align=PP_ALIGN.CENTER)
    chrome(s)


def main():
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, B.H
    cover(prs)
    for no, stem, title, src in FIGS:
        put_fig(prs, no, stem, title, src)
    prs.save(OUT)
    print('OK', OUT, '共', len(prs.slides._sldIdLst), '頁')


if __name__ == '__main__':
    main()
