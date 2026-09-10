# -*- coding: utf-8 -*-
"""
Fig. 1 系統架構圖（向量輸出，論文用，英文標籤）
════════════════════════════════════════════════════════════════════════

設計要求（見 docs/圖表與LaTeX待辦清單_2026-08-05.md）：
  · 向量格式（PDF），不可用點陣
  · 黑白可辨識——模組以邊框樣式與填色深淺區分，不單靠顏色
  · 字級印出後 ≥ 6 pt

內容上必須與改版後的論文一致：主論點是「自助校準認證估計量、不認證模型類」，
因此架構圖畫**兩道閘門**（Alg.3 同模型虛無 / Alg.4 異模型類虛無），
而不是只畫一道 calibration gate。上排為線上路徑，下排為認證路徑。

輸出 -> docs/analysis_charts_3batch/fig1_architecture.pdf (+ .png 供校對)
"""
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.path import Path
from matplotlib.patches import PathPatch

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                   'docs', 'analysis_charts_3batch'))

INK = '#1A1A1A'
MUTED = '#6E6E6E'
FILL_PLANT = '#F2F2F2'
FILL_EDGE = '#FFFFFF'
FILL_GATE = '#EAF3FA'
FILL_OUT = '#F0F6EE'
LW = 1.1

# LNCS 單欄文字寬約 122 mm = 4.80 in。圖必須**以最終尺寸繪製**，否則排版縮放
# 會把字級一併縮小：7.2 in 的圖縮到 4.8 in 是 0.67 倍，7 pt 會變成 4.7 pt，
# 低於「印出後 ≥ 6 pt」的要求。故 figsize 寬度固定 4.8 in，字級即為印出字級。
FIG_W = 4.80
BODY = 6.0
TITLE = 6.8


def box(ax, x, y, w, h, title, body='', fill=FILL_EDGE, ls='-', lw=LW,
        tcol=INK, bold=True):
    ax.add_patch(FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h,
        boxstyle='round,pad=0.006,rounding_size=0.012',
        linewidth=lw, edgecolor=INK, facecolor=fill, linestyle=ls, zorder=2))
    if body:
        ax.text(x, y + h * 0.20, title, ha='center', va='center',
                fontsize=TITLE, color=tcol,
                fontweight='bold' if bold else 'normal', zorder=3)
        ax.text(x, y - h * 0.19, body, ha='center', va='center',
                fontsize=BODY, color=MUTED, linespacing=1.45, zorder=3)
    else:
        ax.text(x, y, title, ha='center', va='center', fontsize=TITLE,
                color=tcol, fontweight='bold' if bold else 'normal', zorder=3)


def arrow(ax, p0, p1, ls='-', col=INK, lw=LW):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle='-|>', mutation_scale=9,
                                 linewidth=lw, color=col, linestyle=ls,
                                 shrinkA=0, shrinkB=0, zorder=4))


def elbow(ax, pts, col=INK, lw=LW):
    """正交折線，末端帶箭頭。"""
    codes = [Path.MOVETO] + [Path.LINETO] * (len(pts) - 1)
    ax.add_patch(PathPatch(Path(pts, codes), fill=False, edgecolor=col,
                           linewidth=lw, zorder=4))
    arrow(ax, pts[-2], pts[-1], col=col, lw=lw)


def main():
    fig, ax = plt.subplots(figsize=(FIG_W, 3.05))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis('off')

    yt, yb = 0.700, 0.215          # 上下兩排的中心
    h = 0.215

    # ── 內生激發：補氣回饋到反應器本身（畫在最上方，避開所有框）──
    top = yt + h / 2               # 0.7925
    ax.add_patch(PathPatch(Path(
        [(0.115, top), (0.115, top + 0.075), (0.300, top + 0.075),
         (0.300, top)],
        [Path.MOVETO, Path.LINETO, Path.LINETO, Path.LINETO]),
        fill=False, edgecolor=MUTED, linewidth=LW, linestyle=(0, (4, 2)),
        zorder=1))
    arrow(ax, (0.300, top + 0.036), (0.300, top + 0.004), col=MUTED)
    ax.text(0.330, top + 0.075,
            'endogenous excitation:\n2.2 relaxations per day',
            ha='left', va='center', fontsize=BODY, color=MUTED,
            linespacing=1.4)

    # ── 上排：線上路徑 ──────────────────────────────────────────
    box(ax, 0.122, yt, 0.228, h, 'Reactor',
        'threshold-triggered\nrefill 0.9 → 1.2', fill=FILL_PLANT)
    box(ax, 0.380, yt, 0.232, h, 'Signals',
        'pressure, ORP, pH\n1-min sampling')
    box(ax, 0.638, yt, 0.230, h, 'Alg. 1',
        'streaming cycle\nsegmentation')
    box(ax, 0.888, yt, 0.220, h, 'Alg. 2',
        'joint estimate\n$\\rightarrow \\hat{r}_b$')

    for x0, x1 in ((0.236, 0.264), (0.496, 0.523), (0.753, 0.778)):
        arrow(ax, (x0, yt), (x1, yt))

    # 被排除的訊號：掛在 Trusted signals 正下方，位於連接線之上
    ex_y = 0.505
    ax.add_patch(PathPatch(Path([(0.380, yt - h / 2), (0.380, ex_y + 0.040)],
                                [Path.MOVETO, Path.LINETO]),
                           fill=False, edgecolor=MUTED, linewidth=0.9,
                           linestyle=(0, (3, 2)), zorder=1))
    box(ax, 0.380, ex_y, 0.335, 0.080,
        'CO₂ / CH₄ excluded (vent-only)',
        fill='#FFFFFF', ls=(0, (3, 2)), lw=0.9, tcol=MUTED, bold=False)

    # ── 上排 → 下排 ─────────────────────────────────────────────
    ymid = 0.415
    elbow(ax, [(0.888, yt - h / 2), (0.888, ymid), (0.115, ymid),
               (0.115, yb + h / 2 + 0.004)])
    ax.text(0.878, ymid + 0.018, '$\\hat{r}_b$, not yet reportable',
            ha='right', va='bottom', fontsize=BODY, color=MUTED)

    # ── 下排：認證路徑 ──────────────────────────────────────────
    box(ax, 0.115, yb, 0.235, h, 'Alg. 3',
        'null: SAME model\ncertifies estimator', fill=FILL_GATE)
    box(ax, 0.392, yb, 0.255, h, 'Alg. 4',
        'null: OTHER class\ncertifies model', fill=FILL_GATE, lw=1.7)
    box(ax, 0.676, yb, 0.222, h, 'Gate',
        'both must pass,\nelse unidentified', fill=FILL_OUT)
    box(ax, 0.912, yb, 0.155, h, 'Upstream', '', fill=FILL_PLANT)

    arrow(ax, (0.2225, yb), (0.2675, yb))
    arrow(ax, (0.5125, yb), (0.5695, yb))
    arrow(ax, (0.7745, yb), (0.8345, yb))

    # 本研究的實測結論
    ax.text(0.5, 0.012,
            'here: Alg. 3 passes (p < 0.005), Alg. 4 does not (p = 0.40)'
            '  →  $r_b$ not identified',
            ha='center', va='bottom', fontsize=TITLE, color=INK,
            fontweight='bold')

    fig.savefig(f'{OUT}/fig1_architecture.pdf', bbox_inches='tight',
                pad_inches=0.02)
    fig.savefig(f'{OUT}/fig1_architecture.png', dpi=300, bbox_inches='tight',
                pad_inches=0.02)
    plt.close(fig)
    print(f'輸出 → {OUT}/fig1_architecture.pdf (+ .png)')


if __name__ == '__main__':
    main()
