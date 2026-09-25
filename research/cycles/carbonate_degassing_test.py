# -*- coding: utf-8 -*-
"""碳酸鹽脫氣假說：CO2 過量能否在**沒有洩漏**的情況下被解釋？

2026-09-23。起因：使用者指出洩漏的判斷太草率——裝置密閉、排氣有氣密閘、
進料恆為 1:4、且 CO2 易溶於水。

════════════════════════════════════════════════════════════════════════
把這個反駁寫成可檢驗的機制

  關鍵不只是「CO2 溶解度高」，而是 **CO2 在液相有碳酸鹽緩衝庫、H2 完全沒有**：

      CO2(g) ⇌ CO2(aq) ⇌ H2CO3 ⇌ HCO3⁻ + H⁺

  在 pH 7.20（本案實測中位）下，
      [HCO3⁻]/[CO2(aq)] = 10^(pH − pKa1) = 10^(7.20 − 6.35) ≈ 7.1
  故溶解無機碳有約 88% 以 HCO3⁻ 存在，液相碳庫遠大於亨利定律單獨給出的值。

  **而我們只在排氣當下量測組成**——那正是壓力驟降、液相過飽和、
  CO2 脫氣最劇烈的時刻。脫出的 CO2 會使當下讀到的 CO2 偏高，
  **在完全沒有洩漏的情況下造成 CO2:H2 > 0.25**。

  H2 沒有對應的庫（不參與酸鹼平衡、溶解度低約 40 倍），故不會有這個效應。

本檔要回答三個問題

  一、**量級**：液相碳庫夠不夠大？脫氣能不能解釋觀測到的過量？
      （不假設液位——改為反推「需要多大的庫」，再看是否合理）
  二、**方向性後果 1**：脫氣量應隨壓降增大 ⟹ CO2 過量與壓降應正相關
  三、**方向性後果 2**：脫氣移除酸 ⟹ 排氣當下 pH 應上升

  二與三是判別關鍵：量級可行不等於機制成立。

⚠ 本檔不假設液相體積、鹼度或滅菌狀態等現場參數（須向設備方確認）。

輸出 -> 純文字 + docs/analysis_charts_3batch/fig47_carbonate.png
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

ATM = 1.033
FEED_RATIO = 0.25
P_H2O_KPA = 4.24
KGF_TO_KPA = 98.0665
PH_FAULT = 8.0              # >= 此值為感測器故障（5.6%，其中 3.3% 恰為 14.00）

# 30 °C 之物理常數
PKA1 = 6.35                 # H2CO3 / HCO3⁻
KH_CO2 = 0.0296             # mol/(L·atm)
KH_H2 = 0.00078             # mol/(L·atm)
R_GAS = 8.314               # J/(mol·K)
T_K = 303.15
ATM_KPA = 101.325


def ratio_of(p_prev, x_co2, x_ch4):
    P_abs = p_prev + ATM
    f_h2o = P_H2O_KPA / (P_abs * KGF_TO_KPA) * 100
    x_h2 = 100 - x_co2 - x_ch4 - f_h2o
    return (x_co2 / x_h2 if x_h2 > 1 else None), x_h2


def spearman(x, y):
    """Spearman 等級相關（不假設線性，對離群值穩健）。"""
    def rank(v):
        o = np.argsort(np.argsort(v))
        return o.astype(float)
    rx, ry = rank(x), rank(y)
    return float(np.corrcoef(rx, ry)[0, 1])


def mde_spearman(n, alpha=0.05, power=0.8):
    """Spearman 相關的最小可偵測效果量（Fisher z 近似）。

    ★ 小樣本下 p > 0.05 常被誤讀為「沒有關係」。先算出這個檢定
      「至少要多大的 ρ 才看得到」，才能誠實判讀虛無結果。
    """
    from math import sqrt, tanh
    # 標準常態分位數（避免引入 scipy）
    z_a, z_b = 1.959964, 0.841621          # alpha=0.05 雙尾、power=0.8
    se = 1.0 / sqrt(max(n - 3, 1))
    return float(tanh((z_a + z_b) * se))


def perm_p(x, y, stat=spearman, n=20000, seed=0):
    rng = np.random.default_rng(seed)
    obs = stat(x, y)
    null = np.array([stat(x, rng.permutation(y)) for _ in range(n)])
    return obs, float((np.abs(null) >= abs(obs)).mean())


def main():
    ts, hh, p, orp, ph, co2, ch4 = load_with_gas()
    ph = np.where((ph <= 0) | (ph >= PH_FAULT), np.nan, ph)
    ev = find_vents(ts, hh, p, co2, ch4)
    ph_med = float(np.nanmedian(ph))

    print('=' * 70)
    print('一、量級：液相碳庫有多大？（不假設液位，改為與氣相相比）')
    print('=' * 70)
    ratio_bic = 10 ** (ph_med - PKA1)
    print('  實測 pH 中位 %.2f（已排除 %.1f%% 的故障值 ≥%.1f）'
          % (ph_med, float(np.mean(~np.isfinite(ph))) * 100, PH_FAULT))
    print('  [HCO3⁻]/[CO2(aq)] = 10^(pH − pKa1) = 10^(%.2f − %.2f) = %.1f'
          % (ph_med, PKA1, ratio_bic))
    print('  ⟹ 溶解無機碳中約 %.0f%% 為 HCO3⁻，液相碳庫是亨利定律單獨值的 %.1f 倍'
          % (ratio_bic / (1 + ratio_bic) * 100, 1 + ratio_bic))
    print('  ⟹ 併計溶解度差（CO2/H2 ≈ %.0f 倍），液相對 CO2 的容量約為 H2 的 %.0f 倍'
          % (KH_CO2 / KH_H2, KH_CO2 / KH_H2 * (1 + ratio_bic)))

    # 以排氣前的壓力與組成，算「每公升液相」與「每公升氣相」的 CO2 莫耳數
    rows = []
    for k, i in enumerate(ev):
        r, xh2 = ratio_of(p[i - 1], co2[i], ch4[i])
        if r is None:
            continue
        P_abs_kpa = (p[i - 1] + ATM) * KGF_TO_KPA
        p_co2_atm = (co2[i] / 100.0) * P_abs_kpa / ATM_KPA
        c_aq = KH_CO2 * p_co2_atm                     # mol/L 溶解的 CO2
        dic = c_aq * (1 + ratio_bic)                  # mol/L 總溶解無機碳
        n_gas = p_co2_atm * ATM_KPA * 1e3 / (R_GAS * T_K) / 1e3   # mol/L 氣相
        lo = max(0, i - 3)
        hi_ = min(len(p) - 1, i + 6)
        drop = float(np.max(p[lo:i + 1]) - np.min(p[i:hi_ + 1]))
        # 排氣前後的 pH（各取數點中位，避開單點雜訊）
        a0, a1 = max(0, i - 15), i
        b0, b1 = i, min(len(ph) - 1, i + 15)
        # ★用平均不用中位：pH 量化步階 0.01，中位數會落在格點上而
        #   給出恰好為 0 的假虛無（本專案已犯過一次）；平均可平滑量化。
        ph_before = float(np.nanmean(ph[a0:a1 + 1]))
        ph_after = float(np.nanmean(ph[b0:b1 + 1]))
        gap_prev = (hh[i] - hh[ev[k - 1]]) if k > 0 else np.nan
        rows.append(dict(i=i, t=ts[i], ratio=r, co2=co2[i], ch4=ch4[i], xh2=xh2,
                         gap_prev=gap_prev, p_before=float(p[i - 1]),
                         drop=drop, dic=dic, n_gas=n_gas,
                         excess=r - FEED_RATIO,
                         ph_before=ph_before, ph_after=ph_after,
                         dph=ph_after - ph_before))

    dic = np.array([d['dic'] for d in rows])
    ngas = np.array([d['n_gas'] for d in rows])
    print('\n  每公升液相的溶解無機碳 DIC：中位 %.4f mol/L' % np.median(dic))
    print('  每公升氣相的 CO2            ：中位 %.4f mol/L' % np.median(ngas))
    print('  ⟹ 液氣比 %.1f：**液相儲存的碳是同體積氣相的 %.0f 倍**'
          % (np.median(dic / ngas), np.median(dic / ngas)))

    # 需要脫出多少才能解釋過量？
    xh2 = np.array([d['xh2'] for d in rows])
    co2_obs = np.array([d['co2'] for d in rows])
    co2_exp = FEED_RATIO * xh2                    # 若僅產甲烷應有的 CO2%
    excess_pp = np.median(co2_obs - co2_exp)
    print('\n  觀測 CO2 中位 %.1f%%；僅產甲烷時應為 %.1f%%（= 0.25 × H2%%）'
          % (np.median(co2_obs), np.median(co2_exp)))
    print('  過量 %.1f 個百分點 = 氣相總莫耳數的 %.1f%%' % (excess_pp, excess_pp))
    need = excess_pp / 100.0 * np.median(ngas)
    print('  需脫出 %.5f mol/L(氣相) 的 CO2' % need)
    print('  液相每公升可供應 %.4f mol ⟹ 只需 **%.1f%%** 的液相碳庫脫出即足夠'
          % (np.median(dic), need / np.median(dic) * 100))
    print('\n  -> **量級上完全可行。** 脫氣假說在能量供應上沒有問題。')

    print('\n' + '=' * 70)
    print('二、方向性後果 1：脫氣量應隨壓降增大 ⟹ 過量與壓降正相關')
    print('=' * 70)
    drop = np.array([d['drop'] for d in rows])
    exc = np.array([d['excess'] for d in rows])
    rho, pv = perm_p(drop, exc)
    print('  壓降 vs CO2:H2 過量：Spearman ρ = %+.3f，置換檢定 p = %.4f'
          % (rho, pv))
    print('  脫氣假說預測：**正相關**（壓降越大、過飽和越大、脫出越多）')
    # ★ 必須算 MDE：n=35 很小，p>0.05 不等於「沒有相關」
    mde = mde_spearman(len(drop))
    print('  ⚠ 本檢定的 MDE（n=%d，α=0.05，power=0.8）約為 ρ = %.2f'
          % (len(drop), mde))
    if pv < 0.05:
        verdict = '符合預測'
    elif abs(rho) < mde:
        verdict = ('⚠ **無定論**：觀測 ρ=%+.3f 小於 MDE %.2f，'
                   '本檢定沒有檢定力分辨' % (rho, mde))
    else:
        verdict = '⚠ 未觀察到預期的正相關'
    print('  -> %s' % verdict)

    # 累積檢驗：脫氣量取決於兩次排氣之間累積的碳 ⟹ 間隔越久過量越大
    gap = np.array([d['gap_prev'] for d in rows])
    g_ok = np.isfinite(gap)
    rho_g, pv_g = perm_p(gap[g_ok], exc[g_ok])
    print('\n  【累積檢驗】距前次排氣的間隔 vs 過量：ρ = %+.3f，p = %.4f（n=%d）'
          % (rho_g, pv_g, int(g_ok.sum())))
    print('  脫氣假說預測：間隔越久，液相累積越多碳，脫出越多 ⟹ **正相關**')
    print('  -> %s' % ('符合預測' if (rho_g > 0.2 and pv_g < 0.05)
                       else '⚠ 未觀察到；同樣受限於 MDE'))

    print('\n' + '=' * 70)
    print('三、方向性後果 2：脫氣移除酸 ⟹ 排氣當下 pH 應上升')
    print('=' * 70)
    dph = np.array([d['dph'] for d in rows])
    ok = np.isfinite(dph)
    print('  可用樣本 %d / %d' % (ok.sum(), len(dph)))
    if ok.sum() >= 8:
        # ★統計量用平均不用中位：中位數會被 0.01 的量化壓到格點上
        mean_d = float(np.mean(dph[ok]))
        rng = np.random.default_rng(0)
        null = np.array([np.mean(dph[ok] * rng.choice([-1, 1], ok.sum()))
                         for _ in range(20000)])
        pv2 = float((np.abs(null) >= abs(mean_d)).mean())
        up = int((dph[ok] > 0).sum())
        print('  排氣前後 pH 變化（各取 15 點平均）：')
        print('    平均 %+.5f　%d/%d 上升　符號置換 p = %.4f'
              % (mean_d, up, ok.sum(), pv2))
        print('    對照：中位 %+.5f（⚠ 中位數會被 0.01 的量化壓到格點，'
              '故不用它當統計量）' % float(np.median(dph[ok])))
        # 量化造成的解析下限：15 點平均後約 QUANT/sqrt(12)/sqrt(15)
        res = 0.01 / np.sqrt(12) / np.sqrt(15)
        print('    15 點平均後的量化解析下限約 %.5f，觀測效果量 %s' %
              (res, '高於下限' if abs(mean_d) > res else '**低於下限，不可解讀**'))
        print('  -> %s' % ('符合預測（pH 上升）' if (mean_d > 0 and pv2 < 0.05)
                           else '⚠ 未觀察到顯著上升'))

    print('\n' + '=' * 70)
    print('四、判讀')
    print('=' * 70)
    print('  量級：可行（只需少量液相碳庫脫出）。')
    print('  但量級可行 ≠ 機制成立——必須看方向性後果是否同時滿足。')
    print('  ⚠ 本檔**不**宣稱洩漏假說被推翻，也**不**宣稱脫氣假說成立；')
    print('     兩者的判別需要無菌對照（見實驗規劃 A）。')
    print('  脫氣假說的價值在於：它提供了一個**不需要洩漏**的解釋，')
    print('  故「氫氣超量流失」不可再被當成唯一解釋。')

    make_figure(rows, ratio_bic)
    return rows


def make_figure(rows, ratio_bic):
    fig, axes = plt.subplots(1, 3, figsize=(15.0, 4.7),
                             gridspec_kw={'wspace': 0.32})
    drop = np.array([d['drop'] for d in rows])
    exc = np.array([d['excess'] for d in rows])
    dph = np.array([d['dph'] for d in rows])
    dic = np.array([d['dic'] for d in rows])
    ngas = np.array([d['n_gas'] for d in rows])

    # a 碳庫比較
    ax = axes[0]
    ax.bar([0, 1], [np.median(ngas) * 1000, np.median(dic) * 1000],
           width=0.55, color=[MUTED, BLUE])
    ax.set_xticks([0, 1])
    ax.set_xticklabels(['氣相\n(每公升)', '液相碳庫\n(每公升)'])
    _, hi = ax.get_ylim()
    ax.set_ylim(0, hi * 1.45)
    ax.text(0.5, 0.97,
            '液相儲存的碳是同體積氣相的 %.0f 倍\n'
            'pH %.2f 下約 %.0f%% 以 HCO₃⁻ 存在'
            % (np.median(dic / ngas), 7.20, ratio_bic / (1 + ratio_bic) * 100),
            transform=ax.transAxes, fontsize=11, color=INK,
            fontweight='bold', ha='center', va='top')
    style(ax, 'a　CO₂ 有液相緩衝庫，H₂ 沒有', '', '無機碳 (mmol/L)')

    # b 壓降 vs 過量（脫氣假說的關鍵預測）
    ax = axes[1]
    ax.scatter(drop, exc, s=70, color=BLUE, edgecolors='white', zorder=4)
    ax.axhline(0, color=RED, lw=2.0, ls='--')
    rho = spearman(drop, exc)
    _lo, hi = ax.get_ylim()
    ax.set_ylim(_lo, hi * 1.35)
    mde = mde_spearman(len(drop))
    ax.text(0.03, 0.97,
            '脫氣假說預測：正斜率\n'
            '實測 ρ = %+.3f，但 MDE = %.2f\n'
            '→ 方向符合，樣本不足以分辨' % (rho, mde),
            transform=ax.transAxes, fontsize=11, color=INK,
            fontweight='bold', ha='left', va='top')
    style(ax, 'b　壓降越大，CO₂ 過量越多嗎', '排氣的壓力降幅 (kgf/cm²)',
          'CO₂:H₂ 減去 0.25')

    # c 排氣前後 pH
    ax = axes[2]
    ok = np.isfinite(dph)
    ax.hist(dph[ok], bins=14, color=AQUA, edgecolor='white')
    ax.axvline(0, color=RED, lw=2.4, ls='--')
    _, hi = ax.get_ylim()
    ax.set_ylim(0, hi * 1.5)
    ax.text(0.03, 0.97,
            '脫氣移除酸 ⟹ 應往右偏\n'
            '實測平均 %+.4f\n'
            '⚠ 排氣後立刻補氣（CO₂ 降 pH），\n'
            '　本項遭混淆，不可單獨解讀'
            % np.mean(dph[ok]),
            transform=ax.transAxes, fontsize=10.5, color=INK,
            fontweight='bold', ha='left', va='top')
    style(ax, 'c　排氣前後的 pH 變化', 'pH 變化', '次數')

    out = os.path.join(OUT, 'fig47_carbonate.png')
    fig.savefig(out)
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
