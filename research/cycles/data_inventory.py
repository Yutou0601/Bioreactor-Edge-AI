
# -*- coding: utf-8 -*-
"""
Testing_data 全盤點：哪些資料夾能撐起 ORP 特徵？
════════════════════════════════════════════════════════════════════════

**先前的錯誤**：`cond_of()` 只認四個時間窗（1:1／pump_off／pump_on5／tau1,5,10），
其餘一律回傳 'other' 直接跳過。於是這些整批被丟掉——

    0417-0427_有循環_10mins_74%      從未使用
    old data/2026        84 檔       從未使用
    old data/2025       102 檔       從未使用
    old data/co溶入液體              從未使用（名稱像純物理對照！）

特徵健檢已量出門檻：**ORP 的 |中位|/SE 要 ≥ 2，大約需要每組 15 個以上循環**
（tau10 有 15 個 → 3.1 通過；tau1 只有 7 個 → 0.6 不過）。

本檔對**每一個資料夾**獨立算出：
  · 可用循環數
  · ORP 的 dORP/dt 中位、SE、訊噪比 → 是否過門檻
  · 壓力軌跡的線性度 R² → 斜率／截距分解是否成立
  · 壓力與 ORP 的絕對水準 → 判斷是否為同一套感測設定

輸出 -> docs/analysis_charts_3batch/data_inventory.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv
import glob

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from regime_changepoints import TD                                 # noqa: E402
from multivariate_increments import load4, seg, wrate              # noqa: E402

PORD = 6
F_CO2_DEFAULT = 0.2


def weak_pairs(t, y, nw=5):
    T = t[-1]-t[0]; m = T/(nw+1); out = []
    for c in np.linspace(t[0]+m, t[-1]-m, nw):
        u = (t-c)/m; ins = np.abs(u) < 1
        if ins.sum() < 8:
            continue
        base = 1-u[ins]**2
        ph = base**PORD
        dph = PORD*base**(PORD-1)*(-2*u[ins])/m
        w = np.trapezoid(ph, t[ins])
        if w > 0:
            out.append((np.trapezoid(ph*y[ins], t[ins])/w,
                        np.trapezoid(dph*y[ins], t[ins])/w))
    return out


def main():
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

    print('══ Testing_data 全盤點 ══\n')
    print(f'   {"資料夾":<32}{"檔":>4}{"循環":>5}{"期間":>24}')
    print('   '+'-'*68)
    store = []
    for path, tag in folders:
        try:
            raw = load4(path)
        except Exception:
            continue
        if len(raw) < 500:
            print(f'   {tag[:31]:<32}{len(glob.glob(os.path.join(path,"*.csv"))):>4}'
                  f'{"—":>5}{"資料過少":>24}')
            continue
        ts = [r[0] for r in raw]
        P = np.array([r[1] for r in raw]); O = np.array([r[2] for r in raw])
        H = np.array([r[3] for r in raw])
        h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
        cyc = seg(h, P)
        span = f'{ts[0].date()}~{ts[-1].date()}'
        print(f'   {tag[:31]:<32}'
              f'{len(glob.glob(os.path.join(path,"*.csv"))):>4}'
              f'{len(cyc):>5}{span:>24}')
        if len(cyc) < 3:
            continue
        rec = []
        for a, b in cyc:
            t = h[a:b+1]-h[a]
            half = t <= t[-1]/2
            if half.sum() < 20:
                continue
            ro = wrate(t, O[a:b+1])
            rec.append(dict(pairs=weak_pairs(t[half], P[a:b+1][half]),
                            dorp=ro, P0=P[a], dur=t[-1]))
        store.append((tag, rec, np.median(P), np.median(O), np.median(H)))

    # ── 逐資料夾的特徵品質 ──────────────────────────────
    print('\n── 特徵品質（門檻：ORP 訊噪 ≥ 2、k_La > 0）──')
    print(f'   {"資料夾":<32}{"n":>4}{"dORP 中位":>11}{"SE":>8}'
          f'{"訊噪":>7}{"k_La":>9}{"R²":>7}   判定')
    print('   '+'-'*82)
    rows = []
    for tag, rec, mP, mO, mH in store:
        o = np.array([r['dorp'] for r in rec
                      if np.isfinite(r.get('dorp', np.nan))])
        allp = [p for r in rec for p in r['pairs']]
        if len(o) < 3 or len(allp) < 10:
            continue
        se = o.std(ddof=1)/np.sqrt(len(o))
        snr = abs(np.median(o))/se if se > 0 else np.inf
        x = np.array([F_CO2_DEFAULT*p[0] for p in allp])
        y = np.array([p[1] for p in allp])
        A = np.vstack([x, np.ones_like(x)]).T
        c, *_ = np.linalg.lstsq(A, y, rcond=None)
        res = y-A@c
        ss = np.sum((y-y.mean())**2)
        r2 = 1-float(res @ res)/ss if ss > 0 else np.nan
        kla = -c[0]
        ok = (snr >= 2) and (kla > 0)
        print(f'   {tag[:31]:<32}{len(o):>4}{np.median(o):>11.2f}{se:>8.2f}'
              f'{snr:>7.1f}{kla:>9.4f}{r2:>7.3f}   '
              f'{"✓ 可用" if ok else "✘"}')
        rows.append([tag, len(o), f'{np.median(o):.3f}', f'{se:.3f}',
                     f'{snr:.2f}', f'{kla:.4f}', f'{r2:.3f}',
                     f'{mP:.2f}', f'{mO:.0f}', f'{mH:.2f}', int(ok)])

    # ── 感測設定是否一致 ────────────────────────────────
    print('\n── 感測水準（判斷是否同一套設定）──')
    print(f'   {"資料夾":<32}{"壓力中位":>10}{"ORP 中位":>10}{"pH 中位":>9}')
    print('   '+'-'*62)
    for tag, rec, mP, mO, mH in store:
        print(f'   {tag[:31]:<32}{mP:>10.2f}{mO:>10.0f}{mH:>9.2f}')

    good = [r for r in rows if r[-1]]
    print(f'\n══ 結論 ══')
    print(f'   {len(good)}/{len(rows)} 個資料夾的 ORP 特徵通過門檻')
    for r in good:
        print(f'      ✓ {r[0]}   n={r[1]}   訊噪 {r[4]}')
    if len(good) >= 2:
        print('\n   → 有兩組以上可用，可嘗試跨資料夾的聯合估計。')
    else:
        print('\n   → 可用組數不足，聯合估計仍缺超定性。')

    with open(f'{OUT}/data_inventory.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['folder', 'n_cycles', 'dORP_median', 'dORP_se', 'snr',
                    'kLa', 'r2', 'P_median', 'ORP_median', 'pH_median', 'ok'])
        w.writerows(rows)
    print(f'\n輸出 → {OUT}/data_inventory.csv')


if __name__ == '__main__':
    main()
