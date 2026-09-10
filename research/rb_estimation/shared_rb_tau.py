
# -*- coding: utf-8 -*-
"""
共用 rb 的 τ 系列擬合：把超定性用出來
════════════════════════════════════════════════════════════════════════

**先前失敗的原因（現在才想通）**：我讓每個條件各有自己的 P_eq，
於是「3 個截距 → 3 個未知數」剛好定死，沒有多餘資訊可用來檢驗。

**正確的約束**（來自實驗設計，不是假設）：
  τ = 1 / 5 / 10 min/hr 是**同一批、同一液體、同樣 4:1 進氣、相隔數天**
  ⇒ r_b 與 P_eq 在三個條件下**必須是同一個值**
  ⇒ f_CO2 = 0.2 是**已知**，不是待估

模型（循環早期，遠離平衡）：

    dP/dt = −k_La(τ)·(P − P_eq) − r_b

  每個條件：斜率 = −k_La(τ)，截距 = k_La(τ)·P_eq − r_b

  3 個斜率 → 3 個 k_La
  3 個截距 → **只有 2 個未知數 (P_eq, r_b)** ⇒ **超定**

超定就有一致性檢查：若三個截距無法用同一組 (P_eq, r_b) 解釋，
模型就是錯的；若能，殘差大小就是這個估計的可信度。

⚠ **本檔給的是近似值，不是定案。** 見檔末對設定誤差虛無的說明。

輸出 -> docs/analysis_charts_3batch/shared_rb_tau.csv
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
from math import sqrt, erfc

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from regime_changepoints import load, segment, TD                  # noqa: E402

PORD = 6
NBOOT = 3000

TAU = [('tau1', 1, dt.date(2026, 7, 22), dt.date(2026, 7, 27)),
       ('tau5', 5, dt.date(2026, 7, 27), dt.date(2026, 7, 30)),
       ('tau10', 10, dt.date(2026, 7, 30), dt.date(2026, 8, 4))]


def weak_pairs(t, y, nw=5):
    T = t[-1]-t[0]
    m = T/(nw+1)
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
    seen, out = {}, {k: [] for k, _, _, _ in TAU}
    for path in folders:
        try:
            raw = load(path)
        except Exception:
            continue
        if len(raw) < 2000:
            continue
        cyc, h, P, ts = segment(raw)
        for a, b in cyc:
            d = ts[a].date()
            lab = next((k for k, _, s, e in TAU if s <= d < e), None)
            if lab is None:
                continue
            key = (ts[a].replace(second=0), round(h[b]-h[a], 1))
            if key in seen:
                continue
            seen[key] = 1
            t = h[a:b+1]-h[a]; y = P[a:b+1]
            half = t <= t[-1]/2                 # 只用前半，遠離平衡
            if half.sum() < 20:
                continue
            out[lab].extend(weak_pairs(t[half], y[half]))
    return out


def per_cond(pairs):
    """單一條件：rate = s·P + i，回傳 (斜率, 截距, SE, n)。"""
    P = np.array([p[0] for p in pairs]); R = np.array([p[1] for p in pairs])
    A = np.vstack([P, np.ones_like(P)]).T
    c, *_ = np.linalg.lstsq(A, R, rcond=None)
    res = R-A@c
    dof = max(len(P)-2, 1)
    s2 = float(res @ res)/dof
    cov = s2*np.linalg.inv(A.T@A)
    return c[0], c[1], np.sqrt(np.diag(cov)), len(P)


def solve_shared(k, inter, w=None):
    """3 個截距 → (P_eq, r_b)：intercept_i = k_i·P_eq − r_b。超定，最小平方。"""
    A = np.vstack([k, -np.ones_like(k)]).T
    if w is None:
        w = np.ones_like(k)
    Aw = A*w[:, None]; yw = np.asarray(inter)*w
    sol, *_ = np.linalg.lstsq(Aw, yw, rcond=None)
    resid = A@sol-np.asarray(inter)
    return sol[0], sol[1], resid


def main():
    data = gather()
    print('══ 共用 rb 的 τ 系列擬合 ══\n')
    print('   約束來自實驗設計：同批、同液、同樣 4:1 進氣、相隔數天')
    print('   ⇒ r_b 與 P_eq 三個條件共用；f_CO2 = 0.2 已知\n')

    ks, ins, ses, ns = [], [], [], []
    print(f'   {"條件":<8}{"n(配對)":>9}{"斜率 = −kLa":>14}{"截距":>12}'
          f'{"k_La":>10}')
    print('   '+'-'*54)
    labs = []
    for lab, tau, _, _ in TAU:
        pr = data[lab]
        if len(pr) < 8:
            print(f'   {lab:<8}   資料不足（{len(pr)}）')
            continue
        s, i, se, n = per_cond(pr)
        ks.append(-s); ins.append(i); ses.append(se); ns.append(n)
        labs.append(lab)
        print(f'   {lab:<8}{n:>9}{s:>14.5f}{i:>12.5f}{-s:>10.4f}')

    if len(ks) < 3:
        print('\n   ✘ 少於三個條件，超定性不存在')
        return

    k = np.array(ks); it = np.array(ins)
    w = 1/np.array([s[1] for s in ses])          # 以截距 SE 加權
    Peq, rb, resid = solve_shared(k, it, w)

    print('\n── 3 個截距 → 2 個未知數（超定）──')
    print(f'   P_eq = {Peq:+.4f} kg/cm²')
    print(f'   r_b  = {rb:+.5f} kg/cm²/hr')
    print(f'\n   {"條件":<8}{"截距實測":>12}{"截距模型":>12}{"殘差":>11}'
          f'{"截距 SE":>11}')
    print('   '+'-'*54)
    for j, lab in enumerate(labs):
        pred = k[j]*Peq-rb
        print(f'   {lab:<8}{it[j]:>12.5f}{pred:>12.5f}{resid[j]:>+11.5f}'
              f'{ses[j][1]:>11.5f}')
    chi2 = float(np.sum((resid*w)**2))
    print(f'\n   一致性：加權殘差平方和 = {chi2:.2f}（自由度 1）')
    print(f'   → {"✓ 三個截距可用同一組 (P_eq, r_b) 解釋" if chi2 < 3.84 else "✘ 不一致，模型設定有問題"}')

    # ── 自助信賴區間 ──────────────────────────────────
    rng = np.random.default_rng(101)
    boot = []
    for _ in range(NBOOT):
        kb = k+rng.normal(0, [s[0] for s in ses])
        ib = it+rng.normal(0, [s[1] for s in ses])
        try:
            _, rbb, _ = solve_shared(kb, ib, w)
            boot.append(rbb)
        except Exception:
            pass
    boot = np.array(boot)
    lo, hi = np.quantile(boot, [.025, .975])
    print(f'\n── 自助（{NBOOT} 次，依各條件的 SE 擾動）──')
    print(f'   r_b = {rb:+.5f}   95% CI [{lo:+.5f}, {hi:+.5f}]')
    print(f'   P(r_b > 0) = {np.mean(boot > 0):.3f}')

    print('\n── ⚠ 這個數字能說什麼、不能說什麼 ──')
    print('   能說：在「兩通道線性模型 + 三條件共用 r_b」的設定下，')
    print('         三個截距可以（或不能）用同一組參數解釋，且 r_b 落在上述區間。')
    print('   不能說：r_b 顯著大於零。理由是先前的設定誤差虛無檢定——')
    print('         以雙指數（r_b ≡ 0）為真相產生的資料，經同一管線也會')
    print('         回收出同量級的 r_b（無噪聲時 0.01099 對實測 0.01104）。')
    print('         要排除那個可能，需要的是**額外的觀測量**（溶解氣體電極），')
    print('         不是更好的擬合。')

    with open(f'{OUT}/shared_rb_tau.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        wr = csv.writer(fh)
        wr.writerow(['cond', 'n_pairs', 'slope', 'intercept', 'kLa',
                     'intercept_se'])
        for j, lab in enumerate(labs):
            wr.writerow([lab, ns[j], f'{-k[j]:.5f}', f'{it[j]:.5f}',
                         f'{k[j]:.4f}', f'{ses[j][1]:.5f}'])
        wr.writerow([])
        wr.writerow(['P_eq', f'{Peq:.4f}', 'r_b', f'{rb:.5f}',
                     'ci_lo', f'{lo:.5f}', 'ci_hi', f'{hi:.5f}'])
    print(f'\n輸出 → {OUT}/shared_rb_tau.csv')


if __name__ == '__main__':
    main()
