
# -*- coding: utf-8 -*-
"""§4 的方法架構圖（Methodology Framework Figure）。

結構依指導教授 2026-08-24 核可：

    Pressure cycles
        ↓
    Algorithm 1（唯一產生數字的一步）
        ↓
    per-cycle (r̂_b, k̂)
        ↓  分成兩條並行的驗證
    Algorithm 2 ┆ Algorithm 3
        ↓  匯聚
    Calibrated rate, with its accuracy

⚠ 2026-08-24 由橫向改為**縱向、單欄**。橫向版寬 6.89"，必須以連續分節符
  跨欄；Word 一旦塞不下就把整塊推到次頁，實測在圖上方留下約 0.3 頁空白。
  縱向版寬 3.27"（＝ACM 單欄），直接排在文字流裡，結構上不可能產生
  那種空白，佔的欄吋也更少。橫向版留存於
  scratchpad/figF_horizontal_backup.py。

⚠ Algorithm 2 與 3 **不產生估計值**，只回答關於 Algorithm 1 那個數字的
  兩個問題。圖上必須看出主從，不能三者等高。
⚠ 端點裁切、ORP、C2ST 為補充檢核，降為圖下的附註。
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from fig_pressure_cascade import FIGDIR
from paper_style import C, FS_NOTE, FS_SMALL, apply, save

WCOL = 3.27          # ACM 單欄寬（in）


def box(ax, x, y, w, h, cap, sub=None, fill=None, edge=None, lw=.9):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle='round,pad=0.03,rounding_size=0.09',
        facecolor=fill or C['fill'], edgecolor=edge or C['main'],
        lw=lw, zorder=2))
    cy = y + h / 2
    if sub:
        ax.text(x + w / 2, cy + .19, cap, ha='center', va='center',
                fontsize=FS_NOTE, zorder=5)
        ax.text(x + w / 2, cy - .19, sub, ha='center', va='center',
                fontsize=FS_SMALL, color=C['main'], zorder=5)
    else:
        ax.text(x + w / 2, cy, cap, ha='center', va='center',
                fontsize=FS_NOTE, zorder=5)


def arr(ax, p, q):
    ax.add_patch(FancyArrowPatch(
        p, q, arrowstyle='-|>', mutation_scale=6.0, lw=.9,
        color=C['main'], shrinkA=0.5, shrinkB=0.5, zorder=1))


def line(ax, xs, ys):
    ax.plot(xs, ys, lw=.9, color=C['main'], solid_joinstyle='miter',
            zorder=1)


def main():
    apply()
    fig, ax = plt.subplots(figsize=(WCOL, 3.42))
    H, GAP = 0.98, 0.52
    X, W = 0.40, 9.20
    VAL = '#DDE8F3'

    # ⚠ 第 2→3 列的間距要加大：Algorithm 1 的標籤就站在那個空隙裡，
    #   用一般間距的話它會與虛線框的上緣、以及上一格的下緣同時相犯。
    GAP2 = GAP + 0.42
    tops = [10.60, 10.60 - (H + GAP),
            10.60 - (H + GAP) - (H + GAP2),
            10.60 - (H + GAP) - (H + GAP2) - (H + GAP)]
    rows = [('Pressure log', '1/min, 0.01 step'),
            ('Segment at refills', '280 descents'),
            ('Curvature screen', r'$c \geq 0.45$, 239 kept'),
            ('Profiled least squares', r'per-cycle $\hat{r}_b,\ \hat{k}$')]
    for y, (cap, sub) in zip(tops, rows):
        box(ax, X, y, W, H, cap, sub)
    # 箭頭一律由上一格的底邊畫到下一格的頂邊，間距不同也不會出錯
    for i in range(3):
        arr(ax, (X + W / 2, tops[i]), (X + W / 2, tops[i + 1] + H))

    # Algorithm 1 的涵蓋範圍：虛線框把預篩與擬合兩格圈起來。
    # 縱向版用框而非托架——托架在窄欄裡會與下降箭頭相犯。
    top, bot = tops[2] + H, tops[3]
    ax.add_patch(FancyBboxPatch(
        (X - .26, bot - .10), W + .52, top - bot + .20,
        boxstyle='round,pad=0.02,rounding_size=0.08',
        facecolor='none', edgecolor=C['accent'], lw=.8, ls=(0, (3, 2)),
        zorder=3))
    # 標籤置於加大的空隙正中：上距「Segment at refills」的底邊、
    # 下距虛線框的上緣都留出一個字高以上，兩邊都不相犯。
    ax.text(X + W, top + (GAP2 - .10) / 2 + .05,
            'Algorithm 1: the estimator', ha='right',
            va='center', fontsize=FS_SMALL, fontweight='bold',
            color=C['accent'], zorder=4)

    # ── 分岔 ────────────────────────────────────────────────
    SP = tops[3] - GAP * .52
    yv = tops[3] - GAP - 1.16
    cxL, cxR = X + 2.25, X + W - 2.25
    line(ax, [X + W / 2, X + W / 2], [tops[3], SP])
    line(ax, [cxL, cxR], [SP, SP])
    for cx in (cxL, cxR):
        arr(ax, (cx, SP), (cx, yv + 1.16))

    box(ax, X - .10, yv, 4.40, 1.16, 'Algorithm 2', 'degeneracy', fill=VAL)
    box(ax, X + 4.90, yv, 4.40, 1.16, 'Algorithm 3', 'physics-only',
        fill=VAL)
    for cx, a, b in ((cxL, 'How much is', 'the estimator?'),
                     (cxR, 'Could physics', 'alone do it?')):
        ax.text(cx, yv - .30, a, ha='center', va='center',
                fontsize=FS_SMALL, color=C['main'])
        ax.text(cx, yv - .62, b, ha='center', va='center',
                fontsize=FS_SMALL, color=C['main'])

    # ── 匯聚 ────────────────────────────────────────────────
    MG = yv - .98
    yf = MG - .44 - H
    line(ax, [X + .50, X + .50], [yv, MG])
    line(ax, [X + W - .50, X + W - .50], [yv, MG])
    line(ax, [X + .50, X + W - .50], [MG, MG])
    arr(ax, (X + W / 2, MG), (X + W / 2, yf + H))
    box(ax, X, yf, W, H, r'Calibrated $r_b$', '0.0126 [0.0112, 0.0142]',
        fill='white', edge=C['accent'], lw=1.1)

    ax.text(X + W / 2, yf - .38, 'Further checks: endpoint trimming,',
            ha='center', va='center', fontsize=FS_SMALL, color=C['main'])
    ax.text(X + W / 2, yf - .70, 'ORP terciles, classifier two-sample test',
            ha='center', va='center', fontsize=FS_SMALL, color=C['main'])

    ax.set_xlim(-.30, 10.30)
    ax.set_ylim(yf - .98, 10.60 + H + .55)
    ax.axis('off')
    fig.tight_layout(pad=0.06)
    save(fig, 'figF_method_flow', FIGDIR)


if __name__ == '__main__':
    main()
