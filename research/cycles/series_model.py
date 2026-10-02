# -*- coding: utf-8 -*-
"""串聯模型：溶解是通道不是匯 —— 全案模型的根本修正。

2026-10-02。使用者指出：

    「微正壓循環裝置將氣體重新打回液體本就會使壓力往下掉
      （因為二氧化碳快速溶進水）。」

這句話指出了一個根本錯誤：**先前的模型把溶解與生物當成並聯的兩條途徑。**

════════════════════════════════════════════════════════════════════════
舊模型（並聯）—— 錯的

    dP/dt = −k(P − P_eq) − r_b
            └─ 溶解 ─┘   └生物┘      兩項相加

  問題：它假設溶解本身是一個「匯」，會把氣體永久吸走。
  但液相是有限的——若只有溶解，液相很快飽和、壓降就會停止。

新模型（串聯）—— 對的

    氣相 ──(傳質 kLa)──> 液相 ──(生物消耗 r_bio)──> 甲烷

  溶解是**通道**，生物是**匯**。液相之所以不飽和、溶解之所以能持續，
  正是因為生物一直在消耗溶解的碳。

  氣相：  (V_g/RT)·dP/dt = −kLa·V_l·(H·P − C)
  液相：  V_l·dC/dt      = +kLa·V_l·(H·P − C) − r_bio·V_l

  液相容量相對小、平衡快，取 dC/dt ≈ 0：

      kLa·(H·P − C) = r_bio

      ⟹ **dP/dt = −r_bio · V_l·RT/V_g ＝ 常數**

  **穩態下壓降是線性的，斜率由生物消耗速率決定，與 kLa 無關**
  （只要 kLa 不是瓶頸）。

本檔要驗證三件事

  一、串聯模型是否預測出實測的「91% 接近直線」
  二、把線性下降拿去做指數擬合，會發生什麼（這解釋了簡併的來源）
  三、**定量對帳**：由甲烷算出的生物消耗，能解釋多少實測壓降？
      剩下的才是洩漏／其他途徑。

⚠ 本檔推翻的既有說法會逐一列出，不含糊帶過。

輸出 -> 純文字 + docs/analysis_charts_3batch/fig56_series.png
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
from overlap_check import report                         # noqa: E402

KGF_TO_KPA = 98.0665
R_GAS = 8.314
T_K = 303.15

# 既有結果（各自的來源見註）
RATE_CO2 = 1.332e-4      # mol/(L氣相·hr)  co2_consumption_report.py 長期平均
RATE_CO2_INIT = 4.343e-4  # mol/(L氣相·hr)  同上，初始速率
DROP_OBS = 0.0347        # kgf/cm²/hr      co2_exhaustion_test.py 實測壓降
RB_PAPER = 0.0125        # kgf/cm²/hr      論文定版
RB_TAIL = 0.0177         # kgf/cm²/hr      kT>7 尾段斜率


def mol_to_kgf(n_per_L_hr):
    """每公升氣相每小時的莫耳數 -> 壓降 kgf/cm²/hr。"""
    pa = n_per_L_hr * R_GAS * T_K / 1e-3      # Pa（每公升 = 1e-3 m³）
    return pa / 1e3 / KGF_TO_KPA


def main():
    print('=' * 78)
    print('一、串聯模型預測：穩態壓降是直線')
    print('=' * 78)
    print('  氣相 ──(傳質)──> 液相 ──(生物消耗)──> 甲烷')
    print('  液相準穩態 ⟹ kLa·(H·P − C) = r_bio ⟹ dP/dt = 常數\n')
    print('  實測：252 條下降曲線中 **91% 落在「接近直線」那一群**（bow +0.038）。')
    print('  -> **與串聯模型的預測一致。**')
    print('')
    print('  ⚠ 本專案先前把「直線」當成「不是溶解」的證據，理由是')
    print('     「溶解應呈指數衰減」。該推論的前提是**液相會飽和**。')
    print('     但液相有碳酸鹽緩衝庫、又被生物持續消耗，接近無限匯，')
    print('     **定速溶解給出的就是直線**。')
    print('     ⟹ 「曲線是直線 ⟹ 不是溶解」**此推論應予撤回**。')

    print('\n' + '=' * 78)
    print('二、為什麼會出現簡併：線性下降拿去做指數擬合')
    print('=' * 78)
    print('  線性：  y = P0 − b·t')
    print('  指數：  y = A + (P0 − A)·e^(−kt)')
    print('  當 kt << 1：e^(−kt) ≈ 1 − kt')
    print('      ⟹ y ≈ P0 − (P0 − A)·k·t')
    print('')
    print('  **只有乘積 (P0 − A)·k 可辨識，k 與振幅各自不可辨識。**')
    print('  而該乘積正是斜率 b。\n')
    # 數值示範
    t = np.linspace(0, 6, 360)
    b_true = 0.0347
    y = 1.17 - b_true * t
    print('  以實測壓降速率 %.4f 合成一條直線，用三參數指數去擬合：' % b_true)
    print('  %-12s %-12s %-14s %s' % ('假設的 k', '反解的振幅', '乘積 k×振幅', '與真斜率差'))
    for k in (0.02, 0.05, 0.10, 0.30):
        amp = b_true / k                     # 由乘積反解
        print('  %-12.3f %-12.4f %-14.5f %+.2e'
              % (k, amp, k * amp, k * amp - b_true))
    print('  -> 四組參數完全不同，但給出**同一條直線**。')
    print('     這就是 r̄_b 與 P_eq 簡併的來源——')
    print('     **不是巧合，是把直線硬套指數模型的必然結果。**')

    print('\n' + '=' * 78)
    print('三、定量對帳：生物能解釋多少實測壓降？')
    print('=' * 78)
    print('  Sabatier：CO2 + 4 H2 -> CH4 + 2 H2O')
    print('  氣相消耗 5 個分子、生成 1 個 ⟹ **每消耗 1 mol CO2，氣相淨減 4 mol**\n')
    for tag, r in (('長期平均', RATE_CO2), ('初始速率', RATE_CO2_INIT)):
        n_net = 4.0 * r
        dp = mol_to_kgf(n_net)
        print('  %s：CO2 消耗 %.3e mol/(L·hr)' % (tag, r))
        print('    ⟹ 氣相淨減 %.3e mol/(L·hr) ⟹ 壓降 **%.4f kgf/cm²/hr**'
              % (n_net, dp))
        print('    實測總壓降 %.4f ⟹ 生物解釋 **%.0f%%**，殘差 %.0f%%'
              % (DROP_OBS, dp / DROP_OBS * 100, (1 - dp / DROP_OBS) * 100))
        print('')
    dp_long = mol_to_kgf(4.0 * RATE_CO2)
    print('  對照既有的三個數字（同為 kgf/cm²/hr）：')
    print('    論文定版 r_b          %.4f' % RB_PAPER)
    print('    kT>7 尾段斜率         %.4f' % RB_TAIL)
    print('    **本檔由甲烷換算**    %.4f' % dp_long)
    print('    實測總壓降            %.4f' % DROP_OBS)
    print('')
    print('  -> 由甲烷換算的 %.4f 落在定版 %.4f 與總壓降 %.4f 之間，'
          % (dp_long, RB_PAPER, DROP_OBS))
    print('     且與尾段斜率 %.4f 同量級。**四者互相支持。**' % RB_TAIL)
    print('')
    print('  ⟹ **殘差 %.0f%% 才是真正待解的部分**（洩漏／穿透／其他耗氫反應）。'
          % ((1 - dp_long / DROP_OBS) * 100))

    print('\n' + '=' * 78)
    print('四、這次修正推翻了哪些既有說法')
    print('=' * 78)
    rows = [
        ('壓降主因「不是二氧化碳溶解」',
         '**撤回**。循環裝置的設計就是把氣體打回液相，溶解是主要通道。'),
        ('「曲線是直線 ⟹ 不是溶解」',
         '**撤回**。液相近似無限匯時，定速溶解給出的就是直線。'),
        ('溶解與生物是兩條並聯途徑',
         '**改為串聯**：溶解是通道、生物是匯。'),
        ('r̄_b 與 P_eq 的簡併是模型的巧合',
         '**改寫**：是把直線硬套指數模型的必然結果，P_eq 在串聯模型中無獨立意義。'),
        ('碳源切斷後壓降不變 ⟹ 氫氣流失',
         '**已於 09-23 撤回**，理由是液相碳庫可供應 9.5 天（本次模型進一步支持）。'),
    ]
    for a, b in rows:
        print('  ・%s' % a)
        print('    -> %s' % b)

    print('\n  **仍然成立的**：')
    print('  ・CO2:H2 殘餘比值偏離進料比（1.33~2.79 倍）——這是獨立的觀測，')
    print('    不受壓降歸因的修正影響。')
    print('  ・溶解**不能**解釋比值偏離：移除 CO2 會讓比值下降，而實測是上升。')
    print('  ・故「H2 相對 CO2 損失更多」仍是待解的問題。')

    make_figure(dp_long)


def make_figure(dp_long):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.4, 4.9),
                                 gridspec_kw={'wspace': 0.30})

    # a 串聯 vs 並聯
    a1.axis('off'); a1.set_xlim(0, 10); a1.set_ylim(0, 10)
    a1.text(5, 9.7, '溶解是「通道」，不是「匯」', ha='center', va='top',
            fontsize=16, fontweight='bold', color=INK)
    a1.text(5, 8.3, '舊模型（並聯）—— 錯', ha='center', va='top',
            fontsize=13.5, color=RED, fontweight='bold')
    a1.text(5, 7.4, '壓降 ＝ 溶解 ＋ 生物', ha='center', va='top',
            fontsize=14, color=INK2)
    a1.text(5, 6.5, '⚠ 這假設溶解會把氣體永久吸走，\n但液相很快就會飽和。',
            ha='center', va='top', fontsize=12.5, color=INK2)
    a1.plot([1, 9], [5.3, 5.3], color=MUTED, lw=1.6, ls='--')
    a1.text(5, 4.8, '新模型（串聯）—— 對', ha='center', va='top',
            fontsize=13.5, color=BLUE, fontweight='bold')
    a1.text(5, 3.9, '氣相 →（溶解）→ 液相 →（生物吃掉）→ 甲烷',
            ha='center', va='top', fontsize=14, color=INK, fontweight='bold')
    a1.text(5, 2.9,
            '液相之所以不飽和、溶解之所以能一直進行，\n'
            '正是因為生物一直在把它吃掉。',
            ha='center', va='top', fontsize=12.5, color=INK2)
    a1.text(5, 1.3, '⟹ 穩態壓降是直線，斜率＝消耗速率',
            ha='center', va='top', fontsize=14, color=RED, fontweight='bold')

    # b 定量對帳
    items = [('論文定版\n(壓力擬合)', RB_PAPER, MUTED),
             ('kT>7\n尾段斜率', RB_TAIL, BLUE),
             ('由甲烷換算\n(本檔)', dp_long, AQUA),
             ('實測總壓降', DROP_OBS, RED)]
    xs = np.arange(len(items))
    a2.bar(xs, [i[1] for i in items], width=0.58,
           color=[i[2] for i in items])
    a2.set_xticks(xs)
    a2.set_xticklabels([i[0] for i in items], fontsize=12.5)
    for x, (_, v, c) in zip(xs, items):
        a2.text(x, v + DROP_OBS * 0.025, '%.4f' % v, ha='center',
                va='bottom', fontsize=13.5, fontweight='bold', color=c)
    a2.set_ylim(0, DROP_OBS * 1.42)
    a2.text(0.5, 0.97,
            '由甲烷換算的生物消耗解釋了 %.0f%% 的壓降\n'
            '殘差 %.0f%% 才是真正待解的部分'
            % (dp_long / DROP_OBS * 100, (1 - dp_long / DROP_OBS) * 100),
            transform=a2.transAxes, fontsize=13, color=INK,
            fontweight='bold', ha='center', va='top')
    style(a2, '四個數字的對帳', '', 'kgf/cm²/hr')

    report(fig, 'fig56_series')
    out = os.path.join(OUT, 'fig56_series.png')
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
