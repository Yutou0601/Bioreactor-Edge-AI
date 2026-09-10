# -*- coding: utf-8 -*-
"""從輸入側算莫耳速率——不需要知道頭空體積。

先前卡住是因為在輸出側量：反應槽壓力掉多少，要換成莫耳就需要頭空體積。
換到輸入側就不必：補氣的氣體來自**體積已知的 1L 預混槽**，溫度也已知。

    每次補氣送出的莫耳數 = dP_premix * V_premix / (R T)

穩定循環下頭空每個循環回到同一壓力，淨變化為零，所以
「一個循環裡消失的氣體」＝「該次補氣送進去的氣體」。頭空體積不出現。

⚠ 只用**總和**，不用逐次比值。上一版失敗正是因為逐次比值把量化與
  取樣切割的誤差放大成 20 倍散布；加總會讓那些誤差互相抵消。
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys

import numpy as np

sys.path.insert(0, __import__('os').path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from analyze_three_batches import load_all

V_PREMIX = 1.0e-3        # m^3
T_K = 303.15             # 30 C，逐行紀錄確認
R = 8.314
KGCM2_PA = 98066.5
MOL_PER_KGCM2 = KGCM2_PA * V_PREMIX / (R * T_K)   # 1L 槽內每 kg/cm2 的莫耳
RISE = 0.03


def main():
    df = load_all()
    t = df.ts.values
    pr, pm = df.p_reactor.values, df.p_mix.values
    hrs = (t[-1] - t[0]) / np.timedelta64(1, 'h')
    print('期間 %s ~ %s   共 %.0f hr（%.1f 天）'
          % (df.ts.iloc[0].date(), df.ts.iloc[-1].date(), hrs, hrs / 24))
    print('1L 預混槽每 1 kg/cm2 壓降 = %.4f mol\n' % MOL_PER_KGCM2)

    dR = np.diff(pr)
    dt = np.diff(t) / np.timedelta64(1, 'm')
    idx = np.flatnonzero((dR > RISE) & (dt <= 3)) + 1

    sum_pm, sum_pr, n_ev = 0.0, 0.0, 0
    for i in idx:
        a, b = max(0, i - 3), min(len(pr) - 1, i + 3)
        dm = pm[a:i].max() - pm[i:b + 1].min()     # 預混槽降幅
        drr = pr[i] - pr[i - 1]
        if dm > 0.01 and drr > 0:
            sum_pm += dm; sum_pr += drr; n_ev += 1
    print('補氣事件 %d 次   預混槽總降 %.2f kg/cm2   反應槽總升 %.2f'
          % (n_ev, sum_pm, sum_pr))

    mol_tot = sum_pm * MOL_PER_KGCM2
    rate_tot = mol_tot / hrs
    print('\n== 總氣體消耗（不需頭空體積） ==')
    print('  送出總量 %.3f mol   平均 %.5f mol/hr' % (mol_tot, rate_tot))

    # 生物份額：直接由資料算 r_b*T / 振幅
    import csv
    from dataset_c import EXCLUDE
    rows = [r for r in csv.DictReader(
        open('docs/analysis_charts_3batch/rb_per_cycle.csv',
             encoding='utf-8-sig')) if r['folder'] not in EXCLUDE]
    du = np.array([float(r['dur_hr']) for r in rows])
    tr = np.array([float(r['total_rate']) for r in rows])
    share = 0.0126 * np.median(du) / (np.median(tr) * np.median(du))
    print('\n== 生物份額 ==')
    print('  定版 r_b 0.0126 ÷ 總下降速率中位 %.4f = %.0f%%'
          % (np.median(tr), share * 100))

    bio = rate_tot * share
    ch4 = bio / 4.0
    print('\n== 換算結果 ==')
    print('  生物消耗   %.5f mol/hr' % bio)
    print('  甲烷生成   %.5f mol/hr  = %.2f mmol/hr  （淨少 4 分子 → 1 CH4）'
          % (ch4, ch4 * 1000))
    print('  換成標準狀態體積約 %.1f mL/hr' % (ch4 * 22400))

    # 交叉檢核：用總和比值反推頭空體積（比逐次比值穩健）
    vh = V_PREMIX * 1000 * sum_pm / sum_pr
    print('\n== 交叉檢核 ==')
    print('  以總和比值反推頭空體積 = 1L × %.2f/%.2f = %.2f L'
          % (sum_pm, sum_pr, vh))
    print('  （上一版逐次比值的中位是 1.92 L，四分位 1.55~2.30）')


if __name__ == '__main__':
    main()
