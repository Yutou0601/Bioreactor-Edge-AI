# -*- coding: utf-8 -*-
"""fig61：生物活性時間軸（讀 bio_activity_timeline.py 的輸出）。

  a　每個循環的 CO2 轉換速率上限（假設無洩漏）＋ 以排氣 CH4 校正後的生物活性
  b　每個排氣區間的生物份額（CH4 實測 ÷ 壓降推算）：若壓降全是生物應為 100%

用法：python fig_bio_activity.py
"""
import csv
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
REPO = os.path.dirname(RESEARCH)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, os.path.join(RESEARCH, 'ml'))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import matplotlib                                            # noqa: E402
matplotlib.use('Agg')
import matplotlib.dates as mdates                           # noqa: E402
import matplotlib.pyplot as plt                             # noqa: E402

from fig_pinn_batched import (BLUE, AQUA, RED, INK, INK2, MUTED, BASELINE,  # noqa: E402
                              OUT, style)
from core import descent_report as DR                       # noqa: E402

TEMP_C = 30.0                     # 全程 30.0 °C（bio_activity_cycles.csv 的 temp 欄）


def read(name):
    with open(os.path.join(OUT, name), encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def mmol_day(rate_kgf_hr):
    """降速（kg/cm²/hr）→ CO2 轉換（mmol/天）：÷4（化學計量），頭空 DR.HEADSPACE_L。"""
    return 1000 * DR.moles_from_pressure(rate_kgf_hr / 4 * 24, DR.HEADSPACE_L, TEMP_C)


def main():
    C = read('bio_activity_cycles.csv')
    V = [v for v in read('bio_activity_vents.csv') if v['status'] == 'ok']
    p = lambda s: dt.datetime.strptime(s, '%Y-%m-%d %H:%M')
    tc = [p(r['start']) for r in C]
    y = np.array([float(r['co2_mmol_day']) for r in C])
    lo = np.array([float(r['co2_mmol_day_lo80']) for r in C])
    hi = np.array([float(r['co2_mmol_day_hi80']) for r in C])

    fig, axes = plt.subplots(2, 1, figsize=(14.5, 8.6), sharex=True,
                             gridspec_kw={'height_ratios': [1.6, 1], 'hspace': 0.18})
    ax = axes[0]
    ax.vlines(tc, lo, hi, color=BLUE, alpha=0.35, lw=1.6, zorder=2)
    ax.scatter(tc, y, s=14, color=BLUE, zorder=3, label='壓降上限（假設無洩漏；每點＝一個循環，線＝80% 區間）')
    shares = []
    for v in V:
        t0, t1 = p(v['start']), p(v['end'])
        rate = float(v['consumed']) / float(v['hours'])
        sh = float(v['bio_share'])
        shares.append(sh)
        ax.plot([t0, t1], [mmol_day(rate * sh)] * 2, color=AQUA, lw=4, solid_capstyle='butt', zorder=4)
    ax.plot([], [], color=AQUA, lw=4, label='以排氣 CH4 校正的生物活性（只有生物會產生 CH4；每段＝一個排氣區間）')
    ax.set_ylim(0, np.percentile(hi, 99) * 1.15)
    ax.legend(loc='upper right', fontsize=9, frameon=False)
    style(ax, 'a　生物活性：CO2 轉換速率（mmol/天；頭空 1.00 L——絕對值只看相對變化）', None,
          'CO2 轉換（mmol/天）')
    ax.text(0.005, 0.97, '溶解 ≈ 0（pH 分析）⇒ 壓降 ＝ 生物 ＋ 洩漏\n藍點是「洩漏＝0」時的生物上限；綠段是 CH4 實測的生物',
            transform=ax.transAxes, fontsize=9, color=INK2, va='top')

    ax = axes[1]
    for v in V:
        t0, t1 = p(v['start']), p(v['end'])
        ax.plot([t0, t1], [float(v['bio_share']) * 100] * 2, color=AQUA, lw=5, solid_capstyle='butt')
    med = float(np.median(shares)) * 100
    ax.axhline(100, color=INK, lw=1, ls='--')
    ax.text(tc[0], 103, '壓降全是生物時應為 100%', fontsize=9, color=INK2, va='bottom')
    ax.axhline(med, color=RED, lw=1.2, ls=':')
    ax.text(tc[-1], med + 3, '中位 %.0f%%（%d 個區間）' % (med, len(shares)), fontsize=9,
            color=INK2, ha='right', va='bottom')
    ax.set_ylim(0, 115)
    style(ax, 'b　壓降裡真正來自產甲烷的份額（CH4 實測 ÷ 壓降推算；50 個排氣區間中 16 個通過化學計量檢查）',
          None, '生物份額（%）')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    plt.setp(ax.get_xticklabels(), rotation=0, fontsize=8.5)

    fig.suptitle('看得出生物：254 個循環（2025-08 ~ 2026-08，去重後 341,013 筆）的生物活性時間軸\n'
                 '假設無洩漏的上限 vs 甲烷實測——兩者差約 %.1f 倍，差的那部分最可能是洩漏／氫氣流失' % (100 / med),
                 fontweight='bold', x=0.06, ha='left', y=0.995, fontsize=11)
    path = os.path.join(OUT, 'fig61_bio_activity.png')
    fig.savefig(path)
    plt.close(fig)
    print('-> %s' % path)


if __name__ == '__main__':
    main()
