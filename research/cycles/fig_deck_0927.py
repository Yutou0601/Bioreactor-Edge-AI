# -*- coding: utf-8 -*-
"""2026-09-27 補進簡報的四張圖（簡報專用規格）。

⚠ 報告圖不可直接貼簡報：報告圖寬 13~15 吋、字級 9~12pt，
  貼到 25cm 投影片縮放僅 0.66，字高剩 7pt。
  簡報規則：一張圖一個訊息、面板最多兩個、圖寬 12 吋、基礎字級 15pt。

  deck11_pinn_what   PINN 是什麼（示意圖，給完全不熟的人）
  deck12_co2         CO2 消耗量（洪博要求的數字）
  deck13_ventloss    排氣本身就會選擇性移除 H2
  deck14_curvature   曲率配對：第四個同向證據

輸出 -> docs/analysis_charts_3batch/deck11~14_*.png
"""
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                          # noqa: E402
from matplotlib import rcParams                          # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

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
    # ★ 存檔前先自動檢查「圖上文字是否壓到資料」
    from overlap_check import report
    p = os.path.join(OUT, name + '.png')
    report(fig, name)
    fig.savefig(p)
    plt.close(fig)
    print('  ->', name + '.png')


def box(ax, x, y, w, h, text, fc, ec, fs=14, bold=True):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.12',
                                facecolor=fc, edgecolor=ec, linewidth=2.4))
    ax.text(x + w / 2, y + h / 2, text, ha='center', va='center',
            fontsize=fs, color=INK, fontweight='bold' if bold else 'normal')


def arrow(ax, x0, y0, x1, y1, color=INK, lw=2.4):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle='-|>',
                                 mutation_scale=22, color=color, lw=lw))


# ═══════════════════════════════════════════════════════════════
def fig_pinn_what():
    """PINN 是什麼：與一般做法的對照。"""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(FIGW, 5.8),
                                 gridspec_kw={'wspace': 0.10})
    for ax in (a1, a2):
        ax.axis('off')
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)

    # ── 左：一般做法 ──
    a1.text(5, 9.8, '一般做法：套一個固定的公式', ha='center', va='top',
            fontsize=17, fontweight='bold', color=INK)
    box(a1, 0.6, 7.6, 8.8, 1.3, '壓力資料（每分鐘一筆）', '#EDF2F7', MUTED)
    arrow(a1, 5, 7.5, 5, 6.7)
    box(a1, 0.6, 5.2, 8.8, 1.5,
        '假設公式  P = 平衡值 + 衰減項 − 生物速率×t', '#E6F0FA', BLUE, fs=13.5)
    arrow(a1, 5, 5.1, 5, 4.3)
    box(a1, 0.6, 2.9, 8.8, 1.4, '擬合出三個數字', '#E6F0FA', BLUE)
    a1.text(5, 2.2, '⚠ 這裡把「生物速率」當成固定不變', ha='center',
            va='top', fontsize=14.5, color=RED, fontweight='bold')
    a1.text(5, 1.2, '但氫氣會在循環中耗盡，\n生物速率其實一直在變。',
            ha='center', va='top', fontsize=13.5, color=INK2)

    # ── 右：PINN ──
    a2.text(5, 9.8, 'PINN：讓網路自己學形狀，但必須守物理定律',
            ha='center', va='top', fontsize=16, fontweight='bold', color=INK)
    box(a2, 0.4, 7.9, 4.3, 1.1, '神經網路 ①\n學壓力 P(t)', '#E6F0FA', BLUE,
        fs=13)
    box(a2, 5.3, 7.9, 4.3, 1.1, '神經網路 ②\n學生物速率 r(t)', '#FDE8E8', RED,
        fs=13)
    arrow(a2, 2.5, 7.8, 3.6, 6.9)
    arrow(a2, 7.5, 7.8, 6.4, 6.9)
    box(a2, 0.8, 5.3, 8.4, 1.5,
        '訓練時同時要求兩件事：\n'
        '① 壓力要貼近實測　② 物理方程式要成立',
        '#FFF7E6', '#E0A800', fs=13.5)
    arrow(a2, 5, 5.2, 5, 4.4)
    box(a2, 0.8, 3.0, 8.4, 1.4,
        '好處：生物速率可以是任何形狀\n不必事先假設它固定',
        '#E8F6EF', AQUA, fs=13)
    a2.text(5, 2.3, '物理方程式就是那條質量平衡：', ha='center', va='top',
            fontsize=13, color=INK2)
    a2.text(5, 1.55, '壓力掉的速度 ＝ 溶進水裡 ＋ 被菌吃掉',
            ha='center', va='top', fontsize=14, color=INK, fontweight='bold')
    a2.text(5, 0.7, '（PINN = Physics-Informed Neural Network，'
                    '物理資訊神經網路）',
            ha='center', va='top', fontsize=12, color=MUTED)
    save(fig, 'deck11_pinn_what')


# ═══════════════════════════════════════════════════════════════
def fig_co2():
    """CO2 消耗量：由甲烷反推，並說明兩個數字為何不同。"""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(FIGW, 5.4),
                                 gridspec_kw={'wspace': 0.30})

    # 左：為什麼甲烷可以代表 CO2 消耗
    a1.axis('off'); a1.set_xlim(0, 10); a1.set_ylim(0, 10)
    a1.text(5, 9.7, '為什麼可以用甲烷反推', ha='center', va='top',
            fontsize=17, fontweight='bold', color=INK)
    box(a1, 0.5, 7.5, 9.0, 1.3, 'CO₂ + 4 H₂  →  CH₄ + 2 H₂O',
        '#E6F0FA', BLUE, fs=16)
    a1.text(5, 7.0, '吃掉 1 個 CO₂ ⟺ 產生 1 個 CH₄', ha='center', va='top',
            fontsize=15, color=INK, fontweight='bold')
    box(a1, 0.5, 4.5, 9.0, 1.6,
        '而甲烷只能來自生物\n溶解不產生、洩漏不產生、排氣也不產生',
        '#E8F6EF', AQUA, fs=14)
    a1.text(5, 3.9, '⟹ 不需要氫氣感測器\n⟹ 不受「壓降到底是誰造成的」爭議影響',
            ha='center', va='top', fontsize=14.5, color=RED,
            fontweight='bold')
    a1.text(5, 1.6, '⚠ 要用「絕對莫耳數」不能用濃度：\n'
                    '補氣會稀釋、排氣會減量，濃度會失真。',
            ha='center', va='top', fontsize=13, color=INK2)

    # 右：兩個數字
    bars = [('長期平均\n（含基質耗盡期）', 0.1332, BLUE),
            ('初始速率\n（基質充足）', 0.4343, RED)]
    xs = [0, 1]
    a2.bar(xs, [b[1] for b in bars], width=0.55,
           color=[b[2] for b in bars])
    a2.set_xticks(xs)
    a2.set_xticklabels([b[0] for b in bars], fontsize=14)
    for x, (_, v, c) in zip(xs, bars):
        a2.text(x, v + 0.018, '%.3f' % v, ha='center', va='bottom',
                fontsize=17, fontweight='bold', color=c)
    a2.set_ylim(0, 0.60)
    a2.text(0.5, 0.97,
            '兩者差 3.3 倍，原因已查明：\n'
            '量測間隔越長，平均速率越低（ρ=−0.55, p=0.01）\n'
            '長間隔把「基質耗盡後的零產量」也平均進來',
            transform=a2.transAxes, fontsize=13, color=INK,
            fontweight='bold', ha='center', va='top')
    style(a2, '每公升氣相的 CO₂ 消耗速率', '', 'mmol / (L·hr)')
    save(fig, 'deck12_co2')


# ═══════════════════════════════════════════════════════════════
def fig_ventloss():
    """排氣本身就會選擇性移除 H2。"""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(FIGW, 5.4),
                                 gridspec_kw={'wspace': 0.28})

    a1.axis('off'); a1.set_xlim(0, 10); a1.set_ylim(0, 10)
    a1.text(5, 9.8, '排氣之後發生什麼事', ha='center', va='top',
            fontsize=17, fontweight='bold', color=INK)
    box(a1, 0.5, 7.9, 9.0, 1.2, '排氣：兩種氣體按比例一起排掉（公平）',
        '#EDF2F7', MUTED, fs=13.5)
    arrow(a1, 5, 7.8, 5, 7.0)
    box(a1, 0.5, 5.4, 9.0, 1.5,
        '壓力降低 → 水裡的 CO₂ 冒回氣相\n（只有 CO₂ 補得回來）',
        '#E8F6EF', AQUA, fs=14)
    arrow(a1, 5, 5.3, 5, 4.5)
    box(a1, 0.5, 2.9, 9.0, 1.5,
        'H₂ 在水裡幾乎沒有存量\n⟹ 補不回來，被淨移除',
        '#FDE8E8', RED, fs=14)
    a1.text(5, 2.2, '每排一次氣，CO₂:H₂ 就往上推一點，而且會累積',
            ha='center', va='top', fontsize=14, color=INK,
            fontweight='bold')
    a1.text(5, 1.0, '★ 這完全不需要「洩漏」，是正常操作的必然結果',
            ha='center', va='top', fontsize=14.5, color=RED,
            fontweight='bold')

    n = np.arange(0, 31)
    for f, c, ls, lab in ((1.0, BLUE, '-', 'CO₂ 全部補回'),
                          (0.5, AQUA, '--', 'CO₂ 補回一半'),
                          (0.1, MUTED, ':', 'CO₂ 只補回一成')):
        a2.plot(n, 0.25 * np.power(np.power(1.228, f), n),
                color=c, lw=3.0, ls=ls, label=lab)
    a2.axhline(0.699, color=RED, lw=2.6, ls='--')
    a2.set_yscale('log')
    a2.set_yticks([0.25, 0.5, 1.0, 2.0])
    a2.set_yticklabels(['0.25', '0.5', '1.0', '2.0'])
    a2.minorticks_off()
    a2.legend(loc='lower right', frameon=False, fontsize=13)
    _lo, hi = a2.get_ylim()
    a2.set_ylim(_lo, hi * 3.0)
    a2.text(0.5, 0.97,
            '只要 5 次排氣就能從 0.25 漲到實測的 0.699\n'
            '而實際排氣有 108 次',
            transform=a2.transAxes, fontsize=14, color=INK,
            fontweight='bold', ha='center', va='top')
    # ★ 此處原有「實測中位 0.699」標註，不論放哪都會穿過曲線。
    #   頂部文字已說「漲到實測的 0.699」，標註屬冗餘，故移除。
    style(a2, '每次排氣都把比值往上推', '排氣次數', 'CO₂:H₂（對數軸）')
    save(fig, 'deck13_ventloss')


# ═══════════════════════════════════════════════════════════════
def fig_curvature():
    """四個方法都指向同一個方向：定版被低估。"""
    fig, ax = plt.subplots(1, 1, figsize=(FIGW, 5.4))
    items = [
        ('曲率配對（本次新做）', 0.0321, 0.0286, 0.0349, RED),
        ('甲烷化學計量對帳', 0.0225, 0.016, 0.029, BLUE),
        ('kT>7 的尾段斜率', 0.0177, np.nan, np.nan, BLUE),
        ('論文定版（壓力擬合）', 0.0125, 0.0112, 0.0139, MUTED),
    ]
    yy = np.arange(len(items))
    for y, (nm, v, lo, hi, c) in zip(yy, items):
        if np.isfinite(lo):
            ax.plot([lo, hi], [y, y], color=c, lw=4.0, solid_capstyle='round')
        ax.scatter([v], [y], s=200, color=c, edgecolors='white',
                   linewidths=2.0, zorder=5)
        # 數值標籤放在區間右端的右側，不壓到點與線
        xt = (hi if np.isfinite(hi) else v) + 0.0012
        ax.text(xt, y, '%.4f' % v, ha='left', va='center',
                fontsize=14, fontweight='bold', color=c)
    ax.set_yticks(yy)
    ax.set_yticklabels([i[0] for i in items], fontsize=15)
    ax.invert_yaxis()
    ax.axvline(0.0125, color=MUTED, lw=2.0, ls=':')
    ax.set_xlim(0, 0.046)
    ax.set_ylim(len(items) - 0.4, -0.9)
    # 說明文字放左上空白處（第一列的區間從 0.0286 才開始）
    ax.text(0.015, 0.93,
            '四個彼此獨立的方法，三個都高於論文定版',
            transform=ax.transAxes, fontsize=14.5, color=INK,
            fontweight='bold', ha='left', va='top')
    ax.set_xlabel('推得的 r̄_b （kgf/cm²/hr）')
    ax.set_title('★ 定版的生物速率可能被低估', color=INK,
                 fontweight='bold', loc='left', pad=14)
    ax.grid(True, axis='x', linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    for s_ in ('top', 'right'):
        ax.spines[s_].set_visible(False)
    fig.subplots_adjust(left=0.27, right=0.97, top=0.85, bottom=0.17)
    save(fig, 'deck14_curvature')


if __name__ == '__main__':
    print('產圖：')
    fig_pinn_what()
    fig_co2()
    fig_ventloss()
    fig_curvature()
