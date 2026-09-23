# -*- coding: utf-8 -*-
"""進料確認為 1:4 之後，頂空的 CO2:H2 比值偏離量說明了什麼。

2026-09-21。設備方確認進料為 CO2:H2 = 1:4（莫耳比），與 Sabatier 反應的
化學計量完全相同：

    CO2 + 4 H2 -> CH4 + 2 H2O(液)

════════════════════════════════════════════════════════════════════════
為什麼「進料比 = 反應計量比」是一個很強的分析槓桿

  若系統內**只有**產甲烷反應在進行，則消耗與補充都依 1:4 進行，
  頂空的 CO2:H2 莫耳比會**永遠停在 0.25**，與轉化率無關。
  因此比值的偏離方向即為診斷：

      比值 < 0.25  ->  CO2 被額外移除（CO2 溶解度為 H2 的約 44 倍，溶解即屬此類）
      比值 = 0.25  ->  僅有產甲烷
      比值 > 0.25  ->  H2 被額外移除（洩漏、或其他耗氫反應）

  這項檢定不需要任何校準常數，也不依賴壓力模型，只需要排氣瞬間的組成。

資料來源與可信度

  氣體分析儀在排氣瞬間（閥開啟後一至二分鐘）會被頂空氣體沖洗乾淨，
  該時段之讀值可視為真實頂空組成；其餘時間為取樣管路之延遲拖尾，不可採用。
  本檔僅取排氣事件當下之讀值，全資料庫去重後共 35 筆。

  ⚠ 水蒸氣修正：30 °C 之飽和水蒸氣壓為 4.24 kPa。於絕對壓力約 2.2 kgf/cm²
    （215 kPa）下約佔 2.0%，已自乾基換算中扣除。

輸出 -> docs/analysis_charts_3batch/feed_ratio_drift.csv
        docs/analysis_charts_3batch/fig43_feed_ratio.png
"""
import csv
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
from orp_calibration import find_vents, load_with_gas    # noqa: E402

ATM = 1.033
FEED_RATIO = 0.25          # 進料 CO2:H2 = 1:4（設備方確認）
P_H2O_KPA = 4.24           # 30 °C 飽和水蒸氣壓
KGF_TO_KPA = 98.0665


def main():
    ts, hh, p, orp, ph, co2, ch4 = load_with_gas()
    ev = find_vents(ts, hh, p, co2, ch4)
    print('全資料庫去重後 %d 筆；排氣事件 %d 筆（%s ~ %s）'
          % (len(ts), len(ev), ts[ev[0]].date(), ts[ev[-1]].date()))
    print('進料組成：CO2 : H2 = 1 : 4（莫耳比），即 CO2 佔 %.0f%%' % (FEED_RATIO / (1 + FEED_RATIO) * 100))
    print('Sabatier 反應計量：CO2 + 4 H2 -> CH4 + 2 H2O，消耗比同為 1 : 4')
    print('故若系統內僅有產甲烷反應，頂空 CO2:H2 應恆為 %.2f\n' % FEED_RATIO)

    rows = []
    print('%-17s %6s %7s %7s %7s %8s %8s'
          % ('排氣時刻', '前壓', 'CO2%', 'CH4%', 'H2%*', 'CO2:H2', '偏離'))
    for i in ev:
        P_abs = p[i - 1] + ATM
        f_h2o = P_H2O_KPA / (P_abs * KGF_TO_KPA) * 100          # 水蒸氣佔比 (%)
        x_co2, x_ch4 = co2[i], ch4[i]
        x_h2 = 100 - x_co2 - x_ch4 - f_h2o
        if x_h2 <= 1:                                            # H2 已近耗盡，比值失去意義
            continue
        r = x_co2 / x_h2
        rows.append(dict(t=ts[i], P=p[i - 1], co2=x_co2, ch4=x_ch4, h2=x_h2,
                         ratio=r, dev=r / FEED_RATIO))
        print('%-17s %6.2f %7.2f %7.2f %7.2f %8.3f %7.2f×'
              % (ts[i].strftime('%Y-%m-%d %H:%M'), p[i - 1], x_co2, x_ch4, x_h2,
                 r, r / FEED_RATIO))

    R = np.array([x['ratio'] for x in rows])
    D = np.array([x['dev'] for x in rows])
    print('\n── 統計 ──')
    print('   可用事件 %d 筆（已排除 H2 近耗盡者 %d 筆）' % (len(rows), len(ev) - len(rows)))
    print('   CO2:H2 中位 %.3f　IQR [%.3f, %.3f]　（進料比 %.2f）'
          % (np.median(R), *np.percentile(R, [25, 75]), FEED_RATIO))
    print('   相對進料比：中位 %.2f 倍　高於進料比者 %d/%d（%.0f%%）'
          % (np.median(D), (D > 1).sum(), len(D), (D > 1).mean() * 100))

    rng = np.random.default_rng(0)
    obs = abs(np.median(np.log(D)))
    pv = float(np.mean([abs(np.median(np.log(D) * rng.choice([-1, 1], len(D)))) >= obs
                        for _ in range(20000)]))
    print('   對數比值的符號置換檢定　p = %.4f' % pv)
    if np.median(D) > 1 and pv < 0.05:
        print('   -> 比值顯著**高於**進料比：H2 相對於 CO2 被額外移除')
        print('      （若主因為 CO2 物理溶解，比值應低於進料比，方向相反）')
    elif np.median(D) < 1 and pv < 0.05:
        print('   -> 比值顯著**低於**進料比：CO2 被額外移除，符合物理溶解')
    else:
        print('   -> 未偏離進料比')

    # 量化：要讓比值從 0.25 漂到實測值，需要多少額外的 H2 移除
    print('\n── 換算：額外移除的 H2 佔進料 H2 的比例 ──')
    print('   設進料 1 mol CO2 + 4 mol H2，產甲烷消耗 x 與 4x，')
    print('   另有 y mol H2 被額外移除，則殘餘比 = (1−x)/(4−4x−y)。')
    for q, lab in ((25, '第 25 百分位'), (50, '中位'), (75, '第 75 百分位')):
        r = float(np.percentile(R, q))
        # 以殘餘分率 f = 1−x 表示：r = f/(4f − y) => y = 4f − f/r，取 f=1（保守：單次通過）
        y = 4 - 1 / r
        print('   %-10s 比值 %.3f -> 需額外移除 H2 約 %.2f mol／每 4 mol 進料（%.0f%%）'
              % (lab, r, y, y / 4 * 100))
    print('   ⚠ 此為單次通過之保守換算；實際為連續補氣，數值僅示意量級。')

    make_figure(rows, R, D)
    path = os.path.join(OUT, 'feed_ratio_drift.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['排氣時刻', '排氣前壓力', 'CO2%', 'CH4%', 'H2%(差額)',
                    'CO2:H2', '相對進料比'])
        for x in rows:
            w.writerow([x['t'].strftime('%Y-%m-%d %H:%M'), round(x['P'], 2),
                        round(x['co2'], 2), round(x['ch4'], 2), round(x['h2'], 2),
                        round(x['ratio'], 4), round(x['dev'], 3)])
    print('\n逐事件明細 -> %s（%d 列）' % (os.path.relpath(path, REPO), len(rows)))


def make_figure(rows, R, D):
    fig, axes = plt.subplots(1, 3, figsize=(14.6, 4.6), gridspec_kw={'wspace': 0.3})

    ax = axes[0]
    hi = float(np.percentile(R, 90))
    n_over = int((R > hi).sum())
    ax.hist(np.clip(R, None, hi), bins=np.linspace(0, hi, 22),
            color=BLUE, alpha=0.8, lw=0)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.5)           # 先留出標註空間再放標註
    top = ax.get_ylim()[1]
    ax.axvline(FEED_RATIO, color=RED, lw=2, ls='--')
    ax.annotate('進料比 0.25\n（只有產甲烷時應停在這裡）',
                xy=(FEED_RATIO, top * 0.55), xytext=(hi * 0.40, top * 0.95),
                color=RED, fontsize=9, ha='left', va='top',
                arrowprops=dict(arrowstyle='->', color=RED, lw=1))
    ax.axvline(np.median(R), color=INK, lw=2)
    ax.annotate('實測中位 %.2f' % np.median(R),
                xy=(np.median(R), top * 0.38), xytext=(hi * 0.40, top * 0.66),
                color=INK, fontsize=9.5, ha='left', va='top',
                arrowprops=dict(arrowstyle='->', color=INK, lw=1))
    if n_over:
        ax.text(0.98, 0.04, '另有 %d 次比值更高（併入最右格）' % n_over,
                transform=ax.transAxes, fontsize=8.5, color=MUTED,
                ha='right', va='bottom')
    style(ax, 'a　排氣當下量到的二氧化碳與氫氣比例', '二氧化碳 ÷ 氫氣', '排氣次數')

    ax = axes[1]
    tt = [x['t'] for x in rows]
    ax.scatter(tt, R, s=34, color=BLUE, alpha=0.75, lw=0)
    ax.axhline(FEED_RATIO, color=RED, lw=2, ls='--')
    ax.text(tt[0], FEED_RATIO * 1.06, ' 進料比 0.25', color=RED, fontsize=9,
            ha='left', va='bottom')
    ax.set_yscale('log')
    ax.text(0.03, 0.97, '每一點是一次排氣。\n點落在紅線上方 = 氫氣比二氧化碳消失得更快。',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='top')
    style(ax, 'b　一整年下來都偏在同一側', None, '二氧化碳 ÷ 氫氣（對數軸）')
    import matplotlib.dates as mdates
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    ax = axes[2]
    co2 = np.array([x['co2'] for x in rows])
    h2 = np.array([x['h2'] for x in rows])
    ax.scatter(h2, co2, s=34, color=BLUE, alpha=0.75, lw=0)
    xs = np.linspace(0, max(h2) * 1.05, 20)
    ax.plot(xs, FEED_RATIO * xs, color=RED, lw=2, ls='--',
            label='只有產甲烷時該落在這條線上')
    ax.legend(loc='upper left', fontsize=9, frameon=False)
    ax.text(0.97, 0.06, '幾乎所有點都在線的上方：\n二氧化碳剩得比應有的多，\n'
                        '等於氫氣少得比應有的多。',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='right', va='bottom')
    style(ax, 'c　二氧化碳剩多少 vs 氫氣剩多少', '氫氣 (%)', '二氧化碳 (%)')

    out = os.path.join(OUT, 'fig43_feed_ratio.png')
    fig.savefig(out)
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
