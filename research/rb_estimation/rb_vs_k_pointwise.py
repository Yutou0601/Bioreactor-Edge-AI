
# -*- coding: utf-8 -*-
"""r_b(k) 的**逐區間逼近**——不承諾函數形式，只問各 k 區間上的數值
════════════════════════════════════════════════════════════════════════

`rb_vs_k_form.py` 的回收檢定失敗，證明的是「**分不出參數家族**」
（恆定／線性／飽和三種真值都被挑成飽和）。它**沒有**證明
「分 k 區間估不出數值」——那是另一個問題，本檔測它。

**做法：逐區間的間接推論。**
對每個 k̂ 區間 j，建立校準曲線

    觀測中位數_j  =  g_j(投入的真值)

方法是掃描一系列**恆定**真值，每個都走完全相同的管線（同樣的設計、
AR(1) 雜訊、量化、曲率篩選、逐循環擬合），記錄該區間的中位數。
估計假影同時出現在模擬與實測兩側而抵消，故 g_j 是校準過的映射。
最後把實測的區間中位數代進 g_j 的反函數，得到該區間的 r_b。

**這不是在找形式，是在找數值。** 若各區間的估計彼此可分辨（信賴區間不重疊），
就得到一條逼近的 r_b(k)；若全部重疊，則連數值也分不出。

⚠ 最低 k 區間（k < 0.03）的實測中位是 −0.093，屬簡併廢區，一併報告但不解讀。

輸出 -> docs/analysis_charts_3batch/rb_vs_k_pointwise.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from simulator_check import QUANT                                  # noqa: E402
from rb_vs_k_form import fit_LE_fast, prep, ar1, summary, NBIN     # noqa: E402
from residual_structure import collect                             # noqa: E402
from rb_recovery_study import curvature                            # noqa: E402

RNG = np.random.default_rng(1414213)
CURV_MIN = 0.45
NREP = 8                      # 每個候選真值重複幾次
GRID = np.arange(-0.005, 0.0451, 0.005)   # 候選恆定真值


def sim_binned(fits, rb_true, edges):
    """以**恆定**真值走完整管線，回傳各 k̂ 區間的 r̂_b 中位數。"""
    rr, kk = [], []
    for f in fits:
        t = f['t']
        y = f['peq']+f['amp']*np.exp(-f['k']*t)-rb_true*t \
            + ar1(len(t), f['sd'], f['phi'])
        y = np.round(y/QUANT)*QUANT
        if curvature(t, y) < CURV_MIN:
            continue
        g = fit_LE_fast(t, y)
        if g:
            rr.append(g['rb']); kk.append(g['k'])
    return summary(rr, kk, edges)


def main():
    fits = prep(collect())
    ks = np.array([f['k'] for f in fits])
    rbs = np.array([f['rb'] for f in fits])
    edges = np.quantile(ks, np.linspace(0, 1, NBIN+1))
    edges[-1] *= 1.001
    obs = summary(rbs, ks, edges)

    print('══ r_b(k) 的逐區間逼近 ══\n')
    print(f'   循環 {len(fits)}   候選真值 {len(GRID)} 個 × {NREP} 次重複')
    print(f'   每個候選都走完整管線（設計、AR(1)、量化、篩選、擬合）\n')

    # ── 建立校準曲線 g_j ────────────────────────────────
    print('   掃描候選真值中…')
    cal = np.full((len(GRID), NREP, NBIN), np.nan)
    for a, rb_true in enumerate(GRID):
        for r in range(NREP):
            cal[a, r] = sim_binned(fits, rb_true, edges)
        print(f'      投入 {rb_true:+.4f} → 各區間回收中位 '
              + '  '.join(f'{v:+.4f}' for v in np.nanmean(cal[a], axis=0)))

    # ── 反解：實測中位數對應的真值 ──────────────────────
    print(f'\n── 逐區間反解 ──')
    print(f'   {"k 區間":<20}{"n":>5}{"實測中位":>11}'
          f'{"校準後 r_b":>13}{"95% 區間":>20}')
    print('   '+'-'*70)
    rows = []
    for j in range(NBIN):
        m = (ks >= edges[j]) & (ks < edges[j+1])
        # ⚠ cal 的形狀是 (候選值, 重複, 區間)。要對**重複**平均（axis=1）
        #   才得到「回收值隨候選真值變化」的校準曲線；先前寫 axis=0 是對
        #   候選值平均，長度變成 NREP，於是每條都被判成非單調。
        gj = np.nanmean(cal[:, :, j], axis=1)          # 平均校準曲線
        sj = np.nanstd(cal[:, :, j], axis=1, ddof=1)   # 重複間的散布
        if np.any(np.isnan(gj)) or not np.all(np.diff(gj) > 0):
            rows.append([f'{edges[j]:.3f}-{edges[j+1]:.3f}', int(m.sum()),
                         f'{obs[j]:.5f}', 'n/a', 'n/a', 'n/a'])
            print(f'   [{edges[j]:.3f}, {edges[j+1]:.3f}){"":<3}{m.sum():>5}'
                  f'{obs[j]:>11.5f}{"校準曲線非單調":>13}')
            continue
        est = float(np.interp(obs[j], gj, GRID))
        # ⚠ 不確定度有**兩個**來源，先前只算了第一個，結果 CI 只有 ±0.0001，
        #   那不可能是真的：
        #     (a) 校準曲線在重複間的散布（模擬雜訊）—— 很小
        #     (b) **實測中位數本身的抽樣誤差** —— 每區間僅約 60 個循環，
        #         而逐循環 r̂_b 的散布極大（IQR 橫跨 0.003–0.021），這一項
        #         比 (a) 大一到兩個數量級，漏掉它會把區間縮到假的窄。
        #   以自助法估 (b)，與 (a) 平方相加，再經校準曲線的斜率換算成真值。
        rb_bin = rbs[m]
        boot = np.array([np.median(RNG.choice(rb_bin, len(rb_bin)))
                         for _ in range(600)])
        se_obs = float(np.std(boot, ddof=1))
        se_cal = float(np.interp(est, GRID, sj))
        slope = np.gradient(gj, GRID)
        sl = float(np.interp(est, GRID, slope))
        se = np.hypot(se_obs, se_cal)/max(abs(sl), 1e-9)
        lo, hi = est-1.96*se, est+1.96*se
        rows.append([f'{edges[j]:.3f}-{edges[j+1]:.3f}', int(m.sum()),
                     f'{obs[j]:.5f}', f'{est:.5f}', f'{lo:.5f}', f'{hi:.5f}'])
        print(f'   [{edges[j]:.3f}, {edges[j+1]:.3f}){"":<3}{m.sum():>5}'
              f'{obs[j]:>11.5f}{est:>13.5f}'
              f'{f"[{lo:+.4f}, {hi:+.4f}]":>20}')

    # ── 判定：各區間分不分得開 ──────────────────────────
    good = [r for r in rows if r[3] != 'n/a']
    print(f'\n── 判定 ──')
    if len(good) < 2:
        print('   ✘ 可反解的區間不足兩個，無法談 r_b 隨 k 的變化')
    else:
        lo1, hi1 = float(good[0][4]), float(good[0][5])
        lo2, hi2 = float(good[-1][4]), float(good[-1][5])
        sep = (lo2 > hi1) or (lo1 > hi2)
        print(f'   最低可用區間 {good[0][3]}  [{lo1:+.4f}, {hi1:+.4f}]')
        print(f'   最高區間     {good[-1][3]}  [{lo2:+.4f}, {hi2:+.4f}]')
        print(f'   → {"✓ 兩端信賴區間**不重疊**：r_b 確實隨 k 變，且變化量可估" if sep else "✘ 兩端信賴區間重疊：連數值也分不出"}')
        if sep:
            print('     ⇒ 可報告「逐區間的 r_b 逼近」，但仍**不宣稱函數形式**')

    with open(f'{OUT}/rb_vs_k_pointwise.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['k_bin', 'n', 'observed_median', 'calibrated_rb',
                    'ci_lo', 'ci_hi'])
        w.writerows(rows)
    print(f'\n輸出 → {OUT}/rb_vs_k_pointwise.csv')


if __name__ == '__main__':
    main()
