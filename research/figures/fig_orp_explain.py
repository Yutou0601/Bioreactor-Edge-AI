
# -*- coding: utf-8 -*-
"""ORP 的三格說明圖：端點差 vs 擺幅、真實範圍與參考電極、時長混淆。

第一格是關鍵：找一個「擺幅很大但端點差接近零」的真實循環，
把 dORP 的定義問題畫出來——洪博一眼看出 2 mV 不合理，
正是因為他知道真實擺幅是幾十到上百 mV。
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import glob
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from analyze_three_batches import load_txt

plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei']
plt.rcParams['axes.unicode_minus'] = False
B, R, G, O = '#1F6FB5', '#C0392B', '#666666', '#E8912B'
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
SHE = 200.0                      # Ag/AgCl → SHE 的約略偏移（mV）


def main():
    df = pd.concat([load_txt(p) for p in sorted(glob.glob(DATA + '/*.txt'))],
                   ignore_index=True).sort_values('ts')
    df = df.drop_duplicates('ts').reset_index(drop=True)
    o_all = df.orp.values
    print('ORP 紀錄 %d 筆  範圍 %.0f ~ %.0f  中位 %.0f'
          % (o_all.size, o_all.min(), o_all.max(), np.median(o_all)))

    # 切循環，找「擺幅大但端點差小」的一段
    p = df.p_reactor.values
    cut = np.flatnonzero(np.diff(p) > 0.03) + 1
    e = np.concatenate([[0], cut, [len(p)]])
    best = None
    for u, v in zip(e[:-1], e[1:]):
        if v - u < 200:
            continue
        o = o_all[u:v]
        span = o.max() - o.min()
        end = abs(o[-1] - o[0])
        if span > 60 and end < 0.25 * span:
            if best is None or span - end > best[0]:
                best = (span - end, u, v)
    if best is None:
        print('找不到適合的示範循環'); return
    _, u, v = best
    o = o_all[u:v]
    t = (df.ts.iloc[u:v] - df.ts.iloc[u]).dt.total_seconds().values / 3600
    span, end = o.max() - o.min(), o[-1] - o[0]
    print('示範循環：擺幅 %.0f mV，端點差 %+.0f mV' % (span, end))

    fig, ax = plt.subplots(1, 3, figsize=(14.6, 4.4))

    # (a) 端點差 vs 擺幅
    ax[0].plot(t, -o, lw=1.0, color=B)
    ax[0].plot([t[0], t[-1]], [-o[0], -o[-1]], 'o', ms=10, color=R,
               zorder=5)
    ax[0].annotate('', xy=(t[-1], -o[-1]), xytext=(t[0], -o[0]),
                   arrowprops=dict(arrowstyle='<->', color=R, lw=2.2))
    ax[0].text(t[len(t) // 2], -o[0] + 14,
               '端點差 %+.0f mV' % (-end), color=R, fontsize=12,
               ha='center', fontweight='bold')
    lo, hi = -o.max(), -o.min()
    ax[0].annotate('', xy=(t[-1] * 0.06, lo), xytext=(t[-1] * 0.06, hi),
                   arrowprops=dict(arrowstyle='<->', color=G, lw=2.0))
    ax[0].text(t[-1] * 0.09, (lo + hi) / 2, '擺幅\n%.0f mV' % span,
               color=G, fontsize=12, va='center', fontweight='bold')
    ax[0].set_xlabel('補氣後經過時間（hr）')
    ax[0].set_ylabel('ORP 真值（mV，對 Ag/AgCl）')
    ax[0].set_title('程式量的是端點差，不是擺幅', fontweight='bold',
                    color=R)
    ax[0].grid(alpha=.25)

    # (b) 真實範圍與文獻最適區間
    ax[1].hist(-o_all, bins=60, color=B, alpha=.8, edgecolor='white',
               lw=.4)
    ax[1].axvline(np.median(-o_all), color=B, lw=2.2,
                  label='本反應器中位 %.0f mV' % np.median(-o_all))
    ax[1].axvspan(-400 - SHE, -200 - SHE, color=O, alpha=.22,
                  label='文獻最適區間（換算至此軸）')
    ax[1].axvline(-335.63 - SHE, color=O, lw=2.2, ls='--',
                  label='文獻最適 −336 mV vs SHE')
    ax[1].set_xlabel('ORP 真值（mV，對 Ag/AgCl）')
    ax[1].set_ylabel('筆數')
    ax[1].set_title('換算後落在文獻的最適窗口內', fontweight='bold')
    ax[1].legend(fontsize=9, framealpha=.95, loc='upper left')
    ax[1].grid(alpha=.22, axis='y')
    ax[1].text(.98, .55, '對 SHE ＝ 本軸 + %.0f mV' % SHE,
               transform=ax[1].transAxes, fontsize=10, color=G,
               ha='right')

    # (c) 時長混淆與剩下的關聯
    lbl = ['未控制\n時長', '控制\n時長後', 'dORP/Δt\n（已撤回）']
    val = [0.213, 0.150, 0.040]
    col = [B, B, G]
    bb = ax[2].bar(lbl, val, width=.55, color=col, edgecolor='#123A57',
                   lw=.8)
    bb[2].set_hatch('///')
    for r_, x in zip(bb, val):
        ax[2].text(r_.get_x() + r_.get_width() / 2, x + .008,
                   '%.3f' % x, ha='center', fontsize=12,
                   fontweight='bold', color=B if x > .1 else G)
    ax[2].set_ylim(0, .27)
    ax[2].set_ylabel('與 r_b 的秩相關')
    ax[2].set_title('控制時長後掉三成，但沒有消失', fontweight='bold')
    ax[2].grid(alpha=.22, axis='y')
    ax[2].text(.5, .93, 'dORP 與時長的秩相關 −0.231', transform=ax[2].transAxes,
               ha='center', fontsize=10, color=R)
    ax[2].text(2, .075, '對對數量\n做算術，撤回', ha='center',
               fontsize=9.5, color=G)

    fig.suptitle('ORP：量到的是什麼、真值範圍、以及還剩下什麼',
                 fontsize=13.5, fontweight='bold')
    fig.tight_layout(rect=(0, 0, 1, .93))
    q = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                     'docs', 'paper_figures', 'figY_orp.png')
    fig.savefig(q, dpi=180)
    plt.close(fig)
    print('→ figY_orp.png')


if __name__ == '__main__':
    main()
