# -*- coding: utf-8 -*-
"""實驗設計模擬：哪一種實驗能讓 r̄_b 變得可辨識？—— GPU 一次評估幾百種設計。

2026-10-16。

════════════════════════════════════════════════════════════════════════
為什麼要重做（前期分析已有）
  tau_crossover_design.py（9/23）證明：兩種 τ 下 k 不同、P_eq 與 r̄_b 相同時，
      A = P_eq − r̄_b / k      ⟹   r̄_b = (A₁ − A₂) / (1/k₂ − 1/k₁)
  可以打開單一循環裡的簡併。當時的精度分析假設 k₁ = 0.15、k₂ = 0.63（τ 讓 k 差 4.2 倍）。

  但 10/16 的實測讓兩個前提變得不確定：
    · 論文估計器的逐循環 k：τ=1 批 0.32、τ=5 批 0.19、τ=10 批 0.01（15 個裡 10 個撞網格
      下限）；PINN 給 0.047／0.059／0.041。兩者差到 7 倍，且**都沒有顯示 k 隨 τ 變大**。
    · 很多循環 k·T < 1（曲線近乎直線），k 本身就估不準（pinn_batched --real：5/29 個循環
      連 A 都定不了）。
  所以要在**真實條件**下重問：k 要差幾倍、要幾個循環、循環多長，r̄_b 才估得準？

模擬（每種設計 R 次重複實驗）
  · 每個循環：P(t) = A + (P0 − A)·e^(−k t)，A = P_eq − r̄_b/k（r̄_b 為常數時的解析解），
    每分鐘一筆，加雜訊 0.004、量化 0.01（與 pinn_rb_recovery 相同）。
  · 旋鈕：基準 k₁；τ 造成的 k 倍數 ρ（1＝沒改 τ）；每種條件的循環數 N；循環長度 T；
    循環間 k 的自然浮動（對數常態 σ）；兩條件間 r̄_b 的漂移 δ（菌齡、交替不夠快）。
  · 估計：逐循環在 k 的對數網格上解線性最小平方（給定 k，模型對 (A, P0) 是線性的），
    取殘差最小的 k̂（拋物線內插細化）→ (Â_i, k̂_i)；再以全部循環做迴歸
    Â_i = P_eq − r̄_b·(1/k̂_i) 得 r̂_b。與 9/23 的 (★) 是同一件事的 N 循環版。
  ⚠ 全部設計估到的都是 r̄_b = r_bio + r_leak：洩漏也是定速項、也不隨 k 變（實驗規劃 B.4）。
    要分開兩者仍需修漏前後對照或無菌保壓。本檔只回答「r̄_b 這個總和估不估得出來」。
  ⚠ 不含泵的每小時鋸齒（τ=5／10 批的擬合 RMSE 因此高於雜訊下限）與 k 在循環內的變化。
    結論是相對比較，不是絕對精度。

校準：⚠ 白雜訊模擬會嚴重高估（2026-10-16 實測）
  · 只有量測雜訊時，跨循環迴歸的殘差 SD 約 0.002；真實 τ 批內是 0.05–0.09（20–50 倍）。
  · 假象：讓 k 完全不變、只有估計雜訊，跨循環迴歸照樣得出 r̂_b ≈ 平均降速、P̂_eq ≈ 起點
    壓力（k=0.05：0.026 vs 降速 0.028；P̂_eq 1.03）——與真實資料的圖樣（r̂_b 0.022–0.034、
    P̂_eq 0.95–1.12、相關 −0.97）一模一樣。⟹ 真實資料上「跨循環迴歸出的 r_b」不可信
    （含 9/23 曲率配對的證據，應回頭重看）。
  · 真實 k̂ 的循環間變異 vs 單一循環內的估計變異（區塊殘差重抽）：信度 τ=1 0、τ=5 0.70、
    τ=10 0。單一真實循環的 k̂ 本身就有 1.3–2.3 倍的不確定度；白雜訊模擬只有 2–7%。
  ⟹ 本檔的設計表只在「k 對比是真的、且遠大於估計誤差」時成立；「不改 τ、靠自然浮動」
    的設計在真實條件下不成立。改用真實殘差的版本見 separation_sim.py。

輸出 -> research/ml/out_design_identifiability/designs.csv
用法（在 Jetson）：ML_DEVICE=cuda python3 design_identifiability.py
"""
import csv
import itertools
import math
import os
import sys
import time

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out_design_identifiability')
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DEVICE = torch.device(os.environ.get('ML_DEVICE', 'cpu'))
# ⚠ 一律 fp64：k·T 小時基底 {1, e^(−kt)} 幾乎共線，fp32 會選錯 k（論文 Algorithm 1 的教訓）
DT = torch.float64

PEQ, RB, P0 = 0.75, 0.0125, 1.17        # 論文定版 r̄_b；P0 為真實循環的典型起點
NOISE, QUANT = 0.004, 0.01
KGRID = torch.logspace(math.log10(0.003), math.log10(3.0), 160, dtype=DT)


def fit_cycles(y, t):
    """y: (B, n) 觀測；t: (n,)。回傳 k̂、Â、是否撞網格邊界。全部向量化。

    給定 k，P = a + b·e^(−kt) 對 (a, b) 是線性的：2×2 正規方程有閉式解。
    在 k 網格上算殘差平方和，取最小者，再對 log k 做拋物線內插。
    """
    g = KGRID.to(y.device)
    E = torch.exp(-g[:, None] * t[None, :])                  # (G, n)
    n = t.numel()
    Se = E.sum(1)                                            # (G,)
    See = (E * E).sum(1)
    det = n * See - Se ** 2
    Sy = y.sum(1)                                            # (B,)
    Syy = (y * y).sum(1)
    Sey = E @ y.T                                            # (G, B)
    a = (See[:, None] * Sy[None, :] - Se[:, None] * Sey) / det[:, None]
    b = (n * Sey - Se[:, None] * Sy[None, :]) / det[:, None]
    rss = Syy[None, :] - a * Sy[None, :] - b * Sey           # (G, B)
    j = torch.argmin(rss, 0)                                 # (B,)
    G = g.numel()
    edge = (j == 0) | (j == G - 1)
    jc = j.clamp(1, G - 2)
    cols = torch.arange(y.shape[0], device=y.device)
    r0, r1, r2 = rss[jc - 1, cols], rss[jc, cols], rss[jc + 1, cols]
    lg = torch.log(g)
    h = lg[1] - lg[0]
    denom = r0 - 2 * r1 + r2
    off = torch.where(denom > 0, 0.5 * (r0 - r2) / denom, torch.zeros_like(denom)).clamp(-1, 1)
    logk = torch.where(edge, lg[j], lg[jc] + off * h)
    k = torch.exp(logk)
    # 用細化後的 k 重算 A（＝a）
    e = torch.exp(-k[:, None] * t[None, :])
    Se1, See1 = e.sum(1), (e * e).sum(1)
    Sey1 = (e * y).sum(1)
    det1 = n * See1 - Se1 ** 2
    A = (See1 * Sy - Se1 * Sey1) / det1
    return k, A, edge


def run_design(k1, rho, N, T, sig, drift, R, gen, psig=0.0):
    """一種設計 × R 次重複實驗。回傳 r̂_b 陣列與撞邊界比例。

    psig：每個循環的 P_eq 各自浮動的標準差（kg/cm²）——補氣組成、溶解 CO2 等使平衡
    壓力逐循環不同。⚠ 沒有這一項時模擬過度樂觀（見檔頭「校準」）。
    """
    t = torch.arange(0, T * 60 + 1, dtype=DT, device=DEVICE) / 60.0        # 每分鐘一筆
    M = 2 * N                                            # 兩種條件各 N 個循環
    cond = torch.cat([torch.zeros(N), torch.ones(N)]).to(DEVICE, DT)       # (M,)
    kc = torch.where(cond > 0, torch.tensor(k1 * rho, dtype=DT, device=DEVICE),
                     torch.tensor(k1, dtype=DT, device=DEVICE))
    rbc = RB * (1 + drift * cond)                        # 條件 2 的 r̄_b 漂移 δ
    # 每個循環的實際 k：條件值 × 對數常態浮動
    z = torch.randn(R, M, generator=gen, dtype=DT, device=DEVICE)
    k = kc[None, :] * torch.exp(sig * z)                 # (R, M)
    peq = PEQ + psig * torch.randn(R, M, generator=gen, dtype=DT, device=DEVICE)
    A = peq - rbc[None, :] / k
    P = A[..., None] + (P0 - A[..., None]) * torch.exp(-k[..., None] * t[None, None, :])
    P = P + NOISE * torch.randn(P.shape, generator=gen, dtype=DT, device=DEVICE)
    P = torch.round(P / QUANT) * QUANT
    kh, Ah, edge = fit_cycles(P.reshape(R * M, -1), t)
    kh, Ah = kh.reshape(R, M), Ah.reshape(R, M)
    # 迴歸 Â = P_eq − r̄_b · (1/k̂)
    x = 1.0 / kh
    xm, ym = x.mean(1, keepdim=True), Ah.mean(1, keepdim=True)
    sxx = ((x - xm) ** 2).sum(1)
    sxy = ((x - xm) * (Ah - ym)).sum(1)
    slope = torch.where(sxx > 0, sxy / sxx, torch.full_like(sxx, float('nan')))
    rb_hat = -slope
    return rb_hat.cpu().numpy(), float(edge.double().mean()), float(k.mean())


def main():
    K1 = (0.05, 0.15)                    # PINN 實測 0.04–0.06；論文估計器中位 0.14
    RHO = (1.0, 1.5, 2.0, 3.0, 4.2)      # 1＝沒改 τ（只靠自然浮動）；4.2＝9/23 的假設
    NS = (4, 8, 16, 32, 64)              # 每種條件的循環數
    TS = (6.0, 12.0)                     # 循環長度（實測 4.6–15 小時）
    SIG = (0.0, 0.3)                     # 循環間 k 的自然浮動（對數常態 σ）
    PSIG = (0.0, 0.03, 0.06)             # 循環間 P_eq 浮動；0.06 ≈ 真實資料的迴歸殘差
    DRIFT = (0.0, 0.1)                   # 兩條件間 r̄_b 漂移 10%
    R = int(os.environ.get('DESIGN_REPS', 200))
    designs = list(itertools.product(K1, RHO, NS, TS, SIG, PSIG, DRIFT))
    print('設計 %d 種 × 每種 %d 次重複實驗；%s fp64' % (len(designs), R, DEVICE.type))
    gen = torch.Generator(device=DEVICE).manual_seed(20261016)
    rows = []
    t0 = time.perf_counter()
    n_cyc = 0
    for i, (k1, rho, N, T, sig, psig, drift) in enumerate(designs):
        rb_hat, edge, kmean = run_design(k1, rho, N, T, sig, drift, R, gen, psig=psig)
        n_cyc += R * 2 * N
        ok = np.isfinite(rb_hat)
        rel = (rb_hat[ok] - RB) / RB
        rows.append(dict(k1=k1, rho=rho, N=N, T=T, sig=sig, psig=psig, drift=drift,
                         kT=round(k1 * T, 3), n_ok=int(ok.sum()),
                         bias=round(float(np.median(rel)), 4),
                         rel_rmse=round(float(np.sqrt(np.mean(rel ** 2))), 4),
                         mad=round(float(np.median(np.abs(rel))), 4),
                         p90=round(float(np.percentile(np.abs(rel), 90)), 4),
                         edge=round(edge, 4)))
        if (i + 1) % 200 == 0:
            print('  %d/%d  %.0f 秒' % (i + 1, len(designs), time.perf_counter() - t0))
    sec = time.perf_counter() - t0
    print('完成：%d 種設計、%d 個循環的擬合，%.0f 秒' % (len(designs), n_cyc, sec))
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'designs.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print('-> %s' % path)

    # 速覽：每個 k 倍數 ρ 下，要多少循環才能「中位相對誤差 ≤ 20%、偏誤 ≤ 10%」
    print('\n達標（中位誤差 ≤ 20%、偏誤 ≤ 10%）所需的最少總時數；k 浮動 σ=0.3、無漂移')
    for k1, psig in itertools.product(K1, PSIG):
        line = '  k₁=%.2f P_eq 浮動 %.2f：' % (k1, psig)
        for rho in RHO:
            cand = [r for r in rows if r['k1'] == k1 and r['psig'] == psig and r['rho'] == rho
                    and r['sig'] == 0.3 and r['drift'] == 0.0
                    and r['mad'] <= 0.2 and abs(r['bias']) <= 0.1]
            if cand:
                b = min(cand, key=lambda r: 2 * r['N'] * r['T'])
                line += ' ρ=%.1f→%d×%.0fh(%d天)' % (rho, 2 * b['N'], b['T'],
                                                   math.ceil(2 * b['N'] * b['T'] / 24))
            else:
                line += ' ρ=%.1f→無' % rho
        print(line)


if __name__ == '__main__':
    main()
