
# -*- coding: utf-8 -*-
"""
Fig. 5 — 年度事件盤點（Springer LNCS 規範）
════════════════════════════════════════════════════════════════════════

**第一版是散點時間軸，作廢**：55 個事件擠在 122 mm 寬、12 個月的軸上，
2026-02 前後的瞬時介入疊成一團三角形，上方的已知事件標籤也互相碰撞。
密度不適合這個版面寬度。

改為**月度堆疊長條**：計數不可能重疊；再加一條「當月實際覆蓋天數」的細帶，
把資料不連續這件事講得比灰底陰影更明確（讀者能看出某些月只有幾天資料）。

LNCS 規範：122 mm 寬、**黑白可讀**（以填色深淺與網底區分類別，不靠顏色）、
線寬 ≥ 0.5 pt、字型 Type 42 內嵌、圖內不含 "Fig. n"。

輸出 -> docs/paper_figures/fig5_event_timeline.pdf / .png
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv
import datetime as dt
import collections

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                                    # noqa: E402
from matplotlib.patches import Patch                               # noqa: E402

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(os.path.dirname(HERE), 'docs', 'paper_figures')
os.makedirs(FIG, exist_ok=True)

from paper_style import apply, W, FS_LABEL, FS_NOTE, PNG_DPI                # noqa: E402
apply()                    # 字級／字型／Type 42 與其餘四張圖同源
H = 2.60
INK = '#000000'

# 由下而上堆疊；填色深淺＋網底，黑白印刷可分辨
CLASSES = [
    ('●', 'Process drift',             '#b8b8b8', ''),
    ('⚡', 'Transient intervention',    '#ffffff', '////'),
    ('★', 'Persistent reconfiguration', '#000000', ''),
    ('✘', 'Recording artifact',        '#ffffff', 'xxxx'),
]


def load_events():
    rows = []
    with open(f'{OUT}/three_class_typology.csv', encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            rows.append((dt.datetime.strptime(r['date'], '%Y-%m-%d').date(),
                         r['class'].strip()))
    return rows


def coverage_by_month():
    """各月的覆蓋天數 —— **直接數原始取樣的日期**。

    ⚠ 不可由衍生事件（循環或補氣）的間隔反推：
      · 由循環間隔推得 174 天（49%）—— 循環僅 1.4 次/天，兩循環隔 3 天
        不代表沒資料，可能只是那幾天沒在做循環 ⇒ **低估**
      · 由補氣間隔推得 232 天
      · 直接數原始取樣：**235 天**（有任何取樣）／220 天（≥720 筆，即至少半天）
    三者不同，只有最後一個是「記錄涵蓋了哪些日子」的正解。
    """
    import glob
    from regime_changepoints import load, TD                      # noqa: E402
    folders = []
    for d in sorted(os.listdir(TD)):
        p = os.path.join(TD, d)
        if not os.path.isdir(p):
            continue
        if glob.glob(os.path.join(p, '*.csv')):
            folders.append(p)
        for s in sorted(os.listdir(p)):
            sp = os.path.join(p, s)
            if os.path.isdir(sp) and glob.glob(os.path.join(sp, '*.csv')):
                folders.append(sp)
    per_day = collections.Counter()
    for path in folders:
        try:
            rows = load(path)
        except Exception:
            continue
        for t, _ in rows:
            per_day[t.date()] += 1
    cov = collections.Counter((d.year, d.month) for d in per_day)
    print(f'   覆蓋 {len(per_day)} 天（有任何取樣）')
    return cov


def main():
    ev = load_events()
    cov = coverage_by_month()
    months = sorted({(d.year, d.month) for d, _ in ev}
                    | set(cov.keys()))
    idx = {m: i for i, m in enumerate(months)}

    cnt = {c[0]: np.zeros(len(months)) for c in CLASSES}
    for d, cl in ev:
        cnt[cl[0]][idx[(d.year, d.month)]] += 1

    print('══ Fig. 5 年度事件盤點 ══')
    print(f'   事件 {len(ev)} 個   月份 {len(months)} 個')
    for sym, en, _, _ in CLASSES:
        print(f'   {en:<28} {int(cnt[sym].sum()):>3}')

    fig, (ax, axc) = plt.subplots(
        2, 1, figsize=(W, H), sharex=True,
        gridspec_kw=dict(height_ratios=[4.4, 1.0], hspace=0.16))

    x = np.arange(len(months))
    bottom = np.zeros(len(months))
    for sym, en, fc, hh in CLASSES:
        ax.bar(x, cnt[sym], bottom=bottom, width=0.72, facecolor=fc,
               edgecolor=INK, linewidth=0.55, hatch=hh, label=en, zorder=3)
        bottom += cnt[sym]

    ax.set_ylabel('Detected events', fontsize=FS_LABEL)
    ax.set_ylim(0, bottom.max()*1.42)      # 留白給兩列圖例，避免壓到最高的長條
    ax.grid(axis='y', lw=0.3, color='#dddddd', zorder=0)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    ax.legend(loc='upper left', frameon=False, ncol=2,
              handlelength=1.5, handleheight=0.9, columnspacing=1.0,
              borderpad=0.0, labelspacing=0.35)

    # 覆蓋天數細帶
    days = np.array([cov.get(m, 0) for m in months], float)
    axc.bar(x, days, width=0.72, facecolor='#6e6e6e', edgecolor=INK,
            linewidth=0.4, zorder=3)
    axc.set_ylabel('Days\ncovered', fontsize=FS_NOTE, linespacing=1.1)
    axc.set_ylim(0, 33)
    axc.set_yticks([0, 15, 30])
    axc.grid(axis='y', lw=0.3, color='#dddddd', zorder=0)
    axc.set_axisbelow(True)
    for s in ('top', 'right'):
        axc.spines[s].set_visible(False)

    axc.set_xticks(x)
    axc.set_xticklabels([f'{y}-{m:02d}' for y, m in months], rotation=45,
                        ha='right')
    axc.set_xlim(-0.7, len(months)-0.3)

    fig.align_ylabels([ax, axc])
    for ext in ('pdf', 'png'):
        fig.savefig(os.path.join(FIG, f'fig5_event_timeline.{ext}'),
                    dpi=(PNG_DPI if ext == 'png' else None))
    plt.close(fig)
    print(f'\n   ✓ fig5_event_timeline.pdf / .png  →  {FIG}')
    print('   ✓ 黑白可讀（填色深淺＋網底，不靠顏色）')


if __name__ == '__main__':
    main()
