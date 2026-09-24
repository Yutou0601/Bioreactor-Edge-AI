# -*- coding: utf-8 -*-
"""下一階段實驗的檢定力與時程規劃 —— 先算清楚再排。

2026-09-23。回答三個排程問題：

  A. 無菌保壓要測幾天？前幾小時能不能用？要多久才分得出「洩漏」與「穿透」？
  B. τ 交叉設計要跑幾天？（已於 tau_crossover_design.py 算過，此處併列）
  C. 排氣加密到什麼頻率，甲烷才足以直接給出生物速率？

════════════════════════════════════════════════════════════════════════
A 的關鍵陷阱：前期壓降不是洩漏

  無菌系統充壓後，壓力會下降的原因有兩個：
    (1) 氣體溶進水裡，直到液相飽和 —— 這是**暫態**，以時間常數 1/k 衰減
    (2) 洩漏／穿透 —— 這是**定速**，永遠持續

  若一充壓就開始擬合斜率，量到的是 (1)+(2)，會把洩漏**嚴重高估**。
  正確作法：**捨棄前面數個時間常數**，待 (1) 衰減殆盡後才開始擬合。

  以現場實測 k ≈ 0.15 /hr（τ 小）計，時間常數 1/k ≈ 6.7 hr：
    3 個時間常數後殘餘 5%，5 個之後 0.7%。

判別「機械洩漏」與「材料穿透」

  機械洩漏（孔隙流）依 Graham 定律，速率 ∝ 1/√M
      r(N2) : r(H2) = √(2/28) = 0.267，即 H2 比 N2 快 3.74 倍
  材料穿透（溶解–擴散）依 溶解度×擴散係數，比值由材質決定，一般不等於 3.74

  故 N2 與 H2 的衰減率比值本身就是判別量。本檔算出「要多準才分得出來」。

輸出 -> 純文字
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from pinn_rb_recovery import QUANT, NOISE            # noqa: E402

SIGMA = float(np.sqrt(NOISE ** 2 + QUANT ** 2 / 12))   # 單點量測誤差
K_SITE = 0.15                                          # 現場 k（τ 小）1/hr
SAMPLE_PER_HR = 60                                     # 每分鐘一筆
GRAHAM = float(np.sqrt(28.0 / 2.0))                    # H2 比 N2 快幾倍


def slope_se(t_hours, per_hr=SAMPLE_PER_HR, sigma=SIGMA):
    """以最小平方擬合直線時，斜率的標準誤。

    SE(slope) = sigma / (sd(t) * sqrt(N))，均勻取樣下 sd(t) = T/sqrt(12)。
    """
    n = max(2, int(t_hours * per_hr))
    sd_t = t_hours / np.sqrt(12.0)
    return sigma / (sd_t * np.sqrt(n))


def main():
    print('單點量測誤差 sigma = %.5f kgf/cm²（雜訊 %.3f ＋ 量化 %.2f）'
          % (SIGMA, NOISE, QUANT))
    print('現場 k ≈ %.2f /hr ⟹ 溶解暫態的時間常數 1/k = %.1f hr\n'
          % (K_SITE, 1 / K_SITE))

    print('=' * 70)
    print('A-1　前期必須捨棄多久？（溶解暫態衰減到可忽略）')
    print('=' * 70)
    print('  %-14s %-12s %s' % ('捨棄時間', '殘餘暫態', '判讀'))
    for n_tau in (1, 2, 3, 5, 7):
        t = n_tau / K_SITE
        resid = np.exp(-n_tau)
        ok = '可忽略' if resid < 0.01 else ('偏大' if resid < 0.10 else '不可用')
        print('  %-14s %-12s %s'
              % ('%.0f hr (%d/k)' % (t, n_tau), '%.1f%%' % (resid * 100), ok))
    print('\n  -> 建議捨棄前 %.0f 小時（5 個時間常數，殘餘 0.7%%）。'
          % (5 / K_SITE))

    print('\n' + '=' * 70)
    print('A-2　擬合窗長 vs 洩漏率的量測精度')
    print('=' * 70)
    print('  待解析的量級：舊估計洩漏率 ≤0.001；若洩漏要能解釋壓降，')
    print('  需達 0.01 量級（與 r_b = 0.0125 同量級）。\n')
    print('  %-12s %-16s %-16s %s'
          % ('擬合窗長', '斜率標準誤', '對 0.001 的相對', '對 0.010 的相對'))
    for T in (6, 12, 24, 48, 72):
        se = slope_se(T)
        print('  %-12s %-16.2e %-16s %s'
              % ('%d hr' % T, se, '±%.0f%%' % (se / 0.001 * 100),
                 '±%.1f%%' % (se / 0.010 * 100)))
    print('\n  -> 即使只擬合 24 小時，對 0.001 量級的洩漏率也有 ±%.0f%% 的精度。'
          % (slope_se(24) / 0.001 * 100))

    print('\n' + '=' * 70)
    print('A-3　總時程與「洩漏 vs 穿透」的判別力')
    print('=' * 70)
    t_drop = 5 / K_SITE
    for T_fit in (24, 48):
        total = t_drop + T_fit
        se = slope_se(T_fit)
        # 比值 r_H2/r_N2 的標準誤（兩次獨立量測，誤差傳遞）
        for r_n2 in (0.001, 0.005):
            r_h2 = r_n2 * GRAHAM
            se_ratio = (r_h2 / r_n2) * np.sqrt((se / r_h2) ** 2 + (se / r_n2) ** 2)
            # 要能區分 3.74（洩漏）與 1.0（無差異）需幾個標準差
            z = abs(GRAHAM - 1.0) / se_ratio
            print('  總時程 %.0f hr（捨棄 %.0f + 擬合 %d）　'
                  'r(N2)=%.3f ⟹ 比值 %.2f ± %.2f　與「無差異」相距 %.1f σ'
                  % (total, t_drop, T_fit, r_n2, GRAHAM, se_ratio, z))
    print('\n  -> 只要洩漏率達 0.001 以上，%.0f 小時（約 %.1f 天）即可明確判別。'
          % (t_drop + 48, (t_drop + 48) / 24))
    print('     若實測衰減遠低於 0.001，結論是「洩漏很小」——')
    print('     那會**否定**氫氣流失假說，必須另尋解釋（見判讀準則）。')

    print('\n' + '=' * 70)
    print('C　排氣加密：甲烷要多久一筆才能直接給出生物速率')
    print('=' * 70)
    print('  甲烷是**唯一**只能來自生物的量（溶解與洩漏都不產生甲烷）。')
    print('  故 CH4 的累積速率直接就是產甲烷速率，不需要解任何簡併。\n')
    print('  現況：全資料庫 35 筆可用，平均每 %.0f 天一筆。' % (365 / 35))
    print('  %-16s %-14s %s' % ('排氣間隔', '一週可得', '一年可得'))
    for gap_hr in (264, 24, 12, 3.5):
        per_week = 7 * 24 / gap_hr
        per_year = 365 * 24 / gap_hr
        print('  %-16s %-14.0f %.0f'
              % ('每 %.1f hr' % gap_hr if gap_hr < 24 else '每 %.0f hr' % gap_hr,
                 per_week, per_year))
    print('\n  -> 改為每 3.5 hr 一次，**一週 48 筆即超過過去一整年的 35 筆**。')

    print('\n' + '=' * 70)
    print('三個實驗的閉合檢驗（最重要的一點）')
    print('=' * 70)
    print('  A 給洩漏率           r_leak')
    print('  B 給「不隨 k 變的」  r̄_b = r_bio + r_leak')
    print('  C 給生物速率         r_bio（由甲烷直接算）')
    print('')
    print('  ⟹ **三者必須滿足 B = A + C**。')
    print('     這是一個事前就能寫定的閉合檢驗，三個實驗互為對照；')
    print('     任何一項若對不上，即表示模型仍缺了一條途徑。')
    print('')
    print('  這比任何單一實驗都強：目前全案所有數字都只有單一來源。')


if __name__ == '__main__':
    main()
