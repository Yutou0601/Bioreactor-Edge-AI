# -*- coding: utf-8 -*-
"""雙狀態氣相模型：以「組成漂移」打破 kLa 與 rb 的簡併（2026-08-03）。

── 先更正前一輪的過度宣稱 ─────────────────────────────────
前一輪結論為「生物受質傳限制 => rb 正比於 kLa(P-Peq)，與物理同形式 => 恆不可辨識」。
此推導有誤。若生物受 H2 質傳限制，則

    R (生物 CO2 消耗) 正比於 p_H2      <-- 注意：不是 (P - P_sat)

因為溶解的 H2 被立刻消耗，液相 H2 濃度趨近 0，沒有飽和項。
故兩通道的漸近行為根本不同：

    生物通道 ~ p_H2      -> 隨 H2 耗竭而趨近 0
    物理通道 ~ (p_CO2 - p_sat) -> 趨近 0 但 p_CO2 停在 p_sat（不為 0）

兩者「終點」不同、時間常數也不同 => 原理上可辨識。
前一輪的失敗來自把 h(t) 交給雜訊很大的 ORP（Nernst R2 僅 0.13~0.24），
而非結構性簡併。本檔改由「質量守恆＋化學計量」內生地決定 h(t)。

── 模型（解析解，無需數值積分）─────────────────────────────
    dh/dt = -4 k_b h                      h = p_H2
    dm/dt =    k_b h                      m = p_CH4
    dc/dt =   -k_b h - kLa (c - c_sat)    c = p_CO2
    P = h + c + m

    令 lam = 4 k_b：
      h(t) = h0 e^{-lam t}
      m(t) = m0 + (h0/4)(1 - e^{-lam t})
      c(t) = c_sat + (c0 - c_sat) e^{-kLa t}
             - k_b h0 (e^{-lam t} - e^{-kLa t}) / (kLa - lam)

    => P(t) 為「振幅受化學計量約束」的雙指數。約束來自 4:1 進氣比，
       這正是使 k_b 可辨識的關鍵資訊。

輸出 -> docs/analysis_charts_3batch/fig21, fig22
"""
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import optimize, stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (  # noqa: E402
    BATCHES, OUT, BCOL, BLUE, RED, AQUA, INK, INK2, MUTED, BASELINE, style)
from analyze_new_methods import collect  # noqa: E402

MAX_T = 24.0


# ══════════════════════════════════════════════════════════
# 模型（皆為解析式）
# ══════════════════════════════════════════════════════════
def p_single(t, P0, k, peq):
    """單一指數＝目前使用的模型。"""
    return peq + (P0 - peq) * np.exp(-k * t)


def p_two_state(t, P0, kla, k_b, c_sat, f, m0):
    """雙狀態氣相模型的總壓解析解。

    f  = 補氣後「非甲烷氣體」中 H2 的分率（由 4:1 進氣與殘氣混合決定）
    m0 = 該循環起始的累積 CH4 分壓
    """
    lam = 4.0 * k_b
    free = np.maximum(P0 - m0, 1e-6)
    h0, c0 = f * free, (1.0 - f) * free
    e_lam = np.exp(-lam * t)
    e_kla = np.exp(-kla * t)
    denom = kla - lam
    if abs(denom) < 1e-8:                      # 兩時間常數重合的極限
        cross = k_b * h0 * t * e_kla
    else:
        cross = k_b * h0 * (e_lam - e_kla) / denom
    h = h0 * e_lam
    m = m0 + (h0 / 4.0) * (1.0 - e_lam)
    c = c_sat + (c0 - c_sat) * e_kla - cross
    return h + c + m


def p_biexp(t, P0, a, k1, k2, C):
    """無約束雙指數（純現象學對照，用來確認是否真有第二時間尺度）。"""
    A2 = P0 - C - a
    return C + a * np.exp(-k1 * t) + A2 * np.exp(-k2 * t)


# ══════════════════════════════════════════════════════════
def cycle_data(cycs):
    out = []
    for c in cycs:
        t = (c.ts - c.ts.iloc[0]).dt.total_seconds().values / 3600
        p = c.p_reactor.values.astype(float)
        m = t <= MAX_T
        out.append((t[m], p[m], float(p[0])))
    return out


def sse(fn, theta, data):
    s = 0.0
    for t, P, P0 in data:
        pred = fn(t, P0, *theta)
        if not np.all(np.isfinite(pred)):
            return 1e9
        s += float(np.sum((P - pred) ** 2))
    return s


def fit(fn, data, p0, bounds, restarts=None):
    """有界限的擬合。Nelder-Mead 精修時必須同樣帶入 bounds，
    否則會逃出參數框、得到 kLa->inf 與 c_sat/m0 互相抵消的無意義解。"""
    best, bth = np.inf, np.asarray(p0, float)
    starts = [p0] if restarts is None else restarts
    for st in starts:
        r = optimize.minimize(lambda th: sse(fn, th, data), st,
                              method='L-BFGS-B', bounds=bounds)
        if r.fun < best:
            best, bth = r.fun, r.x
        r2 = optimize.minimize(lambda th: sse(fn, th, data), bth,
                               method='Nelder-Mead', bounds=bounds,
                               options=dict(maxiter=8000, fatol=1e-13, xatol=1e-9))
        if r2.fun < best:
            best, bth = r2.fun, r2.x
    return bth, best


def loco_cv(fn, data, p0, bounds, restarts=None):
    """留一循環交叉驗證：對 1 分鐘取樣的強自相關資料，這是唯一誠實的比較方式
    （F 檢定會因為把 4000+ 個相關點當獨立而給出假的 p=0）。"""
    errs = []
    for i in range(len(data)):
        tr = [d for j, d in enumerate(data) if j != i]
        th, _ = fit(fn, tr, p0, bounds, restarts)
        t, P, P0 = data[i]
        pred = fn(t, P0, *th)
        if not np.all(np.isfinite(pred)):
            return np.nan
        errs.append(P - pred)
    e = np.concatenate(errs)
    return float(np.sqrt(np.mean(e ** 2)))


def aicc(s, n, k):
    return n * np.log(s / n) + 2 * k + 2 * k * (k + 1) / max(n - k - 1, 1)


def bio_share(data, th):
    """整段積分的生物氣體移除佔比。"""
    kla, k_b, c_sat, f, m0 = th
    lam = 4.0 * k_b
    tot_bio = tot_all = 0.0
    for t, P, P0 in data:
        free = max(P0 - m0, 1e-6)
        h0 = f * free
        # 生物移除的氣體 = 4 x 累積 CH4 = h0(1 - e^{-lam T})
        tot_bio += h0 * (1.0 - np.exp(-lam * t[-1]))
        tot_all += P[0] - P[-1]
    return tot_bio / tot_all if tot_all > 0 else np.nan


def profile_kb(data, th_best, s_best, n):
    """對 k_b 做 profile likelihood：碗狀＝可辨識。"""
    kla0, kb0, cs0, f0, m00 = th_best
    grid = np.unique(np.clip(kb0 * np.array(
        [0.0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0]), 0, 0.5))
    out = []
    bnd = [(1e-3, 2.0), (0.0, 0.9), (0.25, 0.9), (0.0, 0.5)]
    for kb in grid:
        r = optimize.minimize(
            lambda q: sse(p_two_state, [q[0], kb, q[1], q[2], q[3]], data),
            [kla0, cs0, f0, m00], method='Nelder-Mead', bounds=bnd,
            options=dict(maxiter=6000, fatol=1e-13))
        out.append((kb, r.fun))
    A = np.array(out)
    thr = s_best * (1 + 5 / (n - 5) * stats.f.ppf(0.95, 5, n - 5))
    return A, thr


def main():
    cycles = collect()
    print('══ 更正：生物受 H2 質傳限制時，生物項正比於 p_H2（無飽和項），')
    print('   與物理項 (p_CO2 - p_sat) 的漸近終點不同 => 原理上可辨識。')
    print('   前一輪的失敗源於 ORP 雜訊，非結構性簡併。\n')

    rows, store = [], {}
    for name, cycs in cycles.items():
        data = cycle_data(cycs)
        n = sum(len(t) for t, *_ in data)

        th1, s1 = fit(p_single, data, [0.05, 0.6],
                      [(1e-4, 3.0), (0.0, 1.0)])
        th_b, s_b = fit(p_biexp, data, [0.2, 0.3, 0.03, 0.6],
                        [(0.0, 1.0), (1e-3, 5.0), (1e-4, 1.0), (0.0, 1.0)],
                        restarts=[[0.2, 0.5, 0.02, 0.6], [0.1, 1.5, 0.04, 0.7]])
        th2, s2 = fit(p_two_state, data, [0.10, 0.02, 0.45, 0.6, 0.15],
                      [(1e-3, 2.0), (1e-4, 0.5), (0.0, 0.9),
                       (0.25, 0.9), (0.0, 0.5)],
                      restarts=[[0.10, 0.02, 0.45, 0.60, 0.15],
                                [0.30, 0.005, 0.30, 0.80, 0.05],
                                [0.05, 0.05, 0.60, 0.45, 0.25]])

        cv1 = loco_cv(p_single, data, [0.05, 0.6], [(1e-4, 3.0), (0.0, 1.0)])
        cv2 = loco_cv(p_two_state, data, [0.10, 0.02, 0.45, 0.6, 0.15],
                      [(1e-3, 2.0), (1e-4, 0.5), (0.0, 0.9),
                       (0.25, 0.9), (0.0, 0.5)])
        bs = bio_share(data, th2)
        rows.append(dict(
            batch=name, tau=BATCHES[name][2], n=n, n_cyc=len(data),
            rmse1=np.sqrt(s1 / n), rmse_bi=np.sqrt(s_b / n), rmse2=np.sqrt(s2 / n),
            cv1=cv1, cv2=cv2,
            aicc1=aicc(s1, n, 2), aicc_bi=aicc(s_b, n, 4), aicc2=aicc(s2, n, 5),
            kla=th2[0], k_b=th2[1], c_sat=th2[2], f=th2[3], m0=th2[4],
            lam=4 * th2[1], bio=bs,
            sane=bool(0 < bs < 1 and th2[0] < 2.0 and th2[2] < 0.9)))
        store[name] = (data, th1, th_b, th2, s2, n)

        r = rows[-1]
        print(f'{name}  （{len(data)} 循環、{n} 點）')
        print(f'  單一指數   RMSE={r["rmse1"]:.5f}  留一循環CV={cv1:.5f}')
        print(f'  無約束雙指數 RMSE={r["rmse_bi"]:.5f}')
        print(f'  雙狀態氣相  RMSE={r["rmse2"]:.5f}  留一循環CV={cv2:.5f}   <-- 本文')
        print(f'  kLa={r["kla"]:.4f}  k_b={r["k_b"]:.4f}（H2 衰減 lam={r["lam"]:.4f}）'
              f'  c_sat={r["c_sat"]:.3f}  f_H2={r["f"]:.2f}  m0={r["m0"]:.3f}')
        print(f'  生物份額 {bs*100:.1f}%   參數是否物理合理：'
              f'{"是" if r["sane"] else "否（解已跑到邊界或份額不合理）"}')
        print(f'  時間常數比 kLa/lam = {r["kla"]/max(r["lam"],1e-9):.2f}'
              f'（越接近 1 越難分離）\n')

    T = pd.DataFrame(rows)
    T.to_csv(f'{OUT}/two_state_model.csv', index=False, encoding='utf-8-sig')

    print('══ profile likelihood：k_b 是否可辨識（碗狀）══')
    PR = {}
    for name in BATCHES:
        data, _, _, th2, s2, n = store[name]
        A, thr = profile_kb(data, th2, s2, n)
        PR[name] = (A, thr)
        lo = A[A[:, 1] <= thr, 0]
        rel0 = (A[0, 1] - s2) / s2 * 100          # k_b=0（純物理）的懲罰
        print(f'  {name}: k_b=0 時 SSE 增加 {rel0:+.1f}%  '
              f'95% 區間 k_b ∈ [{lo.min():.4f}, {lo.max():.4f}]  '
              f'{"→ 碗狀、可辨識" if rel0 > 2 else "→ 平坦、不可辨識"}')

    print('\n══ 總結（以留一循環 CV 判定，不用 F 檢定）══')
    win = T[(T.cv2 < T.cv1) & T.sane]
    print(f'  雙狀態模型在「留一循環 CV」上勝出且參數合理：{len(win)}/3 批')
    for _, r in T.iterrows():
        better = '優於' if r.cv2 < r.cv1 else '不如'
        print(f'    {r.batch}: CV {r.cv1:.5f} → {r.cv2:.5f}（{better}單指數）'
              f'  參數合理={"是" if r.sane else "否"}')
    if len(win):
        print('  生物份額：' + '、'.join(
            f'{b.split()[1]} {v*100:.0f}%' for b, v in zip(win.batch, win.bio)))
    figures(store, T, PR)
    print(f'\n輸出 → {OUT}')


def figures(store, T, PR):
    # ── 圖21：擬合與殘差 ──
    fig, axes = plt.subplots(2, 3, figsize=(14.5, 7.4))
    for j, name in enumerate(BATCHES):
        data, th1, th_b, th2, _, _ = store[name]
        ax, axr = axes[0, j], axes[1, j]
        for t, P, P0 in data:
            ax.plot(t, P, lw=0.7, color=MUTED, alpha=0.5)
            ax.plot(t, p_single(t, P0, *th1), lw=1.3, color=RED, alpha=0.75)
            ax.plot(t, p_two_state(t, P0, *th2), lw=1.6, color=AQUA, alpha=0.9)
            axr.plot(t, P - p_single(t, P0, *th1), lw=0.7, color=RED, alpha=0.45)
            axr.plot(t, P - p_two_state(t, P0, *th2), lw=0.7, color=AQUA, alpha=0.6)
        r = T[T.batch == name].iloc[0]
        style(ax, f'{name}\n單指數 {r.rmse1:.4f} → 雙狀態 {r.rmse2:.4f}',
              None, '反應槽壓力 (kg/cm²)' if j == 0 else None)
        axr.axhline(0, color=BASELINE, lw=1.1)
        style(axr, f'殘差（留一CV {r.cv2:.4f}，生物 {r.bio*100:.0f}%）',
              '補氣後時間 (hr)', '殘差 (kg/cm²)' if j == 0 else None)
    axes[0, 0].plot([], [], color=RED, lw=2, label='單一指數（現行）')
    axes[0, 0].plot([], [], color=AQUA, lw=2, label='雙狀態氣相（本文）')
    axes[0, 0].legend(frameon=False, fontsize=9)
    fig.suptitle('圖21  以氣體組成漂移打破簡併：雙狀態氣相模型 vs 單一指數',
                 fontweight='bold', x=0.06, ha='left')
    fig.text(0, -0.03,
             '生物項正比於 p_H2（隨 H2 耗竭趨近 0），物理項正比於 (p_CO2 − p_sat)（p_CO2 停在 p_sat）——'
             '兩者漸近終點與時間常數皆不同，故 P(t) 為雙指數。\n'
             '振幅比受 4:1 進氣化學計量約束，這正是使生物速率常數 k_b 可辨識的關鍵資訊；'
             '下排殘差若在雙狀態下變平，即證實第二時間尺度存在。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig21_two_state_gas_model.png')
    plt.close(fig)

    # ── 圖22：profile likelihood + 模型比較 ──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.7))
    for name in BATCHES:
        A, thr = PR[name]
        s_min = A[:, 1].min()
        ax1.plot(A[:, 0], (A[:, 1] - s_min) / s_min * 100, 'o-', ms=5, lw=1.8,
                 color=BCOL[name], label=name)
    ax1.axvline(0, color=BASELINE, lw=1.2)
    ax1.annotate('k_b = 0 ＝ 純物理（無生物）', xy=(0.02, 0.9),
                 xycoords='axes fraction', fontsize=9.5, color=INK2)
    style(ax1, '圖22a  生物速率常數 k_b 的 Profile Likelihood',
          'k_b (1/hr)', 'SSE 相對最小值增加 (%)')
    ax1.legend(frameon=False, fontsize=9)

    xp = np.arange(3)
    w = 0.26
    base = T.aicc1.values
    for i, (col, key, lab) in enumerate([
            (MUTED, 'aicc1', '單一指數'), (RED, 'aicc_bi', '無約束雙指數'),
            (AQUA, 'aicc2', '雙狀態氣相（本文）')]):
        ax2.bar(xp + (i - 1) * w, T[key].values - base, width=w,
                color=col, label=lab)
    ax2.axhline(0, color=BASELINE, lw=1.2)
    ax2.set_xticks(xp, [f'{t:.0f} min' for t in T.tau])
    style(ax2, '圖22b  ΔAICc 相對單一指數（越負越好）',
          '循環時間 τ', 'ΔAICc')
    ax2.legend(frameon=False, fontsize=9)
    fig.text(0, -0.06,
             'profile likelihood 若呈碗狀（k_b=0 有明顯懲罰），代表資料本身要求生物通道存在，'
             '即簡併已被打破。\n無約束雙指數為現象學對照：它證明「第二時間尺度存在」，'
             '而雙狀態模型進一步以化學計量把該尺度歸因於 H2 耗竭。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig22_kb_identifiability.png')
    plt.close(fig)
    print('  圖 21–22 完成')


if __name__ == '__main__':
    main()
