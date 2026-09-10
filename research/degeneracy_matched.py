
# -*- coding: utf-8 -*-
"""
簡併判讀：配對基準（取代 rb_recovery_study 的通用合成基準）
════════════════════════════════════════════════════════════════════════

`rb_recovery_study.py` 用「實測 ρ(r̂_b,k̂)=0.829 vs 合成基準 0.383」判定簡併
未解除。**那個比較不合法**：0.383 來自一個通用合成母體
（k~log-uniform[0.01,2]、amp~uniform[0.05,0.45]），與真實資料的
(k, T, 幅度, 雜訊) 聯合分布不同。相關係數對邊際散布極度敏感，
不同母體的 ρ 不可互比。

**正確的基準**：沿用每個真實循環**自己的** (k̂, Â, P̂eq, T, 殘差 SD, φ)，
只把 r_b 換成常數，其餘照搬。這樣「設計」完全一致，
唯一的差別就是「真值有沒有隨 k 變」。

三個基準：
  B0  r_b ≡ 常數（＝實測中位）        ← 若 ρ 就到 0.83，實測的相關全是假影
  B1  r_b 隨機但**與 k 獨立**，散布比照實測  ← 更貼近「r_b 會變但不隨 k」
  B2  r_b 真的隨 k 線性上升，斜率由實測迴歸給 ← 若這個才配得上 0.83，就是真耦合

同時回答一個被忽略的問題：**聚合中位數本身回不回得來？**
逐循環的 ρ 高，不代表中位數有偏；R3 的回收表顯示偏誤僅 0–10 %。
本檔在**真實設計**（非通用母體）上直接驗證中位數的回收。

輸出 -> docs/analysis_charts_3batch/degeneracy_matched.csv
"""
import os
import sys
import csv

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from simulator_check import fit_LE, QUANT                          # noqa: E402
# ⚠ 2026-08-24 由 residual_structure.collect（全部 351 段，含重複副本與
#   條件不一致的批次）改為資料集 C。本檔的 B0/B1/B2 有被論文表 2 引用，
#   與其他結果必須跑在同一個集合上，否則同一張表會混用兩種資料。
from dataset_c import collect_c as collect                         # noqa: E402
from rb_recovery_study import curvature                            # noqa: E402

RNG = np.random.default_rng(112358)
CURV_MIN = 0.45
NREP = 25


def sp(a, b):
    ra = np.argsort(np.argsort(np.asarray(a, float))).astype(float)
    rb_ = np.argsort(np.argsort(np.asarray(b, float))).astype(float)
    return float(np.corrcoef(ra, rb_)[0, 1])


def ar1(n, sd, phi):
    e = RNG.normal(0, sd*np.sqrt(max(1-phi**2, 1e-6)), n)
    z = np.empty(n); z[0] = RNG.normal(0, sd)
    for i in range(1, n):
        z[i] = phi*z[i-1]+e[i]
    return z


def main():
    cyc = collect()
    print('══ 簡併判讀：配對基準 ══\n')

    # ── 逐循環擬合，並套曲率門檻 ────────────────────────
    fits = []
    for tag, t, y in cyc:
        cv = curvature(t, y)
        if not np.isfinite(cv) or cv < CURV_MIN:
            continue
        f = fit_LE(t, y)
        r = f['resid']
        phi = float(np.corrcoef(r[:-1], r[1:])[0, 1]) if r.std() > 0 else 0.
        fits.append(dict(t=t, k=f['k'], amp=f['amp'], peq=f['peq'],
                         rb=f['rb'], sd=max(f['sd'], QUANT/4),
                         phi=float(np.clip(phi*1.3, 0, 0.98))))
    rb_obs = np.array([f['rb'] for f in fits])
    k_obs = np.array([f['k'] for f in fits])
    rho_obs = sp(rb_obs, k_obs)
    R0 = float(np.median(rb_obs))
    print(f'   通過曲率門檻 {CURV_MIN} 的循環：{len(fits)}')
    print(f'   實測 r_b 中位 {R0:+.5f}   ρ(r̂_b, k̂) = {rho_obs:+.3f}')

    # 實測的 r_b~k 迴歸斜率（供 B2 用）
    A = np.vstack([np.log(k_obs), np.ones_like(k_obs)]).T
    slope, icpt = np.linalg.lstsq(A, rb_obs, rcond=None)[0]
    print(f'   實測 r_b 對 log k 的迴歸：斜率 {slope:+.5f}')

    # ── 三個配對基準 ────────────────────────────────────
    sd_rb = float(np.std(rb_obs, ddof=1))

    def run(mode):
        rhos, meds = [], []
        for _ in range(NREP):
            rr, kk = [], []
            for f in fits:
                if mode == 'B0':
                    rb_true = R0
                elif mode == 'B1':
                    rb_true = R0+RNG.normal(0, sd_rb)
                else:
                    rb_true = icpt+slope*np.log(f['k'])
                t = f['t']
                y = f['peq']+f['amp']*np.exp(-f['k']*t)-rb_true*t \
                    + ar1(len(t), f['sd'], f['phi'])
                g = fit_LE(t, np.round(y/QUANT)*QUANT)
                rr.append(g['rb']); kk.append(g['k'])
            rhos.append(sp(rr, kk)); meds.append(float(np.median(rr)))
        return np.array(rhos), np.array(meds)

    print(f'\n── 配對基準（沿用每個循環自己的 k̂, Â, T, 雜訊；'
          f'{NREP} 次重複）──')
    print(f'   {"基準":<34}{"ρ 平均":>10}{"±SD":>8}'
          f'{"vs 實測":>10}   判定')
    print('   '+'-'*66)
    labels = {'B0': 'B0  r_b ≡ 常數',
              'B1': 'B1  r_b 隨機但與 k 獨立',
              'B2': 'B2  r_b 隨 log k 上升（實測斜率）'}
    rows, res = [], {}
    for mode in ('B0', 'B1', 'B2'):
        rh, md = run(mode)
        res[mode] = (rh, md)
        d = rho_obs-rh.mean()
        ok = abs(d) < 2*max(rh.std(ddof=1), 0.01)
        print(f'   {labels[mode]:<34}{rh.mean():>10.3f}'
              f'{rh.std(ddof=1):>8.3f}{d:>+10.3f}   '
              f'{"✓ 相容" if ok else "✘ 不相容"}')
        rows.append([mode, f'{rh.mean():.4f}', f'{rh.std(ddof=1):.4f}',
                     f'{md.mean():.6f}'])

    # ── 聚合中位數的回收（真實設計下）──────────────────
    print(f'\n── 聚合中位數回不回得來？（在真實設計上）──')
    print(f'   {"基準":<34}{"投入真值中位":>14}{"回收中位":>12}{"偏誤":>9}')
    print('   '+'-'*68)
    truths = {'B0': R0, 'B1': R0,
              'B2': float(np.median(icpt+slope*np.log(k_obs)))}
    for mode in ('B0', 'B1', 'B2'):
        md = res[mode][1]
        bias = md.mean()/truths[mode]-1
        print(f'   {labels[mode]:<34}{truths[mode]:>14.5f}'
              f'{md.mean():>12.5f}{bias*100:>8.0f}%')

    print('\n══ 判定 ══')
    b0 = res['B0'][0].mean(); b2 = res['B2'][0].mean()
    if abs(rho_obs-b0) < abs(rho_obs-b2):
        print(f'   實測 ρ={rho_obs:+.3f} **較接近 B0（真值恆定）**')
        print('   ⇒ 逐循環的 r̂_b–k̂ 相關主要是估計假影，')
        print('     但這**不影響聚合中位數**（見上表偏誤）。')
    else:
        print(f'   實測 ρ={rho_obs:+.3f} **較接近 B2（真值隨 k 上升）**')
        print('   ⇒ 相關反映真實的 r_b–k 耦合（H2 傳質限制），不是簡併假影。')
    print('   ⚠ 無論哪一種，判讀的關鍵都是**聚合中位數的偏誤**，')
    print('     不是逐循環的 ρ——先前用裸 ρ 下結論是錯的。')

    with open(f'{OUT}/degeneracy_matched.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['baseline', 'rho_mean', 'rho_sd', 'recovered_median'])
        w.writerows(rows)
        w.writerow([]); w.writerow(['rho_observed', f'{rho_obs:.4f}'])
        w.writerow(['rb_observed_median', f'{R0:.6f}'])
        w.writerow(['n_cycles', len(fits)])
    print(f'\n輸出 → {OUT}/degeneracy_matched.csv')


if __name__ == '__main__':
    main()
