# -*- coding: utf-8 -*-
"""把 P(t) 做傅立葉轉換，能不能分開生物與物理？

2026-09-23。使用者提問：

    「若將 P(t) 的式子經過 Fourier Transform 把 e^{-kt} 轉成常數項，
      再和原式比對之殘差，用於計算的可能性？」

════════════════════════════════════════════════════════════════════════
先講結論：一半不行，一半非常有用

【不行的那一半】可逆線性變換不會創造資訊

  傅立葉轉換是**可逆的線性變換**。若兩組參數在時域給出「逐點相同」的 P(t)，
  則它們的頻譜也必然逐點相同，殘差恆為零——與在哪個空間比對無關。

  ⚠ 本專案已踩過同型的坑：改到「速率空間」雖成功消掉 P_eq，
    但簡併原封不動地重現（資料處理不等式）。

【非常有用的那一半】頻域正好把兩種成分分開

  把生物速率拆成常數與變動：r_b(t) = r̄_b + δ(t)，並令 P(t) = A + p(t)，
  其中 A = P_eq − r̄_b/k。代入 dP/dt = −k(P − P_eq) − r_b(t) 得

      dp/dt = −k·p(t) − δ(t)

  兩邊取傅立葉：

      (iω + k)·p̃(ω) = −δ̃(ω)
      ⟹ **p̃(ω) = −δ̃(ω) / (iω + k)**

  這個式子把整件事講得非常清楚：

    ω = 0（常數部分）：k·P_eq 與 r̄_b 只以「A」這一個組合出現
                       ⟹ **結構性簡併，頻域也救不了**
    ω ≠ 0（變動部分）：p̃(ω) 與 δ̃(ω) 一一對應
                       ⟹ **原則上可辨識，只受雜訊限制**

  且 |p̃(ω)| = |δ̃(ω)| / √(ω² + k²)：**高頻被質傳低通濾掉**。
  這就是「生物訊號被質傳遮蔽」的頻域形式。

本檔做三件事

  一、數值驗證「可逆變換不創造資訊」——把簡併的兩組參數各做 FFT 比對
  二、算出**可辨識的頻帶**：δ 的頻譜在哪些頻率仍高於雜訊
  三、由該頻帶反推**實務建議**：觀測窗要多長、取樣要多快

輸出 -> 純文字 + docs/analysis_charts_3batch/fig52_fourier.png
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
from pinn_rb_recovery import QUANT, NOISE                # noqa: E402

T, NP = 6.0, 360                      # 6 小時、每分鐘一筆
K_TRUE, PEQ, P0 = 1.4, 0.75, 1.17
RB = lambda tt: 0.012 * np.exp(-0.7 * tt / T * 3)
SIGMA = float(np.sqrt(NOISE ** 2 + QUANT ** 2 / 12))


def integrate(t, rb_fun, k, peq, p0):
    """RK4 積分 dP/dt = −k(P−peq) − r_b(t)。"""
    f = lambda tt, P: -k * (P - peq) - rb_fun(tt)
    dt = t[1] - t[0]
    P = np.empty(len(t))
    P[0] = p0
    for i in range(1, len(t)):
        s, y = t[i - 1], P[i - 1]
        k1 = f(s, y); k2 = f(s + dt / 2, y + dt / 2 * k1)
        k3 = f(s + dt / 2, y + dt / 2 * k2); k4 = f(s + dt, y + dt * k3)
        P[i] = y + dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
    return P


def main():
    t = np.linspace(0, T, NP)
    dt = t[1] - t[0]
    rb_mean = float(RB(t).mean())
    A = PEQ - rb_mean / K_TRUE

    print('=' * 76)
    print('一、可逆變換不創造資訊（數值驗證）')
    print('=' * 76)
    print('  取兩組完全不同、但 A = P_eq − r̄_b/k 相同的參數：\n')
    P1 = integrate(t, lambda tt: rb_mean, K_TRUE, PEQ, P0)          # 有生物
    P2 = integrate(t, lambda tt: 0.0, K_TRUE, A, P0)                # 無生物
    F1, F2 = np.fft.rfft(P1), np.fft.rfft(P2)
    print('    (a) r̄_b = %.5f, P_eq = %.4f' % (rb_mean, PEQ))
    print('    (b) r̄_b = 0,       P_eq = %.6f' % A)
    print('  時域逐點最大差　%.3e' % np.abs(P1 - P2).max())
    print('  **頻域**逐點最大差 %.3e' % np.abs(F1 - F2).max())
    print('  -> 兩者皆為機器精度。**換到頻域，殘差一樣是零。**')
    print('     傅立葉是可逆線性變換，不會生出時域沒有的資訊。')

    print('\n' + '=' * 76)
    print('二、但頻域把「可辨識」與「不可辨識」切得很乾淨')
    print('=' * 76)
    print('  由 dp/dt = −k·p − δ(t) 取傅立葉：')
    print('      p̃(ω) = −δ̃(ω) / (iω + k)')
    print('')
    print('  ω = 0：k·P_eq 與 r̄_b 只以組合 A 出現 ⟹ 結構性簡併')
    print('  ω ≠ 0：p̃ 與 δ̃ 一一對應   ⟹ 原則上可辨識')
    print('')
    print('  |p̃(ω)| = |δ̃(ω)| / √(ω² + k²)　⟹ **高頻被質傳低通濾掉**')
    print('  這正是「生物訊號被質傳遮蔽」的頻域寫法。')

    print('\n' + '=' * 76)
    print('三、可辨識的頻帶：δ 的頻譜在哪裡還高於雜訊')
    print('=' * 76)
    delta = RB(t) - rb_mean
    # δ 經低通後在壓力上的足跡（頻域直接算）
    freq = np.fft.rfftfreq(NP, d=dt)          # 1/hr
    w = 2 * np.pi * freq
    Dd = np.fft.rfft(delta)
    Pd = np.abs(Dd) / np.sqrt(w ** 2 + K_TRUE ** 2)
    # 白雜訊在每個頻率 bin 的期望振幅
    noise_bin = SIGMA * np.sqrt(NP / 2.0)
    snr = Pd / noise_bin
    print('  取樣 %d 點、間隔 %.3f hr ⟹ 頻率上限（Nyquist）%.1f /hr'
          % (NP, dt, freq[-1]))
    print('  單頻 bin 的雜訊振幅 %.4f（σ=%.5f）' % (noise_bin, SIGMA))
    print('')
    print('  %-14s %-14s %-12s %s' % ('頻率 (1/hr)', '對應週期 (hr)', 'SNR', '判讀'))
    for idx in (1, 2, 3, 5, 8, 12, 20, 40):
        if idx >= len(freq):
            continue
        per = 1.0 / freq[idx] if freq[idx] > 0 else np.inf
        tag = '可辨識' if snr[idx] > 1 else ('邊緣' if snr[idx] > 0.5 else '埋在雜訊裡')
        print('  %-14.3f %-14.2f %-12.2f %s' % (freq[idx], per, snr[idx], tag))
    ok = np.flatnonzero(snr[1:] > 1.0) + 1
    if len(ok):
        print('\n  -> SNR > 1 的頻帶：%.3f ~ %.3f /hr'
              % (freq[ok].min(), freq[ok].max()))
        print('     對應週期 %.1f ~ %.1f 小時'
              % (1 / freq[ok].max(), 1 / freq[ok].min()))
    else:
        print('\n  -> 沒有任何單一頻率的 SNR 超過 1')
    print('  總 SNR（各頻帶平方和開根）%.2f'
          % float(np.sqrt((snr[1:] ** 2).sum())))

    print('\n' + '=' * 76)
    print('四、實務結論')
    print('=' * 76)
    print('  1. **不要期待換個變換就能解開簡併**——常數部分在任何空間都簡併。')
    print('  2. 頻域的價值在於**指出該往哪裡找訊號**：')
    print('     δ 的可辨識成分集中在低頻（週期數小時的尺度），')
    print('     高頻被 1/√(ω²+k²) 壓掉。')
    print('  3. ⟹ **提高取樣率沒有用**（高頻本來就沒有訊號），')
    print('     **拉長觀測窗才有用**（把低頻解析出來）。')
    print('     這與「加密排氣取樣」的建議不衝突：那是為了甲烷，不是為了壓力。')
    print('  4. ⚠ 生物速率的**絕對大小**仍然要靠獨立通道（甲烷或無菌對照）；')
    print('     頻域最多只能給出它的**變化形狀**。')

    make_figure(freq, Pd, noise_bin, snr)


def make_figure(freq, Pd, noise_bin, snr):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.6, 4.8),
                                 gridspec_kw={'wspace': 0.30})
    m = freq > 0
    a1.loglog(freq[m], Pd[m], color=BLUE, lw=2.6, label='生物變動的足跡')
    a1.axhline(noise_bin, color=RED, lw=2.4, ls='--', label='雜訊底')
    a1.legend(loc='lower left', frameon=False, fontsize=12)
    a1.text(0.97, 0.95,
            '訊號只在低頻露出雜訊\n高頻被質傳以 1/√(ω²+k²) 壓掉',
            transform=a1.transAxes, fontsize=12, color=INK,
            fontweight='bold', ha='right', va='top')
    # ⚠ log 軸刻度走 mathtext，不受 axes.unicode_minus 管，
    #   中文字型下負號會缺字顯示成方框；手動指定刻度避開。
    a1.set_yticks([1e-4, 1e-3, 1e-2, 1e-1])
    a1.set_yticklabels(['0.0001', '0.001', '0.01', '0.1'])
    a1.minorticks_off()
    style(a1, 'a　頻譜：訊號 vs 雜訊', '頻率 (1/hr)', '振幅')

    a2.semilogx(freq[m], snr[m], color=BLUE, lw=2.8)
    a2.axhline(1.0, color=RED, lw=2.4, ls='--')
    a2.set_ylim(0, max(2.0, float(snr[m].max()) * 1.35))
    a2.text(freq[m][-1], 1.0, 'SNR = 1 ', color=RED, fontsize=12,
            fontweight='bold', ha='right', va='bottom')
    ok = np.flatnonzero(snr[1:] > 1.0) + 1
    if len(ok):
        a2.axvspan(freq[ok].min(), freq[ok].max(), color=AQUA, alpha=0.20)
        a2.text(0.03, 0.95,
                '可辨識頻帶\n%.2f ~ %.2f /hr\n(週期 %.1f ~ %.1f 小時)'
                % (freq[ok].min(), freq[ok].max(),
                   1 / freq[ok].max(), 1 / freq[ok].min()),
                transform=a2.transAxes, fontsize=12, color=INK,
                fontweight='bold', ha='left', va='top')
    style(a2, 'b　哪些頻率還看得見', '頻率 (1/hr)', '訊噪比')

    out = os.path.join(OUT, 'fig52_fourier.png')
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
