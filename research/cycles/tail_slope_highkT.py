# -*- coding: utf-8 -*-
"""在「指數項已經死透」的子樣本上，直接量尾段斜率——結構上無簡併。

想法不是新演算法（就是直線迴歸），而是**用物理推導的可辨識性條件挑段**：
曲率預篩管的是「指數項看不看得見」；這裡管的是「指數項死了沒有」。
    kT > 5  ->  exp(-kT) < 0.007  ->  尾段幾乎是純直線，斜率即 r_b
在這些段上簡併不存在，因為指數項在該區間內已無貢獻。

可檢定的預測（把兩個獨立分析綁在一起）：
    高 k 子樣本的 r_b 應該高於全體中位，倍率 = (k_high/k_med)^beta
    論文反演出的相容 beta 落在 [0.20, 0.80]
若實測倍率落在該區間 -> 兩個分析互相佐證；若落在外面 -> 有問題。

⚠ 端點選擇偏誤：最後一點因壓力夠低才觸發補氣，會讓斜率偏大。
   所以一律丟掉尾端數點，並掃描丟幾點看穩不穩。
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import csv
import sys

import numpy as np

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dataset_c import EXCLUDE, collect_c


def main():
    rows = [r for r in csv.DictReader(
        open('../docs/analysis_charts_3batch/rb_per_cycle.csv',
             encoding='utf-8-sig')) if r['folder'] not in EXCLUDE]
    cyc = collect_c()
    kk = np.array([float(r['k']) for r in rows])
    du = np.array([float(r['dur_hr']) for r in rows])
    rb = np.array([float(r['rb']) for r in rows])
    kT = kk * du
    print('kT 分布  中位 %.2f   >3 有 %d 段   >5 有 %d 段   >7 有 %d 段'
          % (np.median(kT), (kT > 3).sum(), (kT > 5).sum(), (kT > 7).sum()))
    kmed = float(np.median(kk))
    print('全體 k 中位 %.3f    全體 r_b 中位 %.5f\n' % (kmed, np.median(rb)))

    print('門檻  丟尾  段數   尾段斜率中位   k中位   倍率   對應 beta')
    for thr in (3.0, 5.0, 7.0):
        for drop in (0, 10, 30):
            s, ks = [], []
            for i, (tag, x, y) in enumerate(cyc):
                if kT[i] <= thr:
                    continue
                # 指數項殘量降到 1% 以下之後才開始取
                t0 = x[0] + 4.6 / max(kk[i], 1e-9)
                m = x >= t0
                if drop:
                    m &= x <= x[-1] - drop / 60.0
                if m.sum() < 25:
                    continue
                A = np.polyfit(x[m], y[m], 1)
                s.append(-A[0]); ks.append(kk[i])
            if len(s) < 10:
                continue
            md, km = float(np.median(s)), float(np.median(ks))
            ratio = md / np.median(rb)
            beta = np.log(ratio) / np.log(km / kmed) if km != kmed else np.nan
            print('%4.1f   %2dmin  %4d   %10.5f   %6.3f  %5.2f   %6.2f'
                  % (thr, drop, len(s), md, km, ratio, beta))

    print('\n論文反演的相容 beta 落在 [0.20, 0.80]')
    print('若上表的 beta 落在該區間，兩個獨立分析互相佐證')


if __name__ == '__main__':
    main()
