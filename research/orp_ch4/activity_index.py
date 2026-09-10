
# -*- coding: utf-8 -*-
"""
菌群活躍度指標：把 ORP 縮回可跨批次比較的固定量
════════════════════════════════════════════════════════════════════════

**問題**：ORP 的絕對值在不同批次差很多（368–761 mV vs 0–268 mV）。
那是電極校準與參考電極漂移，是合理的，但讓跨批次比較失去意義。

**解法**：定義一個**尺度自由**的活躍度指標。

    A = (dORP/dt) / (dP/dt)          單位 mV per kg/cm²

  · 用 **dORP** 而非 ORP ⇒ 電極偏移自動消掉
  · 除以 **dP/dt** ⇒ 消掉「這個循環走得快或慢」
  · 物理意義：**每移除一單位氣體，氧化還原電位變動多少**

  物理通道（CO2 溶解）**不消耗 H2** ⇒ 對 ORP 無貢獻 ⇒ A ≈ 0
  生物通道（CO2 + 4H2 → CH4）消耗 H2 ⇒ A ≠ 0
  ⇒ **A 是生物份額的尺度自由代理**

再對每個批次做穩健正規化（除以該批次 |A| 的中位數），得到 Â，
使不同電極的靈敏度也一併縮掉。

檢定（這是判別 A 到底測到什麼的關鍵）：
  D1  A 對**只改物理**的操作（循環工作比 τ，只改 k_La）應**不敏感**
  D2  A 對**改生物基質**的操作（進氣 H2 分率 4:1 vs 1:1）應**敏感**
  D3  預測：用 A 預測同批次下一個循環的下降速率，與不用 A 比較

⚠ 欄位：ORP=欄7、pH=欄9、反應器壓力=欄11（見 multivariate_increments 的註）

輸出 -> docs/analysis_charts_3batch/activity_index.csv
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
from math import erfc, sqrt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from regime_changepoints import TD                                 # noqa: E402
from multivariate_increments import load4, seg, wrate, cond_of     # noqa: E402

# 進氣 H2 莫耳分率：這是**生物**的基質可得性
FH2 = {'1:1': 0.5}
DEFAULT_FH2 = 0.8


def welch(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3 or len(b) < 3:
        return np.nan, np.nan
    va, vb = a.var(ddof=1)/len(a), b.var(ddof=1)/len(b)
    if va+vb <= 0:
        return np.nan, np.nan
    t = (a.mean()-b.mean())/sqrt(va+vb)
    return t, erfc(abs(t)/sqrt(2))


def gather():
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
    seen, rec = {}, []
    for path, tag in folders:
        try:
            raw = load4(path)
        except Exception:
            continue
        if len(raw) < 2000:
            continue
        ts = [r[0] for r in raw]
        P = np.array([r[1] for r in raw]); O = np.array([r[2] for r in raw])
        H = np.array([r[3] for r in raw])
        h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
        for a, b in seg(h, P):
            key = (ts[a].replace(second=0), round(h[b]-h[a], 1))
            if key in seen:
                continue
            seen[key] = 1
            c, _ = cond_of(tag, ts[a].date())
            if c == 'other':
                continue
            t = h[a:b+1]-h[a]
            dP = wrate(t, P[a:b+1]); dO = wrate(t, O[a:b+1])
            dH = wrate(t, H[a:b+1])
            if not all(np.isfinite(v) for v in (dP, dO, dH)) or abs(dP) < 1e-4:
                continue
            rec.append(dict(t=ts[a], cond=c, batch=tag,
                            fH2=FH2.get(c, DEFAULT_FH2),
                            dP=dP, dORP=dO, dpH=dH,
                            A=dO/dP,                     # 尺度自由指標
                            rate=(P[a]-P[b])/(h[b]-h[a])))
    rec.sort(key=lambda r: r['t'])
    return rec


def main():
    rec = gather()
    print('══ 菌群活躍度指標 A = (dORP/dt)/(dP/dt) ══\n')
    print(f'   循環 {len(rec)} 個')

    # ── 批次內穩健正規化，縮掉電極靈敏度 ──────────────────
    for b in {r['batch'] for r in rec}:
        sub = [r for r in rec if r['batch'] == b]
        s = np.median([abs(r['A']) for r in sub])
        for r in sub:
            r['Ahat'] = r['A']/s if s > 0 else np.nan
    rec = [r for r in rec if np.isfinite(r.get('Ahat', np.nan))]

    conds = sorted({r['cond'] for r in rec})
    print(f'\n   {"條件":<10}{"n":>4}{"f_H2":>7}{"A 中位":>12}'
          f'{"Â 中位":>10}{"Â IQR":>20}')
    print('   '+'-'*64)
    for c in conds:
        s = [r for r in rec if r['cond'] == c]
        A = np.array([r['A'] for r in s]); Ah = np.array([r['Ahat'] for r in s])
        q = np.quantile(Ah, [.25, .75])
        print(f'   {c:<10}{len(s):>4}{s[0]["fH2"]:>7.1f}{np.median(A):>12.1f}'
              f'{np.median(Ah):>10.2f}{f"[{q[0]:.2f}, {q[1]:.2f}]":>20}')

    # ── D1 對 τ（只改物理）應不敏感 ─────────────────────
    print('\n── D1  A 對循環工作比 τ 的敏感度（τ 只改 k_La，是物理）──')
    taus = [c for c in ('pump_off', 'tau1', 'tau5', 'tau10') if c in conds]
    print(f'   {"條件 A":<10}{"條件 B":<10}{"Â 差":>9}{"t":>8}{"p":>9}')
    print('   '+'-'*46)
    nsig_tau = 0
    for i in range(len(taus)):
        for j in range(i+1, len(taus)):
            a = [r['Ahat'] for r in rec if r['cond'] == taus[i]]
            b = [r['Ahat'] for r in rec if r['cond'] == taus[j]]
            t, p = welch(a, b)
            sig = '  ✓顯著' if (np.isfinite(p) and p < 0.05) else ''
            nsig_tau += int(np.isfinite(p) and p < 0.05)
            print(f'   {taus[i]:<10}{taus[j]:<10}'
                  f'{np.mean(a)-np.mean(b):>9.2f}{t:>8.2f}{p:>9.3f}{sig}')
    npair = len(taus)*(len(taus)-1)//2
    print(f'   → {nsig_tau}/{npair} 對顯著'
          f'   {"（A 受物理影響，指標不純）" if nsig_tau > npair/2 else "（A 大致不受物理影響 ✓）"}')

    # ── D2 對進氣 H2 分率（改生物基質）應敏感 ──────────────
    print('\n── D2  A 對進氣 H2 分率的敏感度（改基質，是生物）──')
    if '1:1' in conds:
        a = [r['Ahat'] for r in rec if r['fH2'] == 0.5]
        b = [r['Ahat'] for r in rec if r['fH2'] == 0.8]
        t, p = welch(a, b)
        print(f'   f_H2 = 0.5  n={len(a):>3}  Â 中位 {np.median(a):+.2f}')
        print(f'   f_H2 = 0.8  n={len(b):>3}  Â 中位 {np.median(b):+.2f}')
        print(f'   Welch t = {t:+.2f}   p = {p:.4f}'
              f'   {"✓ 顯著" if p < 0.05 else "✘ 不顯著"}')
    else:
        print('   ✘ 無 1:1 資料')

    # ── D3 預測：A 能否改善下一循環速率的預測？ ────────────
    print('\n── D3  預測同批次下一個循環的下降速率 ──')
    print('   基準：只用當前循環的速率；比較：再加上 Â')
    X0, X1, Y = [], [], []
    for i in range(len(rec)-1):
        a, b = rec[i], rec[i+1]
        if a['batch'] != b['batch']:
            continue
        if (b['t']-a['t']).total_seconds()/3600 > 72:
            continue
        X0.append([a['rate'], 1.0])
        X1.append([a['rate'], a['Ahat'], 1.0])
        Y.append(b['rate'])
    X0, X1, Y = np.array(X0), np.array(X1), np.array(Y)
    print(f'   相鄰循環對 n = {len(Y)}')
    if len(Y) >= 15:
        def loo(X, y):
            e = []
            for i in range(len(y)):
                m = np.ones(len(y), bool); m[i] = False
                c, *_ = np.linalg.lstsq(X[m], y[m], rcond=None)
                e.append((X[i] @ c-y[i])**2)
            return np.sqrt(np.mean(e))
        r0, r1 = loo(X0, Y), loo(X1, Y)
        print(f'   基準（只用速率）      留一 RMSE = {r0:.5f}')
        print(f'   加上活躍度指標 Â      留一 RMSE = {r1:.5f}')
        print(f'   → 改善 {(r0-r1)/r0*100:+.1f}%'
              f'   {"✓ Â 帶來預測資訊" if r1 < r0 else "✘ Â 沒有幫助"}')
    else:
        print('   樣本不足')

    with open(f'{OUT}/activity_index.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['time', 'batch', 'cond', 'f_H2', 'dP_dt', 'dORP_dt',
                    'dpH_dt', 'A', 'A_hat', 'cycle_rate'])
        for r in rec:
            w.writerow([r['t'].strftime('%Y-%m-%d %H:%M'), r['batch'],
                        r['cond'], r['fH2'], f'{r["dP"]:.5f}',
                        f'{r["dORP"]:.3f}', f'{r["dpH"]:.5f}',
                        f'{r["A"]:.2f}', f'{r["Ahat"]:.3f}',
                        f'{r["rate"]:.5f}'])
    print(f'\n輸出 → {OUT}/activity_index.csv')


if __name__ == '__main__':
    main()
