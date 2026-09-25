# -*- coding: utf-8 -*-
"""2026-09-23 新增兩頁的簡報專用圖。

⚠ 報告的圖不可直接貼進簡報：報告圖寬 14.8~15 吋、字級 9~11pt，
  貼到投影片 25cm 時縮放僅 0.66，字高剩 7pt，投影看不清。
  簡報圖規則：**一張圖一個訊息、面板最多兩個、圖寬 12 吋、基礎字級 15pt**。

  deck9_carbonate ：CO2 有液相緩衝庫、H2 沒有 → 兩個候選解釋並列
  deck10_coupling ：ORP 與 pH 的關聯，哪些超過可偵測門檻

輸出 -> docs/analysis_charts_3batch/deck9_carbonate.png
        docs/analysis_charts_3batch/deck10_coupling.png
"""
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                          # noqa: E402
from matplotlib import rcParams                          # noqa: E402
from matplotlib.patches import FancyArrowPatch, Rectangle  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (                      # noqa: E402
    BLUE, RED, AQUA, INK, INK2, MUTED, BASELINE, OUT)

rcParams.update({
    'font.size': 15, 'axes.titlesize': 19, 'axes.labelsize': 16,
    'xtick.labelsize': 14, 'ytick.labelsize': 14, 'legend.fontsize': 14,
})
FIGW = 12.0


def style(ax, title=None, xlabel=None, ylabel=None):
    if title:
        ax.set_title(title, color=INK, fontweight='bold', loc='left', pad=12)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(True, linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    for s_ in ('top', 'right'):
        ax.spines[s_].set_visible(False)
    return ax


def save(fig, name):
    p = os.path.join(OUT, name + '.png')
    fig.savefig(p)
    plt.close(fig)
    print('  ->', name + '.png')


# ═══════════════════════════════════════════════════════════════
def fig_carbonate():
    """左：碳庫對比（為什麼 CO2 和 H2 不對稱）；右：兩個候選解釋並列。"""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(FIGW, 5.6),
                                 gridspec_kw={'wspace': 0.30})

    # ── 左：液相能存多少 ──
    a1.bar([0, 1], [16.6, 99.0], width=0.55, color=[MUTED, BLUE])
    a1.set_xticks([0, 1])
    a1.set_xticklabels(['氣相裡的 CO₂\n（每公升）', '液相存的碳\n（每公升）'],
                       fontsize=15)
    a1.set_ylim(0, 150)
    a1.text(0, 16.6 + 4, '16.6', ha='center', va='bottom', fontsize=17,
            fontweight='bold', color=INK)
    a1.text(1, 99.0 + 4, '99.0', ha='center', va='bottom', fontsize=17,
            fontweight='bold', color=BLUE)
    # ★文字一律放在長條之外的空白：頂部留 ylim 到 150，左欄上方大片可用
    a1.text(0.50, 0.985,
            '水裡存的碳是氣體裡的 6 倍',
            transform=a1.transAxes, fontsize=15.5, color=INK,
            fontweight='bold', ha='center', va='top')
    a1.text(0.50, 0.915,
            'pH 7.2 下，CO₂ 有 88% 變成碳酸氫根',
            transform=a1.transAxes, fontsize=13.5, color=INK2,
            ha='center', va='top')
    a1.text(0.22, 0.52, '★ H₂ 完全\n沒有這個\n「倉庫」',
            transform=a1.transAxes, fontsize=15, color=RED,
            fontweight='bold', ha='center', va='center')
    style(a1, 'a　CO₂ 在水裡有倉庫，H₂ 沒有', '', '無機碳 (mmol/L)')

    # ── 右：兩個候選解釋 ──
    a2.axis('off')
    a2.set_xlim(0, 10); a2.set_ylim(0, 10)
    a2.text(5, 9.6, '同一個觀測：排氣時 CO₂ 相對偏多',
            ha='center', va='top', fontsize=16.5, fontweight='bold', color=INK)

    for y0, col, tag, title, body_ in (
            (5.3, RED, '①', '氫氣被額外移除',
             '洩漏、穿透，或其他耗氫反應。\nH₂ 變少 ⟹ 比值上升。'),
            (1.0, AQUA, '②', '碳酸鹽脫氣',
             '排氣時壓力驟降，水裡的碳\n冒回氣相 ⟹ CO₂ 變多，比值也上升。')):
        a2.add_patch(Rectangle((0.3, y0), 9.4, 3.3, facecolor=col, alpha=0.13,
                               edgecolor=col, lw=2.4))
        a2.text(0.8, y0 + 2.7, tag, fontsize=24, fontweight='bold', color=col,
                ha='left', va='center')
        a2.text(1.8, y0 + 2.7, title, fontsize=17, fontweight='bold',
                color=INK, ha='left', va='center')
        a2.text(1.8, y0 + 1.1, body_, fontsize=14, color=INK2,
                ha='left', va='center')
    a2.text(5, 0.5, '★ 兩者目前都無法排除 —— 要靠無菌對照才能分辨',
            ha='center', va='center', fontsize=15, fontweight='bold', color=RED)
    a2.set_title('b　所以有兩種解釋，不是只有一種',
                 color=INK, fontweight='bold', loc='left', pad=12)
    save(fig, 'deck9_carbonate')


# ═══════════════════════════════════════════════════════════════
def fig_coupling():
    """哪些關聯真的存在（超過可偵測門檻），哪些沒有。"""
    fig, ax = plt.subplots(1, 1, figsize=(FIGW, 5.6))

    items = [
        ('壓降越快，pH 越往鹼', +0.229, True),
        ('壓降越快，ORP 走得越少', -0.241, True),
        ('越飽和，ORP 走得越少', -0.207, True),
        ('ORP 水準越低，pH 走得越多', -0.295, True),
        ('ORP 的「變化」和 pH 的「變化」', +0.018, False),
    ]
    names = [i[0] for i in items]
    vals = [i[1] for i in items]
    sig = [i[2] for i in items]
    yy = np.arange(len(items))
    cols = [BLUE if s_ else MUTED for s_ in sig]
    ax.barh(yy, vals, height=0.55, color=cols)
    ax.axvline(0, color=INK, lw=1.4)
    for v in (0.176, -0.176):
        ax.axvline(v, color=RED, lw=2.2, ls=':')
    ax.set_yticks(yy)
    ax.set_yticklabels(names, fontsize=15)
    ax.invert_yaxis()
    ax.set_xlim(-0.46, 0.40)
    for y_, v in zip(yy, vals):
        off = 0.022 if v > 0 else -0.022
        ax.text(v + off, y_, '%+.2f' % v, va='center',
                ha='left' if v > 0 else 'right',
                fontsize=15, fontweight='bold', color=INK)
    # 門檻標籤放軸內底部；說明文字放最後一列左側的空白（該列長條僅 0.02 長）
    ax.text(-0.176, 0.015, ' 可偵測門檻', color=RED, fontsize=13.5,
            fontweight='bold', ha='left', va='bottom',
            transform=ax.get_xaxis_transform())
    # 標註直接放在該列旁邊，不另開文字塊（先前放圖內會壓到長條）
    ax.text(vals[-1] + 0.115, yy[-1], '← 沒有超過門檻，幾乎沒有關係',
            fontsize=13.5, color=INK2, ha='left', va='center')
    ax.set_xlabel('關聯強度（−1 到 +1，n = 251）')
    ax.set_title('ORP 與 pH 確實有關聯，但不是「變化對變化」',
                 color=INK, fontweight='bold', loc='left', pad=14)
    ax.grid(True, axis='x', linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    for s_ in ('top', 'right'):
        ax.spines[s_].set_visible(False)
    fig.subplots_adjust(left=0.30, right=0.97, top=0.86, bottom=0.14)
    save(fig, 'deck10_coupling')


if __name__ == '__main__':
    print('產圖：')
    fig_carbonate()
    fig_coupling()
