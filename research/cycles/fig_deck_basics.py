# -*- coding: utf-8 -*-
"""簡報的「先看懂這個」三張示意圖（2026-09-21）。

════════════════════════════════════════════════════════════════════════
為什麼要補這三張

  原本的簡報預設讀者已經知道反應器長什麼樣、為什麼壓力會下降、
  以及「進料比 = 反應計量比」有什麼特別。對完全不熟的人，這三件事
  才是真正的門檻——後面所有結論都建立在它們上面。

  這三張是**示意圖不是資料圖**：沒有座標軸、沒有統計，只解釋機制。

    A　反應器怎麼運作（容器剖面 + 壓力鋸齒）
    B　氣體可能去哪裡（三條途徑，含分子數）
    C　為什麼 1:4 是關鍵（守恆論證，全案樞紐）

輸出 -> docs/analysis_charts_3batch/deck0a~0c_*.png
"""
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                          # noqa: E402
from matplotlib.patches import (Circle, FancyArrowPatch, FancyBboxPatch,  # noqa: E402
                                Rectangle)
from matplotlib import rcParams                          # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (                      # noqa: E402
    BLUE, YELLOW, AQUA, RED, INK, INK2, MUTED, BASELINE, OUT)

rcParams.update({'font.size': 15, 'axes.titlesize': 19})
FIGW = 12.0
GAS = '#eaf3fb'          # 頂空底色
LIQ = '#dcefe4'          # 液體底色


def blank(ax):
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    return ax


def save(fig, name):
    p = os.path.join(OUT, name + '.png')
    fig.savefig(p)
    plt.close(fig)
    print('  ->', name + '.png')


def arrow(ax, p0, p1, color, lw=2.4, style='-|>', rad=0.0):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle=style, color=color,
                                 lw=lw, mutation_scale=22,
                                 connectionstyle='arc3,rad=%.2f' % rad,
                                 zorder=6))


# ═══════════════════════════════════════════════════════════════
def deck0a_reactor():
    """A　反應器怎麼運作。左：容器剖面；右：壓力鋸齒。"""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(FIGW, 5.4),
                                 gridspec_kw={'wspace': 0.18,
                                              'width_ratios': [1, 1.25]})
    # ── 左：剖面 ──
    blank(a1); a1.set_xlim(0, 10); a1.set_ylim(0, 10)
    a1.add_patch(FancyBboxPatch((2.2, 1.2), 5.6, 7.0, boxstyle='round,pad=0.12',
                                fc=LIQ, ec=INK, lw=2.4, zorder=1))
    a1.add_patch(Rectangle((2.2, 4.9), 5.6, 3.3, fc=GAS, ec='none', zorder=2))
    a1.plot([2.2, 7.8], [4.9, 4.9], color=INK, lw=1.8, zorder=3)

    rng = np.random.default_rng(3)
    for _ in range(26):                                   # 頂空的氣體分子
        a1.add_patch(Circle((rng.uniform(2.6, 7.4), rng.uniform(5.2, 7.9)),
                            0.13, fc=BLUE, ec='none', alpha=0.75, zorder=4))
    for _ in range(34):                                   # 液體裡的菌
        a1.add_patch(Circle((rng.uniform(2.6, 7.4), rng.uniform(1.6, 4.5)),
                            0.10, fc=AQUA, ec='none', alpha=0.85, zorder=4))

    a1.text(5.0, 7.6, '頂空（氣體）', color=INK, fontsize=16, fontweight='bold',
            ha='center', va='center')
    a1.text(5.0, 0.75, '液體（含微生物）', color=INK, fontsize=16,
            fontweight='bold', ha='center', va='top')

    # 氣泵：把頂空的氣打進液體
    arrow(a1, (7.9, 6.6), (8.9, 6.6), MUTED, lw=2.6)
    # ⚠ 直線要在圓圈之外斷開，否則線會穿過「泵」字
    arrow(a1, (8.9, 6.6), (8.9, 5.25), MUTED, lw=2.6, style='-')
    arrow(a1, (8.9, 3.95), (8.9, 2.6), MUTED, lw=2.6, style='-')
    arrow(a1, (8.9, 2.6), (7.9, 2.6), MUTED, lw=2.6)
    a1.add_patch(Circle((8.9, 4.6), 0.58, fc='white', ec=MUTED, lw=2.4, zorder=7))
    a1.text(8.9, 4.6, '泵', color=MUTED, fontsize=15, fontweight='bold',
            ha='center', va='center', zorder=8)
    a1.text(9.6, 4.6, '把氣打進\n液體裡', color=MUTED, fontsize=13,
            ha='left', va='center')

    # 補氣與排氣
    arrow(a1, (0.5, 7.4), (2.1, 7.4), YELLOW, lw=3.0)
    a1.text(0.4, 7.9, '補氣\nCO₂ + H₂', color=YELLOW, fontsize=14,
            fontweight='bold', ha='left', va='bottom')
    arrow(a1, (6.6, 8.25), (6.6, 9.4), RED, lw=3.0)
    a1.text(6.9, 9.4, '排氣\n（人工）', color=RED, fontsize=14,
            fontweight='bold', ha='left', va='top')
    a1.set_title('a　反應器長什麼樣', color=INK, fontweight='bold', loc='left',
                 pad=12)

    # ── 右：壓力鋸齒 ──
    blank(a2)
    # 只畫 4 個循環：畫太密就看不出「一個循環」是什麼
    t, y, cur, up = [], [], 1.17, False
    for k in range(600):
        t.append(k / 100)
        y.append(cur)
        cur += 0.09 if up else -0.0021
        if up and cur >= 1.17:
            cur, up = 1.17, False
        if not up and cur <= 0.92:
            up = True
    a2.plot(t, y, color=INK, lw=3.0)
    a2.axhline(1.17, color=YELLOW, lw=2.0, ls='--')
    a2.axhline(0.92, color=BLUE, lw=2.0, ls='--')
    a2.set_ylim(0.80, 1.34)
    a2.set_xlim(0, 6)
    a2.text(6.0, 1.185, '補到滿（約 1.17）', color=YELLOW, fontsize=15,
            fontweight='bold', ha='right', va='bottom')
    a2.text(6.0, 0.905, '掉到這裡就自動補（約 0.92）', color=BLUE, fontsize=15,
            fontweight='bold', ha='right', va='top')
    a2.annotate('壓力慢慢下降\n= 氣體正在消失', xy=(1.55, 1.02), xytext=(2.5, 1.30),
                color=RED, fontsize=16, fontweight='bold', ha='left', va='top',
                arrowprops=dict(arrowstyle='->', color=RED, lw=2.2))
    a2.annotate('', xy=(0.02, 0.858), xytext=(1.24, 0.858),
                arrowprops=dict(arrowstyle='<->', color=INK2, lw=2.0))
    a2.text(0.63, 0.838, '一個循環', color=INK2, fontsize=14.5,
            ha='center', va='top')
    a2.set_title('b　壓力就一直這樣上上下下', color=INK, fontweight='bold',
                 loc='left', pad=12)
    save(fig, 'deck0a_reactor')


# ═══════════════════════════════════════════════════════════════
def deck0b_fates():
    """B　氣體可能去哪裡：三條途徑，含分子數。"""
    fig, ax = plt.subplots(figsize=(FIGW, 5.8))
    blank(ax); ax.set_xlim(0, 12); ax.set_ylim(0, 10.2)

    ax.add_patch(FancyBboxPatch((0.3, 3.6), 2.6, 2.6,
                                boxstyle='round,pad=0.14', fc=GAS,
                                ec=INK, lw=2.2))
    ax.text(1.6, 5.7, '容器裡的氣', color=INK, fontsize=17, fontweight='bold',
            ha='center', va='center')
    ax.text(1.6, 4.8, 'CO₂ 與 H₂\n依 1 : 4', color=INK2, fontsize=15,
            ha='center', va='center')

    rows = [
        (7.6, AQUA, '① 被微生物變成甲烷',
         'CO₂ + 4 H₂ → CH₄ + 2 H₂O（水是液體）\n'
         '氣體分子 5 個進、1 個出 → 淨少 4 個 → 壓力掉'),
        (4.9, YELLOW, '② 溶進液體裡',
         '二氧化碳的溶解度約是氫氣的 44 倍\n'
         '→ 會優先帶走二氧化碳'),
        (2.2, RED, '③ 漏掉了',
         '氫氣是最小的分子，容易穿過管件與墊片\n'
         '→ 會優先帶走氫氣'),
    ]
    for y, col, title, body in rows:
        arrow(ax, (3.05, 4.9), (4.35, y), col, lw=3.0, rad=0.0)
        ax.add_patch(FancyBboxPatch((4.5, y - 1.02), 7.2, 2.04,
                                    boxstyle='round,pad=0.12', fc='white',
                                    ec=col, lw=2.4))
        ax.text(4.85, y + 0.60, title, color=col, fontsize=17,
                fontweight='bold', ha='left', va='center')
        ax.text(4.85, y - 0.30, body, color=INK, fontsize=14.5,
                ha='left', va='center')

    ax.text(6.0, 10.1, '壓力下降只告訴你「氣體少了」，不會告訴你少到哪去',
            color=INK, fontsize=18, fontweight='bold', ha='center', va='top')
    ax.text(6.0, 0.28, '三條路都讓壓力下降 —— 這就是為什麼分不開',
            color=INK2, fontsize=15.5, ha='center', va='bottom')
    save(fig, 'deck0b_fates')


# ═══════════════════════════════════════════════════════════════
def deck0c_ratio():
    """C　為什麼 1:4 是關鍵。守恆論證，全案樞紐。"""
    fig, ax = plt.subplots(figsize=(FIGW, 6.0))
    blank(ax); ax.set_xlim(0, 12); ax.set_ylim(0, 10)

    def balls(x0, y0, n_co2, n_h2, scale=1.0):
        """畫出 CO2（黃）與 H2（藍）的分子。"""
        r = 0.17 * scale
        for i in range(n_co2):
            ax.add_patch(Circle((x0 + i * 0.44 * scale, y0), r,
                                fc=YELLOW, ec='none', zorder=5))
        for i in range(n_h2):
            ax.add_patch(Circle((x0 + i * 0.44 * scale, y0 - 0.55 * scale), r,
                                fc=BLUE, ec='none', zorder=5))

    ax.text(6.0, 9.7, '進料的比例，剛好就是反應吃掉的比例',
            color=INK, fontsize=19, fontweight='bold', ha='center', va='top')

    steps = [
        (8.3, '補進去', 1, 4, INK2),
        (6.3, '反應吃掉', 1, 4, AQUA),
        (4.3, '所以剩下的', 1, 4, BLUE),
    ]
    for y, lab, nc, nh, col in steps:
        ax.text(2.6, y - 0.28, lab, color=col, fontsize=17, fontweight='bold',
                ha='right', va='center')
        balls(3.0, y, nc, nh)
        ax.text(5.6, y, ' ← 二氧化碳 1 個', color=YELLOW, fontsize=14.5,
                ha='left', va='center')
        ax.text(5.6, y - 0.55, ' ← 氫氣 4 個', color=BLUE, fontsize=14.5,
                ha='left', va='center')
    for y0, y1 in ((7.6, 6.95), (5.6, 4.95)):
        arrow(ax, (2.0, y0), (2.0, y1), MUTED, lw=2.4)

    ax.add_patch(FancyBboxPatch((8.6, 3.5), 3.1, 5.4,
                                boxstyle='round,pad=0.14', fc='#fdf3f3',
                                ec=RED, lw=2.6))
    ax.text(10.15, 8.4, '所以', color=RED, fontsize=17, fontweight='bold',
            ha='center', va='center')
    ax.text(10.15, 7.1, '剩下的比例\n永遠是 1 : 4', color=RED, fontsize=18,
            fontweight='bold', ha='center', va='center')
    ax.text(10.15, 5.6, '不管反應\n進行得快或慢', color=INK2, fontsize=14.5,
            ha='center', va='center')
    ax.text(10.15, 4.2, '這件事不需要\n任何校準或模型', color=INK2, fontsize=14,
            ha='center', va='center')

    ax.add_patch(FancyBboxPatch((0.4, 0.5), 11.2, 2.2,
                                boxstyle='round,pad=0.14', fc='white',
                                ec=INK, lw=2.4))
    ax.text(0.9, 2.05, '於是這就成了一把尺：', color=INK, fontsize=17,
            fontweight='bold', ha='left', va='center')
    ax.text(0.9, 1.30, '量到的比例 低於 1:4', color=YELLOW, fontsize=15.5,
            fontweight='bold', ha='left', va='center')
    ax.text(4.3, 1.30, '→ 二氧化碳被多拿走了（溶解）', color=INK, fontsize=15,
            ha='left', va='center')
    ax.text(0.9, 0.80, '量到的比例 高於 1:4', color=RED, fontsize=15.5,
            fontweight='bold', ha='left', va='center')
    ax.text(4.3, 0.80, '→ 氫氣被多拿走了（洩漏，或其他耗氫反應）',
            color=INK, fontsize=15, ha='left', va='center')
    save(fig, 'deck0c_ratio')


def main():
    print('產生「先看懂這個」三張示意圖：')
    deck0a_reactor()
    deck0b_fates()
    deck0c_ratio()


if __name__ == '__main__':
    main()
