# -*- coding: utf-8 -*-
"""體積敏感度：所有依賴「氣相／液相各佔多少」的結果，一次列清楚。

2026-09-23。現場提供反應槽總量 **1.8 L**。

════════════════════════════════════════════════════════════════════════
⚠ 先釐清一個矛盾

  先前的會議需求與本專案記憶寫的是 **1.99 L**
  （「P_total,abs = 1.2 + 1.033 … 容器 1.99 L」）。
  現場現在說 **1.8 L**。兩者差 10%，而所有體積換算都會跟著動。

  可能是「總容積（含配件、管路）」與「反應槽有效容量」的差別。
  **本檔以 1.8 L 為主、1.99 L 併列，待設備方確認後擇一。**

為什麼總容積還不夠

  真正決定換算的是**氣相體積 V_gas**：

    CO2 消耗速率（整機）  = 每公升氣相的速率 × V_gas
    液相碳庫總量          = 每公升液相的 DIC × V_liq
    碳庫可供應的天數      = 碳庫總量 ÷ 消耗速率

  而 V_gas = V_total − V_liq。**只要給出液位（或液體體積），全部定案。**
  本檔把液相體積當自變數，列出整張對照表。

本檔不重新分析，只做換算。原始數據來自：
  co2_consumption_report.py  每公升氣相的 CO2 消耗速率
  carbonate_degassing_test.py  每公升液相的溶解無機碳

輸出 -> 純文字 + docs/analysis_charts_3batch/fig54_volume.png
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

V_FIELD = 1.8             # 現場回報的反應槽總量 (L)
V_MEMO = 1.99             # 先前會議需求／專案記憶所載 (L)
RATE_LONG = 9.153e-5      # mol/(L氣相·hr)  長期平均（含基質耗盡期）
RATE_INIT = 4.343e-4      # mol/(L氣相·hr)  初始速率（2026-09-14 短實驗）
DIC = 0.0990              # mol/L液相       pH 7.2 下的溶解無機碳
M_CO2 = 44.01
VM_STP = 22.414


def table(v_total, rate, tag):
    print('\n  【總容積 %.2f L，%s %.3e mol/(L氣相·hr)】' % (v_total, tag, rate))
    print('  %-10s %-10s %-14s %-14s %-12s %s'
          % ('液相(L)', '氣相(L)', 'CO2 mmol/hr', 'mL(STP)/hr',
             '碳庫(mmol)', '碳庫續航(天)'))
    out = []
    for f in (0.3, 0.4, 0.5, 0.6, 0.7):
        v_liq = v_total * f
        v_gas = v_total - v_liq
        mmol_hr = rate * v_gas * 1e3
        ml_hr = rate * v_gas * VM_STP * 1e3
        bank = DIC * v_liq * 1e3
        days = (bank / mmol_hr / 24) if mmol_hr > 0 else np.inf
        print('  %-10.2f %-10.2f %-14.4f %-14.3f %-12.1f %.1f'
              % (v_liq, v_gas, mmol_hr, ml_hr, bank, days))
        out.append((v_liq, v_gas, mmol_hr, ml_hr, bank, days))
    return out


def main():
    print('=' * 84)
    print('一、⚠ 總容積有兩個版本，須確認')
    print('=' * 84)
    print('  現場回報（2026-09-23）　%.2f L' % V_FIELD)
    print('  會議需求／專案記憶　　　%.2f L' % V_MEMO)
    print('  差 %.0f%%。所有體積換算都會跟著動 —— **請設備方擇一確認**。'
          % ((V_MEMO / V_FIELD - 1) * 100))
    print('  （可能一個是含配件管路的總容積，一個是反應槽有效容量。）')

    print('\n' + '=' * 84)
    print('二、為什麼「總容積」還不夠：真正要的是氣相體積')
    print('=' * 84)
    print('  CO2 消耗速率（整機）= 每公升氣相的速率 × V_gas')
    print('  液相碳庫總量        = 每公升液相的 DIC × V_liq')
    print('  V_gas = V_total − V_liq ⟹ **只要給液位，全部定案**')

    print('\n' + '=' * 84)
    print('三、對照表：填入液位即可讀出答案（以現場 %.2f L 為準）' % V_FIELD)
    print('=' * 84)
    a = table(V_FIELD, RATE_LONG, '長期平均')
    b = table(V_FIELD, RATE_INIT, '初始速率')

    print('\n' + '=' * 84)
    print('四、若總容積是 %.2f L（記憶版本）' % V_MEMO)
    print('=' * 84)
    table(V_MEMO, RATE_LONG, '長期平均')

    print('\n' + '=' * 84)
    print('五、這張表回答了什麼')
    print('=' * 84)
    mid = a[2]        # 液相佔 50%
    mid_i = b[2]
    print('  以液相佔一半（各 %.2f L）為例：' % (V_FIELD / 2))
    print('    CO2 消耗速率　長期 %.4f mmol/hr（%.2f mL(STP)/hr）'
          % (mid[2], mid[3]))
    print('    　　　　　　　初始 %.4f mmol/hr（%.2f mL(STP)/hr）'
          % (mid_i[2], mid_i[3]))
    print('    液相碳庫　　　%.1f mmol' % mid[4])
    print('    碳庫續航　　　長期速率下 %.0f 天、初始速率下 %.0f 天'
          % (mid[5], mid_i[5]))
    print('')
    print('  ★ **續航天數只依賴液相／氣相的比例，不依賴總容積**')
    print('     （續航 = DIC×V_liq ÷ rate×V_gas，總容積約分掉）。')
    print('     → 1.80 vs 1.99 L 的爭議，對下面這個關鍵推論沒有影響。\n')
    print('  碳源切斷實驗約為 3 天（%s ~ %s）。對照碳庫續航：'
          % ('2026-08-22', '2026-08-25'))
    print('    最保守（液相三成 + 初始速率）%.1f 天 —— 僅 %.1f 倍於實驗長度'
          % (b[0][5], b[0][5] / 3))
    print('    較合理（液相一半 + 長期速率）%.0f 天 —— %.0f 倍'
          % (a[2][5], a[2][5] / 3))
    print('  -> 切斷期間基質已在耗盡，適用的是長期速率，故碳庫遠足以支應。')
    print('     **「切斷後壓降速率不變」不需要用氫氣流失解釋。**')
    print('     ⚠ 但在最保守的情境下僅 %.1f 倍，不宜寫成「遠遠超過」。'
          % (b[0][5] / 3))
    print('')
    print('  ⚠ 仍需確認：液位、以及總容積究竟是 %.2f 還是 %.2f L。'
          % (V_FIELD, V_MEMO))

    make_figure()


def make_figure():
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.2, 4.8),
                                 gridspec_kw={'wspace': 0.30})
    frac = np.linspace(0.2, 0.8, 200)
    v_liq = V_FIELD * frac
    v_gas = V_FIELD - v_liq

    a1.plot(frac * 100, RATE_LONG * v_gas * 1e3, color=BLUE, lw=3.0,
            label='長期平均')
    a1.plot(frac * 100, RATE_INIT * v_gas * 1e3, color=RED, lw=3.0, ls='--',
            label='初始速率')
    a1.legend(loc='upper right', frameon=False, fontsize=12)
    _lo, hi = a1.get_ylim()
    a1.set_ylim(0, hi * 1.30)
    a1.text(0.03, 0.97, '總容積 %.1f L\n液相佔越多，氣相越少，整機速率越低'
            % V_FIELD,
            transform=a1.transAxes, fontsize=12, color=INK,
            fontweight='bold', ha='left', va='top')
    style(a1, 'a　整機的 CO₂ 消耗速率', '液相佔總容積的比例 (%)',
          'mmol / hr')

    days_long = (DIC * v_liq) / (RATE_LONG * v_gas) / 24
    days_init = (DIC * v_liq) / (RATE_INIT * v_gas) / 24
    a2.plot(frac * 100, days_long, color=BLUE, lw=3.0, label='長期平均')
    a2.plot(frac * 100, days_init, color=RED, lw=3.0, ls='--', label='初始速率')
    a2.axhline(3, color=MUTED, lw=2.2, ls=':')
    a2.set_yscale('log')
    a2.set_yticks([1, 3, 10, 30, 100, 300])
    a2.set_yticklabels(['1', '3', '10', '30', '100', '300'])
    a2.minorticks_off()
    a2.legend(loc='upper left', frameon=False, fontsize=12)
    a2.text(80, 3, '碳源切斷實驗的長度 ', color=MUTED, fontsize=11.5,
            ha='right', va='bottom')
    _lo, hi = a2.get_ylim()
    a2.set_ylim(_lo, hi * 3.2)
    a2.text(0.03, 0.97,
            '★ 續航只依賴液相／氣相的比例，\n　 與總容積無關\n'
            '切斷期間適用長期速率（藍線），\n碳庫遠足以支應',
            transform=a2.transAxes, fontsize=11.5, color=INK,
            fontweight='bold', ha='left', va='top')
    style(a2, 'b　液相碳庫可供應多久', '液相佔總容積的比例 (%)', '天（對數）')

    out = os.path.join(OUT, 'fig54_volume.png')
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
