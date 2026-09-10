
# -*- coding: utf-8 -*-
"""
循環工作比的飽和律（Duty-Cycle Saturation Law）
════════════════════════════════════════════════════════════════════════

尋找「規律」的錯誤做法：先想一個好聽的機制，再去資料裡找。
（實例：`vent_sawtooth.py` 的排氣鋸齒假說，T1 與 T3 皆被推翻。）

正確做法：**先看哪個關係在所有穩健性檢驗下都沒垮，再問它為什麼。**
以此標準掃過全部分析，只有一個關係從未被推翻：

    組成校正的 k_La 代理隨循環工作比 τ 單調上升，**但在 5 min/hr 後飽和**。

本檔把它量化成可寫進論文的定律，並檢驗飽和是真的還是雜訊：

  L1  飽和模型擬合：κ(τ) = κ₀ + Δ·τ/(τ + τ½)
  L2  模型比較：飽和 vs 線性（樣本外）
  L3  邊際報酬：每多一分鐘泵運轉換到多少 k_La
  L4  自助信賴區間

輸出 -> docs/analysis_charts_3batch/duty_cycle_law.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys
import csv

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402

NBOOT = 4000

# 五個條件的組成校正 k_La 代理（來源：analyze_three_batches / 三批次分析）
# τ = 每小時循環分鐘數。「泵開5min」為 2026-04 之後的連續循環期。
COND = [
    ('泵關',      0.0, [0.0954, 0.0909, 0.1023], 40),
    ('τ=1min',    1.0, [0.1065, 0.1019, 0.1101],  6),
    ('τ=5min',    5.0, [0.1659, 0.1484, 0.1737],  8),
    ('τ=10min',  10.0, [0.1708, 0.1653, 0.1782], 12),
]
#   每筆為 (中位, Q1, Q3)


def sat(t, k0, d, th):
    return k0 + d*t/(t+th)


def fit_sat(tau, y, w):
    """加權最小平方擬合飽和模型（格點 + 線性求解）。"""
    best = None
    for th in np.concatenate([np.arange(0.05, 5, 0.02),
                              np.arange(5, 60, 0.25)]):
        X = np.vstack([np.ones_like(tau), tau/(tau+th)]).T
        Xw = X*w[:, None]; yw = y*w
        try:
            c, *_ = np.linalg.lstsq(Xw, yw, rcond=None)
        except Exception:
            continue
        r = (X@c-y)*w
        s = float(r @ r)
        if best is None or s < best[0]:
            best = (s, c[0], c[1], th)
    return best[1], best[2], best[3], best[0]


def main():
    tau = np.array([c[1] for c in COND])
    y = np.array([c[2][0] for c in COND])
    iqr = np.array([c[2][2]-c[2][1] for c in COND])
    nn = np.array([c[3] for c in COND], float)
    # 權重：以 IQR 推得的中位數標準誤（1.253·σ/√n，σ≈IQR/1.349）
    se = 1.253*(iqr/1.349)/np.sqrt(nn)
    w = 1/se

    print('══ 循環工作比的飽和律 ══\n')
    print(f'   {"條件":<10}{"τ (min/hr)":>12}{"κ 中位":>10}{"IQR":>18}{"n":>5}{"SE":>9}')
    print('   '+'-'*66)
    for (nm, t, q, n), s in zip(COND, se):
        print(f'   {nm:<10}{t:>12.0f}{q[0]:>10.4f}'
              f'{f"[{q[1]:.4f}, {q[2]:.4f}]":>18}{n:>5}{s:>9.4f}')

    # ── L1 飽和擬合 ──────────────────────────────────────
    k0, d, th, ss = fit_sat(tau, y, w)
    print(f'\n── L1  飽和模型 κ(τ) = κ₀ + Δ·τ/(τ+τ½) ──')
    print(f'   κ₀  = {k0:.4f}   （τ=0 的基礎傳質）')
    print(f'   Δ   = {d:.4f}   （循環能帶來的最大增益）')
    print(f'   τ½  = {th:.2f} min/hr   （達到一半增益所需的工作比）')
    print(f'   加權殘差平方和 = {ss:.4f}')
    print(f'\n   {"τ":>6}{"實測":>10}{"模型":>10}{"殘差":>10}')
    print('   '+'-'*36)
    for t, v in zip(tau, y):
        m = sat(t, k0, d, th)
        print(f'   {t:>6.0f}{v:>10.4f}{m:>10.4f}{v-m:>+10.4f}')

    # ── L2 飽和 vs 線性 ──────────────────────────────────
    print('\n── L2  飽和 vs 線性（留一交叉驗證）──')
    for nm, fn in (('飽和', 'sat'), ('線性', 'lin')):
        errs = []
        for i in range(len(tau)):
            m = np.ones(len(tau), bool); m[i] = False
            if fn == 'sat':
                a, b, c, _ = fit_sat(tau[m], y[m], w[m])
                pred = sat(tau[i], a, b, c)
            else:
                X = np.vstack([np.ones(m.sum()), tau[m]]).T
                cf, *_ = np.linalg.lstsq(X*w[m][:, None], y[m]*w[m], rcond=None)
                pred = cf[0]+cf[1]*tau[i]
            errs.append((pred-y[i])**2)
        print(f'   {nm}模型  留一 RMSE = {np.sqrt(np.mean(errs)):.5f}')

    # ── L3 邊際報酬 ──────────────────────────────────────
    print('\n── L3  邊際報酬（每多 1 min/hr 泵運轉換到多少 κ）──')
    print(f'   {"區間":<16}{"Δκ":>10}{"Δτ":>7}{"每分鐘":>11}{"相對 0→1":>11}')
    print('   '+'-'*56)
    base = None
    for i in range(len(tau)-1):
        dk = y[i+1]-y[i]; dt_ = tau[i+1]-tau[i]
        per = dk/dt_
        if base is None:
            base = per
        print(f'   {f"{tau[i]:.0f} → {tau[i+1]:.0f} min":<16}'
              f'{dk:>+10.4f}{dt_:>7.0f}{per:>+11.5f}{per/base:>11.1%}')
    tot = y[-1]-y[0]
    at5 = (y[2]-y[0])/tot
    print(f'\n   τ=5 已達成總增益的 {at5:.0%}；'
          f'5→10 min 泵運轉加倍只再換到 {(y[3]-y[2])/tot:.0%}')

    # ── L4 自助信賴區間 ──────────────────────────────────
    print(f'\n── L4  參數自助信賴區間（{NBOOT} 次，以各條件 SE 擾動）──')
    rng = np.random.default_rng(67)
    ths, ds, k0s = [], [], []
    for _ in range(NBOOT):
        yb = y + rng.normal(0, se)
        try:
            a, b, c, _ = fit_sat(tau, yb, w)
        except Exception:
            continue
        k0s.append(a); ds.append(b); ths.append(c)
    for nm, v in (('κ₀', k0s), ('Δ', ds), ('τ½', ths)):
        v = np.array(v)
        q = np.quantile(v, [.025, .5, .975])
        print(f'   {nm:<4} 中位 {q[1]:>8.3f}   95% CI [{q[0]:.3f}, {q[2]:.3f}]')
    thv = np.array(ths)
    print(f'\n   P(τ½ < 5 min/hr) = {np.mean(thv < 5):.1%}'
          f'   → {"✓ 飽和點確實在 5 min 之前" if np.mean(thv<5) > 0.9 else "✘ 飽和點位置不確定"}')

    print('\n── 工程意涵 ──')
    print(f'   每小時循環超過 {th:.1f} min 後，傳質增益已達一半；')
    print(f'   5 → 10 min 泵運轉時間**加倍**，κ 僅增 '
          f'{(y[3]-y[2])/y[2]*100:.1f}%。')
    print('   ⚠ 限制：τ 與菌齡／液相飽和完全共線（全程未換液），')
    print('     故不能排除飽和是時間效應而非工作比效應。'
          '需批次內隨機交替 τ 方能定論。')

    with open(f'{OUT}/duty_cycle_law.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w_ = csv.writer(fh)
        w_.writerow(['tau_min_per_hr', 'kla_proxy', 'q1', 'q3', 'n',
                     'se', 'model'])
        for (nm, t, q, n), s in zip(COND, se):
            w_.writerow([t, q[0], q[1], q[2], n, f'{s:.5f}',
                         f'{sat(t, k0, d, th):.5f}'])
    print(f'\n輸出 → {OUT}/duty_cycle_law.csv')


if __name__ == '__main__':
    main()
