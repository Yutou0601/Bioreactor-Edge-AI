
# -*- coding: utf-8 -*-
"""
論文圖表（英文標籤．向量 PDF）
════════════════════════════════════════════════════════════════════════

Paper: Edge-Side Pressure-Only Change-Point Mining Recovers Undocumented
       Setpoint Changes and Manual Interventions in a Micro-Pressurized
       Recirculating Hydrogenotrophic Biomethanation Reactor

Fig. 2  一年份觸發設定點史（含空窗遮罩、07-11 標註）  ← 主圖
Fig. 3  07-11 前後的補氣起始壓力分布（雙峰檢定）
Fig. 4  五個循環設定的組成校正質傳代理

Fig. 1（系統與管線架構）為向量繪圖，另由 fig1_architecture.py 產生。

輸出 -> docs/paper_figures/*.pdf（向量）與 *.png（校稿用）
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv
import datetime as dt

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                                    # noqa: E402
from matplotlib.ticker import MultipleLocator                      # noqa: E402

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(os.path.dirname(HERE), 'docs', 'paper_figures')
os.makedirs(FIG, exist_ok=True)

# 字級、單位、配色一律取自 paper_style，五張圖才會一致
from paper_style import apply, W, C, U, FS_NOTE, FS_SMALL         # noqa: E402
apply()
W1 = W2 = W


def save(fig, name):
    from paper_style import save as _s
    _s(fig, name, FIG)


def load_refills():
    """⚠ 必須與 trigger_setpoint_tracker.py 走**同一條管線**（先合併碎片）。

    直接讀 refill_kinetics.csv 的原始上升事件會把同一次補氣的碎片重複計入，
    月度眾數會偏低（2025-08 得到 0.77 而非 1.22），造成圖文不符。
    """
    from trigger_setpoint_tracker import (load_events,           # noqa: E402
                                          merge_fragments)
    ev = merge_fragments(load_events())
    return sorted((e['t'], e['P_from']) for e in ev)


def mode_bin(v, w=0.05):
    """與 trigger_setpoint_tracker.mode_bin 相同的穩健眾數。"""
    v = np.asarray(v, float)
    lo, hi = np.floor(v.min()/w)*w, np.ceil(v.max()/w)*w+w
    edges = np.arange(lo, hi+w, w)
    c, _ = np.histogram(v, bins=edges)
    k = int(np.argmax(c))
    s = v[(v >= edges[k]) & (v < edges[k+1])]
    return float(np.median(s)) if len(s) else np.nan


# ══════════════════════════════════════════════════════════════════
#  Fig. 2  Trigger-setpoint history
# ══════════════════════════════════════════════════════════════════
# 實驗條件分期（來源：資料夾名稱與三批次紀錄）。
# ⚠ Fig. 2 必須標出這些，否則整年的補氣點看起來像同一個母體，
#   但 2026-01-09~01-23 是 1:1 進氣、7 月是 τ 系列，兩者都是獨立的實驗。
CAMPAIGNS = [
    (dt.date(2025, 8,  4), dt.date(2025, 10, 28), 'commissioning', '#d0d0d0'),
    (dt.date(2025, 10, 28), dt.date(2026, 1,  9), '4:1', '#ffffff'),
    (dt.date(2026, 1,  9), dt.date(2026, 1, 24), '1:1', '#8a8a8a'),
    (dt.date(2026, 1, 24), dt.date(2026, 7, 22), '4:1', '#ffffff'),
    # ⚠ 這一段只有 13 天寬，標籤必須夠短，否則會溢出色帶（"4:1, τ series" 就會）。
    #   進氣仍是 4:1，由圖說說明；色帶只標最短的識別字。
    (dt.date(2026, 7, 22), dt.date(2026, 8,  4), r'$\tau$', '#b8b8b8'),
]


def fig2():
    ev = load_refills()
    T = [t for t, _ in ev]
    P = np.array([p for _, p in ev])

    # 不重疊窗的設定點軌跡（與 trigger_setpoint_tracker 同法，WIN=15）
    WIN = 15
    wt, wm = [], []
    for i in range(0, len(P)-WIN+1, WIN):
        m = mode_bin(P[i:i+WIN])
        if np.isfinite(m):
            wt.append(T[i+WIN//2].date()); wm.append(m)

    fig, (ax, axc) = plt.subplots(
        2, 1, figsize=(W2, 2.85), sharex=True,
        gridspec_kw=dict(height_ratios=[6.2, 0.62], hspace=0.10))

    # 資料空窗遮罩
    gaps = []
    for i in range(1, len(T)):
        g = (T[i]-T[i-1]).days
        if g > 3:
            gaps.append((T[i-1].date(), T[i].date(), g))
    for a, b, g in gaps:
        ax.axvspan(a, b, color=C['gap'], zorder=0, lw=0)

    ax.scatter([t.date() for t in T], P, s=2.0, c=C['fill'],
               alpha=0.45, lw=0, zorder=2, label='Individual refills')
    ax.step(wt, wm, where='post', color=C['main'], lw=1.5,
            zorder=4, label='Tracked setpoint (15-refill windows)')

    # 2026-07-11 標註
    ev_date = dt.date(2026, 7, 11)
    ax.axvline(ev_date, color=C['accent'], lw=1.1, ls='--', zorder=3)
    ax.annotate('Undocumented\nreconfiguration\n' r'0.72 $\rightarrow$ 0.92',
                xy=(ev_date, 0.93), xytext=(dt.date(2026, 4, 5), 1.30),
                fontsize=FS_NOTE, color=C['accent'], ha='center', va='center',
                arrowprops=dict(arrowstyle='->', color=C['accent'], lw=0.8,
                                shrinkA=1, shrinkB=2,
                                connectionstyle='arc3,rad=-0.20'), zorder=6)
    # 九個月穩定期
    ax.annotate('', xy=(dt.date(2025, 10, 28), 0.545),
                xytext=(dt.date(2026, 7, 11), 0.545),
                arrowprops=dict(arrowstyle='<->', color=C['sec'], lw=0.8))
    ax.text(dt.date(2026, 2, 20), 0.47, 'stable at 0.71 for ~9 months',
            fontsize=FS_NOTE, color=C['sec'], ha='center')

    ax.set_ylabel('Trigger pressure  (kg/cm$^2$)')
    ax.set_ylim(0.35, 1.62)
    ax.yaxis.set_major_locator(MultipleLocator(0.2))
    ax.grid(axis='y', lw=0.35, color='#dddddd', zorder=0)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    # 圖例放在左上的空白區（2025-11 → 2026-03、y 1.35–1.6），
    # 該處既無資料點也無標註；lower left 會壓到 "stable at 0.71" 那條註記。
    ax.legend(loc='upper left', bbox_to_anchor=(0.26, 1.00), frameon=False,
              handletextpad=0.5, borderpad=0.0, labelspacing=0.3)

    # ── 條件帶：標出這不是單一實驗，而是數個獨立的批次 ──────
    for a, b, lab, fc in CAMPAIGNS:
        axc.axvspan(a, b, facecolor=fc, edgecolor='#000000', lw=0.5,
                    zorder=2)
        mid = a+(b-a)/2
        axc.text(mid, 0.5, lab, ha='center', va='center', fontsize=FS_SMALL,
                 zorder=3,
                 color=('#ffffff' if fc == '#8a8a8a' else '#000000'))
    axc.set_ylim(0, 1)
    axc.set_yticks([])
    axc.set_ylabel('Feed', fontsize=FS_NOTE, rotation=0, ha='right', va='center')
    for s in ('top', 'right', 'left', 'bottom'):
        axc.spines[s].set_visible(False)
    axc.tick_params(axis='y', length=0)

    fig.autofmt_xdate(rotation=0, ha='center')
    # ⚠ 不要在此標覆蓋率：陰影標的是「>3 天沒有補氣」，不等於沒有資料。
    #   真正的覆蓋率須由原始取樣時戳統計（235/365 天），見 Fig. 5 下方面板。
    axc.text(0.5, -1.55, 'Shaded: intervals > 3 d with no refill.   '
             'Lower band: feed composition and campaign.',
             transform=axc.transAxes, fontsize=FS_NOTE, color=C['sec'],
             ha='center')
    save(fig, 'fig2_setpoint_history')


# ══════════════════════════════════════════════════════════════════
#  Fig. 3  Bimodality test around 2026-07-11
# ══════════════════════════════════════════════════════════════════
def fig3():
    ev = load_refills()
    A = np.array([p for t, p in ev
                  if dt.date(2025, 11, 1) <= t.date() < dt.date(2026, 6, 1)])
    B = np.array([p for t, p in ev
                  if dt.date(2026, 7, 11) <= t.date() < dt.date(2026, 8, 4)])
    edges = np.arange(0.10, 1.30, 0.05)

    fig, axs = plt.subplots(2, 1, figsize=(W1, 2.7), sharex=True)
    for ax, v, ttl, n in ((axs[0], A, '2025-11 to 2026-05', len(A)),
                          (axs[1], B, '2026-07-11 to 08-04', len(B))):
        cnt, _, _ = ax.hist(v, bins=edges, color=C['fill'],
                            edgecolor=C['main'], lw=0.5)
        lo = np.mean((v >= 0.60) & (v < 0.80))*100
        hi = np.mean((v >= 0.85) & (v < 1.00))*100
        ax.set_ylim(0, cnt.max()*1.30)          # 留白，避免標籤壓到長條
        ax.axvspan(0.60, 0.80, color=C['main'], alpha=0.07, lw=0)
        ax.axvspan(0.85, 1.00, color=C['accent'], alpha=0.07, lw=0)
        ax.text(0.70, cnt.max()*1.12, f'{lo:.1f}%', ha='center',
                fontsize=FS_SMALL, color=C['main'], weight='bold')
        ax.text(0.925, cnt.max()*1.12, f'{hi:.1f}%', ha='center',
                fontsize=FS_SMALL, color=C['accent'], weight='bold')
        ax.set_title(f'{ttl}   (n = {n})', loc='left', pad=2)
        ax.set_ylabel('Refills')
        for s in ('top', 'right'):
            ax.spines[s].set_visible(False)
    axs[1].set_xlabel('Refill starting pressure  ('+U['p']+')')
    axs[1].xaxis.set_major_locator(MultipleLocator(0.2))
    fig.align_ylabels(axs)
    save(fig, 'fig3_bimodality')


# ══════════════════════════════════════════════════════════════════
#  Fig. 4  Mass-transfer proxy by recirculation setting
# ══════════════════════════════════════════════════════════════════
def fig4():
    # (label, median, q1, q3, n) — 見 §5.5
    D = [('Pump off',       0.0954, 0.0909, 0.1023, 40),
         ('1 '+U['duty'], 0.1065, 0.1019, 0.1101,  6),
         ('5 '+U['duty'], 0.1659, 0.1484, 0.1737,  8),
         ('Continuous 5 min', 0.1677, 0.1345, 0.2192, 16),
         ('10 '+U['duty'], 0.1708, 0.1653, 0.1782, 12)]
    fig, ax = plt.subplots(figsize=(W1, 2.15))
    y = np.arange(len(D))[::-1]
    for i, (lab, m, q1, q3, n) in enumerate(D):
        yy = y[i]
        ax.plot([q1, q3], [yy, yy], color=C['main'], lw=4.5,
                solid_capstyle='butt', alpha=0.30)
        ax.plot([m], [yy], 'o', ms=5, color=C['main'], zorder=3)
        ax.text(0.228, yy, f'n = {n}', va='center', fontsize=6.8,
                color=C['sec'])
    ax.set_yticks(y)
    ax.set_yticklabels([d[0] for d in D])
    ax.set_xlabel('Composition-corrected mass-transfer proxy  $\hat{\kappa}$  ('+U['inv']+')')
    ax.set_xlim(0.08, 0.255)
    ax.grid(axis='x', lw=0.35, color='#dddddd')
    ax.set_axisbelow(True)
    for s in ('top', 'right', 'left'):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis='y', length=0)
    ax.text(0.0, -0.34, 'Marker: median.  Bar: interquartile range.',
            transform=ax.transAxes, fontsize=FS_NOTE, color=C['sec'])
    save(fig, 'fig4_masstransfer')


def main():
    print('══ 論文圖表（英文標籤．向量 PDF）══')
    print(f'   輸出目錄 {FIG}\n')
    fig2(); fig3(); fig4()
    print(f'\n   Fig.1（系統與管線架構）另由 fig1_architecture.py 產生')


if __name__ == '__main__':
    main()
