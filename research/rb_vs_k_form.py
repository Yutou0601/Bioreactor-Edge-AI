
# -*- coding: utf-8 -*-
"""
r_b(k) 的函數形式：飽和？線性？還是根本分不出來？
════════════════════════════════════════════════════════════════════════

`degeneracy_matched.py` 確立兩件事：
  · 聚合 r_b 中位數在真實設計下**無偏**（B0 偏誤 0 %）
  · 實測 ρ(r̂_b,k̂)=0.831 排除「r_b 恆定」(0.268) 與「與 k 獨立」(0.143)
    ⇒ **真值確實隨 k 變**

但**斜率還不能宣稱**：先前的 log 線性是直接對 (r̂_b, log k̂) 迴歸得到的，
而 B0 證明「真值恆定時 ρ 就有 0.268」——**估計誤差本身就會造出正斜率**。
直接迴歸必然高估。而且那條線在實測 k 上解出負 r_b，物理不可能。

**解法：間接推論（indirect inference）。**
不對 (r̂_b, k̂) 迴歸，而是把候選形式當**真值**餵進模擬器，
走**完全相同的管線**（同樣的 t、雜訊、AR(1)、量化、曲率篩選、逐循環擬合），
再比對「k̂ 分層的 r̂_b 中位數」這個摘要統計量。
估計假影同時出現在模擬與實測兩邊，因此被抵消。

  候選形式   C  r_b = r0                      （恆定）
             L  r_b = a + b·k                 （線性）
             S  r_b = rmax·k/(K+k)            （飽和＝H2 傳質限制）

**兩道防線**：
  · **切半**：參數只在 A 半校準，形式比較只在 B 半評分
  · **形式回收研究**：先用已知形式產生資料，看整套程序挑不挑得回來。
    **挑不回來就代表這個雜訊下三種形式不可分辨，結論只能是「分不出」。**

輸出 -> docs/analysis_charts_3batch/rb_vs_k_form.csv
"""
import os
import sys
import csv

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from simulator_check import QUANT                                  # noqa: E402
from residual_structure import collect                             # noqa: E402
from rb_recovery_study import curvature                            # noqa: E402

RNG = np.random.default_rng(271828)
KGRID = np.arange(0.01, 3.001, 0.02)
CURV_MIN = 0.45
NBIN = 5


# ── 向量化的 LE 擬合 ────────────────────────────────────
# ⚠ 逐 k 呼叫 lstsq（SVD）在這個規模下跑不完：160 次全資料集模擬 ×
#   301 循環 × 150 個 k。改成一次算完所有 k 的正規方程（3×3），快兩個量級。
def fit_LE_fast(t, y):
    E = np.exp(-KGRID[:, None]*t[None, :])          # (K, n)
    n = len(t)
    st, stt = t.sum(), float(t @ t)
    G = np.empty((len(KGRID), 3, 3))
    G[:, 0, 0] = (E*E).sum(1)
    G[:, 0, 1] = G[:, 1, 0] = E @ t
    G[:, 0, 2] = G[:, 2, 0] = E.sum(1)
    G[:, 1, 1] = stt
    G[:, 1, 2] = G[:, 2, 1] = st
    G[:, 2, 2] = n
    b = np.empty((len(KGRID), 3))
    b[:, 0] = E @ y
    b[:, 1] = float(t @ y)
    b[:, 2] = y.sum()
    G[:, 0, 0] += 1e-12
    try:
        # b 要給成 (K,3,1)，否則 numpy 會把它當成單一 (m,n) 矩陣解讀
        c = np.linalg.solve(G, b[:, :, None])[:, :, 0]
    except np.linalg.LinAlgError:
        return None
    sse = float(y @ y)-np.einsum('ij,ij->i', c, b)
    j = int(np.argmin(sse))
    return dict(amp=c[j, 0], rb=-c[j, 1], peq=c[j, 2], k=KGRID[j],
                sd=np.sqrt(max(sse[j], 0)/max(n-4, 1)))


def ar1(n, sd, phi):
    e = RNG.normal(0, sd*np.sqrt(max(1-phi**2, 1e-6)), n)
    z = np.empty(n); z[0] = RNG.normal(0, sd)
    for i in range(1, n):
        z[i] = phi*z[i-1]+e[i]
    return z


def rb_of(form, p, k):
    if form == 'C':
        return p[0]
    if form == 'L':
        return p[0]+p[1]*k
    return p[0]*k/(p[1]+k)                          # S


def summary(rbs, ks, edges):
    """k̂ 分層的 r̂_b 中位數——比對用的摘要統計量。"""
    rbs, ks = np.asarray(rbs), np.asarray(ks)
    out = []
    for i in range(len(edges)-1):
        m = (ks >= edges[i]) & (ks < edges[i+1])
        out.append(np.median(rbs[m]) if m.sum() >= 3 else np.nan)
    return np.array(out)


def simulate_set(fits, form, p, edges):
    rr, kk = [], []
    for f in fits:
        t = f['t']
        y = f['peq']+f['amp']*np.exp(-f['k']*t)-rb_of(form, p, f['k'])*t \
            + ar1(len(t), f['sd'], f['phi'])
        y = np.round(y/QUANT)*QUANT
        if curvature(t, y) < CURV_MIN:
            continue
        g = fit_LE_fast(t, y)
        if g:
            rr.append(g['rb']); kk.append(g['k'])
    if len(rr) < 3*NBIN:
        return None
    return summary(rr, kk, edges)


def discrep(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 3:
        return np.inf
    return float(np.mean(((a[m]-b[m])/max(np.std(b[m]), 1e-6))**2))


def calibrate(fits, target, edges, nrep=2):
    """在給定資料上，為三種形式各找最佳參數。"""
    R0 = float(np.nanmedian(target))
    grids = {
        'C': [(r,) for r in np.linspace(0.4*R0, 1.8*R0, 8)],
        'L': [(a, b) for a in np.linspace(0.0, 1.4*R0, 6)
              for b in np.linspace(0.0, 0.10, 6)],
        'S': [(rm, K) for rm in np.linspace(0.8*R0, 4.0*R0, 6)
              for K in np.linspace(0.02, 1.20, 6)],
    }
    best = {}
    for form, grid in grids.items():
        bp, bd = None, np.inf
        for p in grid:
            ds = []
            for _ in range(nrep):
                s = simulate_set(fits, form, p, edges)
                if s is not None:
                    ds.append(discrep(s, target))
            if ds and np.mean(ds) < bd:
                bd, bp = float(np.mean(ds)), p
        best[form] = (bp, bd)
    return best


def score(fits, target, edges, best, nrep=5):
    """在**沒看過的**半邊上評分。"""
    out = {}
    for form, (p, _) in best.items():
        if p is None:
            out[form] = np.inf; continue
        ds = [discrep(s, target) for s in
              (simulate_set(fits, form, p, edges) for _ in range(nrep))
              if s is not None]
        out[form] = float(np.mean(ds)) if ds else np.inf
    return out


def prep(cycles):
    fits = []
    for tag, t, y in cycles:
        cv = curvature(t, y)
        if not np.isfinite(cv) or cv < CURV_MIN:
            continue
        f = fit_LE_fast(t, y)
        if not f:
            continue
        E = np.exp(-f['k']*t)
        res = y-(f['peq']+f['amp']*E-f['rb']*t)
        phi = float(np.corrcoef(res[:-1], res[1:])[0, 1]) \
            if res.std() > 0 else 0.
        fits.append(dict(t=t, k=f['k'], amp=f['amp'], peq=f['peq'],
                         rb=f['rb'], sd=max(f['sd'], QUANT/4),
                         phi=float(np.clip(phi*1.3, 0, 0.98))))
    return fits


def main():
    fits = prep(collect())
    ks = np.array([f['k'] for f in fits])
    rbs = np.array([f['rb'] for f in fits])
    edges = np.quantile(ks, np.linspace(0, 1, NBIN+1))
    edges[-1] *= 1.001
    print('══ r_b(k) 的函數形式 ══\n')
    print(f'   循環 {len(fits)}   r_b 中位 {np.median(rbs):+.5f}'
          f'   k 中位 {np.median(ks):.3f}')

    obs = summary(rbs, ks, edges)
    print(f'\n── 實測：k̂ 分層的 r̂_b 中位數 ──')
    for i in range(NBIN):
        print(f'   k ∈ [{edges[i]:.3f}, {edges[i+1]:.3f})'
              f'   r̂_b 中位 {obs[i]:+.5f}')

    idx = RNG.permutation(len(fits))
    A = [fits[i] for i in idx[:len(fits)//2]]
    B = [fits[i] for i in idx[len(fits)//2:]]
    tA = summary([f['rb'] for f in A], [f['k'] for f in A], edges)
    tB = summary([f['rb'] for f in B], [f['k'] for f in B], edges)
    print(f'\n   切半：校準 {len(A)} / 評分 {len(B)}')

    # ── 形式回收研究（先做，決定結論說不說得出口）──────
    print('\n── 形式回收研究：已知形式挑不挑得回來？──')
    R0 = float(np.median(rbs))
    # 三個真值都設成「在 k 中位處給出約 R0」，否則不同列的訊噪比不可比。
    truth = {'C': (R0,), 'L': (0.36*R0, 0.05), 'S': (2.2*R0, 0.25)}
    print(f'   {"投入形式":<10}{"C 分數":>10}{"L 分數":>10}{"S 分數":>10}'
          f'{"挑中":>7}   判定')
    print('   '+'-'*52)
    recov, conf = {}, {}
    for tf, tp in truth.items():
        syn = []
        for f in A+B:
            t = f['t']
            y = f['peq']+f['amp']*np.exp(-f['k']*t) \
                - rb_of(tf, tp, f['k'])*t+ar1(len(t), f['sd'], f['phi'])
            syn.append(('syn', t, np.round(y/QUANT)*QUANT))
        sf = prep(syn)
        if len(sf) < 40:
            print(f'   {tf:<10}   樣本不足'); continue
        sA, sB = sf[:len(sf)//2], sf[len(sf)//2:]
        stA = summary([f['rb'] for f in sA], [f['k'] for f in sA], edges)
        stB = summary([f['rb'] for f in sB], [f['k'] for f in sB], edges)
        bst = calibrate(sA, stA, edges)
        sc = score(sB, stB, edges, bst)
        pick = min(sc, key=sc.get)
        recov[tf] = pick; conf[tf] = sc
        print(f'   {tf:<10}{sc.get("C",np.inf):>10.3f}'
              f'{sc.get("L",np.inf):>10.3f}{sc.get("S",np.inf):>10.3f}'
              f'{pick:>7}   {"✓ 對" if pick == tf else "✘ 錯"}')

    can_tell = all(recov.get(k) == k for k in truth)
    print(f'\n   → {"✓ 形式可分辨，下面的比較有意義" if can_tell else "✘ **形式不可分辨**——下面的比較不可當結論"}')

    # ── 實測資料上的形式比較 ────────────────────────────
    print('\n── 實測資料：切半後的形式比較 ──')
    best = calibrate(A, tA, edges)
    sc = score(B, tB, edges, best)
    print(f'   {"形式":<28}{"校準參數":>26}{"B 半分數":>11}')
    print('   '+'-'*66)
    names = {'C': 'C  r_b = r0（恆定）',
             'L': 'L  r_b = a + b·k（線性）',
             'S': 'S  r_b = rmax·k/(K+k)（飽和）'}
    rows = []
    for form in ('C', 'L', 'S'):
        p = best[form][0]
        ps = '—' if p is None else '  '.join(f'{v:.4f}' for v in p)
        print(f'   {names[form]:<28}{ps:>26}{sc[form]:>11.3f}')
        rows.append([form, ps, f'{sc[form]:.4f}'])
    win = min(sc, key=sc.get)

    print('\n══ 判定 ══')
    if not can_tell:
        print('   ✘ **形式不可分辨**：連已知真值都挑不回來。')
        print('     ⇒ 只能報告 r_b 的聚合中位數，**不可宣稱 r_b(k) 的形式**。')
    else:
        srt = sorted(sc.items(), key=lambda x: x[1])
        gap = srt[1][1]-srt[0][1]
        print(f'   勝出：**{names[win]}**   分數 {sc[win]:.3f}'
              f'（次佳 {srt[1][0]} 差 {gap:.3f}）')
        if gap < 0.3*max(srt[1][1], 1e-9):
            print('   ⚠ 與次佳差距 < 30 %，**不足以宣稱形式**。')
        elif win == 'S':
            print('   ⇒ 飽和形式勝出，與 H2 傳質限制的物理預期一致。')
            print(f'     r_max = {best["S"][0][0]:.5f}   K = {best["S"][0][1]:.3f}')

    with open(f'{OUT}/rb_vs_k_form.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['form', 'params', 'heldout_score'])
        w.writerows(rows)
        w.writerow([])
        w.writerow(['recovery_truth', 'score_C', 'score_L', 'score_S',
                    'picked'])
        for tf, sc_ in conf.items():
            w.writerow([tf] + [f'{sc_.get(f, float("inf")):.4f}'
                               for f in ('C', 'L', 'S')] + [recov.get(tf)])
        w.writerow([]); w.writerow(['forms_distinguishable', can_tell])
        w.writerow(['winner', win])
        w.writerow(['rb_median', f'{R0:.6f}'])
    print(f'\n輸出 → {OUT}/rb_vs_k_form.csv')


if __name__ == '__main__':
    main()
