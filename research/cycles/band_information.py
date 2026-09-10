
# -*- coding: utf-8 -*-
"""
微正壓控制帶＝實驗設計變數（Band-as-Design）
════════════════════════════════════════════════════════════════════════

鑑識分析發現：這台裝置的控制帶（補氣上限 P0、觸發下限 Pend）一年來一直在變。
也就是說，它在無意間跑了一整年的實驗設計。

本檔檢驗那個設計的**資訊產出**：

  H1  控制帶越寬 → 單次循環對 k_La 的估計越精確（Fisher 資訊越大）
  H2  但越寬的帶 → 循環越久 → **單位時間的資訊有最佳值**
  H3  該最佳值可由裝置在**邊緣端**即時算出，無需任何額外儀器

若 H2 成立，則「選擇微正壓帶寬」就是一個可在邊緣執行的最佳實驗設計問題，
而且它的致動器**已經存在**（就是原本的安全控制迴路），零額外硬體。

輸出 -> docs/analysis_charts_3batch/band_information.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys
import csv

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from regime_changepoints import load, segment, TD, FCO2, DEFAULT_FCO2  # noqa
from changepoint_forensics import gather_rich                      # noqa: E402

NW = 6          # 每個循環放幾個測試函數窗
PORD = 6


def weak_pairs(t, y, nw=NW):
    """在循環內放 nw 個緊支撐測試函數，各回傳一組（壓力, 速率）。"""
    T = t[-1]-t[0]
    m = T/(nw+1)                       # 半寬
    out = []
    for c in np.linspace(t[0]+m, t[-1]-m, nw):
        u = (t-c)/m
        ins = np.abs(u) < 1
        if ins.sum() < 8:
            continue
        base = 1-u[ins]**2
        ph = base**PORD
        dph = PORD*base**(PORD-1)*(-2*u[ins])/m
        w = np.trapezoid(ph, t[ins])
        if w <= 0:
            continue
        rate = np.trapezoid(dph*y[ins], t[ins])/w     # dy/dt 的弱形式
        pres = np.trapezoid(ph*y[ins], t[ins])/w      # 同權重的壓力
        out.append((pres, rate))
    return np.array(out)


def cycle_kla(t, y):
    """單一循環的 k_La 估計與其標準誤。

    模型 dP/dt = -k(P - Peq)  →  rate = -k*P + k*Peq
    對 nw 組弱形式配對做 OLS，斜率即 -k。
    """
    pr = weak_pairs(t, y)
    if len(pr) < 4:
        return np.nan, np.nan, 0
    P, R = pr[:, 0], pr[:, 1]
    if P.std() < 1e-6:
        return np.nan, np.nan, len(pr)
    A = np.vstack([P, np.ones_like(P)]).T
    coef, res, *_ = np.linalg.lstsq(A, R, rcond=None)
    k = -coef[0]
    dof = len(pr)-2
    if dof < 1 or k <= 0:
        return np.nan, np.nan, len(pr)
    resid = R-A@coef
    s2 = float(resid @ resid)/dof
    cov = s2*np.linalg.inv(A.T@A)
    return k, float(np.sqrt(cov[0, 0])), len(pr)


def main():
    rows = gather_rich()
    print('══ 微正壓控制帶作為實驗設計變數 ══\n')

    # 重新走一次原始資料以取得每個循環的完整軌跡
    import os
    import glob
    seen, rec = {}, []
    folders = []
    for d in sorted(os.listdir(TD)):
        p = os.path.join(TD, d)
        if not os.path.isdir(p):
            continue
        if glob.glob(os.path.join(p, '*.csv')):
            folders.append((p, d))
        for s in sorted(os.listdir(p)):
            sp = os.path.join(p, s)
            if os.path.isdir(sp) and glob.glob(os.path.join(sp, '*.csv')):
                folders.append((sp, f'{d}/{s}'))
    for path, tag in folders:
        try:
            raw = load(path)
        except Exception:
            continue
        if len(raw) < 2000:
            continue
        cyc, h, P, ts = segment(raw)
        f = FCO2.get(tag.split('/')[0], DEFAULT_FCO2)
        for a, b in cyc:
            key = (ts[a].replace(second=0), round(h[b]-h[a], 1))
            if key in seen:
                continue
            seen[key] = 1
            t = h[a:b+1]-h[a]; y = P[a:b+1]
            k, se, nw = cycle_kla(t, y)
            if not np.isfinite(k) or not np.isfinite(se) or se <= 0:
                continue
            rec.append(dict(t=ts[a], band=y[0]-y[-1], dur=t[-1],
                            P0=y[0], k=k, se=se, f=f,
                            # 單次循環的 Fisher 資訊 ∝ 1/SE²
                            info=1.0/se**2,
                            inforate=1.0/se**2/t[-1]))
    rec.sort(key=lambda r: r['t'])
    print(f'   可估計 k_La 的循環 {len(rec)} / {len(rows)}\n')

    band = np.array([r['band'] for r in rec])
    dur = np.array([r['dur'] for r in rec])
    se = np.array([r['se'] for r in rec])
    info = np.array([r['info'] for r in rec])
    irate = np.array([r['inforate'] for r in rec])

    print(f'   控制帶寬 P0−Pend：中位 {np.median(band):.3f}'
          f'   範圍 [{band.min():.2f}, {band.max():.2f}] kg/cm²')
    print(f'   循環時長      ：中位 {np.median(dur):.1f} hr'
          f'   範圍 [{dur.min():.1f}, {dur.max():.1f}]\n')

    # ── H1：帶寬 → 精度 ──────────────────────────────────
    print('── H1  控制帶越寬，單次循環的 k_La 越精確？──')
    lb, ls = np.log(band), np.log(se)
    m = np.isfinite(lb) & np.isfinite(ls)
    sl = np.polyfit(lb[m], ls[m], 1)[0]
    r1 = np.corrcoef(lb[m], ls[m])[0, 1]
    print(f'   log SE 對 log 帶寬  斜率 = {sl:+.3f}   r = {r1:+.3f}   n = {m.sum()}')
    print(f'   → 帶寬加倍，SE 變為 {2**sl:.2f}×'
          f'（{"支持 H1" if sl < -0.1 else "不支持 H1"}）\n')

    # ── H2：單位時間資訊的最佳帶寬 ───────────────────────
    print('── H2  單位時間的資訊是否有最佳帶寬？──')
    qs = np.quantile(band, np.linspace(0, 1, 7))
    print(f'   {"帶寬區間":<20}{"n":>5}{"中位時長":>10}{"中位 SE":>12}'
          f'{"資訊/循環":>12}{"資訊/小時":>12}')
    print('   '+'-'*72)
    best, bestv = None, -1
    for i in range(len(qs)-1):
        s = (band >= qs[i]) & (band < qs[i+1] if i < len(qs)-2
                               else band <= qs[i+1])
        if s.sum() < 4:
            continue
        mi, mr = np.median(info[s]), np.median(irate[s])
        print(f'   [{qs[i]:.2f}, {qs[i+1]:.2f})      {s.sum():>5}'
              f'{np.median(dur[s]):>10.1f}{np.median(se[s]):>12.5f}'
              f'{mi:>12.0f}{mr:>12.0f}')
        if mr > bestv:
            bestv, best = mr, (qs[i], qs[i+1])
    print(f'\n   單位時間資訊最高的帶寬區間：'
          f'[{best[0]:.2f}, {best[1]:.2f}) kg/cm²')

    # 帶寬 vs 時長：是否真的有取捨
    ld = np.log(dur)
    m2 = np.isfinite(lb) & np.isfinite(ld)
    sd = np.polyfit(lb[m2], ld[m2], 1)[0]
    print(f'   log 時長 對 log 帶寬  斜率 = {sd:+.3f}'
          f'   → 帶寬加倍，循環時長變 {2**sd:.2f}×'
          f'（{"有取捨" if sd > 0.1 else "無明顯取捨"}）')

    # ── H3：邊緣端可算性 ─────────────────────────────────
    print('\n── H3  邊緣端算得動嗎？──')
    import time
    t0 = time.perf_counter()
    N = 2000
    for _ in range(N):
        cycle_kla(np.linspace(0, 10, 600), np.linspace(1.2, 0.9, 600)
                  + np.random.default_rng(0).normal(0, 0.005, 600))
    dt_ = (time.perf_counter()-t0)/N
    print(f'   單循環的 k_La + SE 估計：{dt_*1e3:.2f} ms')
    print(f'   一天約 2.2 次循環 → 每日計算量 {dt_*2.2*1e3:.2f} ms')
    print(f'   記憶體：僅需 numpy（27 MB）＋單循環緩衝'
          f'（600 點 × 8 B = 5 KB）→ **60 MB 預算內**')

    with open(f'{OUT}/band_information.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['time', 'band', 'dur_hr', 'P0', 'kla', 'se',
                    'info', 'info_per_hr'])
        for r in rec:
            w.writerow([r['t'].strftime('%Y-%m-%d %H:%M'),
                        f'{r["band"]:.3f}', f'{r["dur"]:.2f}',
                        f'{r["P0"]:.3f}', f'{r["k"]:.5f}', f'{r["se"]:.5f}',
                        f'{r["info"]:.1f}', f'{r["inforate"]:.1f}'])
    print(f'\n輸出 → {OUT}/band_information.csv')


if __name__ == '__main__':
    main()
