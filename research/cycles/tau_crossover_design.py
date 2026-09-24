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

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from pinn_rb_recovery import QUANT, NOISE              # noqa: E402

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


def fit_kA(t, P):
    """由單一循環估 (k, A)。三參數指數擬合：P = A + (P0−A)e^(−kt)。

    用網格搜 k、對每個 k 以線性最小平方解 A 與振幅 —— 比直接非線性
    最佳化穩健，且不需要初始猜值。
    """
    best = None
    for k in np.linspace(0.02, 3.0, 600):
        X = np.column_stack([np.ones_like(t), np.exp(-k * t)])
        coef, *_ = np.linalg.lstsq(X, P, rcond=None)
        resid = float(((X @ coef - P) ** 2).sum())
        if best is None or resid < best[0]:
            best = (resid, k, float(coef[0]))
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


if __name__ == '__main__':
    main()
