
# -*- coding: utf-8 -*-
"""r_b(k) 的兩階段逼近：小問題的解鎖住大模型的搜尋空間
════════════════════════════════════════════════════════════════════════

**問題**（由 `rb_vs_k_nsga2.py` 的結果指出）：同一批資料，
拆成小問題解得出來，合成大模型就解不出來。

  逐區間逼近   4 個**獨立**純量，各約 60 循環、只比對 1 個統計量 → 區間不重疊
  全曲線 NSGA-II  5 個**耦合**節點、同時餵 4 個目標          → 前緣寬 89–437 %

前緣寬的來源是**節點間的互相補償**：某節點抬高、鄰居壓低，可維持同樣的
摘要統計量。自由度沒被鎖住，最佳化器就在等價的曲線族裡漂。

**解法（使用者提出）：用小問題的解去解大模型。**

  第一階段  逐區間反解 → 4 個彼此獨立、各帶信賴區間的錨點
  第二階段  NSGA-II **只在錨點的信賴區間內**搜尋
            → 補償空間被鎖住，且能同時滿足 ρ、正值比例、IQR
              這三個逐區間法用不到的統計量

全程未承諾任何函數形式：錨點由資料反解而來，NSGA-II 只負責在錨點之間
插值並讓分布層級的統計量也對上。

輸出 -> docs/analysis_charts_3batch/rb_vs_k_twostage.csv
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
from rb_vs_k_form import prep, summary, NBIN                       # noqa: E402
from residual_structure import collect                             # noqa: E402
from rb_vs_k_nsga2 import (make_evaluator, nds, crowding,          # noqa: E402
                           spearman, K_MIN)

RNG = np.random.default_rng(31415926)
POP, GEN = 24, 18
PAD = 1.6                     # 錨點信賴區間放寬倍率（留給插值誤差）


def read_anchors():
    """讀第一階段（逐區間反解）的錨點與信賴區間。"""
    ks, lo, hi = [], [], []
    with open(f'{OUT}/rb_vs_k_pointwise.csv', encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            if not r.get('k_bin') or r['calibrated_rb'] in ('n/a', ''):
                continue
            a, _, b = r['k_bin'].partition('-')
            ks.append(np.sqrt(float(a)*float(b)))      # 幾何中心
            lo.append(float(r['ci_lo'])); hi.append(float(r['ci_hi']))
    return np.array(ks), np.array(lo), np.array(hi)


def evolve_bounded(evaluate, lo, hi, pop=POP, gen=GEN):
    n = len(lo)
    X = RNG.uniform(lo, hi, (pop, n))
    F = np.array([evaluate(x) for x in X])
    for g in range(gen):
        r = nds(F); c = crowding(F)
        idx = []
        for _ in range(pop):
            a, b = RNG.integers(pop, size=2)
            idx.append(a if (r[a], -c[a]) < (r[b], -c[b]) else b)
        P = X[idx]; Q = P.copy()
        for i in range(0, pop-1, 2):
            if RNG.random() < 0.9:
                u = RNG.random(n)
                be = np.where(u <= .5, (2*u)**(1/16), (1/(2*(1-u)))**(1/16))
                Q[i] = .5*((1+be)*P[i]+(1-be)*P[i+1])
                Q[i+1] = .5*((1-be)*P[i]+(1+be)*P[i+1])
        mut = RNG.random((pop, n)) < 1.0/n
        Q = np.where(mut, Q+RNG.normal(0, (hi-lo)*0.20, (pop, n)), Q)
        Q = np.clip(Q, lo, hi)                    # ← 錨點區間為硬約束
        FQ = np.array([evaluate(x) for x in Q])
        XA = np.vstack([X, Q]); FA = np.vstack([F, FQ])
        rA = nds(FA); cA = crowding(FA)
        o = sorted(range(len(XA)), key=lambda i: (rA[i], -cA[i]))
        X, F = XA[o[:pop]], FA[o[:pop]]
        print(f'      世代 {g+1:2d}/{gen}   前緣 {int((nds(F)==0).sum()):2d}'
              f'   最佳各目標 {np.min(F,axis=0).round(3)}')
    return X, F


def main():
    kn, lo, hi = read_anchors()
    # 放寬信賴區間：錨點是**分層**的估計，曲線在節點上不必精確等於它
    mid = (lo+hi)/2
    lo2, hi2 = mid-(mid-lo)*PAD, mid+(hi-mid)*PAD

    fits = [f for f in prep(collect()) if f['k'] >= K_MIN]
    ks = np.array([f['k'] for f in fits])
    rbs = np.array([f['rb'] for f in fits])
    edges = np.quantile(ks, np.linspace(0, 1, NBIN+1)); edges[-1] *= 1.001
    q = np.quantile(rbs, [.25, .75])
    obs = dict(med=summary(rbs, ks, edges), rho=spearman(rbs, ks),
               pos=float(np.mean(rbs > 0)), iqr=float(q[1]-q[0]),
               sc=float(np.nanstd(summary(rbs, ks, edges))))

    print('══ r_b(k) 兩階段逼近 ══\n')
    print(f'   循環 {len(fits)}（已排除 k < {K_MIN} 的簡併廢區）')
    print(f'\n── 第一階段：逐區間反解得到的錨點 ──')
    print(f'   {"k（幾何中心）":>14}{"錨點":>11}{"95% 區間":>22}'
          f'{"放寬後搜尋範圍":>24}')
    print('   '+'-'*70)
    for i in range(len(kn)):
        print(f'   {kn[i]:>14.3f}{mid[i]:>11.5f}'
              f'{f"[{lo[i]:+.4f}, {hi[i]:+.4f}]":>22}'
              f'{f"[{lo2[i]:+.4f}, {hi2[i]:+.4f}]":>24}')

    print(f'\n── 第二階段：NSGA-II 在錨點區間內搜尋 ──')
    print(f'   族群 {POP} × 世代 {GEN}   目標：分層中位數、ρ、正值比例、IQR')
    ev = make_evaluator(fits, edges, kn, obs)
    X, F = evolve_bounded(ev, lo2, hi2)

    front = X[nds(F) == 0]
    print(f'\n── 結果：Pareto 前緣（{len(front)} 條曲線）──')
    print(f'   {"k":>9}{"中位":>11}{"前緣最小":>11}{"前緣最大":>11}'
          f'{"前緣寬度":>11}{"vs 第一階段":>13}')
    print('   '+'-'*66)
    rows = []
    for i, k in enumerate(kn):
        v = front[:, i]
        w1 = hi[i]-lo[i]                     # 第一階段的區間寬
        w2 = v.max()-v.min()                 # 第二階段的前緣寬
        print(f'   {k:>9.3f}{np.median(v):>11.5f}{v.min():>11.5f}'
              f'{v.max():>11.5f}{w2:>11.5f}{w2/w1*100:>12.0f}%')
        rows.append([f'{k:.4f}', f'{np.median(v):.6f}', f'{v.min():.6f}',
                     f'{v.max():.6f}', f'{w1:.6f}'])

    med = np.median(front, axis=0)
    mono = np.all(np.diff(med) > -1e-4)
    widths = np.array([front[:, i].max()-front[:, i].min()
                       for i in range(len(kn))])
    w1s = hi-lo
    print(f'\n── 判定 ──')
    print(f'   前緣中位曲線  ' + '  '.join(f'{v:+.4f}' for v in med))
    print(f'   單調遞增      {"✓ 是" if mono else "✘ 否"}（未強制）')
    print(f'   兩端比值      {med.max()/max(med.min(),1e-9):.2f} 倍')
    shrink = float(np.median(widths/w1s))
    print(f'   前緣寬度 / 第一階段區間寬  中位 {shrink*100:.0f} %')
    ok = shrink < 1.0
    print(f'   → {"✓ 加入 ρ／正值比例／IQR 後，曲線比單看中位數更被定住"if ok else "✘ 多目標未進一步收窄，錨點已是資料的極限"}')

    with open(f'{OUT}/rb_vs_k_twostage.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['k', 'rb_median', 'front_min', 'front_max',
                    'stage1_ci_width'])
        w.writerows(rows)
        w.writerow([]); w.writerow(['front_size', len(front)])
        w.writerow(['monotone', bool(mono)])
        w.writerow(['width_ratio_median', f'{shrink:.4f}'])
    print(f'\n輸出 → {OUT}/rb_vs_k_twostage.csv')


if __name__ == '__main__':
    main()
