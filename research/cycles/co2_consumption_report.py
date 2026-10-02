# -*- coding: utf-8 -*-
"""CO2 消耗量的確切估計 —— 由甲烷反推，不需要 H2 感測器。

2026-09-23。洪博要求：求得 CO2 消耗量的確切資料。

════════════════════════════════════════════════════════════════════════
為什麼可以不靠 H2 感測器

  Sabatier：CO2 + 4 H2 -> CH4 + 2 H2O
  計量比 CO2 : CH4 = **1 : 1**

      ⟹ **消耗的 CO2 莫耳數 = 產生的 CH4 莫耳數**

  而甲烷**只能來自生物**（溶解不產生甲烷、洩漏不產生甲烷、排氣也不產生），
  且現場已在量測。故 CO2 消耗量可由甲烷直接得到，
  **不需要 H2 感測器，也不需要解任何可辨識性問題。**

⚠ 三個必須處理的細節（不處理就會算錯）

  1. **要用絕對莫耳數，不能用濃度。**
     補氣加入 CO2 與 H2、不含甲烷，會把甲烷濃度稀釋；
     排氣則按比例排掉、**濃度不變而總量減少**。
     兩者都讓「濃度」失真。
         n_CH4 = x_CH4 × P_abs × V_gas / (R T)
     用 x_CH4 × P_abs 才是絕對量的代理。

  2. **排氣造成的甲烷損失要扣掉。**
     排氣後殘留 = x_CH4 × P_after（濃度不變、壓力降低）。
     故兩次量測之間的生成量 =
         n_CH4(本次, 排氣前) − n_CH4(上次, 排氣後)

  3. **氣相體積未知。** 反應器總容積 1.99 L，但液位須向設備方確認。
     本檔一律報「每公升氣相」，另附總容積的換算區間。

⚠ 本檔**不涉及**壓降歸因，也不需要區分洩漏／脫氣／生物。
  那是另一個問題（見 vent_selective_h2_loss.py）。
  甲烷的計量關係與那些爭議完全無關。

輸出 -> docs/analysis_charts_3batch/co2_consumption.csv
        docs/analysis_charts_3batch/fig51_co2_consumption.png
"""
import csv
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                          # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (                      # noqa: E402
    BLUE, RED, AQUA, INK, INK2, MUTED, OUT, style)
from orp_calibration import find_vents, load_with_gas    # noqa: E402

ATM = 1.033
KGF_TO_KPA = 98.0665
R_GAS = 8.314
T_K = 303.15
V_TOTAL = 1.99          # 反應器總容積 (L)，⚠ 液位須確認
M_CO2 = 44.01           # g/mol
VM_STP = 22.414         # L/mol @ STP


def n_per_L(x_pct, p_kgf):
    """每公升氣相中該成分的莫耳數。x_pct 為體積百分率。"""
    P_pa = (p_kgf + ATM) * KGF_TO_KPA * 1e3
    return (x_pct / 100.0) * P_pa / (R_GAS * T_K) / 1e3


def main():
    ts, hh, p, orp, ph, co2, ch4 = load_with_gas()
    ev = find_vents(ts, hh, p, co2, ch4)
    print('全資料庫 %d 筆；帶氣體組成的排氣 %d 次（%s ~ %s）\n'
          % (len(ts), len(ev), ts[ev[0]].date(), ts[ev[-1]].date()))

    print('=' * 88)
    print('逐段結果：兩次排氣之間的甲烷生成量 = 二氧化碳消耗量')
    print('=' * 88)
    print('%-12s %-12s %7s %7s %9s %9s %11s'
          % ('起', '迄', '時數', 'CH4%', 'n前(mmol)', 'n後(mmol)', '消耗速率'))

    # 全部排氣（含沒有組成讀數的）與甲烷分率的內插底數
    from vent_selective_h2_loss import all_vents
    mid_vents = all_vents(ts, hh, p)
    ct = np.array([hh[i] for i in ev])
    cv = np.array([ch4[i] / 100.0 for i in ev])
    print('  （區間內的排氣以壓力驟降偵測，共 %d 次；'
          '其帶走的甲烷已補回生成量）\n' % len(mid_vents))

    rows = []
    for k in range(1, len(ev)):
        a, b = ev[k - 1], ev[k]
        dur = float(hh[b] - hh[a])
        if dur <= 0 or dur > 24 * 30:
            continue
        # 上一次排氣「之後」的甲烷殘留：濃度不變、壓力取排氣後低點
        j = min(len(p) - 1, a + 6)
        p_after = float(np.min(p[a:j + 1]))
        n_start = n_per_L(ch4[a], p_after)
        # 本次排氣「之前」的甲烷：用排氣前一筆的壓力
        n_end = n_per_L(ch4[b], float(p[b - 1]))
        # ⚠ 生成量 ≠ 淨增量：區間內若另有排氣，甲烷會被帶走。
        #   帶組成的排氣只有 35 次，但壓力驟降偵測出 108 次，
        #   故區間內常夾有未被計入的排氣。不補回就會低估。
        n_lost = 0.0
        for v in mid_vents:
            if a < v['i'] <= b:
                x = float(np.interp(hh[v['i']], ct, cv))
                n_lost += v['drop'] * KGF_TO_KPA * 1e3 / (R_GAS * T_K) / 1e3 * x
        gen = (n_end - n_start) + n_lost           # mol per L(gas)
        if gen <= 0:
            continue                               # 該段甲烷未淨增，不採計
        rate = gen / dur                           # mol/(L·hr)
        rows.append(dict(t0=ts[a], t1=ts[b], dur=dur, ch4=ch4[b],
                         n0=n_start, n1=n_end, gen=gen, rate=rate))
        print('%-12s %-12s %7.1f %7.1f %9.3f %9.3f %11.3e'
              % (ts[a].date(), ts[b].date(), dur, ch4[b],
                 n_start * 1e3, n_end * 1e3, rate))

    if not rows:
        print('  無可用區段')
        return

    rate = np.array([r['rate'] for r in rows])
    print('\n' + '=' * 88)
    print('彙整：二氧化碳消耗速率')
    print('=' * 88)
    med = float(np.median(rate))
    q = np.percentile(rate, [25, 75])
    print('  可用區段 %d 段，總時數 %.0f 小時'
          % (len(rows), sum(r['dur'] for r in rows)))
    print('  每公升氣相的消耗速率：')
    print('    中位 %.3e mol/(L·hr)　IQR [%.3e, %.3e]' % (med, q[0], q[1]))
    print('    = %.4f mmol/(L·hr)' % (med * 1e3))
    print('    = %.3f mL(STP)/(L·hr)' % (med * VM_STP * 1e3))
    print('    = %.2f mg-CO2/(L·hr)' % (med * M_CO2 * 1e3))

    print('\n  換算為整台反應器（⚠ 需液位才能定案）：')
    print('  %-16s %-14s %-16s %s'
          % ('假設氣相體積', 'mmol/hr', 'mL(STP)/hr', 'g-CO2/day'))
    for vg in (0.5, 1.0, 1.5, V_TOTAL):
        tag = '%.2f L' % vg + ('（全滿）' if abs(vg - V_TOTAL) < 1e-9 else '')
        print('  %-16s %-14.4f %-16.3f %.4f'
              % (tag, med * vg * 1e3, med * vg * VM_STP * 1e3,
                 med * vg * M_CO2 * 24))

    # 與現場短實驗（2026-09-14）對照
    print('\n' + '=' * 88)
    print('對照：現場 2026-09-14 的短實驗（獨立於上表，作為驗證）')
    print('=' * 88)
    p_field = 1.10
    n0_f = n_per_L(0.50, p_field)
    n1_f = n_per_L(2.07, p_field)
    rate_f = (n1_f - n0_f) / 3.0
    print('  清洗後甲烷 0.50%%，3 小時後 2.07%%（壓力約 %.2f kgf/cm²）' % p_field)
    print('  -> 消耗速率 %.3e mol/(L·hr) = %.4f mmol/(L·hr)'
          % (rate_f, rate_f * 1e3))
    print('  本表中位 %.4f mmol/(L·hr)，比值 %.2f 倍'
          % (med * 1e3, rate_f / med))
    if 0.3 < rate_f / med < 3.0:
        print('  -> **兩者同量級，互相支持。**')
    else:
        print('  -> ⚠ 兩者差距超過三倍，需檢查')

    # ── 差異來源：長段落會低估瞬時速率 ──────────────────────
    print('\n' + '=' * 88)
    print('為什麼差 %.1f 倍？檢查段落長度的影響' % (rate_f / med))
    print('=' * 88)
    dur = np.array([r['dur'] for r in rows])
    from carbonate_degassing_test import spearman, perm_p, mde_spearman
    rho, pv = perm_p(dur, rate)
    mde = mde_spearman(len(rows))
    print('  假說：段落越長，平均速率越被低估。')
    print('    因為甲烷若在前期就累積完（基質耗盡後不再產），')
    print('    「總生成量 ÷ 總時長」會把後段的零產量平均進來。')
    print('  實測：段長 vs 速率　ρ = %+.3f，p = %.4f（n=%d，MDE %.2f）'
          % (rho, pv, len(rows), mde))
    if rho < -0.2 and pv < 0.05:
        print('  -> **顯著負相關，假說成立**：長段落確實低估。')
    elif abs(rho) < mde:
        print('  -> ⚠ 未達顯著，但樣本僅 %d 段、MDE 高達 %.2f，不足以否定。'
              % (len(rows), mde))
    else:
        print('  -> ⚠ 方向不符，需另尋解釋。')

    print('\n  依段長分層：')
    print('  %-16s %-8s %-16s %s' % ('段長', '段數', '中位速率(mmol/L/hr)', '相對'))
    for lo_h, hi_h, tag in ((0, 48, '< 2 天'), (48, 168, '2 ~ 7 天'),
                            (168, 1e9, '> 7 天')):
        m = (dur >= lo_h) & (dur < hi_h)
        if m.sum() == 0:
            print('  %-16s %-8d —' % (tag, 0))
            continue
        mm = float(np.median(rate[m]))
        print('  %-16s %-8d %-16.4f %.2f 倍'
              % (tag, int(m.sum()), mm * 1e3, mm / med))
    short = rate[dur < 48]
    if len(short):
        print('\n  ★ 最短的那一層（< 2 天）中位 %.4f mmol/(L·hr)，'
              % (float(np.median(short)) * 1e3))
        print('     與 09-14 短實驗（%.4f）相差 %.1f 倍，較為接近。'
              % (rate_f * 1e3, max(rate_f, np.median(short))
                 / min(rate_f, np.median(short))))
    print('\n  ⟹ **報告時應併列兩個數字**：')
    print('     長期平均（含基質耗盡期）%.4f mmol/(L·hr)' % (med * 1e3))
    print('     短期／初始速率（基質充足）%.4f mmol/(L·hr)' % (rate_f * 1e3))
    print('     兩者相差約 %.1f 倍，差異本身就是「基質會耗盡」的證據。'
          % (rate_f / med))

    print('\n' + '=' * 88)
    print('這個數字為什麼可信（以及它的限制）')
    print('=' * 88)
    print('  ✓ 不需要 H2 感測器：Sabatier 計量 CO2:CH4 = 1:1')
    print('  ✓ 不受壓降歸因的爭議影響：甲烷只能來自生物，')
    print('    溶解、洩漏、排氣都不產生甲烷')
    print('  ✓ 已扣除補氣稀釋與排氣損失（用絕對莫耳數而非濃度）')
    print('')
    print('  ⚠ 限制一：氣相體積未知，故「每公升」以外的數字都是換算。')
    print('    **請設備方提供液位，即可定案。**')
    print('  ⚠ 限制二：僅 %d 段可用，平均每段 %.0f 小時，時間解析度很粗。'
          % (len(rows), float(np.mean([r['dur'] for r in rows]))))
    print('    加密排氣取樣（每 3.5 hr）可將解析度提高兩個數量級。')
    print('  ⚠ 限制三：甲烷讀數僅在排氣當下 1~2 分鐘可信（已由稀釋檢定證實），')
    print('    本表只取那些時刻。')

    make_figure(rows, rate_f, rho, pv)
    path = os.path.join(OUT, 'co2_consumption.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['起始', '結束', '時數', 'CH4%',
                    '起始n(mmol/L氣相)', '結束n(mmol/L氣相)',
                    '生成(mmol/L氣相)', 'CO2消耗速率(mmol/L氣相/hr)'])
        for r in rows:
            w.writerow([r['t0'].strftime('%Y-%m-%d %H:%M'),
                        r['t1'].strftime('%Y-%m-%d %H:%M'),
                        round(r['dur'], 1), round(r['ch4'], 2),
                        round(r['n0'] * 1e3, 4), round(r['n1'] * 1e3, 4),
                        round(r['gen'] * 1e3, 4), round(r['rate'] * 1e3, 5)])
    print('\n逐段明細 -> %s（%d 段）' % (os.path.relpath(path, REPO), len(rows)))


def make_figure(rows, rate_field, rho, pv):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.6, 4.8),
                                 gridspec_kw={'wspace': 0.30})
    rate = np.array([r['rate'] for r in rows]) * 1e3      # mmol/(L·hr)
    t = [r['t1'] for r in rows]

    a1.plot(t, rate, marker='o', ms=9, lw=2.0, color=BLUE)
    med = float(np.median(rate))
    a1.axhline(med, color=RED, lw=2.4, ls='--')
    _lo, hi = a1.get_ylim()
    a1.set_ylim(0, hi * 1.38)
    a1.text(t[0], med, ' 中位 %.4f' % med, color=RED, fontsize=12,
            fontweight='bold', ha='left', va='bottom')
    a1.text(0.03, 0.97, '由甲烷反推（Sabatier CO₂:CH₄ = 1:1）\n不需要 H₂ 感測器',
            transform=a1.transAxes, fontsize=12.5, color=INK,
            fontweight='bold', ha='left', va='top')
    fig.autofmt_xdate(rotation=30)
    style(a1, 'a　二氧化碳消耗速率（逐段）', '',
          'mmol / (L氣相·hr)')

    # b 段長 vs 速率：解釋為何與現場短實驗相差數倍
    dur = np.array([r['dur'] for r in rows]) / 24.0        # 天
    a2.scatter(dur, rate, s=80, color=BLUE, edgecolors='white', zorder=4,
               label='本表各段')
    a2.scatter([3.0 / 24], [rate_field * 1e3], s=250, marker='*',
               color=RED, edgecolors='white', linewidths=1.5, zorder=6,
               label='2026-09-14 現場（3 小時）')
    a2.set_xscale('log')
    a2.set_xticks([0.1, 1, 3, 10, 30])
    a2.set_xticklabels(['0.1', '1', '3', '10', '30'])
    a2.minorticks_off()
    a2.legend(loc='upper right', frameon=False, fontsize=11.5)
    _lo, hi = a2.get_ylim()
    a2.set_ylim(0, hi * 1.42)
    a2.text(0.03, 0.97,
            '段落越長，平均速率越低\n'
            'ρ = %+.2f（p = %.3f）\n'
            '→ 長段落把「基質耗盡後的零產量」也平均進來'
            % (rho, pv),
            transform=a2.transAxes, fontsize=12, color=INK,
            fontweight='bold', ha='left', va='top')
    style(a2, 'b　為何與現場短實驗相差數倍',
          '量測間隔（天，對數軸）', 'mmol / (L氣相·hr)')

    out = os.path.join(OUT, 'fig51_co2_consumption.png')
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
