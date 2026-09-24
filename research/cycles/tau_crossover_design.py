# -*- coding: utf-8 -*-
"""τ 交叉設計：用「多實驗可辨識性」解開 r̄_b —— 先做回收檢定再提議。

2026-09-23。

════════════════════════════════════════════════════════════════════════
想法從哪裡來

  單一循環裡，r̄_b 與 P_eq 是恆等式級的簡併（見 pinn_identifiability_proof.py）：
  只有組合 A = P_eq − r̄_b/k 可辨識。

  但若在**兩種不同的氣泵週期 τ** 下量測，且兩者的 P_eq 與 r̄_b 相同、
  只有 k 不同（k 隨 τ 變已由三批次證實：1→5 min 增 4.2 倍），則

      A₁ = P_eq − r̄_b/k₁
      A₂ = P_eq − r̄_b/k₂
      ──────────────────────────────
      A₁ − A₂ = r̄_b·(1/k₂ − 1/k₁)

      **r̄_b = (A₁ − A₂) / (1/k₂ − 1/k₁)**        …(★)

  k₁、k₂、A₁、A₂ 全都是單一循環就能可靠估計的量。簡併被打開了。

⚠ 先前的 τ 實驗為什麼沒做到這件事

  三批 τ=1/5/10 是**依序**做的，全程未換液 ⟹ τ 與菌齡、飽和度完全共線。
  也就是 (★) 的前提「兩次實驗的 P_eq 與 r̄_b 相同」**不成立**。
  問題出在實驗設計（時間共線），不在數學。

  修正＝**隨機化交叉設計**：同一批液體、同一菌齡下快速交替不同 τ，
  使 τ 與時間去相關。

本檔要回答三個問題（不做完不提議）

  一、(★) 在答案已知的資料上撈不撈得回來？（Rule 8）
  二、需要多大的 k 對比？精度如何隨 Δk 變化？
  三、若前提被破壞（菌齡漂移使 r̄_b 在兩次實驗間不同），偏誤有多大？
      —— 這一項決定交叉設計的「交替週期」要多快。

輸出 -> 純文字
"""
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                        # noqa: E402
from matplotlib import rcParams                        # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from pinn_rb_recovery import QUANT, NOISE              # noqa: E402
from analyze_three_batches import (                    # noqa: E402
    BLUE, RED, AQUA, INK, INK2, MUTED, BASELINE, OUT)

rcParams.update({
    'font.size': 13, 'axes.titlesize': 16, 'axes.labelsize': 14,
    'xtick.labelsize': 12, 'ytick.labelsize': 12, 'legend.fontsize': 12,
})

PEQ_TRUE = 0.75
RB_TRUE = 0.0125            # 論文定版
P0 = 1.17
T_CYC = 6.0                 # 單一循環時長 (hr)
NPTS = 360                  # 每分鐘一筆


def simulate(k, peq, rb, p0=P0, T=T_CYC, n=NPTS, rng=None):
    """解析解 + 量化 + 雜訊。r_b 為常數時 (1) 有閉式解。"""
    t = np.linspace(0, T, n)
    A = peq - rb / k
    P = A + (p0 - A) * np.exp(-k * t)
    if rng is not None:
        P = np.round((P + rng.normal(0, NOISE, n)) / QUANT) * QUANT
    return t, P


def fit_kA(t, P, rounds=4, npts=160):
    """由單一循環估 (k, A)。三參數指數擬合：P = A + (P0−A)e^(−kt)。

    對每個候選 k 以線性最小平方解 A 與振幅 —— 比直接非線性最佳化穩健，
    且不需要初始猜值。

    ⚠ 2026-09-23 修正：原本只掃一層 600 點的固定網格（步長 0.005），
      k 被**量化到網格點上**，A 與 r_b 的估計跟著離散化，
      重抽分布會出現假的梳狀多峰，精度也因而失真。
      改為逐層細化：每一輪把搜尋範圍縮到上一輪最佳點附近，
      四輪後解析度約 10⁻⁶，遠細於雜訊所能決定的程度。
    """
    lo, hi = 0.02, 3.0
    best = None
    for _ in range(rounds):
        ks = np.linspace(lo, hi, npts)
        for k in ks:
            X = np.column_stack([np.ones_like(t), np.exp(-k * t)])
            coef, *_ = np.linalg.lstsq(X, P, rcond=None)
            resid = float(((X @ coef - P) ** 2).sum())
            if best is None or resid < best[0]:
                best = (resid, k, float(coef[0]))
        step = ks[1] - ks[0]
        lo, hi = max(1e-4, best[1] - step), best[1] + step
    return best[1], best[2]          # k, A


def estimate_rb(k1, A1, k2, A2):
    """(★) 式。"""
    denom = 1.0 / k2 - 1.0 / k1
    if abs(denom) < 1e-12:
        return float('nan')
    return (A1 - A2) / denom


def main():
    rng = np.random.default_rng(0)
    print('=' * 70)
    print('一、回收檢定：(★) 撈不撈得回已知的 r̄_b')
    print('=' * 70)
    print('真值　P_eq = %.3f　r̄_b = %.4f' % (PEQ_TRUE, RB_TRUE))
    print('τ 與 k 的對應採三批次實測：τ=1 → k≈0.15、τ=5 → k≈0.63（增 4.2 倍）\n')

    k1, k2 = 0.15, 0.63
    t1, P1 = simulate(k1, PEQ_TRUE, RB_TRUE, rng=rng)
    t2, P2 = simulate(k2, PEQ_TRUE, RB_TRUE, rng=rng)
    kh1, Ah1 = fit_kA(t1, P1)
    kh2, Ah2 = fit_kA(t2, P2)
    print('  實驗 1（τ 小）  k 真值 %.3f -> 估 %.3f　A 真值 %.5f -> 估 %.5f'
          % (k1, kh1, PEQ_TRUE - RB_TRUE / k1, Ah1))
    print('  實驗 2（τ 大）  k 真值 %.3f -> 估 %.3f　A 真值 %.5f -> 估 %.5f'
          % (k2, kh2, PEQ_TRUE - RB_TRUE / k2, Ah2))
    rb_hat = estimate_rb(kh1, Ah1, kh2, Ah2)
    print('\n  (★) 推得 r̄_b = %.5f（真值 %.5f，誤差 %+.1f%%）'
          % (rb_hat, RB_TRUE, (rb_hat / RB_TRUE - 1) * 100))

    print('\n  單次沒有意義，跑 300 次重抽看散布：')
    est = []
    for _ in range(300):
        _, Pa = simulate(k1, PEQ_TRUE, RB_TRUE, rng=rng)
        _, Pb = simulate(k2, PEQ_TRUE, RB_TRUE, rng=rng)
        ka, Aa = fit_kA(t1, Pa)
        kb, Ab = fit_kA(t2, Pb)
        est.append(estimate_rb(ka, Aa, kb, Ab))
    est = np.array(est)
    lo, hi = np.percentile(est, [2.5, 97.5])
    print('    中位 %.5f　95%% 區間 [%.5f, %.5f]' % (np.median(est), lo, hi))
    print('    偏誤 %+.1f%%　相對精度 ±%.1f%%'
          % ((np.median(est) / RB_TRUE - 1) * 100,
             (hi - lo) / 2 / RB_TRUE * 100))
    ok = lo < RB_TRUE < hi
    print('    -> %s' % ('真值落在區間內，方法可用' if ok else
                         '⚠ 真值落在區間外，方法有偏誤'))

    print('\n' + '=' * 70)
    print('二、需要多大的 k 對比？')
    print('=' * 70)
    print('  (★) 的分母是 1/k₂ − 1/k₁，兩個 k 越接近，分母越小、誤差被放得越大。\n')
    print('  %-10s %-10s %-12s %s' % ('k₁', 'k₂', 'k 的倍數', '相對精度'))
    for ratio in (1.5, 2.0, 3.0, 4.2, 8.0):
        ka_t, kb_t = 0.15, 0.15 * ratio
        e = []
        for _ in range(150):
            _, Pa = simulate(ka_t, PEQ_TRUE, RB_TRUE, rng=rng)
            _, Pb = simulate(kb_t, PEQ_TRUE, RB_TRUE, rng=rng)
            t_a = np.linspace(0, T_CYC, NPTS)
            ka, Aa = fit_kA(t_a, Pa)
            kb, Ab = fit_kA(t_a, Pb)
            e.append(estimate_rb(ka, Aa, kb, Ab))
        e = np.array(e)
        p = np.percentile(e, [2.5, 97.5])
        print('  %-10.2f %-10.2f %-12.1f ±%.1f%%'
              % (ka_t, kb_t, ratio, (p[1] - p[0]) / 2 / RB_TRUE * 100))
    print('\n  -> 實測的 4.2 倍對比落在哪一檔，即為可期待的精度。')

    print('\n' + '=' * 70)
    print('三、前提被破壞時的偏誤：交替要多快？')
    print('=' * 70)
    print('  (★) 要求兩次實驗的 r̄_b 相同。若菌齡漂移使其相差 x%%，偏誤多大？\n')
    print('  %-16s %-14s %s' % ('r̄_b 漂移', '推得的 r̄_b', '偏誤'))
    for drift in (0.0, 0.02, 0.05, 0.10, 0.20):
        e = []
        for _ in range(150):
            _, Pa = simulate(k1, PEQ_TRUE, RB_TRUE, rng=rng)
            _, Pb = simulate(k2, PEQ_TRUE, RB_TRUE * (1 + drift), rng=rng)
            t_a = np.linspace(0, T_CYC, NPTS)
            ka, Aa = fit_kA(t_a, Pa)
            kb, Ab = fit_kA(t_a, Pb)
            e.append(estimate_rb(ka, Aa, kb, Ab))
        m = float(np.median(e))
        print('  %-16s %-14.5f %+.1f%%'
              % ('%.0f%%' % (drift * 100), m, (m / RB_TRUE - 1) * 100))
    print('\n  ⚠ 這一欄決定交叉設計的交替週期：偏誤必須小於目標精度。')

    print('\n' + '=' * 70)
    print('四、要幾對循環才夠？（決定實驗要跑幾天）')
    print('=' * 70)
    single = (hi - lo) / 2 / RB_TRUE * 100          # 單對的相對精度 (%)
    print('  單對循環的相對精度 ±%.1f%%；N 對平均後約 ∝ 1/√N。' % single)
    print('  裝置每天自動產生約 2.2 次循環，交叉設計下每天約 1.1 對。\n')
    print('  %-12s %-14s %s' % ('目標精度', '需要的對數', '約需天數'))
    for target in (20, 15, 11, 8, 5):
        n = max(1, int(np.ceil((single / target) ** 2)))
        print('  %-12s %-14d %.1f' % ('±%d%%' % target, n, n / 1.1))
    print('\n  對照：現行定版 r_b = 0.0125 的區間為 ±11.0%。')
    print('  ⚠ 上表為 1/√N 外推，與下方實測略有出入（中位數的收斂非嚴格 1/√N）；')
    print('    規劃天數時以下方實測為準。')

    # 直接驗證 N 對平均確實收斂，不只靠 1/√N 的理論
    print('\n  實際驗證（不套 1/√N，直接模擬多對取中位）：')
    for npair in (1, 3, 10, 30):
        meds = []
        for _ in range(120):
            vals = []
            for _ in range(npair):
                _, Pa = simulate(k1, PEQ_TRUE, RB_TRUE, rng=rng)
                _, Pb = simulate(k2, PEQ_TRUE, RB_TRUE, rng=rng)
                ta = np.linspace(0, T_CYC, NPTS)
                ka, Aa = fit_kA(ta, Pa)
                kb, Ab = fit_kA(ta, Pb)
                vals.append(estimate_rb(ka, Aa, kb, Ab))
            meds.append(np.median(vals))
        q = np.percentile(meds, [2.5, 97.5])
        print('    %2d 對  中位 %.5f  95%% 區間 [%.5f, %.5f]  ±%.1f%%'
              % (npair, np.median(meds), q[0], q[1],
                 (q[1] - q[0]) / 2 / RB_TRUE * 100))

    print('\n' + '=' * 70)
    print('五、判讀')
    print('=' * 70)
    print('  (★) 只用壓力，不需要任何新感測器，也不依賴模擬器校準。')
    print('  它唯一的要求是「同一批液體、同一菌齡下取得兩種不同的 k」——')
    print('  亦即把先前依序進行的 τ 實驗，改為**隨機化交叉設計**。')
    print('  ⚠ 但 r̄_b 在此仍含「生物 + 洩漏」：本式分開的是「隨 k 變的」與')
    print('    「不隨 k 變的」，洩漏也不隨 k 變，故會被算進 r̄_b。')
    print('    ⟹ 仍須先做無菌對照定出洩漏項，(★) 才能解讀為生物速率。')


def style(ax, title=None, xlabel=None, ylabel=None):
    if title:
        ax.set_title(title, color=INK, fontweight='bold', loc='left', pad=10)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(True, linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    for s_ in ('top', 'right'):
        ax.spines[s_].set_visible(False)
    return ax


def headroom(ax, top=0.0, bottom=0.0):
    """★先留白再放字。"""
    lo, hi = ax.get_ylim()
    sp = hi - lo
    ax.set_ylim(lo - sp * bottom, hi + sp * top)


def make_figure(k1=0.15, k2=0.63, nrep=200):
    """三張面板：為什麼可行 / 撈不撈得回來 / 要跑幾天。"""
    rng = np.random.default_rng(1)
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(15.0, 4.8),
                                     gridspec_kw={'wspace': 0.30})

    # ── a：兩種 τ 的曲線與各自的漸近線 ─────────────────
    t = np.linspace(0, T_CYC, 400)
    for k, col, lab in ((k1, BLUE, 'τ 小（氣泵少開）'),
                        (k2, AQUA, 'τ 大（氣泵多開）')):
        A = PEQ_TRUE - RB_TRUE / k
        P = A + (P0 - A) * np.exp(-k * t)
        a1.plot(t, P, color=col, lw=3.0, label=lab)
        a1.axhline(A, color=col, lw=1.8, ls=':')
    A1 = PEQ_TRUE - RB_TRUE / k1
    A2 = PEQ_TRUE - RB_TRUE / k2
    # 箭頭貼右緣，文字放其左側並留出間距，避免壓線
    a1.annotate('', xy=(T_CYC * 0.985, A1), xytext=(T_CYC * 0.985, A2),
                arrowprops=dict(arrowstyle='<->', color=RED, lw=2.4))
    a1.text(T_CYC * 0.94, (A1 + A2) / 2, 'A₁−A₂',
            color=RED, fontsize=14, fontweight='bold', ha='right', va='center')
    a1.legend(loc='upper right', frameon=False)
    headroom(a1, bottom=0.34)
    a1.text(0.03, 0.03,
            '兩條曲線停在不同高度。\n'
            '這段高度差只由生物速率決定，\n'
            '量它就等於量到答案。',
            transform=a1.transAxes, fontsize=12, color=INK2,
            ha='left', va='bottom')
    style(a1, 'a　為什麼兩種 τ 就夠', '小時', '壓力 (kgf/cm²)')

    # ── b：回收檢定的分布 ─────────────────────────────
    est = []
    tt = np.linspace(0, T_CYC, NPTS)
    for _ in range(nrep):
        _, Pa = simulate(k1, PEQ_TRUE, RB_TRUE, rng=rng)
        _, Pb = simulate(k2, PEQ_TRUE, RB_TRUE, rng=rng)
        ka, Aa = fit_kA(tt, Pa)
        kb, Ab = fit_kA(tt, Pb)
        est.append(estimate_rb(ka, Aa, kb, Ab))
    est = np.array(est) * 1000
    a2.hist(est, bins=26, color=BLUE, edgecolor='white')
    a2.axvline(RB_TRUE * 1000, color=RED, lw=2.8, ls='--')
    # ★先留白再放字；「真正的答案」擺在紅線正上方的空白區，不壓柱子
    headroom(a2, top=0.62)
    _, hi = a2.get_ylim()
    a2.text(RB_TRUE * 1000, hi * 0.76, '真正的答案', color=RED, fontsize=13,
            fontweight='bold', ha='center', va='bottom')
    # 分兩行，免得單行太寬而被中央的紅虛線穿過
    a2.text(0.02, 0.985,
            '%d 次重抽\n偏誤 %+.1f%%' %
            (nrep, (np.median(est) / (RB_TRUE * 1000) - 1) * 100),
            transform=a2.transAxes, fontsize=12.5, color=INK,
            fontweight='bold', ha='left', va='top')
    style(a2, 'b　撈得回來嗎（已知答案的檢定）',
          '推得的生物速率 (×10⁻³)', '次數')

    # ── c：要跑幾天 ───────────────────────────────────
    pairs = (1, 3, 10, 30)
    prec = []
    for npair in pairs:
        meds = []
        for _ in range(90):
            vals = []
            for _ in range(npair):
                _, Pa = simulate(k1, PEQ_TRUE, RB_TRUE, rng=rng)
                _, Pb = simulate(k2, PEQ_TRUE, RB_TRUE, rng=rng)
                ka, Aa = fit_kA(tt, Pa)
                kb, Ab = fit_kA(tt, Pb)
                vals.append(estimate_rb(ka, Aa, kb, Ab))
            meds.append(np.median(vals))
        q = np.percentile(meds, [2.5, 97.5])
        prec.append((q[1] - q[0]) / 2 / RB_TRUE * 100)
    days = [n / 1.1 for n in pairs]
    a3.plot(days, prec, marker='o', ms=12, lw=3.0, color=BLUE)
    a3.axhline(11.0, color=RED, lw=2.4, ls='--')
    a3.set_xscale('log')
    a3.set_xticks(days)
    a3.set_xticklabels(['%.0f' % d if d >= 1 else '%.1f' % d for d in days])
    a3.minorticks_off()
    headroom(a3, top=0.42)
    a3.text(days[-1], 11.0, '現行方法 ±11% ', color=RED, fontsize=12.5,
            ha='right', va='bottom')
    for d, p_ in zip(days, prec):
        a3.annotate('±%.0f%%' % p_, xy=(d, p_), xytext=(0, 11),
                    textcoords='offset points', ha='center',
                    fontsize=12, color=INK)
    a3.text(0.03, 0.97,
            '約 9 天就追平並超越現行方法，\n而且不依賴模擬器校準。',
            transform=a3.transAxes, fontsize=12.5, color=INK2,
            ha='left', va='top')
    style(a3, 'c　要跑幾天', '實驗天數（每天約 1.1 對循環）', '相對精度 (±%)')

    out = os.path.join(OUT, 'fig46_tau_crossover.png')
    fig.savefig(out)
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    if '--fig' in sys.argv:
        make_figure()
    else:
        main()
        make_figure()
