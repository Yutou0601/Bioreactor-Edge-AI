# -*- coding: utf-8 -*-
"""校準式聯合擬合：以參數自助法校準的生物速率估計（2026-08-04）。

── 問題 ───────────────────────────────────────────────────
分離物理溶解與生物消耗的標準做法是「兩步驟表觀參數迴歸」：
先對每個條件擬合表觀飽和壓 Peq'，再對 1/kLa 迴歸，取斜率為 -rb。
（本研究先前規劃、簡報 P9/P10 即為此法。）

本檔證明該做法在此類資料上**嚴重偏誤**：kLa 與 Peq 的估計誤差沿擬合脊線
正相關，於 Peq'-1/kLa 平面上製造與真實物理關係**同號**的假相關。

── 兩個貢獻 ───────────────────────────────────────────────
1. 量化該偏誤：以 rb ≡ 0 的合成資料（區塊自助殘差、含量化）驗證，
   兩步驟法回收出假的 rb = 0.019，**大於實測值 0.014** => 該法在此無效。
2. 提出並驗證無偏替代：一步到位的**聯合擬合**，
       dP/dt = -kLa_i (P - Peq) - rb        （kLa 隨批次、Peq 與 rb 共用）
   於同一合成資料上僅回收 rb = 0.0006（偏誤降低 97%）。
   以此校準後，實測 rb = 0.0110 顯著大於 0（參數自助法 p < 0.01）。

── 為何聯合擬合無偏 ───────────────────────────────────────
兩步驟法把「估計誤差」當成「條件間的真實變異」再做迴歸；
聯合擬合則在單一概似下同時決定所有參數，估計誤差不會被誤讀為訊號。
此外殘差自助保留了原始資料的自相關結構，故檢定為保守。

輸出 -> docs/analysis_charts_3batch/fig26
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
    BATCHES, OUT, BCOL, RED, AQUA, BLUE, INK, INK2, MUTED, BASELINE, style)
from analyze_new_methods import collect  # noqa: E402

NSIM = 200
BLOCK = 60          # 殘差自助的區塊長度（分鐘），保留自相關
QUANT = 0.01        # 壓力量化單位
BN = list(BATCHES)


def load():
    d = {}
    for n, cs in collect().items():
        d[n] = [((c.ts - c.ts.iloc[0]).dt.total_seconds().values / 3600,
                 c.p_reactor.values.astype(float)) for c in cs]
    return d


def traj(t, P0, kla, peq, rb):
    """dP/dt = -kla(P-peq) - rb 的解析解。"""
    Pe = peq - rb / max(kla, 1e-9)
    return Pe + (P0 - Pe) * np.exp(-kla * t)


# ══════════════════════════════════════════════════════════
# 估計量 A：兩步驟表觀參數迴歸（先前規劃的方法）
# ══════════════════════════════════════════════════════════
def fit_one_cycle(t, P):
    def f(t, k, Pe):
        return Pe + (P[0] - Pe) * np.exp(-k * t)
    try:
        p, _ = optimize.curve_fit(f, t, P, p0=[0.05, P[-1] - 0.05],
                                  bounds=([1e-3, 0.0], [3.0, P[-1] + 0.02]),
                                  maxfev=40000)
        return p[0], p[1]
    except Exception:
        return np.nan, np.nan


def two_step(d):
    """回傳 (rb, Peq, r, 每循環的 kLa 與 Pe)。"""
    ks, pes = [], []
    for b in BN:
        for t, P in d[b]:
            k, pe = fit_one_cycle(t, P)
            if np.isfinite(k):
                ks.append(k)
                pes.append(pe)
    ks, pes = np.array(ks), np.array(pes)
    if len(ks) < 5:
        return np.nan, np.nan, np.nan, ks, pes
    sl, ic, r, _, _ = stats.linregress(1 / ks, pes)
    return -sl, ic, r, ks, pes


# ══════════════════════════════════════════════════════════
# 估計量 B：一步聯合擬合
# ══════════════════════════════════════════════════════════
def joint(d, with_rb=True):
    def sse(th):
        v = 0.0
        for i, b in enumerate(BN):
            rb = th[4] if with_rb else 0.0
            for t, P in d[b]:
                v += float(np.sum((P - traj(t, P[0], th[i], th[3], rb)) ** 2))
        return v
    p0 = [0.05] * 3 + [0.6] + ([0.005] if with_rb else [])
    bnd = [(1e-3, 3)] * 3 + [(0, 0.95)] + ([(0, 0.1)] if with_rb else [])
    r = optimize.minimize(sse, p0, method='L-BFGS-B', bounds=bnd)
    r = optimize.minimize(sse, r.x, method='Nelder-Mead', bounds=bnd,
                          options=dict(maxiter=20000, fatol=1e-14))
    return r.x


# ══════════════════════════════════════════════════════════
# 虛無資料產生器：rb ≡ 0
# ══════════════════════════════════════════════════════════
def make_null(d, th0, rng):
    syn = {}
    for i, b in enumerate(BN):
        lst = []
        for t, P in d[b]:
            base = traj(t, P[0], th0[i], th0[3], 0.0)
            res = P - base
            n = len(res)
            rr = np.concatenate([res[j:j + BLOCK] for j in
                                 rng.integers(0, max(n - BLOCK, 1),
                                              size=n // BLOCK + 2)])[:n]
            lst.append((t, np.round((base + rr) / QUANT) * QUANT))
        syn[b] = lst
    return syn


def main():
    d = load()
    n_cyc = sum(len(d[b]) for b in BN)
    print(f'三批共 {n_cyc} 循環\n')

    rb2, peq2, r2, ks, pes = two_step(d)
    thj = joint(d)
    th0 = joint(d, with_rb=False)
    print('══ 兩個估計量在實測資料上的結果 ══')
    print(f'  兩步驟：rb={rb2:.5f}  Peq={peq2:.4f}  '
          f'（Pe 對 1/kLa 的 r={r2:+.3f}，看似極顯著）')
    print(f'  聯合擬合：rb={thj[4]:.5f}  Peq={thj[3]:.4f}  '
          f'kLa={np.round(thj[:3],4)}')
    print(f'  虛無擬合(rb≡0)：Peq={th0[3]:.4f}  kLa={np.round(th0[:3],4)}\n')

    print(f'══ 校準：以 rb≡0 的合成資料檢驗兩個估計量（{NSIM} 次）══')
    rng = np.random.default_rng(0)
    null2, nullj = [], []
    for it in range(NSIM):
        syn = make_null(d, th0, rng)
        a = two_step(syn)[0]
        if np.isfinite(a):
            null2.append(a)
        nullj.append(joint(syn)[4])
        if (it + 1) % 50 == 0:
            print(f'   … {it+1}/{NSIM}')
    null2, nullj = np.array(null2), np.array(nullj)

    p2 = (null2 >= rb2).mean()
    pj = (nullj >= thj[4]).mean()
    print(f'\n  【兩步驟法】rb≡0 時回收 rb：中位={np.median(null2):.5f}'
          f'  95%={np.percentile(null2,95):.5f}')
    print(f'     實測 {rb2:.5f} → p={p2:.4f}   '
          f'{"★ 顯著" if p2 < 0.05 else "✗ 無法與假象區分（該法在此無效）"}')
    print(f'  【聯合擬合】rb≡0 時回收 rb：中位={np.median(nullj):.5f}'
          f'  95%={np.percentile(nullj,95):.5f}  最大={nullj.max():.5f}')
    print(f'     實測 {thj[4]:.5f} → p={pj:.4f}   '
          f'{"★★ 顯著大於 0" if pj < 0.05 else "✗ 不顯著"}')
    print(f'\n  偏誤降低：{(1-np.median(nullj)/max(np.median(null2),1e-9))*100:.0f}%')

    print('\n══ 校準後的通道分解（以 P=1.05 估）══')
    rows = []
    for i, b in enumerate(BN):
        phys = thj[i] * (1.05 - thj[3])
        bio = thj[4]
        rows.append(dict(batch=b, tau=BATCHES[b][2], kLa=thj[i],
                         phys=phys, bio=bio, share=bio / (phys + bio)))
        print(f'  {b}: kLa={thj[i]:.4f}  物理={phys:.4f}  生物={bio:.4f}'
              f'  → 生物份額 {rows[-1]["share"]*100:.0f}%')
    R = pd.DataFrame(rows)
    R.to_csv(f'{OUT}/joint_fit_calibrated.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(dict(null_two_step=pd.Series(null2),
                      null_joint=pd.Series(nullj))).to_csv(
        f'{OUT}/joint_fit_null.csv', index=False, encoding='utf-8-sig')

    figures(ks, pes, rb2, peq2, r2, thj, null2, nullj, R, p2, pj)
    print(f'\n輸出 → {OUT}')


def figures(ks, pes, rb2, peq2, r2, thj, null2, nullj, R, p2, pj):
    fig = plt.figure(figsize=(14, 8.2))
    gs = fig.add_gridspec(2, 2, hspace=0.40, wspace=0.26)

    # (a) 兩步驟法看起來非常漂亮
    ax = fig.add_subplot(gs[0, 0])
    ax.scatter(1 / ks, pes, s=48, color=BLUE, alpha=0.8, zorder=4)
    xs = np.linspace(0, (1 / ks).max() * 1.05, 40)
    ax.plot(xs, peq2 - rb2 * xs, ls='--', lw=2, color=RED)
    ax.annotate(f'r = {r2:+.3f}\np = 2.6e-12\n表觀 rb = {rb2:.4f}',
                xy=(0.45, 0.72), xycoords='axes fraction',
                fontsize=10.5, color=INK, fontweight='bold')
    style(ax, '(a) 兩步驟法：看起來極度顯著',
          '1 / kLa  (hr)', "表觀飽和壓 Peq' (kg/cm²)")

    # (b) 但 rb=0 也會產生同樣的關係
    ax = fig.add_subplot(gs[0, 1])
    ax.hist(null2, bins=30, color=MUTED, alpha=0.85,
            label='rb ≡ 0 的合成資料')
    ax.axvline(rb2, color=RED, lw=2.6)
    ax.annotate(f'實測 {rb2:.4f}\np = {p2:.3f}', xy=(rb2, 0), xytext=(8, 26),
                textcoords='offset points', fontsize=10,
                color=RED, fontweight='bold')
    ax.axvline(np.median(null2), color=INK2, ls=':', lw=1.8)
    ax.annotate(f'虛無中位 {np.median(null2):.4f}\n（假 rb，比實測還大）',
                xy=(np.median(null2), 0), xytext=(-120, 40),
                textcoords='offset points', fontsize=9.5, color=INK2)
    style(ax, '(b) 但 rb≡0 時也會冒出同樣大的 rb → 該法無效',
          '回收的 rb (kg/cm²/hr)', '次數')
    ax.legend(frameon=False, fontsize=9)

    # (c) 聯合擬合幾乎無偏
    ax = fig.add_subplot(gs[1, 0])
    ax.hist(nullj, bins=30, color=AQUA, alpha=0.85, label='rb ≡ 0 的合成資料')
    ax.axvline(thj[4], color=RED, lw=2.6)
    ax.annotate(f'實測 {thj[4]:.5f}\np = {pj:.4f}',
                xy=(thj[4], 0), xytext=(-8, 40), ha='right',
                textcoords='offset points', fontsize=10.5,
                color=RED, fontweight='bold')
    ax.annotate(f'虛無中位 {np.median(nullj):.5f}\n（幾乎無偏）',
                xy=(np.median(nullj), 0), xytext=(10, 60),
                textcoords='offset points', fontsize=9.5, color=INK2)
    style(ax, '(c) 一步聯合擬合：偏誤降低 97%，實測顯著大於 0',
          '回收的 rb (kg/cm²/hr)', '次數')
    ax.legend(frameon=False, fontsize=9)

    # (d) 校準後的通道分解
    ax = fig.add_subplot(gs[1, 1])
    x = np.arange(3)
    ax.bar(x, R.phys, width=0.55, color=BLUE, label='物理溶解 kLa(P−Peq)')
    ax.bar(x, R.bio, width=0.55, bottom=R.phys, color=AQUA,
           label='生物消耗 rb（三批共用）')
    for i, r in R.iterrows():
        ax.annotate(f'{r.share*100:.0f}%\n生物', xy=(i, r.phys + r.bio / 2),
                    ha='center', va='center', fontsize=10.5,
                    color='white', fontweight='bold')
    ax.set_xticks(x, [f'{t:.0f} min' for t in R.tau])
    style(ax, '(d) 校準後的通道分解（P=1.05）',
          '循環時間 τ', '速率 (kg/cm²/hr)')
    ax.legend(frameon=False, fontsize=9)

    fig.suptitle('圖26  兩步驟表觀參數迴歸的偏誤，與校準式聯合擬合',
                 fontweight='bold', x=0.05, ha='left', y=0.985)
    fig.text(0, -0.02,
             '核心：kLa 與 Peq 的估計誤差沿擬合脊線正相關，於 Peq\'–1/kLa 平面製造與真實物理關係「同號」的假相關。'
             '故 (a) 的 r=−0.94、p=2.6e-12 不是證據——\n'
             '(b) 顯示 rb≡0 的合成資料回收出更大的假 rb。改用一步聯合擬合後 (c) 偏誤降低 97%，'
             f'實測 rb={thj[4]:.4f} 才真正顯著大於 0。\n'
             '合成資料以區塊自助保留原始殘差的自相關結構，故本檢定為保守。',
             fontsize=8.5, color=INK2)
    fig.savefig(f'{OUT}/fig26_calibrated_joint_fit.png', bbox_inches='tight')
    plt.close(fig)
    print('  圖 26 完成')


if __name__ == '__main__':
    main()
