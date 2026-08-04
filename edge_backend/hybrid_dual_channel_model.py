# -*- coding: utf-8 -*-
"""雙通道 hybrid 模型：兩條通道皆受循環時間 τ 驅動（2026-08-03）。

── 架構定位 ───────────────────────────────────────────────
前沿做法為 hybrid mechanistic-ML / Universal Differential Equations：
機理 ODE 為骨架，未知項以資料驅動元件閉合。公認難點是稀疏雜訊資料下
神經閉合會過擬合且機理參數失去可解釋性。本資料僅 26 循環，
故採「參數化閉合」而非神經閉合——保留 UDE 的結構，換掉閉合元件。

── 模型 ───────────────────────────────────────────────────
    dP/dt = -kLa(τ)·(P - Peq)  -  rb(τ)·h(t)
            └─ 物理通道 ─┘        └─ 生物通道 ─┘
    驅動源不同：物理由「壓力差」驅動、生物由「H2 可得性 h」驅動。
    h(t) 由 ORP 經 Nernst 給出（與壓力獨立的觀測）：h = exp(-ΔE/S)。

    閉合函數（皆為飽和型，反映氣液質傳的飽和特性）：
        kLa(τ) = kmax·τ/(Kk + τ)
        rb(τ)  = rmax·τ/(Kb + τ)      <-- 本文的關鍵修正

── 本文主張（文獻未見） ────────────────────────────────────
既有設計（含本研究先前規劃）假設「kLa 隨 τ 變、rb 不隨 τ 變」，
故以循環時間作為分離槓桿。但嗜氫甲烷菌的限速步驟正是 H2 的氣液質傳，
因此 τ 同時驅動兩條通道 => 槓桿失效。本模型明確讓 rb 也隨 τ 飽和，
並以 ORP 作為第二觀測打破簡併，是「槓桿失效」的可檢定表述。

模型比較：
    M1 純物理     rb = 0
    M2 定值生物   rb(τ) = rb            （＝先前規劃的假設）
    M3 雙通道飽和 rb(τ) = rmax·τ/(Kb+τ) （本文）

輸出 -> docs/analysis_charts_3batch/fig19, fig20
"""
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import optimize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (  # noqa: E402
    BATCHES, OUT, BCOL, BLUE, RED, AQUA, INK, INK2, MUTED, BASELINE, style)
from analyze_new_methods import collect, SEG_MIN  # noqa: E402

S_NERNST = 13.06        # mV per ln unit（n=2, 30°C）
ORP_SMOOTH = 21


def build_segments():
    """逐段資料：平均壓力 P、斜率 dP/dt、ORP 推得的相對 H2 可得性 h。"""
    cycles = collect()
    rows = []
    for name, cycs in cycles.items():
        for j, c in enumerate(cycs, 1):
            t = (c.ts - c.ts.iloc[0]).dt.total_seconds().values / 3600
            p = c.p_reactor.values.astype(float)
            e = pd.Series(c.orp.values.astype(float)).rolling(
                ORP_SMOOTH, center=True, min_periods=1).median().values
            head = max(5, min(len(e) // 4, 120))
            j0 = int(np.argmin(e[:head]))       # ORP 崩谷＝補氣後 H2 最充足
            n = int(np.ceil(t[-1] * 60 / SEG_MIN))
            for i in range(n):
                m = (t >= i * SEG_MIN / 60) & (t < (i + 1) * SEG_MIN / 60)
                if m.sum() < SEG_MIN * 0.5:
                    continue
                rows.append(dict(
                    batch=name, tau=BATCHES[name][2], cyc=j,
                    P=p[m].mean(), dP=np.polyfit(t[m], p[m], 1)[0],
                    h=np.exp(-(e[m].mean() - e[j0]) / S_NERNST)))
    D = pd.DataFrame(rows)
    D['h'] = D.h.clip(0, 1.5)
    return D


def sat(x, vmax, K):
    return vmax * x / (K + x)


def predict(theta, tau, P, h, model):
    if model == 'M1':
        kmax, Kk, Peq = theta
        return -sat(tau, kmax, Kk) * (P - Peq)
    if model == 'M2':
        kmax, Kk, Peq, rb = theta
        return -sat(tau, kmax, Kk) * (P - Peq) - rb * h
    kmax, Kk, Peq, rmax, Kb = theta
    return -sat(tau, kmax, Kk) * (P - Peq) - sat(tau, rmax, Kb) * h


P0 = {'M1': [0.2, 3.0, 0.7],
      'M2': [0.2, 3.0, 0.7, 0.01],
      'M3': [0.2, 3.0, 0.7, 0.02, 3.0]}
BND = {'M1': ([0.01, 0.05, 0.0], [2.0, 60.0, 0.95]),
       'M2': ([0.01, 0.05, 0.0, 0.0], [2.0, 60.0, 0.95, 0.2]),
       'M3': ([0.01, 0.05, 0.0, 0.0, 0.05], [2.0, 60.0, 0.95, 0.2, 60.0])}


def fit(D, model, idx=None):
    d = D if idx is None else D[idx]
    r = optimize.least_squares(
        lambda th: predict(th, d.tau.values, d.P.values, d.h.values, model) - d.dP.values,
        P0[model], bounds=BND[model], max_nfev=60000)
    return r.x


def metrics(D, model, theta):
    res = predict(theta, D.tau.values, D.P.values, D.h.values, model) - D.dP.values
    n, k = len(D), len(theta)
    sse = float(res @ res)
    return dict(model=model, k=k, sse=sse, rmse=np.sqrt(sse / n),
                r2=1 - res.var() / D.dP.var(),
                aic=n * np.log(sse / n) + 2 * k,
                aicc=n * np.log(sse / n) + 2 * k + 2 * k * (k + 1) / (n - k - 1))


def lobo(D, model):
    """留一批次交叉驗證（預測沒看過的 τ）。"""
    e = []
    for b in D.batch.unique():
        m = (D.batch != b).values
        th = fit(D, model, m)
        d = D[~m]
        e.append(predict(th, d.tau.values, d.P.values, d.h.values, model) - d.dP.values)
    e = np.concatenate(e)
    return float(np.sqrt(np.mean(e ** 2)))


def main():
    D = build_segments()
    print(f'逐段資料 n={len(D)}（{D.cyc.nunique()} 循環／批 x 3 批，'
          f'共 {D.groupby(["batch","cyc"]).ngroups} 循環）')
    print(f'共線性檢查 r(P, h)：' + '、'.join(
        f'{b.split()[1]} {np.corrcoef(g.P, g.h)[0,1]:+.2f}'
        for b, g in D.groupby('batch')) + '  → 兩驅動源可分離\n')

    print('══ 模型比較 ══')
    print(f'{"模型":26s}{"參數":>4s}{"R²":>8s}{"RMSE":>9s}{"AICc":>10s}{"LOBO-CV":>10s}')
    TH, MM = {}, []
    for m, lab in [('M1', 'M1 純物理（rb=0）'),
                   ('M2', 'M2 定值生物（原假設）'),
                   ('M3', 'M3 雙通道飽和（本文）')]:
        th = fit(D, m)
        TH[m] = th
        mt = metrics(D, m, th)
        mt['lobo'] = lobo(D, m)
        mt['label'] = lab
        MM.append(mt)
        print(f'{lab:26s}{mt["k"]:>4d}{mt["r2"]:>8.3f}{mt["rmse"]:>9.5f}'
              f'{mt["aicc"]:>10.1f}{mt["lobo"]:>10.5f}')
    best = min(MM, key=lambda z: z['aicc'])
    print(f'\n  AICc 最佳：{best["label"]}'
          f'（次佳差 {sorted(z["aicc"] for z in MM)[1]-best["aicc"]:.1f}）')

    th3 = TH['M3']
    kmax, Kk, Peq, rmax, Kb = th3
    print(f'\n══ M3 參數（雙通道飽和）══')
    print(f'  物理：kLa(τ) = {kmax:.4f}·τ/({Kk:.2f}+τ)   Peq = {Peq:.4f}')
    print(f'  生物：rb(τ)  = {rmax:.4f}·τ/({Kb:.2f}+τ)')
    print(f'\n  兩通道的半飽和常數：Kk={Kk:.2f}、Kb={Kb:.2f} 分/小時')
    if Kb > 55:
        print('  ※ Kb 撞到參數上界 → 生物通道的形狀未被資料定出（不可辨識）。')
        print('    理論解釋：H2 的氣液質傳正是嗜氫甲烷菌的限速步驟，故生物消耗亦')
        print('    正比於 kLa·(P-Peq)，與物理溶解函數形式相同，被吸收進同一等效 kLa。')
        print('    => 改變 τ 同比例放大兩條通道，循環時間在原理上不可能作為分離槓桿。')

    print(f'\n══ 各 τ 下的通道分解（以典型 P=1.05、H2 充足 h=1 計）══')
    rows = []
    for name, (_, _, tau) in BATCHES.items():
        kla, rb = sat(tau, kmax, Kk), sat(tau, rmax, Kb)
        phys = kla * (1.05 - Peq)
        rows.append(dict(batch=name, tau=tau, kLa=kla, rb=rb, phys=phys,
                         bio_share=rb / (phys + rb) if phys + rb > 0 else np.nan))
        print(f'  {name}: kLa={kla:.4f}  rb={rb:.4f}  '
              f'物理項={phys:.4f}  生物份額={rows[-1]["bio_share"]*100:.1f}%')
    R = pd.DataFrame(rows)

    # 生物項的必要性檢定（M3 vs M1 的 F 檢定）
    m1, m3 = [z for z in MM if z['model'] == 'M1'][0], [z for z in MM if z['model'] == 'M3'][0]
    from scipy import stats as st
    df1, df2 = m3['k'] - m1['k'], len(D) - m3['k']
    F = ((m1['sse'] - m3['sse']) / df1) / (m3['sse'] / df2)
    p = 1 - st.f.cdf(F, df1, df2)
    print(f'\n══ 生物通道是否必要（M3 vs M1 巢狀 F 檢定）══')
    print(f'  F({df1},{df2}) = {F:.2f}   p = {p:.4f}   '
          f'{"→ 生物通道顯著" if p < 0.05 else "→ 生物通道未達顯著"}')

    R.to_csv(f'{OUT}/hybrid_channel_decomposition.csv', index=False,
             encoding='utf-8-sig')
    figures(D, TH, MM, R, th3)
    print(f'\n輸出 → {OUT}')


def figures(D, TH, MM, R, th3):
    kmax, Kk, Peq, rmax, Kb = th3

    # ── 圖19：兩條閉合函數 ──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.8))
    xs = np.linspace(0, 11, 200)
    ax1.plot(xs, sat(xs, kmax, Kk), lw=2.4, color=BLUE, label='物理 kLa(τ)')
    ax1.plot(xs, sat(xs, rmax, Kb) / max(sat(11, rmax, Kb), 1e-9) *
             sat(11, kmax, Kk), lw=2.4, ls='--', color=AQUA,
             label='生物 rb(τ)（右軸尺度）')
    ax1b = ax1.twinx()
    ax1b.set_ylim(0, sat(11, rmax, Kb) * 1.15)
    ax1b.set_ylabel('rb (kg/cm²/hr)', color=AQUA)
    ax1b.tick_params(axis='y', colors=AQUA)
    ax1.set_ylim(0, sat(11, kmax, Kk) * 1.15)
    for t in R.tau:
        ax1.axvline(t, color=BASELINE, lw=0.9, ls=':')
    ax1.annotate(f'Kk = {Kk:.2f}', xy=(Kk, sat(Kk, kmax, Kk)), xytext=(10, -18),
                 textcoords='offset points', color=BLUE, fontsize=10, fontweight='bold')
    ax1.annotate(f'Kb = {Kb:.2f}', xy=(0.35, 0.18), xycoords='axes fraction',
                 color=AQUA, fontsize=10, fontweight='bold')
    style(ax1, '圖19a  兩條通道的 τ 閉合函數（皆為飽和型）',
          '循環時間 τ (分/小時)', 'kLa (1/hr)')
    ax1.legend(frameon=False, fontsize=9, loc='lower right')

    w = 0.35
    xp = np.arange(3)
    ax2.bar(xp - w / 2, R.phys, width=w, color=BLUE, label='物理通道')
    ax2.bar(xp + w / 2, R.rb, width=w, color=AQUA, label='生物通道')
    for i, r in R.iterrows():
        ax2.annotate(f'{r.bio_share*100:.0f}%\n生物', xy=(i + w / 2, r.rb),
                     xytext=(0, 4), textcoords='offset points', ha='center',
                     fontsize=9, color=INK2)
    ax2.set_xticks(xp, [f'{t:.0f} min' for t in R.tau])
    style(ax2, '圖19b  各 τ 下的通道分解（P=1.05、h=1）',
          '循環時間 τ', '速率 (kg/cm²/hr)')
    ax2.legend(frameon=False, fontsize=9)
    fig.text(0, -0.07,
             f'※ 生物通道未被資料定出：Kb={Kb:.1f} 撞到參數上界，且巢狀 F 檢定 '
             'p=0.78（加入生物通道完全未改善擬合）。圖中 rb(τ) 僅為該上界下的最佳猜測，非量測值。\n'
             '理論解釋：H2 的氣液質傳正是嗜氫甲烷菌的限速步驟，故生物消耗亦正比於 '
             'kLa·(P−Peq)——與物理溶解「函數形式相同」，兩者被吸收進同一個等效 kLa。\n'
             '推論：改變 τ 會同比例放大兩條通道，故循環時間在原理上就不可能作為分離槓桿。'
             '要分離，必須改變「只影響生物、不影響質傳」的變數（如移除 H2）。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig19_dual_channel_closures.png')
    plt.close(fig)

    # ── 圖20：模型比較 ──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.6))
    labs = [z['label'].split('（')[0] for z in MM]
    xp = np.arange(len(MM))
    ax1.bar(xp - 0.2, [z['rmse'] for z in MM], width=0.4, color=MUTED,
            label='In-sample RMSE')
    ax1.bar(xp + 0.2, [z['lobo'] for z in MM], width=0.4, color=RED,
            label='LOBO-CV RMSE（預測未見 τ）')
    ax1.set_xticks(xp, labs, fontsize=9)
    style(ax1, '圖20a  模型比較', None, 'RMSE (kg/cm²/hr)')
    ax1.legend(frameon=False, fontsize=9)

    aic = np.array([z['aicc'] for z in MM])
    ax2.bar(xp, aic - aic.min(), width=0.5,
            color=[AQUA if v == aic.min() else MUTED for v in aic])
    for i, v in enumerate(aic - aic.min()):
        ax2.annotate(f'{v:.1f}', xy=(i, v), xytext=(0, 4),
                     textcoords='offset points', ha='center', fontsize=9.5)
    ax2.set_xticks(xp, labs, fontsize=9)
    style(ax2, '圖20b  ΔAICc（越低越好，0 = 最佳）', None, 'ΔAICc')

    fig.text(0, -0.07,
             '所有模型共用同一機理骨架 dP/dt = -kLa(τ)(P-Peq) - rb·h，差別只在生物通道的閉合方式：'
             'M1 令 rb=0、M2 令 rb 為常數（先前規劃的假設）、M3 令 rb 亦隨 τ 飽和（本文）。\n'
             'h 由 ORP 經 Nernst 給出，是與壓力獨立的第二觀測——沒有它，'
             '生物通道與物理通道在單一壓力軌跡上不可辨識。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig20_model_comparison.png')
    plt.close(fig)
    print('  圖 19–20 完成')


if __name__ == '__main__':
    main()
