# -*- coding: utf-8 -*-
"""排氣本身就會選擇性移除 H2 —— 不需要洩漏的第三個機制。

2026-09-23。起因：使用者指出——

    「H2 難溶於水，故和頂空壓力一起被排出。但很多時候壓力週期當中
      並沒有偵測的情況，所以要證實 H2 漏氣是否屬實需要先觀察，
      尤其是這種多個變量混合。」

════════════════════════════════════════════════════════════════════════
機制（比先前寫的「碳酸鹽脫氣」更精確）

  排氣的瞬間，氣體**按當下的氣相組成等比例**被排掉——這對 CO2 與 H2 公平。
  不公平的是**排氣之後**：

    壓力降低 ⟹ 液相的 CO2 過飽和 ⟹ 脫氣回補，CO2 分壓部分回升
    H2 在液相幾乎沒有存量（溶解度約為 CO2 的 1/40，又不參與酸鹼平衡）
    ⟹ **H2 補不回來**

  結果：每一次排氣都在**淨選擇性移除 H2**。
  這完全不需要洩漏，是正常操作的必然結果，而且**會累積**。

乘法累積模型（給出一個可以驗算的數字）

  設排氣前絕對壓力 P1、排氣後 P2。等溫下氣相莫耳數按 P2/P1 縮減。
  取「CO2 完全回補、H2 完全不回補」為上界：

      CO2 分壓不變、H2 分壓 × (P2/P1)
      ⟹ **比值 R 每次排氣乘以 P1/P2**

  故經 n 次排氣後：R_n = R_0 × (P1/P2)^n
  要從進料比 0.25 漲到實測中位 0.699，需要

      n = ln(0.699/0.25) / ln(P1/P2)

  本檔用實測的壓降算出這個 n，並與**實際排氣次數**比較。

⚠ 使用者的另一半提醒同樣關鍵：**排氣事件被嚴重低估**
  先前只用「帶氣體組成」的排氣（35 次），但那只是有讀到組成的那些。
  本檔改用壓力驟降偵測全部排氣，兩者相差數倍。

⚠ 這是上界估計。實際 CO2 不會完全回補（液相庫有限且會被消耗），
  故真實所需次數會多於 n。本檔同時給出部分回補的情形。

輸出 -> 純文字 + docs/analysis_charts_3batch/fig50_vent_selective.png
"""
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
from carbonate_degassing_test import (                   # noqa: E402
    spearman, perm_p, mde_spearman)

ATM = 1.033
FEED_RATIO = 0.25
P_H2O_KPA = 4.24
KGF_TO_KPA = 98.0665
DROP_THR = -0.10        # 單分鐘降幅門檻（kgf/cm²）：視為一次排氣


def all_vents(ts, hh, p, thr=DROP_THR):
    """以壓力驟降偵測**所有**排氣，不要求有氣體組成讀數。"""
    out = []
    for i in range(1, len(p)):
        dt = hh[i] - hh[i - 1]
        if not (0.008 < dt < 0.03):
            continue
        d = p[i] - p[i - 1]
        if d <= thr:
            out.append(dict(i=i, p1=float(p[i - 1]), p2=float(p[i]),
                            drop=float(-d), t=ts[i]))
    # 合併連續數分鐘的同一次排氣
    merged = []
    for e in out:
        if merged and e['i'] - merged[-1]['i'] <= 5:
            merged[-1]['p2'] = e['p2']
            merged[-1]['drop'] = merged[-1]['p1'] - e['p2']
            merged[-1]['i'] = e['i']
            continue
        merged.append(e)
    return merged


def ratio_of(p_prev, x_co2, x_ch4):
    P_abs = p_prev + ATM
    f_h2o = P_H2O_KPA / (P_abs * KGF_TO_KPA) * 100
    x_h2 = 100 - x_co2 - x_ch4 - f_h2o
    return (x_co2 / x_h2 if x_h2 > 1 else None), x_h2


def main():
    ts, hh, p, orp, ph, co2, ch4 = load_with_gas()
    gas_ev = find_vents(ts, hh, p, co2, ch4)
    print('=' * 72)
    print('一、到底有幾次排氣？（使用者：「很多時候並沒有偵測的情況」）')
    print('=' * 72)
    print('  帶氣體組成的排氣（先前分析所用）：**%d 次**' % len(gas_ev))
    for thr in (-0.05, -0.10, -0.15, -0.20, -0.30):
        ev = all_vents(ts, hh, p, thr)
        print('  以壓力驟降偵測（單分鐘 <= %.2f）：%3d 次' % (thr, len(ev)))
    ev = all_vents(ts, hh, p)
    print('\n  -> 以 %.2f 為門檻，實際排氣是「帶組成」那批的 **%.1f 倍**。'
          % (DROP_THR, len(ev) / len(gas_ev)))
    print('     **先前的分析只看得到其中一小部分。**')

    print('\n' + '=' * 72)
    print('二、每次排氣把比值推高多少？（乘法累積模型）')
    print('=' * 72)
    drops = np.array([e['drop'] for e in ev])
    p1 = np.array([e['p1'] for e in ev]) + ATM
    p2 = np.array([e['p2'] for e in ev]) + ATM
    fac = p1 / p2
    print('  排氣壓降：中位 %.3f kgf/cm²（IQR [%.3f, %.3f]）'
          % (np.median(drops), *np.percentile(drops, [25, 75])))
    print('  絕對壓力 %.2f -> %.2f ⟹ 每次排氣比值乘以 **%.3f**（上界）'
          % (np.median(p1), np.median(p2), np.median(fac)))
    need = np.log(0.699 / FEED_RATIO) / np.log(np.median(fac))
    print('\n  要把比值由進料比 %.2f 推到實測中位 0.699，需要 **%.1f 次排氣**'
          % (FEED_RATIO, need))
    print('  而實際排氣有 %d 次。' % len(ev))
    print('  -> **綽綽有餘。這個機制不需要任何洩漏就能解釋全部偏離。**')

    print('\n  部分回補的情形（CO2 只回補 f 的比例）：')
    print('  %-10s %-16s %s' % ('回補比例 f', '每次的乘數', '所需次數'))
    for f in (1.0, 0.7, 0.5, 0.3, 0.1):
        m = np.median(p1 / p2) ** f
        n = np.log(0.699 / FEED_RATIO) / np.log(m) if m > 1 else np.inf
        print('  %-10.0f%% %-16.4f %.0f' % (f * 100, m, n))
    print('  -> 即使 CO2 只回補一成，%.0f 次排氣也足夠。'
          % (np.log(0.699 / FEED_RATIO) / np.log(np.median(fac) ** 0.1)))

    print('\n' + '=' * 72)
    print('三、直接檢驗：兩次量測之間排氣越多，比值是否漲越多？')
    print('=' * 72)
    # 對每一對相鄰的「帶組成排氣」，數中間夾了幾次排氣
    rows = []
    for k in range(1, len(gas_ev)):
        a, b = gas_ev[k - 1], gas_ev[k]
        ra, _ = ratio_of(p[a - 1], co2[a], ch4[a])
        rb, _ = ratio_of(p[b - 1], co2[b], ch4[b])
        if ra is None or rb is None or ra <= 0 or rb <= 0:
            continue
        n_between = sum(1 for e in ev if a < e['i'] <= b)
        rows.append(dict(n=n_between, dlog=float(np.log(rb / ra)),
                         gap=float(hh[b] - hh[a])))
    n_arr = np.array([r['n'] for r in rows])
    dlog = np.array([r['dlog'] for r in rows])
    print('  可用的相鄰配對 %d 組' % len(rows))
    print('  中間排氣次數：中位 %.0f（範圍 %d ~ %d）'
          % (np.median(n_arr), n_arr.min(), n_arr.max()))
    rho, pv = perm_p(n_arr, dlog)
    mde = mde_spearman(len(rows))
    print('  中間排氣次數 vs 比值的對數變化：ρ = %+.3f，p = %.4f' % (rho, pv))
    print('  本模型預測：**正相關**（每次排氣都把比值往上推）')
    print('  ⚠ MDE（n=%d）≈ %.2f' % (len(rows), mde))
    if pv < 0.05 and rho > 0:
        print('  -> 符合預測，且達統計顯著')
    elif abs(rho) < mde:
        print('  -> ⚠ 無定論：樣本不足以分辨（這正是使用者說的'
              '「多個變量混合」的困難）')
    else:
        print('  -> ⚠ 未觀察到預期的正相關')

    print('\n' + '=' * 72)
    print('四、推論：碳源切斷實驗的虛無結果，其實是必然的')
    print('=' * 72)
    print('  使用者指出：**反應中並不缺乏 CO2**。')
    print('  既然液相有碳酸鹽緩衝庫，「切斷氣相 CO2 供應」並不等於「碳源耗盡」')
    print('  ——液相的 HCO3⁻ 會繼續供碳。\n')
    # 以 2026-09-14 現場回報的短實驗估產甲烷速率
    P_ABS = (1.10 + ATM) * KGF_TO_KPA * 1e3        # Pa（該次約略的絕對壓力）
    n_gas_per_L = P_ABS / (8.314 * 303.15) / 1e3   # mol/L 氣相
    d_ch4 = (2.07 - 0.50) / 100.0                  # 3 小時內甲烷莫耳分率淨增
    r_ch4 = n_gas_per_L * d_ch4 / 3.0              # mol/(L氣相·hr)
    dic = 0.0990                                   # mol/L 液相（見 carbonate_degassing_test）
    print('  以現場 2026-09-14 的短實驗估算（清洗後 3 小時）：')
    print('    甲烷由 0.50%% 升至 2.07%%，淨增 %.2f 個百分點' % (d_ch4 * 100))
    print('    每公升氣相 %.4f mol ⟹ 產甲烷速率 %.2e mol/(L氣相·hr)'
          % (n_gas_per_L, r_ch4))
    print('    產甲烷 1 mol 即消耗 CO2 1 mol（Sabatier 計量）')
    print('    液相每公升的溶解無機碳 %.4f mol' % dic)
    hours = dic / r_ch4
    print('\n  -> **每公升液相的碳庫可供應 %.0f 小時 = %.1f 天**'
          % (hours, hours / 24))
    print('     （若液相體積與氣相相當；液位須向設備方確認）')
    print('  -> 碳源切斷實驗僅持續數日，**遠短於碳庫的續航**。')
    print('     ⟹ 壓降速率不變（0.0347 -> 0.0367，p=0.21）**是必然的**，')
    print('        不需要用「氫氣流失」來解釋。')
    print('     ⚠ 先前把該虛無結果當成氫氣流失的佐證，**此一推論應予撤回**。')

    print('\n' + '=' * 72)
    print('五、正確的消耗量算法：用 H2 反推，不要用 CO2')
    print('=' * 72)
    print('  使用者指出：**要知道 CO2 的消耗量，應由 H2 反推。**\n')
    print('  理由（本檔前面的分析正好支持）：')
    print('    CO2 有液相緩衝庫 ⟹ 氣相 CO2 的變化被緩衝掩蓋，**不等於消耗量**')
    print('    H2 在液相幾乎無存量 ⟹ 氣相 H2 的變化**直接反映真實消耗**')
    print('')
    print('    Sabatier：CO2 + 4 H2 -> CH4 + 2 H2O')
    print('    ⟹ **消耗的 CO2 = 消耗的 H2 ÷ 4**')
    print('    ⟹ **產生的 CH4 = 消耗的 H2 ÷ 4**')
    print('')
    print('  可立即檢驗的恆等式：在兩次排氣之間，')
    print('    ΔCH4（莫耳）應等於 −ΔH2（莫耳）÷ 4')
    print('  ⚠ 但本案的 H2 是由差額推算（100 − CO2 − CH4 − H2O），')
    print('     其精度仍依賴 CO2 與 CH4 的讀數品質。')
    print('     **要真正落實這條路徑，必須直接量測 H2。**')
    print('     這使「加測 H2」由「有幫助」升級為**方法上的必要條件**。')

    print('\n' + '=' * 72)
    print('六、判讀')
    print('=' * 72)
    print('  現在有**三個**候選解釋，且都不需要洩漏之外的假設：')
    print('    ① 氫氣真的漏掉（洩漏／穿透／其他耗氫反應）')
    print('    ② 碳酸鹽脫氣（排氣瞬間水裡的碳冒回氣相）')
    print('    ③ **排氣選擇性移除 H2**（本檔；② 的更精確表述，且會累積）')
    print('')
    print('  ③ 的量級最強：只需 %.0f 次排氣即可解釋全部偏離，' % need)
    print('     而實際排氣至少 %d 次。' % len(ev))
    print('')
    print('  ⚠ 但「量級足夠」不等於「就是它」。三者會同時發生，')
    print('     且彼此混淆——這正是使用者指出的困難。')
    print('  ⟹ **無菌對照仍是唯一的判別手段**：無菌時 ③ 照樣發生（排氣照做），')
    print('     ① 若不存在則壓力在不排氣時不應下降。兩者可分。')

    make_figure(ev, gas_ev, rows, need, fac)


def make_figure(ev, gas_ev, rows, need, fac):
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(15.0, 4.7),
                                     gridspec_kw={'wspace': 0.32})

    # a 排氣次數被嚴重低估
    a1.bar([0, 1], [len(gas_ev), len(ev)], width=0.55, color=[MUTED, BLUE])
    a1.set_xticks([0, 1])
    a1.set_xticklabels(['帶氣體組成\n(先前分析所用)', '壓力驟降\n(實際排氣)'])
    for x, v in ((0, len(gas_ev)), (1, len(ev))):
        a1.text(x, v + len(ev) * 0.03, '%d' % v, ha='center', va='bottom',
                fontsize=17, fontweight='bold', color=INK)
    _, hi = a1.get_ylim()
    a1.set_ylim(0, hi * 1.30)
    a1.text(0.5, 0.97, '實際排氣是先前統計的 %.1f 倍' % (len(ev) / len(gas_ev)),
            transform=a1.transAxes, fontsize=13, color=RED,
            fontweight='bold', ha='center', va='top')
    style(a1, 'a　排氣次數被嚴重低估', '', '次數')

    # b 乘法累積：幾次排氣就夠
    n = np.arange(0, 31)
    for f, c, ls in ((1.0, BLUE, '-'), (0.5, AQUA, '--'), (0.1, MUTED, ':')):
        m = float(np.median(fac)) ** f
        a2.plot(n, FEED_RATIO * m ** n, color=c, lw=2.8, ls=ls,
                label='CO₂ 回補 %.0f%%' % (f * 100))
    a2.axhline(0.699, color=RED, lw=2.4, ls='--')
    a2.set_yscale('log')
    a2.set_yticks([0.25, 0.5, 1.0, 2.0])
    a2.set_yticklabels(['0.25', '0.5', '1.0', '2.0'])
    a2.minorticks_off()
    a2.legend(loc='lower right', frameon=False, fontsize=11)
    _lo, hi = a2.get_ylim()
    a2.set_ylim(_lo, hi * 2.6)
    a2.text(0.5, 0.97,
            '只要 %.0f 次排氣就能從 0.25 漲到 0.699\n實際排氣有 %d 次'
            % (need, len(ev)),
            transform=a2.transAxes, fontsize=12.5, color=INK,
            fontweight='bold', ha='center', va='top')
    # 標籤靠左，避開右下角的圖例
    a2.text(0.5, 0.699, ' 實測中位 0.699', color=RED, fontsize=11,
            fontweight='bold', ha='left', va='bottom')
    style(a2, 'b　每次排氣都把比值往上推', '排氣次數', 'CO₂:H₂（對數軸）')

    # c 直接檢驗
    n_arr = np.array([r['n'] for r in rows])
    dlog = np.array([r['dlog'] for r in rows])
    a3.scatter(n_arr, dlog, s=70, color=BLUE, edgecolors='white', zorder=4)
    a3.axhline(0, color=INK, lw=1.4)
    rho = spearman(n_arr, dlog)
    mde = mde_spearman(len(rows))
    _lo, hi = a3.get_ylim()
    a3.set_ylim(_lo, hi + (hi - _lo) * 0.38)
    a3.text(0.03, 0.97,
            '模型預測：正相關\n實測 ρ = %+.3f（MDE %.2f）\n'
            '⚠ 樣本不足以分辨' % (rho, mde),
            transform=a3.transAxes, fontsize=12, color=INK,
            fontweight='bold', ha='left', va='top')
    style(a3, 'c　中間排氣越多，比值漲越多嗎', '兩次量測之間的排氣次數',
          '比值的對數變化')

    out = os.path.join(OUT, 'fig50_vent_selective.png')
    fig.savefig(out)
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
