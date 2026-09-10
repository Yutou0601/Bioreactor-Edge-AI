
# -*- coding: utf-8 -*-
"""
組成解析．雙受限模型（CR-DL）的實作與決定性檢驗
════════════════════════════════════════════════════════════════════════

模型（見 docs/模型_組成解析雙受限模型_2026-08-06.md）
    dpCO2/dt = -k (pCO2 - p*) - v
    dpH2 /dt = -eps*k*pH2 - 4v
    dpCH4/dt = +v
    v = vmax * pH2 / (KH + pH2)
    P = pCO2 + pH2 + pCH4                     （唯一觀測）

決定性檢驗
──────────
**只用 4:1 批次擬合，去預測 1:1 批次的形狀。**
兩者形狀差異極大（曲率 0.504 vs 0.805、前後半速率比 1.05-1.23 vs 5.19），
而模型唯一被告知的差異只有**進氣組成**。若能預測出來，那是預測不是擬合。

輸出 -> docs/analysis_charts_3batch/crdl_fit.csv + fig33
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
from paths import testing_data          # Testing_data 的位置解析
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv
import glob
import datetime as dt

import numpy as np
from scipy import optimize

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT, RED, AQUA, BLUE, INK, INK2, MUTED, style  # noqa: E402
from analyze_new_methods import collect                  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TD = testing_data()
EPS = 1.0/44.0            # H2/CO2 亨利常數比


def simulate(t, P0, fH2, k, pstar, vmax, KH, fCH4_0=0.0):
    """RK4 積分，回傳 P(t)。t 為小時、等距。"""
    n = len(t)
    dt_h = t[1]-t[0]
    pC = P0*(1-fH2)*(1-fCH4_0)
    pH = P0*fH2*(1-fCH4_0)
    pM = P0*fCH4_0
    out = np.empty(n)
    out[0] = pC+pH+pM

    def deriv(pC, pH):
        v = vmax*pH/(KH+pH) if pH > 0 else 0.0
        return (-k*(pC-pstar)-v, -EPS*k*pH-4*v, v)

    for i in range(1, n):
        a = deriv(pC, pH)
        b = deriv(pC+0.5*dt_h*a[0], max(pH+0.5*dt_h*a[1], 0))
        c = deriv(pC+0.5*dt_h*b[0], max(pH+0.5*dt_h*b[1], 0))
        d = deriv(pC+dt_h*c[0], max(pH+dt_h*c[1], 0))
        pC += dt_h/6*(a[0]+2*b[0]+2*c[0]+d[0])
        pH = max(pH + dt_h/6*(a[1]+2*b[1]+2*c[1]+d[1]), 0.0)
        pM += dt_h/6*(a[2]+2*b[2]+2*c[2]+d[2])
        out[i] = pC+pH+pM
    return out


def load_folder(folder):
    rows = []
    for fp in sorted(glob.glob(os.path.join(folder, '*.csv'))):
        for line in open(fp, encoding='utf-8', errors='replace'):
            p = line.strip().split(',')
            if len(p) < 14:
                continue
            try:
                rows.append((dt.datetime(int(p[0]), int(p[1]), int(p[2]),
                                         int(p[3]), int(p[4]), int(float(p[5]))),
                             float(p[11])))
            except Exception:
                continue
    rows.sort()
    return rows


def segment(rows, minhr):
    ts = [r[0] for r in rows]; P = np.array([r[1] for r in rows])
    h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
    out, valley, start = [], P[0], 0
    for i in range(1, len(P)):
        if h[i]-h[i-1] > 1.0:
            if h[i-1]-h[start] > minhr:
                out.append((start, i-1))
            start, valley = i, P[i]; continue
        if P[i]-valley > 0.03:
            if h[i-1]-h[start] > minhr:
                out.append((start, i-1))
            start, valley = i, P[i]
        elif P[i] < valley:
            valley = P[i]
    if h[-1]-h[start] > minhr:
        out.append((start, len(P)-1))
    return [(a, b) for a, b in out
            if h[b]-h[a] >= minhr and P[a]-P[b] >= 0.08], h, P


def gather():
    """回傳 [(標籤, fH2, [(t, P), ...])]"""
    sets = []
    lst41 = []
    for name, cs in collect().items():
        for c in cs:
            t = (c.ts-c.ts.iloc[0]).dt.total_seconds().values/3600
            y = c.p_reactor.values.astype(float)
            if t[-1] < 4 or (y[0]-y[-1]) < 0.10:
                continue
            lst41.append((t, y))
    sets.append(('4:1 (7-8月)', 0.8, lst41))
    r = load_folder(os.path.join(TD, '0301-0416_無循環與有循環_5mins'))
    cyc, h, P = segment(r, 4)
    lst = [(h[a:b+1]-h[a], P[a:b+1]) for a, b in cyc]
    sets.append(('4:1 (3-4月)', 0.8, lst))
    r = load_folder(os.path.join(TD, '0109-0123_H2_1CO2_1'))
    cyc, h, P = segment(r, 4)
    lst = [(h[a:b+1]-h[a], P[a:b+1]) for a, b in cyc]
    sets.append(('1:1 (1月)', 0.5, lst))
    return sets


def sse(theta, data, fH2):
    k, pstar, vmax, KH, fM = theta
    s, n = 0.0, 0
    for t, y in data:
        m = simulate(t, y[0], fH2, k, pstar, vmax, KH, fM)
        s += float(np.sum((y-m)**2)); n += len(y)
    return s, n


def fit(data, fH2, p0=None):
    def obj(th):
        return sse(th, data, fH2)[0]
    p0 = p0 or [0.05, 0.15, 0.004, 0.15, 0.05]
    bnd = [(1e-3, 1.0), (0.0, 0.60), (0.0, 0.05), (1e-3, 2.0), (0.0, 0.5)]
    best = None
    for k0 in (0.02, 0.06, 0.15):
        for v0 in (0.002, 0.006, 0.012):
            q = list(p0); q[0] = k0; q[2] = v0
            r = optimize.minimize(obj, q, method='L-BFGS-B', bounds=bnd)
            r = optimize.minimize(obj, r.x, method='Nelder-Mead', bounds=bnd,
                                  options=dict(maxiter=8000, fatol=1e-13))
            if best is None or r.fun < best.fun:
                best = r
    return best.x


def shape(t, y):
    dur = t[-1]-t[0]; drop = y[0]-y[-1]
    tn = (t-t[0])/dur; yn = (y[0]-y)/drop
    h = tn < 0.5
    r1 = (y[h][0]-y[h][-1])/max(t[h][-1]-t[h][0], 1e-9)
    r2 = (y[~h][0]-y[~h][-1])/max(t[~h][-1]-t[~h][0], 1e-9)
    return np.interp(0.5, tn, yn), r1/max(r2, 1e-9)


def main():
    sets = gather()
    print('══ CR-DL 模型 ══\n')
    print(f"{'資料集':<16}{'循環':>5}{'實測曲率':>10}{'實測前後比':>11}")
    print('-'*46)
    for tag, f, d in sets:
        cs = [shape(t, y) for t, y in d]
        print(f'{tag:<16}{len(d):>5}'
              f'{np.mean([c[0] for c in cs]):>10.3f}'
              f'{np.mean([c[1] for c in cs]):>11.2f}')

    # ── 只用 4:1 擬合 ──────────────────────────────────────────
    train = [x for s in sets if s[0].startswith('4:1') for x in s[2]]
    print(f'\n══ 只用 4:1 擬合（{len(train)} 個循環，1:1 完全未使用）══')
    th = fit(train, 0.8)
    s, n = sse(th, train, 0.8)
    print(f'   k_La   = {th[0]:.4f} /hr')
    print(f'   p*_CO2 = {th[1]:.4f} kg/cm²')
    print(f'   v_max  = {th[2]:.5f} kg/cm²/hr')
    print(f'   K_H    = {th[3]:.4f} kg/cm²')
    print(f'   f_CH4,0= {th[4]:.3f}')
    print(f'   訓練 RMSE = {np.sqrt(s/n):.5f}')

    # ── 預測 1:1 ─────────────────────────────────────────────
    test = [s for s in sets if s[0].startswith('1:1')][0]
    s2, n2 = sse(th, test[2], test[1])
    print(f'\n══ 用同一組參數預測 1:1（只換進氣組成 f_H2: 0.8 -> 0.5）══')
    print(f'   預測 RMSE = {np.sqrt(s2/n2):.5f}   （n = {len(test[2])} 循環）')
    pm, pr = [], []
    for t, y in test[2]:
        m = simulate(t, y[0], test[1], *th)
        c = shape(t, m); pm.append(c[0]); pr.append(c[1])
    obs = [shape(t, y) for t, y in test[2]]
    print(f'   1:1 曲率     實測 {np.mean([c[0] for c in obs]):.3f}'
          f'   模型預測 {np.mean(pm):.3f}')
    print(f'   1:1 前後比   實測 {np.mean([c[1] for c in obs]):.2f}'
          f'   模型預測 {np.mean(pr):.2f}')

    # ── 對照：常數 rb 的舊模型能不能做到？──────────────────────
    print('\n══ 對照：舊模型（常數 r_b）同樣「只用 4:1 擬合、預測 1:1」══')

    def sse_old(th2, data):
        k, pe, rb = th2
        s, n = 0.0, 0
        for t, y in data:
            Pe = pe - rb/max(k, 1e-9)
            m = Pe + (y[0]-Pe)*np.exp(-k*t)
            s += float(np.sum((y-m)**2)); n += len(y)
        return s, n
    r = optimize.minimize(lambda q: sse_old(q, train)[0], [0.05, 0.6, 0.01],
                          method='Nelder-Mead',
                          bounds=[(1e-3, 1), (0, 0.95), (0, 0.05)],
                          options=dict(maxiter=20000))
    so, no = sse_old(r.x, train)
    so2, no2 = sse_old(r.x, test[2])
    print(f'   舊模型 訓練 RMSE = {np.sqrt(so/no):.5f}'
          f'   預測 1:1 RMSE = {np.sqrt(so2/no2):.5f}')
    pm2 = []
    for t, y in test[2]:
        Pe = r.x[1]-r.x[2]/max(r.x[0], 1e-9)
        m = Pe+(y[0]-Pe)*np.exp(-r.x[0]*t)
        pm2.append(shape(t, m)[0])
    print(f'   舊模型預測 1:1 曲率 = {np.mean(pm2):.3f}'
          f'   （實測 {np.mean([c[0] for c in obs]):.3f}）')
    print(f'\n   ★ CR-DL 預測 RMSE {np.sqrt(s2/n2):.5f}'
          f'  vs  舊模型 {np.sqrt(so2/no2):.5f}'
          f'   → {"CR-DL 較佳" if s2/n2 < so2/no2 else "舊模型較佳"}'
          f'（改善 {(1-np.sqrt(s2/n2)/np.sqrt(so2/no2))*100:+.0f}%）')

    with open(f'{OUT}/crdl_fit.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['param', 'value'])
        for nme, v in zip(['kLa', 'p_star', 'vmax', 'KH', 'fCH4_0'], th):
            w.writerow([nme, f'{v:.6f}'])
        w.writerow(['train_rmse', f'{np.sqrt(s/n):.6f}'])
        w.writerow(['predict_1to1_rmse', f'{np.sqrt(s2/n2):.6f}'])
        w.writerow(['old_predict_1to1_rmse', f'{np.sqrt(so2/no2):.6f}'])
    print(f'\n輸出 → {OUT}/crdl_fit.csv')


if __name__ == '__main__':
    main()
