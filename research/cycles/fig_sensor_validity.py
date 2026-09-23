# -*- coding: utf-8 -*-
"""氣體分析儀什麼時候可信、什麼時候不可信 —— 報告 3.1 節的圖。

2026-09-21。三個面板構成完整論證：
  (a) 排氣當下的實際讀數：前一分鐘還是 0，排氣那一分鐘跳到真值，下一分鐘幾乎相同
      -> 管路已被頂空氣體沖洗乾淨，那一兩分鐘是真的
  (b) 補氣稀釋檢定：補氣加入不含甲烷的氣體，真頂空必定被稀釋
      -> 實測斜率 +0.008 ± 0.225，距真頂空的 −1 有 4.5σ
  (c) 循環內的斜率分布：中位 −0.551，介於兩者之間 -> 數十分鐘時間常數的滯後追蹤

輸出 -> docs/analysis_charts_3batch/fig44_sensor_validity.png
"""
import datetime as dt
import glob
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                          # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # research/
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (                      # noqa: E402
    BLUE, YELLOW, AQUA, RED, INK, INK2, MUTED, BASELINE, OUT, style)
from co2_exhaustion_test import ATM, AUTO, GAPH, RISE, descents, load  # noqa: E402

TAU_DIR = '202607至08最新循環研究'


def load_tau():
    from core.cycle_store import read_series_full
    d = os.path.join(REPO, 'research', 'Testing_data', TAU_DIR)
    ts, hh, p, temp, co2, ch4 = read_series_full(
        sorted(glob.glob(os.path.join(d, '*.csv'))))
    g = lambda v: np.array([x if x is not None else 0.0 for x in v], float)
    return ts, np.asarray(hh, float), np.asarray(p, float), g(co2), g(ch4)


def ols(x, y):
    X = np.vstack([np.ones(len(x)), x]).T
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = y - X @ b
    s2 = float(r @ r) / max(1, len(x) - 2)
    cov = s2 * np.linalg.inv(X.T @ X)
    return float(b[1]), float(np.sqrt(cov[1, 1])), float(b[0])


def main():
    fig, axes = plt.subplots(1, 3, figsize=(14.8, 4.8), gridspec_kw={'wspace': 0.34})

    # ── (a) 一次排氣的實際讀數 ──
    ts, hh, p, co2, ch4 = load_tau()
    tgt = dt.datetime(2026, 7, 30, 9, 6)
    i = min(range(len(ts)), key=lambda k: abs((ts[k] - tgt).total_seconds()))
    sl = slice(i - 8, i + 12)
    mins = np.arange(-8, 12)
    ax = axes[0]
    ax.plot(mins, ch4[sl], color=AQUA, lw=2, marker='o', ms=4, label='甲烷')
    ax.plot(mins, co2[sl], color=YELLOW, lw=2, marker='s', ms=4, label='二氧化碳')
    ax.axvline(0, color=RED, lw=1.6, ls='--')
    ax.axvspan(-0.5, 1.5, color=RED, alpha=0.10, lw=0)
    ax.annotate('排氣閥開啟', xy=(0, 40), xytext=(-7.5, 52), color=RED, fontsize=9.5,
                ha='left', arrowprops=dict(arrowstyle='->', color=RED))
    ax.annotate('這一兩分鐘\n管路被頂空氣沖乾淨\n= 真實組成',
                xy=(1, 34.7), xytext=(3.2, 47), color=INK, fontsize=9,
                ha='left', va='top',
                arrowprops=dict(arrowstyle='->', color=BASELINE))
    ax.annotate('排氣前讀數接近 0\n不是頂空，是管路殘氣',
                xy=(-4, 0.5), xytext=(-7.5, 20), color=INK2, fontsize=9,
                ha='left', arrowprops=dict(arrowstyle='->', color=BASELINE))
    ax.legend(loc='center right', fontsize=9.5, frameon=False)
    ax.set_ylim(-3, 62)
    style(ax, 'a　一次排氣的實際讀數（2026-07-30 09:06）', '距排氣幾分鐘', '濃度 (%)')

    # ── (b) 補氣稀釋檢定 ──
    ts2, hh2, p2, c2, m2 = load(AUTO)
    dx, dP = [], []
    for j in range(1, len(ts2)):
        if (p2[j] - p2[j - 1] > RISE and hh2[j] - hh2[j - 1] < GAPH
                and m2[j] > 5 and m2[j - 1] > 5):
            dx.append(np.log(m2[j] / m2[j - 1]))
            dP.append(np.log((p2[j] + ATM) / (p2[j - 1] + ATM)))
    dx, dP = np.array(dx), np.array(dP)
    b, se, a0 = ols(dP, dx)
    ax = axes[1]
    ax.scatter(dP, dx, s=22, color=MUTED, alpha=0.55, lw=0)
    xs = np.linspace(dP.min(), dP.max(), 20)
    ax.plot(xs, -xs, color=RED, lw=2.2, ls='--', label='真頂空應落在這條線上（斜率 −1）')
    ax.plot(xs, a0 + b * xs, color=BLUE, lw=2.2,
            label='實測 斜率 %+.3f ± %.3f' % (b, se))
    ax.axhline(0, color=BASELINE, lw=1)
    ax.legend(loc='upper center', fontsize=9, frameon=False)
    ax.text(0.03, 0.05,
            '補氣加入的是二氧化碳與氫氣，不含甲烷。\n'
            '若讀數是真的頂空，甲烷必定被稀釋。\n'
            '實測距 −1 有 %.1f 個標準差，距 0 只有 %.1f 個。'
            % (abs(b + 1) / se, abs(b) / se),
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='bottom')
    style(ax, 'b　補氣時甲烷有沒有被稀釋（%d 次補氣）' % len(dx),
          '壓力的對數變化', '甲烷濃度的對數變化')

    # ── (c) 循環內的斜率分布 ──
    sl_in = []
    for s, e in descents(hh2, p2, min_pts=30, min_drop=0.05, min_hr=0.0):
        if m2[s] <= 5:
            continue
        X = np.log(p2[s:e + 1] + ATM)
        if X.std() < 1e-6:
            continue
        sl_in.append(np.polyfit(X, np.log(np.clip(m2[s:e + 1], 0.1, None)), 1)[0])
    sl_in = np.array(sl_in)
    ax = axes[2]
    ax.hist(sl_in, bins=np.linspace(-3, 2, 30), color=BLUE, alpha=0.8, lw=0)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.35)
    top = ax.get_ylim()[1]
    # 三條線的標籤要錯開高度與左右，否則會疊在一起
    marks = ((-1, RED, '真頂空 −1', 0.97, 'right'),
             (float(np.median(sl_in)), INK,
              '實測中位 %.2f' % np.median(sl_in), 0.80, 'left'),
             (0, MUTED, '完全無反應 0', 0.63, 'left'))
    for v, col, lab, yy, ha in marks:
        ax.axvline(v, color=col, lw=2, ls='-' if col is INK else '--')
        ax.text(v + (0.08 if ha == 'left' else -0.08), top * yy, lab,
                color=col, fontsize=9, ha=ha, va='top')
    ax.text(0.03, 0.05, '分鐘尺度沒反應、小時尺度部分反應，\n'
                        '代表分析儀以數十分鐘的時間常數\n滯後追蹤頂空組成。',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='bottom')
    style(ax, 'c　單一循環內的斜率（%d 個循環）' % len(sl_in),
          '甲烷對壓力的對數斜率', '循環數')

    out = os.path.join(OUT, 'fig44_sensor_validity.png')
    fig.savefig(out)
    plt.close(fig)
    print('補氣稀釋檢定　n=%d　斜率 %+.3f ± %.3f（距 −1 為 %.1fσ，距 0 為 %.1fσ）'
          % (len(dx), b, se, abs(b + 1) / se, abs(b) / se))
    print('循環內斜率　n=%d　中位 %+.3f' % (len(sl_in), np.median(sl_in)))
    print('圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
