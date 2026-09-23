# -*- coding: utf-8 -*-
"""一張圖講完「碳源用完了，壓力還是照樣掉」。

2026-09-21。配合 co2_exhaustion_test.py。刻意用白話，不放模型符號。

輸出 -> docs/analysis_charts_3batch/fig37_co2_story.png
"""
import datetime as dt
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                          # noqa: E402
import matplotlib.dates as mdates                        # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # research/
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (                      # noqa: E402
    BLUE, YELLOW, AQUA, RED, INK, INK2, MUTED, BASELINE, OUT, style)
from co2_exhaustion_test import (                        # noqa: E402
    ATM, AUTO, CUT_A, CUT_B, descents, load, perm_median_p, power_at)

SPLIT = dt.datetime(2026, 8, 23, 12)      # CO2 讀數歸零的時點


def main():
    ts, hh, p, c, m = load(AUTO)
    segs = descents(hh, p)
    t0 = [ts[s] for s, e in segs]
    rate = np.array([(p[s] - p[e]) / (hh[e] - hh[s]) for s, e in segs])
    grp = np.array([0 if ts[s].date() <= CUT_A else (1 if ts[s].date() >= CUT_B else -1)
                    for s, e in segs])
    A, B = rate[grp == 0], rate[grp == 1]

    fig, axes = plt.subplots(3, 1, figsize=(11.5, 9.4), sharex=True,
                             gridspec_kw={'height_ratios': [1, 1.1, 1.15], 'hspace': 0.18})

    def mark(ax, first=False):
        ax.axvline(SPLIT, color=RED, lw=1.4, ls='--', zorder=1)
        ax.axvspan(SPLIT, ts[-1], color=RED, alpha=0.05, lw=0, zorder=0)
        if first:
            ax.text(SPLIT, ax.get_ylim()[1], ' 這裡開始沒有碳源了 ', color=RED,
                    fontsize=10, fontweight='bold', ha='left', va='top')

    # ── (a) 壓力 ──
    ax = axes[0]
    ax.plot(ts, p, color=INK, lw=0.7)
    style(ax, 'a　反應器的壓力：補到滿、慢慢掉、再補滿，一直重複', None, '壓力 (kg/cm²)')
    ax.set_ylim(0.55, 1.35)
    mark(ax, first=True)

    # ── (b) 兩種氣體 ──
    ax = axes[1]
    ax.plot(ts, m, color=AQUA, lw=1.4, label='甲烷（產物）')
    ax.plot(ts, c, color=YELLOW, lw=1.4, label='二氧化碳（原料）')
    ax.fill_between(ts, 0, c, color=YELLOW, alpha=0.18, lw=0)
    ax.legend(loc='upper right', fontsize=10, frameon=False, ncol=2)
    ax.annotate('原料一路用到見底', xy=(dt.datetime(2026, 8, 22), 1.0),
                xytext=(dt.datetime(2026, 8, 15), 13), color=INK2, fontsize=9.5,
                arrowprops=dict(arrowstyle='->', color=BASELINE))
    # 註解放在兩條曲線之上的空白帶（綠線最高約 45），避免壓到曲線
    ax.annotate('產物不再增加，開始被補進來的氣稀釋',
                xy=(dt.datetime(2026, 8, 29), 40), xytext=(dt.datetime(2026, 8, 11, 12), 60),
                color=INK2, fontsize=9.5, arrowprops=dict(arrowstyle='->', color=BASELINE))
    style(ax, 'b　容器裡的兩種氣體：原料見底、產物停止增加', None, '佔氣體的百分比 (%)')
    ax.set_ylim(-2, 70)
    mark(ax)

    # ── (c) 每個週期掉多快 ──
    ax = axes[2]
    for g, col, lab in ((0, MUTED, '還有碳源'), (1, BLUE, '沒有碳源了')):
        ix = grp == g
        ax.scatter(np.array(t0)[ix], rate[ix], s=26, color=col, alpha=0.75, lw=0,
                   label='%s（%d 個週期）' % (lab, ix.sum()))
    ix = grp == -1
    ax.scatter(np.array(t0)[ix], rate[ix], s=26, color=BASELINE, alpha=0.6, lw=0,
               label='過渡期（不採用）')
    for g, col, x0, x1 in ((0, MUTED, ts[0], SPLIT), (1, BLUE, SPLIT, ts[-1])):
        v = np.median(rate[grp == g])
        ax.hlines(v, x0, x1, color=col, lw=2.6, zorder=5)
        # 標籤放在該段起點正上方，避開點雲密集處
        ax.text(x0 + (x1 - x0) * 0.16, v + 0.0075, '中位 %.4f' % v, color=col,
                fontsize=10.5, ha='left', va='bottom', fontweight='bold')
    pv = perm_median_p(A, B)
    pw = power_at(A, B, 0.0125)
    ax.text(0.015, 0.06,
            '兩邊幾乎一樣高（差 %+.4f，p = %.2f）。\n'
            '若原本有三分之一的壓降是微生物造成的，這裡會明顯掉下來——\n'
            '模擬顯示那種情況下 %.0f%% 會被這張圖抓到。結果沒有。'
            % (np.median(B) - np.median(A), pv, pw * 100),
            transform=ax.transAxes, fontsize=10, color=INK2, ha='left', va='bottom')
    ax.legend(loc='upper left', fontsize=9.5, frameon=False, ncol=3)
    style(ax, 'c　每個週期壓力掉多快：碳源沒了，速度一點也沒慢下來',
          None, '壓力下降速度\n(kg/cm² 每小時)')
    ax.set_ylim(0.005, 0.072)
    mark(ax)

    axes[-1].xaxis.set_major_locator(mdates.DayLocator(interval=3))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    fig.savefig(os.path.join(OUT, 'fig37_co2_story.png'))
    plt.close(fig)
    print('圖 -> %s' % os.path.relpath(os.path.join(OUT, 'fig37_co2_story.png'), REPO))


if __name__ == '__main__':
    main()
