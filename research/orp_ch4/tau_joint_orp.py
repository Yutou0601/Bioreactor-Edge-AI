
# -*- coding: utf-8 -*-
"""
τ 系列的完整聯合估計：用 ORP 打破壓力單通道的簡併
════════════════════════════════════════════════════════════════════════

**先前十五次失敗的共同癥結**：只有壓力一個通道，物理項與生物項在任何
單一條件下都共線；加了條件（τ 或組成）仍然是「每加一個條件就多一個
未知數」，自由度永遠不夠。

**ORP 補上的正是缺的那一個方程式。**

模型（同一批、同一液體、同樣 4:1、相隔數天）：

    dP/dt    = −k_La(τ)·(f_CO2·P − p*)  −  r_b(τ)
    dORP/dt  = −c · r_b(τ)                       c 未知但三條件共用

自由度：
    未知  k_La₁, k_La₅, k_La₁₀, p*, r_b₁, r_b₅, r_b₁₀, c        = 8
    觀測  3 個壓力斜率 → 直接給 3 個 k_La                        ✓
          3 個壓力截距 = k_La·p* − r_b       （4 未知，差 1）
          3 個 ORP 速率 = −c·r_b             （4 未知，差 1）
          合併 6 式 5 未知 ⇒ **超定 1 個**

解法：ORP 給比例 ρ_i = r_b_i / r_b_1（c 自動消掉）；
      代入截距式後只剩 (p*, r_b_1) 兩個未知數、三條方程 ⇒ 最小平方 + 一致性檢查。

⚠ ORP 讀取一律經 multivariate_increments.load4（已含 ORP_SIGN = −1）。

輸出 -> docs/analysis_charts_3batch/tau_joint_orp.csv
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

F_CO2 = 0.2                        # τ 系列全程 4:1，已知不是待估
PORD = 6
NBOOT = 4000

TAU = [('tau1', 1, dt.date(2026, 7, 22), dt.date(2026, 7, 27)),
       ('tau5', 5, dt.date(2026, 7, 27), dt.date(2026, 7, 30)),
       ('tau10', 10, dt.date(2026, 7, 30), dt.date(2026, 8, 4))]


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


def gather():
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
    out = {k: {'pairs': [], 'dorp': []} for k, _, _, _ in TAU}
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
            lab = next((k for k, _, s, e in TAU if s <= d < e), None)
            if lab is None:
                continue
            key = (ts[a].replace(second=0), round(h[b]-h[a], 1))
            if key in seen:
                continue
            seen[key] = 1
            t = h[a:b+1]-h[a]
            half = t <= t[-1]/2                 # 前半，遠離平衡
            if half.sum() < 20:
                continue
            out[lab]['pairs'].extend(weak_pairs(t[half], P[a:b+1][half]))
            r = wrate(t, O[a:b+1])
            if np.isfinite(r):
                out[lab]['dorp'].append(r)
    return out


def line_fit(pairs):
    """rate = s·(f·P) + i → 斜率 s 對應 −k_La（因 x 已乘 f_CO2）。"""
    x = np.array([F_CO2*p[0] for p in pairs])
    y = np.array([p[1] for p in pairs])
    A = np.vstack([x, np.ones_like(x)]).T
    c, *_ = np.linalg.lstsq(A, y, rcond=None)
    res = y-A@c
    dof = max(len(x)-2, 1)
    cov = (res @ res/dof)*np.linalg.inv(A.T@A)
    return c[0], c[1], np.sqrt(np.diag(cov)), len(x)


def solve(kla, inter, rho, w):
    """intercept_i = k_i·p* − rb1·rho_i  → 對 (p*, rb1) 最小平方。"""
    A = np.vstack([kla, -np.asarray(rho)]).T
    Aw = A*w[:, None]; yw = np.asarray(inter)*w
    sol, *_ = np.linalg.lstsq(Aw, yw, rcond=None)
    return sol[0], sol[1], A@sol-np.asarray(inter)


def main():
    D = gather()
    labs = [k for k, _, _, _ in TAU if len(D[k]['pairs']) >= 10
            and len(D[k]['dorp']) >= 3]
    print('══ τ 系列聯合估計（壓力 + ORP）══\n')
    if len(labs) < 3:
        print(f'   ✘ 只有 {len(labs)} 個條件有足夠資料'); return

    print(f'   {"條件":<8}{"n(配對)":>9}{"n(ORP)":>8}{"k_La":>10}'
          f'{"截距":>11}{"截距 SE":>11}{"dORP/dt 中位":>14}')
    print('   '+'-'*64)
    kla, inter, ise, dorp, dse = [], [], [], [], []
    for lab in labs:
        s, i, se, n = line_fit(D[lab]['pairs'])
        o = np.array(D[lab]['dorp'])
        kla.append(-s); inter.append(i); ise.append(se[1])
        dorp.append(np.median(o))
        dse.append(1.253*o.std(ddof=1)/np.sqrt(len(o)))
        print(f'   {lab:<8}{n:>9}{len(o):>8}{-s:>10.4f}{i:>11.5f}'
              f'{se[1]:>11.5f}{np.median(o):>14.2f}')

    kla = np.array(kla); inter = np.array(inter)
    ise = np.array(ise); dorp = np.array(dorp); dse = np.array(dse)

    # ── ORP 給出生物速率的比例（c 自動消掉）──────────────
    rho = dorp/dorp[0]
    print(f'\n── ORP 給出的生物速率比例 ρ = r_b(τ)/r_b(1min) ──')
    for j, lab in enumerate(labs):
        print(f'   {lab:<8} ρ = {rho[j]:+.3f}')
    print('   （比例常數 c 在相除時消掉，不需要校準電極）')

    # ── 求解 ─────────────────────────────────────────────
    w = 1/np.maximum(ise, 1e-9)
    ps, rb1, resid = solve(kla, inter, rho, w)
    rb = rb1*rho
    print(f'\n── 解（3 條方程、2 個未知數，超定）──')
    print(f'   p*        = {ps:+.4f} kg/cm²')
    print(f'   r_b(1min) = {rb1:+.5f} kg/cm²/hr')
    print(f'\n   {"條件":<8}{"r_b":>11}{"截距實測":>12}{"截距模型":>12}'
          f'{"殘差":>11}{"截距 SE":>11}')
    print('   '+'-'*66)
    for j, lab in enumerate(labs):
        pred = kla[j]*ps-rb[j]
        print(f'   {lab:<8}{rb[j]:>11.5f}{inter[j]:>12.5f}{pred:>12.5f}'
              f'{resid[j]:>+11.5f}{ise[j]:>11.5f}')
    chi2 = float(np.sum((resid*w)**2))
    print(f'\n   一致性 χ² = {chi2:.2f}（自由度 1，臨界值 3.84）')
    print(f'   → {"✓ 三條方程可用同一組參數解釋" if chi2 < 3.84 else "✘ 不一致，模型設定有問題"}')

    # ── 自助 ────────────────────────────────────────────
    rng = np.random.default_rng(2026)
    B = []
    for _ in range(NBOOT):
        ib = inter+rng.normal(0, ise)
        ob = dorp+rng.normal(0, dse)
        if abs(ob[0]) < 1e-6:
            continue
        try:
            _, r1, _ = solve(kla, ib, ob/ob[0], w)
            B.append(r1*(ob/ob[0]))
        except Exception:
            pass
    B = np.array(B)
    print(f'\n── 自助 {len(B)} 次（擾動截距與 ORP）──')
    print(f'   {"條件":<8}{"r_b":>11}{"95% CI":>26}{"P(r_b>0)":>11}')
    print('   '+'-'*58)
    for j, lab in enumerate(labs):
        lo, hi = np.quantile(B[:, j], [.025, .975])
        pg = float(np.mean(B[:, j] > 0))
        sig = '  ✓' if (lo > 0 or hi < 0) else ''
        print(f'   {lab:<8}{rb[j]:>11.5f}'
              f'{f"[{lo:+.5f}, {hi:+.5f}]":>26}{pg:>11.3f}{sig}')

    # ── 生物份額 ────────────────────────────────────────
    print('\n── 生物份額（r_b 佔總下降速率）──')
    print(f'   {"條件":<8}{"總速率":>11}{"r_b":>11}{"生物份額":>11}')
    print('   '+'-'*42)
    for j, lab in enumerate(labs):
        pr = D[lab]['pairs']
        tot = -np.median([p[1] for p in pr])
        print(f'   {lab:<8}{tot:>11.5f}{rb[j]:>11.5f}'
              f'{rb[j]/tot*100:>10.1f}%')

    with open(f'{OUT}/tau_joint_orp.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w_ = csv.writer(fh)
        w_.writerow(['cond', 'kLa', 'intercept', 'intercept_se',
                     'dORP_median', 'rho', 'r_b'])
        for j, lab in enumerate(labs):
            w_.writerow([lab, f'{kla[j]:.4f}', f'{inter[j]:.5f}',
                         f'{ise[j]:.5f}', f'{dorp[j]:.3f}',
                         f'{rho[j]:.4f}', f'{rb[j]:.5f}'])
        w_.writerow([]); w_.writerow(['p_star', f'{ps:.4f}',
                                      'chi2', f'{chi2:.3f}'])
    print(f'\n輸出 → {OUT}/tau_joint_orp.csv')


if __name__ == '__main__':
    main()
