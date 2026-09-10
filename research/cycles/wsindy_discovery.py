# -*- coding: utf-8 -*-
"""
弱形式稀疏辨識（WSINDy）——不對量化壓力做微分的模型結構探勘
════════════════════════════════════════════════════════════════════════

為什麼需要弱形式
────────────────
反應槽壓力量化到 0.01 kg/cm²，而典型下降速率僅 0.02–0.04 kg/cm²/hr：
一小時的壓降只有 2–4 個 LSB。任何先微分再迴歸的做法（SG 濾波、有限差分）
都建立在這個最脆弱的一步上——實測顯示以 60 分鐘視窗估斜率時，
kLa 甚至會翻號。

弱形式（Messenger & Bortz, 2021）把方程式乘上緊支撐測試函數 phi 後分部積分：

    ∫ phi · dP/dt dt  =  -∫ phi' · P dt

右式**完全不含 P 的導數**——只微分我們自己選定的光滑 phi。
於是 dP/dt = Σ_j c_j f_j 變成線性系統

    b_k = -∫ phi_k' P dt ,   A_kj = ∫ phi_k f_j dt ,   b = A c

測試函數採 Messenger–Bortz 的多項式凸起：
    phi(t) = (1 - ((t-t_k)/m)^2)^p ，支撐 [t_k-m, t_k+m]，C^{p-1} 且兩端為 0，
故分部積分無邊界項。

稀疏化用 STLSQ（序列閾值最小平方，Brunton et al. 2016），
模型選擇一律以**留一循環**樣本外誤差判定——逐點 CV 會因自相關嚴重高估。

輸出 -> docs/analysis_charts_3batch/wsindy_terms.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                    # noqa: E402
from analyze_new_methods import collect                  # noqa: E402

M_HOURS = 2.0        # 測試函數半寬（小時）
P_ORDER = 6          # 凸起次方
N_TEST = 14          # 每循環的測試函數個數
STLSQ_ITER = 12


# ══════════════════════════════════════════════════════════════════
def phi_and_dphi(t, tc, m, p):
    """多項式凸起及其導數；支撐外為 0。"""
    u = (t - tc) / m
    inside = np.abs(u) < 1.0
    ph = np.zeros_like(t)
    dph = np.zeros_like(t)
    uu = u[inside]
    base = 1.0 - uu ** 2
    ph[inside] = base ** p
    dph[inside] = p * base ** (p - 1) * (-2.0 * uu) / m
    return ph, dph


# ── 函式庫調節 ────────────────────────────────────────────────────
# 閾值控制把壓力鎖在 P∈[0.92,1.17] 這個 0.25 寬的窄帶，於是 {1,P,P²} 在該
# 區間上幾乎線性相依（未調節時條件數 ~1e5），STLSQ 會選出巨大且互相抵消的
# 係數——看起來像「發現」，其實是病態。故：
#   (a) 壓力以帶中心 P0 平移，(b) 二次項改用該區間上的正交多項式，
#   (c) 每一欄再做 L2 正規化，係數於解出後還原。
# 這是本問題的結構性限制：提供免費激發的控制器，同時限制了狀態空間的多樣性。
P0, PW = 1.045, 0.125          # 帶中心與半寬（由 26 個循環的實測範圍取得）


def _u(d):
    return (d['P'] - P0) / PW          # 映到 [-1, 1]


LIB = {
    '1':       lambda d: np.ones_like(d['t']),
    'u':       lambda d: _u(d),                      # ~ (P - P0)
    'L2(u)':   lambda d: 1.5 * _u(d) ** 2 - 0.5,     # Legendre P2，與 1,u 正交
    't_in':    lambda d: d['t'],
    't_bat':   lambda d: d['tb'],
    'u*t_bat': lambda d: _u(d) * d['tb'],
    'exp-t':   lambda d: np.exp(-d['t']),
    'ORP':     lambda d: d['orp'] / 100.0,
}


def cycles():
    out = []
    for name, cs in collect().items():
        t0 = cs[0].ts.iloc[0]
        for j, c in enumerate(cs, 1):
            t = (c.ts - c.ts.iloc[0]).dt.total_seconds().values / 3600.0
            if t[-1] < 2 * M_HOURS + 0.5:
                continue
            out.append(dict(batch=name, cyc=j, t=t,
                            P=c.p_reactor.values.astype(float),
                            tb=(c.ts - t0).dt.total_seconds().values / 3600.0,
                            orp=c.orp.values.astype(float)))
    return out


def weak_rows(d, terms):
    """對單一循環產生弱形式的 (A_rows, b_rows)。"""
    t, P = d['t'], d['P']
    centres = np.linspace(t[0] + M_HOURS, t[-1] - M_HOURS, N_TEST)
    A = np.zeros((len(centres), len(terms)))
    b = np.zeros(len(centres))
    F = [LIB[k](d) for k in terms]
    for i, tc in enumerate(centres):
        ph, dph = phi_and_dphi(t, tc, M_HOURS, P_ORDER)
        b[i] = -np.trapezoid(dph * P, t)          # 不需 dP/dt
        for j, f in enumerate(F):
            A[i, j] = np.trapezoid(ph * f, t)
    return A, b


def stlsq(A, b, thresh, iters=STLSQ_ITER):
    """序列閾值最小平方（Brunton et al. 2016）。"""
    c = np.linalg.lstsq(A, b, rcond=None)[0]
    keep = np.ones(len(c), bool)
    for _ in range(iters):
        small = np.abs(c) < thresh
        if not small.any() or (~small).sum() == 0:
            break
        keep = ~small
        c = np.zeros(len(c))
        if keep.sum():
            c[keep] = np.linalg.lstsq(A[:, keep], b, rcond=None)[0]
    return c, keep


def cv_rmse(rows, terms, thresh):
    """留一循環：以弱形式殘差評估。"""
    err, n = 0.0, 0
    for held in range(len(rows)):
        Atr = np.vstack([rows[i][0] for i in range(len(rows)) if i != held])
        btr = np.concatenate([rows[i][1] for i in range(len(rows)) if i != held])
        c, _ = stlsq(Atr, btr, thresh)
        Ate, bte = rows[held]
        err += float(np.sum((bte - Ate @ c) ** 2)); n += len(bte)
    return np.sqrt(err / n)


def main():
    cyc = cycles()
    terms = list(LIB)
    print(f'══ WSINDy 弱形式模型探勘 ══')
    print(f'   循環 {len(cyc)} 個；測試函數 phi(t)=(1-u²)^{P_ORDER}，'
          f'半寬 {M_HOURS} hr，每循環 {N_TEST} 個')
    print(f'   候選項：{terms}')
    print(f'   注意：全程**未對壓力做任何微分**\n')

    by_batch = {}
    for d in cyc:
        by_batch.setdefault(d['batch'], []).append(d)

    res = []
    for b, ds in by_batch.items():
        rows = [weak_rows(d, terms) for d in ds]
        A = np.vstack([r[0] for r in rows])
        bb = np.concatenate([r[1] for r in rows])
        # 條件數診斷：未調節的 {1,P,P²} 對照調節後的 {1,u,L2(u)}
        raw = np.column_stack([np.ones(len(A)), A[:, 1], A[:, 1] ** 2])
        print(f'── {b} ──')
        print(f'   函式庫條件數：調節後 {np.linalg.cond(A):.3g}   '
              f'（未調節的 1,P,P² 版本 {np.linalg.cond(raw):.3g}）')
        # 掃描閾值，取留一循環 CV 最佳
        scale = np.abs(np.linalg.lstsq(A, bb, rcond=None)[0]).max()
        best = None
        for th in np.geomspace(scale * 1e-4, scale * 0.6, 14):
            r = cv_rmse(rows, terms, th)
            c, keep = stlsq(A, bb, th)
            k = int(keep.sum())
            if k == 0:
                continue
            if best is None or r < best[0]:
                best = (r, th, c, keep, k)
        r, th, c, keep, k = best
        sel = [t for t, m in zip(terms, keep) if m]
        print(f'   選中 {k} 項，CV-RMSE(弱形式) = {r:.5f}')
        print('   dP/dt = ' + '  '.join(
            f'{c[i]:+.5f}·{terms[i]}' for i in range(len(terms)) if keep[i]))
        res.append(dict(batch=b, n_terms=k, cv=r,
                        terms=';'.join(sel),
                        coefs=';'.join(f'{c[i]:.6g}' for i in range(len(terms))
                                       if keep[i])))
        print()

    print('══ 對照：強制只用兩通道模型 {1, u}（u = (P−P0)/PW）══')
    for b, ds in by_batch.items():
        rows = [weak_rows(d, ['1', 'u']) for d in ds]
        r = cv_rmse(rows, ['1', 'u'], 0.0)
        A = np.vstack([x[0] for x in rows]); bb = np.concatenate([x[1] for x in rows])
        c = np.linalg.lstsq(A, bb, rcond=None)[0]
        kla = -c[1] / PW                       # dP/dt = c0 + c1·(P−P0)/PW
        peq = P0 + c[0] / (kla * PW) * PW if kla > 0 else np.nan
        print(f'   {b:<14} CV-RMSE = {r:.5f}   kLa = {kla:.4f}   '
              f'Peq_eff = {P0 + c[0]/kla:.4f}')

    import csv
    with open(f'{OUT}/wsindy_terms.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['batch', 'n_terms', 'cv', 'terms',
                                          'coefs'])
        w.writeheader(); w.writerows(res)
    print(f'\n輸出 → {OUT}/wsindy_terms.csv')


if __name__ == '__main__':
    main()
