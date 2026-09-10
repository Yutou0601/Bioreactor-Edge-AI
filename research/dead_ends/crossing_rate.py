
# -*- coding: utf-8 -*-
"""位準跨越估計量：用「壓力何時跨過每一個 0.01 階」取代擬合整條軌跡。

想法。現行估計器把量化當成高斯雜訊做最小平方，但 sigma=0.0065 比階高
delta=0.01 還小，那個近似在此處是設定錯誤的。改用跨越時刻後：

    delta_tau_j  ~=  delta / |dP/dt|  =  delta / (A k e^{-k tau} + r_b)

指數項隨時間衰減、生物項是常數，所以循環後段的階梯間距趨近 delta/r_b。
後段間距因此是「不必擬合 A 與 k」的 r_b 讀數。

已知的三個偏誤來源（結果必須照這個順序解讀，不可略過）：
  1. sigma/delta = 0.65，階界會反覆跳動，需要遲滯確認
  2. AR(1) phi=0.27 讓跳動相關，跨越時刻會系統性偏移
  3. kT 中位 2.84，指數項在循環末端仍有貢獻，讀數會系統性偏高
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys

import numpy as np

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dataset_c import collect_c

DELTA = 0.01
HOLD = 2                     # 遲滯：新位準要連續站住幾筆才算數


def crossings(x, y, hold=HOLD):
    """回傳 (跨越時刻, 該次跨越時的位準)。只取「往下一階」的跨越。

    遲滯的作用：sigma 不遠小於 delta，階界附近會反覆跳動。要求新位準
    連續站住 hold 筆才確認，避免把跳動當成多次跨越。
    """
    q = np.round(y / DELTA).astype(int)
    lvl = q[0]
    tau, lev = [], []
    i = 1
    while i < len(q):
        if q[i] == lvl - 1:
            j = i
            while j < len(q) and q[j] == lvl - 1:
                j += 1
            if j - i >= hold:                    # 站住了才算跨越
                tau.append(0.5 * (x[i - 1] + x[i]))
                lev.append(lvl - 1)
                lvl -= 1
                i = j
                continue
        elif q[i] < lvl - 1:                     # 一次掉多階，跳過不用
            lvl = q[i]
        elif q[i] > lvl:                         # 回升，重設基準
            lvl = q[i]
        i += 1
    return np.array(tau), np.array(lev)


def main():
    cyc = collect_c()
    print('資料集 C：%d 段\n' % len(cyc))
    # 依循環內的相對位置分箱，看 delta_tau 是否趨近平台
    nb = 5
    bins = [[] for _ in range(nb)]
    late, nseg = [], 0
    for tag, x, y in cyc:
        if len(x) < 120:
            continue
        tau, lev = crossings(x, y)
        if len(tau) < 8:
            continue
        nseg += 1
        d = np.diff(tau)
        tm = tau[1:]
        T = x[-1] - x[0]
        for dd, tt in zip(d, tm):
            b = min(nb - 1, int(nb * (tt - x[0]) / max(T, 1e-9)))
            bins[b].append(dd)
        m = tm >= x[0] + 0.6 * T                 # 後 40%
        if m.sum() >= 3:
            late.append(np.median(d[m]))

    print('可用段數 %d\n' % nseg)
    print('循環內位置      階梯間距中位(hr)   δ/Δτ (kg/cm²/hr)   n')
    for b in range(nb):
        a = np.array(bins[b])
        if a.size:
            md = float(np.median(a))
            print('  %d0–%d0%%          %6.3f            %7.4f        %5d'
                  % (b * 2, (b + 1) * 2, md, DELTA / md, a.size))
    L = np.array(late)
    md = float(np.median(L))
    boot = np.median(np.random.default_rng(7).choice(
        L, size=(4000, L.size)), axis=1)
    lo, hi = np.percentile(DELTA / boot, [2.5, 97.5])
    print('\n後 40%% 的逐段中位間距：%.3f hr  → r_b 讀數 %.4f'
          % (md, DELTA / md))
    print('  拔靴 95%%：[%.4f, %.4f]   段數 %d' % (lo, hi, L.size))
    print('  現行估計器（未修正）0.0128 ／ 定版 0.0126')


if __name__ == '__main__':
    main()
