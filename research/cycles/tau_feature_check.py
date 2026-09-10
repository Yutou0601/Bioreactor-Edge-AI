
# -*- coding: utf-8 -*-
"""
τ 系列的特徵健檢——**進 model 之前**必須先過
════════════════════════════════════════════════════════════════════════

聯合估計要用三組特徵：壓力斜率（→ k_La）、壓力截距、dORP/dt（→ r_b 比例）。
若特徵本身是壞的，後面的擬合再漂亮都是假的。

警訊：先前 `shared_rb_tau.py` 解出 **k_La(tau1) = −0.056**（負值，物理上不可能）。
那不是模型問題，是特徵問題。本檔在建模前逐項檢查：

  F1  線性：rate 對 P 是否真的線性？（不線性 ⇒ 斜率／截距分解無意義）
  F2  物理合理性：k_La 是否為正？
  F3  ORP 穩定性：dORP/dt 在條件內的散布有多大？中位數是否可信？
  F4  視窗敏感度：改用前 1/3、前 1/2、全循環，特徵變多少？
  F5  離群循環：留一循環後，特徵變多少？（單一循環主導 = 不可靠）

**任一項不過，就不要進 model。**

輸出 -> docs/analysis_charts_3batch/tau_feature_check.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv
import glob
import datetime as dt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from regime_changepoints import TD                                 # noqa: E402
from multivariate_increments import load4, seg, wrate              # noqa: E402

F_CO2 = 0.2
PORD = 6
TAU = [('tau1', dt.date(2026, 7, 22), dt.date(2026, 7, 27)),
       ('tau5', dt.date(2026, 7, 27), dt.date(2026, 7, 30)),
       ('tau10', dt.date(2026, 7, 30), dt.date(2026, 8, 4))]


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


def gather(frac=0.5):
    """frac = 取循環的前多少比例。"""
    folders = []
    for d in sorted(os.listdir(TD)):
        p = os.path.join(TD, d)
        if not os.path.isdir(p):
            continue
        if glob.glob(os.path.join(p, '*.csv')):
            folders.append(p)
        for s in sorted(os.listdir(p)):
            sp = os.path.join(p, s)
            if os.path.isdir(sp) and glob.glob(os.path.join(sp, '*.csv')):
                folders.append(sp)
    seen = {}
    out = {k: [] for k, _, _ in TAU}          # 每個元素 = 一個循環
    for path in folders:
        try:
            raw = load4(path)
        except Exception:
            continue
        if len(raw) < 2000:
            continue
        ts = [r[0] for r in raw]
        P = np.array([r[1] for r in raw]); O = np.array([r[2] for r in raw])
        h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
        for a, b in seg(h, P):
            d = ts[a].date()
            lab = next((k for k, s, e in TAU if s <= d < e), None)
            if lab is None:
                continue
            key = (ts[a].replace(second=0), round(h[b]-h[a], 1))
            if key in seen:
                continue
            seen[key] = 1
            t = h[a:b+1]-h[a]
            sel = t <= t[-1]*frac
            if sel.sum() < 20:
                continue
            pr = weak_pairs(t[sel], P[a:b+1][sel])
            ro = wrate(t, O[a:b+1])
            if pr:
                out[lab].append(dict(t=ts[a], pairs=pr, dorp=ro,
                                     dur=t[-1], P0=P[a]))
    return out


def line(pairs):
    x = np.array([F_CO2*p[0] for p in pairs])
    y = np.array([p[1] for p in pairs])
    if len(x) < 4 or x.std() < 1e-9:
        return np.nan, np.nan, np.nan, len(x)
    A = np.vstack([x, np.ones_like(x)]).T
    c, *_ = np.linalg.lstsq(A, y, rcond=None)
    res = y-A@c
    ss = np.sum((y-y.mean())**2)
    r2 = 1-float(res @ res)/ss if ss > 0 else np.nan
    return c[0], c[1], r2, len(x)


def main():
    D = gather(0.5)
    labs = [k for k, _, _ in TAU]
    print('══ τ 系列特徵健檢（進 model 之前）══\n')

    rows = []
    print('── F1／F2  線性與 k_La 的物理合理性 ──')
    print(f'   {"條件":<8}{"循環":>5}{"配對":>6}{"斜率":>11}{"k_La":>10}'
          f'{"截距":>11}{"R²":>8}   判定')
    print('   '+'-'*66)
    okF = {}
    for lab in labs:
        cyc = D[lab]
        if not cyc:
            print(f'   {lab:<8}   無資料'); okF[lab] = False; continue
        allp = [p for c in cyc for p in c['pairs']]
        s, i, r2, n = line(allp)
        kla = -s
        bad = []
        if not np.isfinite(kla) or kla <= 0:
            bad.append('k_La ≤ 0')
        if not np.isfinite(r2) or r2 < 0.10:
            bad.append(f'R²={r2:.2f} 過低')
        okF[lab] = not bad
        print(f'   {lab:<8}{len(cyc):>5}{n:>6}{s:>11.5f}{kla:>10.4f}'
              f'{i:>11.5f}{r2:>8.3f}   '
              f'{"✓" if not bad else "✘ "+"、".join(bad)}')
        rows.append([lab, len(cyc), n, f'{kla:.4f}', f'{i:.5f}', f'{r2:.3f}'])

    print('\n── F3  dORP/dt 在條件內的散布 ──')
    print(f'   {"條件":<8}{"n":>4}{"中位":>10}{"平均":>10}{"SD":>10}'
          f'{"SE":>9}{"|中位|/SE":>11}   判定')
    print('   '+'-'*64)
    for lab in labs:
        o = np.array([c['dorp'] for c in D[lab]
                      if np.isfinite(c.get('dorp', np.nan))])
        if len(o) < 3:
            print(f'   {lab:<8}   n={len(o)} 不足'); okF[lab] = False; continue
        se = o.std(ddof=1)/np.sqrt(len(o))
        snr = abs(np.median(o))/se if se > 0 else np.inf
        ok = snr >= 2
        print(f'   {lab:<8}{len(o):>4}{np.median(o):>10.2f}{o.mean():>10.2f}'
              f'{o.std(ddof=1):>10.2f}{se:>9.2f}{snr:>11.1f}   '
              f'{"✓" if ok else "✘ 訊噪 < 2"}')
        okF[lab] = okF.get(lab, True) and ok

    print('\n── F4  視窗敏感度（前 1/3、1/2、2/3、全部）──')
    print(f'   {"條件":<8}' + ''.join(f'{f"k_La@{int(f*100)}%":>13}'
                                      for f in (0.33, 0.5, 0.67, 1.0))
          + '   判定')
    print('   '+'-'*66)
    for lab in labs:
        vals = []
        for f in (0.33, 0.5, 0.67, 1.0):
            Df = gather(f)
            allp = [p for c in Df[lab] for p in c['pairs']]
            vals.append(-line(allp)[0] if allp else np.nan)
        v = np.array(vals)
        spread = (np.nanmax(v)-np.nanmin(v))/abs(np.nanmedian(v)) \
            if np.isfinite(np.nanmedian(v)) and np.nanmedian(v) != 0 else np.inf
        ok = np.all(v > 0) and spread < 1.0
        print(f'   {lab:<8}' + ''.join(f'{x:>13.4f}' for x in v)
              + f'   {"✓" if ok else f"✘ 變異 {spread*100:.0f}%"}')
        okF[lab] = okF.get(lab, True) and ok

    print('\n── F5  留一循環的穩定性 ──')
    print(f'   {"條件":<8}{"k_La":>10}{"留一範圍":>22}{"相對變動":>11}   判定')
    print('   '+'-'*56)
    for lab in labs:
        cyc = D[lab]
        if len(cyc) < 4:
            print(f'   {lab:<8}   循環數 {len(cyc)} 不足'); continue
        base = -line([p for c in cyc for p in c['pairs']])[0]
        loo = []
        for i in range(len(cyc)):
            allp = [p for j, c in enumerate(cyc) if j != i for p in c['pairs']]
            loo.append(-line(allp)[0])
        loo = np.array(loo)
        rel = (loo.max()-loo.min())/abs(base) if base else np.inf
        ok = rel < 0.5 and np.all(loo > 0)
        print(f'   {lab:<8}{base:>10.4f}'
              f'{f"[{loo.min():.4f}, {loo.max():.4f}]":>22}{rel*100:>10.0f}%'
              f'   {"✓" if ok else "✘ 單一循環主導"}')
        okF[lab] = okF.get(lab, True) and ok

    print('\n══ 總結 ══')
    for lab in labs:
        print(f'   {lab:<8} {"✓ 特徵可用" if okF.get(lab) else "✘ 特徵不可用"}')
    ngood = sum(1 for lab in labs if okF.get(lab))
    print(f'\n   {ngood}/3 個條件的特徵通過')
    if ngood < 3:
        print('   → **不要進 model**。三條件聯合估計需要三組都可用，'
              '缺一就沒有超定性。')
    else:
        print('   → 可以進 model。')

    with open(f'{OUT}/tau_feature_check.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['cond', 'n_cycles', 'n_pairs', 'kLa', 'intercept', 'r2'])
        w.writerows(rows)
    print(f'\n輸出 → {OUT}/tau_feature_check.csv')


if __name__ == '__main__':
    main()
