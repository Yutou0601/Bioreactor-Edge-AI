# -*- coding: utf-8 -*-
"""
弱形式 × 壓力分箱固定效應 × 雙時鐘（Weak–Binned Two-Clock, WB2C）
════════════════════════════════════════════════════════════════════════

三個問題，三個對應機制
──────────────────────
(1) 壓力量化 0.01 kg/cm²，一小時僅 2–4 個 LSB
    -> **弱形式**：乘上緊支撐測試函數後分部積分，全程不對 P 微分
       （Messenger & Bortz 2021 的 WSINDy 弱形式）

(2) 封閉頂空內 P 與循環內時間 t_in 幾乎完美負相關（r ~ -0.999）
    -> 任何同時含「狀態項」與「時間項」的字典都是秩虧的；
       實測：未處理時 WSINDy 選出的壓力項係數會出現**正號**（物理上不可能）。
    -> **壓力分箱固定效應**：只在同一壓力箱內比較，等價於把 P 的主效應
       完全吸收掉，剩下的變異純粹來自「同壓力、不同時刻」。

(3) 要分開的兩個機制在**振幅**上不可辨識
    -> **雙時鐘**：改以「是否在補氣時重置」區分。
       t_in  = 循環內經過時間  -> 每次補氣歸零（氣相基質耗竭這類過程）
       t_bat = 批次累積時間    -> 不歸零（液相載入這類過程）
       兩者的係數即為兩個機制的指紋，與絕對振幅無關。

顯著性以「箱內置換 t_in」的無母數檢定判定；標準誤採叢集穩健（叢集 = 循環）。

輸出 -> docs/analysis_charts_3batch/wb2c.csv
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

M_HOURS, P_ORDER, N_TEST = 1.5, 6, 18
NBIN, NPERM = 6, 5000


def phi_dphi(t, tc, m, p):
    u = (t - tc) / m
    ins = np.abs(u) < 1.0
    ph = np.zeros_like(t); dph = np.zeros_like(t)
    uu = u[ins]; base = 1.0 - uu ** 2
    ph[ins] = base ** p
    dph[ins] = p * base ** (p - 1) * (-2.0 * uu) / m
    return ph, dph


def weak_samples():
    """每個測試函數產生一筆樣本：弱形式速率 + 該窗的代表壓力與兩個時鐘。"""
    rows = []
    for name, cs in collect().items():
        t0 = cs[0].ts.iloc[0]
        for j, c in enumerate(cs, 1):
            t = (c.ts - c.ts.iloc[0]).dt.total_seconds().values / 3600.0
            if t[-1] < 2 * M_HOURS + 0.5:
                continue
            P = c.p_reactor.values.astype(float)
            tb = (c.ts - t0).dt.total_seconds().values / 3600.0
            for tc in np.linspace(t[0] + M_HOURS, t[-1] - M_HOURS, N_TEST):
                ph, dph = phi_dphi(t, tc, M_HOURS, P_ORDER)
                w = np.trapezoid(ph, t)
                if w <= 0:
                    continue
                # 弱形式的平均 dP/dt：∫phi·dP/dt / ∫phi = -∫phi'·P / ∫phi
                rate = -np.trapezoid(dph * P, t) / w
                rows.append((name, j,
                             np.trapezoid(ph * P, t) / w,      # 代表壓力
                             np.trapezoid(ph * t, t) / w,      # t_in
                             np.trapezoid(ph * tb, t) / w,     # t_bat
                             rate))
    return rows


def demean_by_bin(x, b):
    out = np.empty_like(x)
    for k in np.unique(b):
        m = b == k
        out[m] = x[m] - x[m].mean()
    return out


def cluster_se(X, y, resid, clusters):
    XtX_inv = np.linalg.pinv(X.T @ X)
    meat = np.zeros((X.shape[1], X.shape[1]))
    for g in np.unique(clusters):
        m = clusters == g
        u = X[m].T @ resid[m]
        meat += np.outer(u, u)
    V = XtX_inv @ meat @ XtX_inv
    return np.sqrt(np.diag(V))


def analyse(rows, tag):
    P = np.array([r[2] for r in rows]); tin = np.array([r[3] for r in rows])
    tba = np.array([r[4] for r in rows]); rate = np.array([r[5] for r in rows])
    cyc = np.array([r[1] for r in rows])
    edges = np.quantile(P, np.linspace(0, 1, NBIN + 1))
    edges[-1] += 1e-9
    b = np.digitize(P, edges[1:-1])

    y = demean_by_bin(rate, b)
    X = np.column_stack([demean_by_bin(tin, b), demean_by_bin(tba, b)])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    se = cluster_se(X, y, resid, cyc)

    rng = np.random.default_rng(3)
    cnt = 0
    for _ in range(NPERM):
        tp = tin.copy()
        for k in np.unique(b):          # 箱內置換 t_in，保留 P 的一切結構
            m = b == k
            tp[m] = rng.permutation(tp[m])
        Xp = np.column_stack([demean_by_bin(tp, b), X[:, 1]])
        bp, *_ = np.linalg.lstsq(Xp, y, rcond=None)
        cnt += abs(bp[0]) >= abs(beta[0])
    p_perm = (cnt + 1) / (NPERM + 1)

    print(f'── {tag} ──')
    print(f'   樣本 {len(rows)}（弱形式窗），循環 {len(np.unique(cyc))}，'
          f'壓力箱 {NBIN}')
    print(f'   b_in  (每循環重置) = {beta[0]:+.6f} ± {se[0]:.6f}'
          f'   t = {beta[0]/se[0]:+.2f}   置換 p = {p_perm:.4f}')
    print(f'   b_bat (整批累積)   = {beta[1]:+.6f} ± {se[1]:.6f}'
          f'   t = {beta[1]/se[1]:+.2f}')
    return dict(batch=tag, n=len(rows), b_in=beta[0], se_in=se[0],
                t_in=beta[0] / se[0], p_perm=p_perm,
                b_bat=beta[1], se_bat=se[1], t_bat=beta[1] / se[1])


def main():
    rows = weak_samples()
    print('══ WB2C：弱形式 × 壓力分箱固定效應 × 雙時鐘 ══')
    print('   分離依據不是振幅，而是「是否在補氣時重置」\n')
    res = []
    for name in sorted({r[0] for r in rows}):
        res.append(analyse([r for r in rows if r[0] == name], name))
    print()
    res.append(analyse(rows, '合併三批'))

    import csv
    with open(f'{OUT}/wb2c.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(res[0]))
        w.writeheader(); w.writerows(res)
    print(f'\n輸出 → {OUT}/wb2c.csv')


if __name__ == '__main__':
    main()
