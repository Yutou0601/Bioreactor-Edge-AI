# -*- coding: utf-8 -*-
"""方向 5：批次 PINN——一次在 GPU 上訓練幾十到幾百個模型。

2026-10-16。

════════════════════════════════════════════════════════════════════════
為什麼要批次
  10/16 實測（pinn_rb_recovery.py --crosscheck）：一個 3 層 × 48 的 PINN、360 個點，
  Jetson GPU 比 CPU 慢 37%。原因有二：
    1 一次只訓練一個模型，GPU 多數時間在等 Python 一個一個送運算（kernel 太小）。
    2 為了安全強制 float64，而 Orin 的 float64 只有 float32 的 1/23
      （實測 GEMM：fp32 731 GFLOPS、fp64 31.5 GFLOPS）。
  這兩點都不是 GPU 不行，是用法不對。這支把 M 個模型的權重疊成一個張量
  （每層權重 shape = (M, 輸入, 輸出)，用 baddbmm 一次算完），M 個模型共用
  同一串 kernel 呼叫——呼叫次數不隨 M 增加，GPU 才有足夠的工作量。

為什麼要很多模型（不只是快）
  pinn_rb_recovery.py 已證明：常數 r_b 與 P_eq 簡併，資料只決定
  A = P_eq − r̄_b / kLa，不決定 r̄_b 本身；r̂_b 由先驗 λ 與起點決定。
  單一模型給一個點，看不出「谷底有多寬」。幾百個（種子 × λ × 循環）一起訓練，
  r̂_b 的散布本身就是可辨識性的量測。這是方向一（考慮可辨識性）要的東西。

正確性（批次 ≠ 換了一個模型）
  · 每個模型的損失只依賴自己的權重，總損失＝各模型損失之和，所以每個模型拿到的
    梯度與單獨訓練時相同；Adam 是逐元素的，所以批次 Adam ＝ M 個獨立的 Adam。
  · dP/dt 用 autograd 對輸入 t 求導：P[m, n] 只依賴 t[m, n]，對總和求導就得到
    逐點導數，不會混到別的模型或別的時間點。
  · ⚠ LBFGS 不是逐元素的（共用曲率記憶與線搜尋步長），批次版會把 M 個模型綁在
    一起。所以這裡只用 Adam（加長、餘弦退火），收斂與否用「擬合 RMSE 是否到達
    雜訊下限」逐模型檢查，不靠信任。
  · 初始權重逐模型用自己的種子在 CPU 以 float64 產生再轉型，所以同一個種子的起點
    與 M、裝置、精度都無關。

實測（2026-10-16，Jetson Orin NX）
  速度（--bench，每步 Adam；模型·步／秒，括號為相對「CPU fp32 單模型」＝原本的用法）
    CPU fp32 M=1 50（1×）  CPU fp32 M=256 280（5.6×）  GPU fp64 M≥16 ~400（8×，雙精度天花板）
    GPU fp32 M=64 2562（51×；每步 25 ms，與 M=1 相同）  GPU fp32 M=256 3429（68×）
  品質（--quality，同一份合成資料、64 個模型＝16 種子 × 4 λ，Adam 4000 + L-BFGS 400）
                         總時間   收斂     A 的 SD          卡住
    純 fp32              197 秒   64/64   0.0001–0.0006    7（kLa 有離群到 1.36）
    fp32＋fp64 收尾      296 秒   64/64   0.0001–0.0002    0      ← 預設
    純 fp64（參考）      844 秒   64/64   0.0001–0.0002    0
    原腳本單模型 CPU fp64 約 102 秒／個；預設組合 4.6 秒／個（22 倍）。
  三組的科學結論相同：A（0.7470，真值 0.7464）與 kLa（~1.44）被資料鎖定；
  r̄_b 散布 0.00001–0.007（真值 0.00504），中位數普遍低估——可辨識性的直接量測。
  ⚠ GPU 上同一模型在不同批次大小下不逐位元相同（批次 GEMM 的加總順序不同），差異會沿
    簡併谷底放大到 r̂_b；CPU 上則逐位元相同（演算法本身沒有把模型綁在一起）。
  真實循環（--real，29 個規律循環 × 8 種子 × λ 0.1、1 = 464 個模型，Jetson GPU 44 分鐘）
    · 24/29 個循環的 A 被鎖死（16 個模型範圍 ≤ 0.005）；另 5 個 kLa·T < 0.15（曲線近乎直線，
      沒有曲率可抓），連 A 都定不了（範圍約 2）。
    · kLa 只有 0.01–0.13 /hr（時間常數 8–100 小時，比循環長）。
    · r̄_b 幾乎全部塌到 0：各循環中位數的中位 6e-6，論文 0.0125 的 1/2100。PINN 把壓降
      歸給「一階物理項＋很低的 P_eq」——常數 r_b 被 P_eq 吸收的那一端。這不是「沒有生物」
      的證據，也不能拿來支持或反駁論文的 r_b（兩者假設不同）。真正被決定的是總移除速率
      kLa(P0−P_eq)+r̄_b（中位 0.037，與直接量的平均降速 0.033 吻合）。
    · ⚠ 該次輸出 real_cycles.csv 的 rb_mean 只存到小數 7 位，更小的值成了 0；之後改存 6 位
      有效數字。圖與摘要表把 < 1e-7 標為「低於記錄下限」。
    · 擬合 RMSE：τ=1 批 ~0.005（≈ 雜訊下限），τ=5／10 批 0.008–0.011——泵每小時的鋸齒
      不是平滑的 P(t) 能描述的。
  圖：docs/analysis_charts_3batch/fig57_pinn_batched.png、fig58_pinn_real_cycles.png
      （fig_pinn_batched.py 畫，讀本目錄的 CSV）

用法（在 Jetson 跑）
  python3 pinn_batched.py --bench               CPU/GPU × fp32/fp64 × M=1..256 速度
  ML_DEVICE=cuda python3 pinn_batched.py --quality            預設：fp32 Adam＋fp64 收尾
  ML_DEVICE=cuda ML_REFINE_DTYPE=same python3 pinn_batched.py --quality      純 fp32
  ML_DEVICE=cuda ML_DTYPE=float64 python3 pinn_batched.py --quality          純 fp64
  ML_DEVICE=cuda python3 pinn_batched.py --real               29 個真實循環（需 Testing_data；
                                                             RESEARCH_DIR 可指定 research/ 的位置）

輸出 -> research/ml/out_pinn_batched/
"""
import csv
import math
import os
import sys
import time

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out_pinn_batched')
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DEVICE = torch.device(os.environ.get('ML_DEVICE', 'cpu'))
DTYPE = torch.float64 if os.environ.get('ML_DTYPE') == 'float64' else torch.float32

# 與 pinn_rb_recovery.py 相同的合成問題，數字才能對照
T_SYN, NP_SYN = 6.0, 360
KLA_TRUE, PEQ_TRUE, P0_TRUE = 1.4, 0.75, 1.17
QUANT, NOISE = 0.01, 0.004
FLOOR = math.sqrt(NOISE ** 2 + QUANT ** 2 / 12)        # 擬合誤差的理論下限


def rb_true(tt):
    return 0.012 * np.exp(-0.7 * tt / T_SYN * 3)


def synth(seed=0):
    """顯式尤拉積分 dP/dt = −kLa(P−Peq) − r_b(t)，加雜訊再量化。與原腳本相同。"""
    rng = np.random.default_rng(seed)
    t = np.linspace(0, T_SYN, NP_SYN)
    dt = t[1] - t[0]
    P = np.empty(NP_SYN)
    P[0] = P0_TRUE
    for i in range(1, NP_SYN):
        P[i] = P[i - 1] + dt * (-KLA_TRUE * (P[i - 1] - PEQ_TRUE) - rb_true(t[i - 1]))
    obs = np.round((P + rng.normal(0, NOISE, NP_SYN)) / QUANT) * QUANT
    return t, obs


# ── 批次 MLP ────────────────────────────────────────────────────────────
class BatchedMLP(torch.nn.Module):
    """M 個獨立的 1→width→…→1 MLP，權重疊在第 0 維。

    初始化與 nn.Linear 預設相同的分布：W、b ~ U(−1/√fan_in, 1/√fan_in)。
    """

    def __init__(self, seeds, width=48, depth=3, positive=False, device=None, dtype=None):
        super().__init__()
        dims = [1] + [width] * depth + [1]
        self.positive = positive
        self.W = torch.nn.ParameterList()
        self.b = torch.nn.ParameterList()
        for li, (din, dout) in enumerate(zip(dims[:-1], dims[1:])):
            bound = 1.0 / math.sqrt(din)
            Ws, bs = [], []
            for s in seeds:
                g = torch.Generator().manual_seed(int(s) * 1000 + li * 2 + (500 if positive else 0))
                Ws.append(torch.empty(din, dout, dtype=torch.float64).uniform_(-bound, bound, generator=g))
                bs.append(torch.empty(1, dout, dtype=torch.float64).uniform_(-bound, bound, generator=g))
            self.W.append(torch.nn.Parameter(torch.stack(Ws).to(device, dtype)))
            self.b.append(torch.nn.Parameter(torch.stack(bs).to(device, dtype)))

    def forward(self, x):                       # x: (M, N, 1)
        n = len(self.W)
        for i in range(n):
            x = torch.baddbmm(self.b[i], x, self.W[i])
            if i < n - 1:
                x = torch.tanh(x)
        return torch.nn.functional.softplus(x) if self.positive else x


def train_batched(t_obs, P_obs, T, lams, seeds, iters=4000, lr=3e-3, lr_end=1e-5,
                  device=None, dtype=None, steps_only=False, refine=400,
                  refine_dtype=torch.float64):
    """一次訓練 M 個 PINN：Adam iters 步，再接逐模型獨立的 L-BFGS refine 步。

    P_obs 可以是 (N,)（全部同一份資料）或 (M, N)。
    預設 Adam 用 dtype（ML_DTYPE，預設 fp32）、L-BFGS 收尾用 fp64。refine_dtype=None
    表示收尾也用 dtype。三種組合的比較見檔頭「實測」。
    回傳每個模型的 kLa、P_eq、r̂_b(t)（每小時）、擬合 RMSE、A = P_eq − r̄_b/kLa。
    steps_only=True 時只跑 iters 步、不收尾，給速度測試用。

    ⚠ 2026-10-16 實測：只用 Adam（6000 步、餘弦退火）64 個模型**全部沒收斂**——
      RMSE 0.030，雜訊下限 0.0049；kLa 0.64（真值 1.4）。與原腳本只跑 Adam 時的
      症狀相同。L-BFGS 收尾不可省略。
    """
    dev = DEVICE if device is None else torch.device(device)
    dt_ = DTYPE if dtype is None else dtype
    M = len(seeds)
    lam = torch.tensor(np.asarray(lams, float), dtype=dt_, device=dev)

    # 兩種輸入：同長度陣列（合成測試），或長度不一的串列（真實循環，各有自己的 T）。
    # 不等長時補到最長、補的位置遮罩為 0——資料、物理、平滑三項都只在真實點上平均。
    if isinstance(P_obs, (list, tuple)):
        ts_list = [np.asarray(x, float) for x in t_obs]
        ps_list = [np.asarray(x, float) for x in P_obs]
        Tm = np.array([x[-1] for x in ts_list], float) if T is None else np.broadcast_to(
            np.asarray(T, float), (M,)).copy()
    else:
        P_arr = np.asarray(P_obs, float)
        if P_arr.ndim == 1:
            P_arr = np.broadcast_to(P_arr, (M, P_arr.size))
        ts_list = [np.asarray(t_obs, float)] * M
        ps_list = list(P_arr)
        Tm = np.broadcast_to(np.asarray(T, float), (M,)).copy()
    N = max(len(x) for x in ps_list)
    t_pad = np.ones((M, N))
    p_pad = np.zeros((M, N))
    m_pad = np.zeros((M, N))
    p_first = np.empty(M)
    p_last = np.empty(M)
    for i, (tx, px) in enumerate(zip(ts_list, ps_list)):
        n = len(px)
        t_pad[i, :n] = tx / Tm[i]
        p_pad[i, :n] = px
        p_pad[i, n:] = px[-1]
        m_pad[i, :n] = 1.0
        p_first[i], p_last[i] = px[0], px[-1]
    tt = torch.tensor(t_pad, dtype=dt_, device=dev).view(M, N, 1)
    pp = torch.tensor(p_pad, dtype=dt_, device=dev).view(M, N, 1)
    mk = torch.tensor(m_pad, dtype=dt_, device=dev).view(M, N, 1)
    cnt = mk.sum(dim=(1, 2))
    T_t = torch.tensor(Tm, dtype=dt_, device=dev)
    p1 = torch.tensor(p_last, dtype=dt_, device=dev)
    sc = (torch.tensor(p_first, dtype=dt_, device=dev) - p1 + 1e-9) ** 2   # (M,) 與原腳本相同

    def mmean(x, mask, n):                      # 只在真實點上平均
        return (x * mask).sum(dim=(1, 2)) / n

    fP = BatchedMLP(seeds, device=dev, dtype=dt_)
    fR = BatchedMLP(seeds, positive=True, device=dev, dtype=dt_)
    log_kLa = torch.nn.Parameter(torch.zeros(M, dtype=dt_, device=dev))
    peq = torch.nn.Parameter((p1 - 0.2).clone())
    params = list(fP.parameters()) + list(fR.parameters()) + [log_kLa, peq]
    opt = torch.optim.Adam(params, lr=lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=iters, eta_min=lr_end)

    tc = tt.clone().requires_grad_(True)

    def per_model_losses():
        P = fP(tc)
        dP = torch.autograd.grad(P, tc, torch.ones_like(P), create_graph=True)[0]
        rb = fR(tc)
        phys = dP + torch.exp(log_kLa).view(M, 1, 1) * (P - peq.view(M, 1, 1)) + rb
        drb = torch.autograd.grad(rb, tc, torch.ones_like(rb), create_graph=True)[0]
        l_data = mmean((P - pp) ** 2, mk, cnt) / sc
        l_phys = mmean(phys ** 2, mk, cnt) / sc
        l_sm = mmean(drb ** 2, mk, cnt) / sc
        return l_data, l_phys, l_sm

    for _ in range(iters):
        opt.zero_grad(set_to_none=True)
        a, b, c = per_model_losses()
        (a + b + lam * c).sum().backward()
        opt.step()
        sched.step()
    if steps_only:
        return None

    # ── 二階收尾：逐模型獨立的批次 L-BFGS ──
    # 參數順序固定：fP 的 W、b，fR 的 W、b，log_kLa，peq。全部有前導維 M。
    order = list(fP.W) + list(fP.b) + list(fR.W) + list(fR.b) + [log_kLa, peq]
    shapes = [p.shape for p in order]
    sizes = [int(np.prod(s[1:])) if len(s) > 1 else 1 for s in shapes]
    nl = len(fP.W)
    rd = dt_ if refine_dtype is None else refine_dtype
    x = torch.cat([p.detach().reshape(M, -1) for p in order], 1).to(rd)
    tc2, pp2, sc2, lam2 = (tc.detach().to(rd).requires_grad_(True), pp.to(rd), sc.to(rd),
                           lam.to(rd))
    mk2, cnt2, T2 = mk.to(rd), cnt.to(rd), T_t.to(rd)

    def unflat(v):
        parts = torch.split(v, sizes, dim=1)
        return [q.reshape(s) for q, s in zip(parts, shapes)]

    def total_loss(v):
        u = unflat(v)
        PW, PB, RW, RB = u[:nl], u[nl:2 * nl], u[2 * nl:3 * nl], u[3 * nl:4 * nl]
        lk, pq = u[4 * nl], u[4 * nl + 1]
        P = _mlp(PW, PB, tc2, False)
        dP = torch.autograd.grad(P, tc2, torch.ones_like(P), create_graph=True)[0]
        rb = _mlp(RW, RB, tc2, True)
        drb = torch.autograd.grad(rb, tc2, torch.ones_like(rb), create_graph=True)[0]
        phys = dP + torch.exp(lk).view(M, 1, 1) * (P - pq.view(M, 1, 1)) + rb
        return (mmean((P - pp2) ** 2, mk2, cnt2) + mmean(phys ** 2, mk2, cnt2)
                + lam2 * mmean(drb ** 2, mk2, cnt2)) / sc2

    def f_and_g(v):
        v = v.detach().requires_grad_(True)
        f = total_loss(v)
        g = torch.autograd.grad(f.sum(), v)[0]
        return f.detach(), g.detach()

    def f_only(v):
        with torch.enable_grad():               # dP/dt 仍要對 t 求導
            return total_loss(v.detach()).detach()

    n_stuck = 0
    if refine:
        x, n_stuck = lbfgs_batched(f_and_g, f_only, x, refine)

    with torch.no_grad():
        u = unflat(x)
        PW, PB, RW, RB = u[:nl], u[nl:2 * nl], u[2 * nl:3 * nl], u[3 * nl:4 * nl]
        grid = torch.linspace(0, 1, 60, dtype=rd, device=dev).view(1, 60, 1).expand(M, 60, 1)
        rb_hat = (_mlp(RW, RB, grid, True)[..., 0] / T2.view(M, 1)).double().cpu().numpy()
        rmse = torch.sqrt(mmean((_mlp(PW, PB, tc2.detach(), False) - pp2) ** 2, mk2, cnt2)
                          ).double().cpu().numpy()                     # rb_hat：(M, 60) 每小時
        kla = (torch.exp(u[4 * nl]) / T2).double().cpu().numpy()
        pe = u[4 * nl + 1].double().cpu().numpy()
    rb_mean = rb_hat.mean(axis=1)
    return dict(kla=kla, peq=pe, rb=rb_hat, rb_mean=rb_mean, rmse=rmse,
                A=pe - rb_mean / kla, grid=np.linspace(0, 1, 60), n_stuck=n_stuck)


def _mlp(Ws, bs, x, positive):
    """與 BatchedMLP.forward 相同，但權重由呼叫者給（L-BFGS 用平攤的參數向量）。"""
    for i in range(len(Ws)):
        x = torch.baddbmm(bs[i], x, Ws[i])
        if i < len(Ws) - 1:
            x = torch.tanh(x)
    return torch.nn.functional.softplus(x) if positive else x


def lbfgs_batched(f_and_g, f_only, x, iters, hist=20, c1=1e-4, max_ls=30):
    """M 個彼此獨立的 L-BFGS，運算疊在一起做。x: (M, D)。

    與 torch.optim.LBFGS 不同的地方（這正是要它的原因）：
      · 曲率記憶 (s, y) 逐模型各自一份；某模型的 s·y ≤ 0 時只跳過它自己那一對。
      · 線搜尋逐模型各自回溯（Armijo），步長互不影響；找不到下降步的模型原地不動。
    回傳 (x, 最後一輪仍找不到下降步的模型數)。
    """
    M = x.shape[0]
    f, g = f_and_g(x)
    S, Y, R = [], [], []
    stuck = torch.zeros(M, dtype=torch.bool, device=x.device)
    for _ in range(iters):
        q = g.clone()
        alphas = []
        for s, y, rho in zip(reversed(S), reversed(Y), reversed(R)):
            a = rho * (s * q).sum(1)
            q = q - a[:, None] * y
            alphas.append(a)
        if S:
            sy = (S[-1] * Y[-1]).sum(1)
            yy = (Y[-1] * Y[-1]).sum(1)
            gamma = torch.where(R[-1] > 0, sy / yy.clamp_min(1e-300), torch.ones_like(sy))
        else:
            gamma = 1.0 / g.abs().sum(1).clamp_min(1.0)       # 第一步與 torch 的做法相同
        r = gamma[:, None] * q
        for (s, y, rho), a in zip(zip(S, Y, R), reversed(alphas)):
            b = rho * (y * r).sum(1)
            r = r + s * (a - b)[:, None]
        d = -r
        gd = (g * d).sum(1)
        bad = ~(gd < 0)                                        # 不是下降方向就退回梯度
        if bad.any():
            d[bad] = -g[bad] / g[bad].abs().sum(1, keepdim=True).clamp_min(1.0)
            gd = (g * d).sum(1)

        step = torch.ones(M, dtype=x.dtype, device=x.device)
        ok_all = torch.zeros(M, dtype=torch.bool, device=x.device)
        x_new = x.clone()
        for _ in range(max_ls):
            xt = x + step[:, None] * d
            ft = f_only(xt)
            ok = (~ok_all) & torch.isfinite(ft) & (ft <= f + c1 * step * gd)
            x_new[ok] = xt[ok]
            ok_all |= ok
            if bool(ok_all.all()):
                break
            step = torch.where(ok_all, step, step * 0.5)
        stuck = ~ok_all
        f_new, g_new = f_and_g(x_new)
        s = x_new - x
        y = g_new - g
        sy = (s * y).sum(1)
        good = sy > 1e-10 * torch.sqrt((s * s).sum(1) * (y * y).sum(1))
        rho = torch.where(good, 1.0 / sy.clamp_min(1e-300), torch.zeros_like(sy))
        S.append(torch.where(good[:, None], s, torch.zeros_like(s)))
        Y.append(torch.where(good[:, None], y, torch.zeros_like(y)))
        R.append(rho)
        if len(S) > hist:
            S.pop(0), Y.pop(0), R.pop(0)
        x, f, g = x_new, f_new, g_new
    return x, int(stuck.sum())


# ── 一　速度 ────────────────────────────────────────────────────────────
def bench(Ms=(1, 4, 16, 64, 256), steps=30, warm=5):
    t, obs = synth()
    rows = []
    combos = [('cpu', torch.float32), ('cpu', torch.float64)]
    if torch.cuda.is_available():
        combos += [('cuda', torch.float32), ('cuda', torch.float64)]
    print('裝置   精度     M    每步 ms   模型·步/秒   相對 CPU-fp32 單模型')
    base = None
    for dev, dt_ in combos:
        for M in Ms:
            seeds = list(range(M))
            lams = [0.1] * M
            train_batched(t, obs, T_SYN, lams, seeds, iters=warm, device=dev, dtype=dt_,
                          steps_only=True)
            if dev == 'cuda':
                torch.cuda.synchronize()
            t0 = time.perf_counter()
            train_batched(t, obs, T_SYN, lams, seeds, iters=steps, device=dev, dtype=dt_,
                          steps_only=True)
            if dev == 'cuda':
                torch.cuda.synchronize()
            ms = (time.perf_counter() - t0) / steps * 1000
            thr = M / ms * 1000
            if base is None:
                base = thr
            name = 'fp32' if dt_ == torch.float32 else 'fp64'
            print('%-5s  %-5s  %4d  %8.2f  %11.0f   %6.1f×' % (dev, name, M, ms, thr, thr / base))
            rows.append([dev, name, M, round(ms, 3), round(thr, 1), round(thr / base, 2)])
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'bench.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['device', 'dtype', 'M', 'ms_per_step', 'model_steps_per_s', 'vs_cpu_fp32_M1'])
        w.writerows(rows)
    print('-> %s' % os.path.relpath(path, os.path.dirname(HERE)))


# ── 二　批次訓練的品質 ───────────────────────────────────────────────────
# 預設 fp64 收尾；ML_REFINE_DTYPE=same 表示收尾沿用 ML_DTYPE（純 fp32，給大範圍初掃用）
REFINE_DTYPE = None if os.environ.get('ML_REFINE_DTYPE') == 'same' else torch.float64


def quality(n_seeds=16, lams=(0.01, 0.1, 1.0, 10.0), iters=4000, refine=400):
    t, obs = synth()
    seeds, lam_list = [], []
    for lam in lams:
        for s in range(n_seeds):
            seeds.append(s)
            lam_list.append(lam)
    M = len(seeds)
    name = 'fp32' if DTYPE == torch.float32 else 'fp64'
    if REFINE_DTYPE is not None and REFINE_DTYPE != DTYPE:
        name += '+fp64收尾'
    print('同一份合成資料，%d 個模型（%d 種子 × λ %s），%s %s，Adam %d 步 + L-BFGS %d 步'
          % (M, n_seeds, list(lams), DEVICE.type, name, iters, refine))
    t0 = time.perf_counter()
    r = train_batched(t, obs, T_SYN, lam_list, seeds, iters=iters, refine=refine,
                      refine_dtype=REFINE_DTYPE)
    sec = time.perf_counter() - t0
    print('總時間 %.1f 秒（每個模型平均 %.2f 秒）；最後一輪找不到下降步的模型 %d 個'
          % (sec, sec / M, r['n_stuck']))

    A_true = PEQ_TRUE - rb_true(r['grid'] * T_SYN).mean() / KLA_TRUE
    rbm_true = rb_true(r['grid'] * T_SYN).mean()
    print('理論下限 RMSE %.4f；真值 kLa %.2f、A %.4f、r̄_b %.5f' % (FLOOR, KLA_TRUE, A_true, rbm_true))
    print('  λ        收斂(RMSE≤1.2×下限)  RMSE 中位    kLa 中位[範圍]           A 中位±SD          r̄_b 中位[範圍]')
    rows = []
    lam_arr = np.asarray(lam_list)
    for lam in lams:
        k = lam_arr == lam
        conv = r['rmse'][k] <= 1.2 * FLOOR
        print('  %-7g  %2d/%-2d               %.4f      %.3f [%.3f, %.3f]   %.4f ± %.4f    %.5f [%.5f, %.5f]'
              % (lam, conv.sum(), k.sum(), np.median(r['rmse'][k]),
                 np.median(r['kla'][k]), r['kla'][k].min(), r['kla'][k].max(),
                 np.median(r['A'][k]), r['A'][k].std(),
                 np.median(r['rb_mean'][k]), r['rb_mean'][k].min(), r['rb_mean'][k].max()))
    for i in range(M):
        rows.append([lam_list[i], seeds[i], round(float(r['rmse'][i]), 6),
                     round(float(r['kla'][i]), 6), round(float(r['peq'][i]), 6),
                     '%.6g' % float(r['rb_mean'][i]), round(float(r['A'][i]), 6)])
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'quality_%s_%s.csv' % (DEVICE.type, name.replace('+fp64收尾', '_fp64refine')))
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['lambda', 'seed', 'rmse', 'kla', 'peq', 'rb_mean', 'A'])
        w.writerows(rows)
    print('-> %s' % os.path.relpath(path, os.path.dirname(HERE)))
    return r


# ── 三　真實循環 ─────────────────────────────────────────────────────────
def load_real_cycles():
    """三個 τ 批的規律循環（pump_mode_split.regular_cycles：≥4 hr、降幅 ≥0.10、
    近似直線、迄壓 ≥0.7＝排除人工排氣）。回傳 [(批, τ, 第幾個, t_hr, P), ...]。"""
    research = os.environ.get('RESEARCH_DIR', os.path.dirname(HERE))
    sys.path.insert(0, os.path.join(research, 'cycles'))
    import pump_mode_split as PM                       # noqa: E402
    from pump_rhythm import BATCHES                    # noqa: E402
    ts, h, p = PM.load()
    out = []
    for nm, tau, d0, d1 in BATCHES:
        B = PM.analyse_batch(ts, h, p, nm, tau, d0, d1)
        for k, c in enumerate(B['reg']):
            s, e = c['s'], c['e']
            out.append((nm, tau, k + 1, B['h2'][s:e + 1] - B['h2'][s], B['p2'][s:e + 1].copy()))
    return out


def real(n_seeds=8, lams=(0.1, 1.0), chunk=128, iters=4000, refine=400):
    """每個真實循環 × n_seeds × lams 個模型。長度相近的循環同一批（補長度浪費少）。"""
    cycles = load_real_cycles()
    cycles.sort(key=lambda c: len(c[4]))
    jobs = [(ci, s, lam) for ci in range(len(cycles)) for lam in lams for s in range(n_seeds)]
    print('真實循環 %d 個 × %d 種子 × λ %s = %d 個模型；每批最多 %d 個；%s Adam %s→收尾 %s'
          % (len(cycles), n_seeds, list(lams), len(jobs), chunk, DEVICE.type,
             'fp32' if DTYPE == torch.float32 else 'fp64',
             'fp64' if REFINE_DTYPE is not None else '同上'))
    rows = []
    t_all = time.perf_counter()
    for b0 in range(0, len(jobs), chunk):
        jb = jobs[b0:b0 + chunk]
        t0 = time.perf_counter()
        r = train_batched([cycles[ci][3] for ci, _, _ in jb], [cycles[ci][4] for ci, _, _ in jb],
                          None, [lam for _, _, lam in jb], [s for _, s, _ in jb],
                          iters=iters, refine=refine, refine_dtype=REFINE_DTYPE)
        npts = [len(cycles[ci][4]) for ci, _, _ in jb]
        print('  批 %d–%d（%d–%d 點）%.0f 秒，卡住 %d'
              % (b0, b0 + len(jb) - 1, min(npts), max(npts), time.perf_counter() - t0, r['n_stuck']))
        for i, (ci, s, lam) in enumerate(jb):
            nm, tau, k, tx, px = cycles[ci]
            rows.append([nm, tau, k, round(float(tx[-1]), 3), len(px), round(float(px[0]), 3),
                         round(float(px[-1]), 3), lam, s, round(float(r['rmse'][i]), 6),
                         round(float(r['kla'][i]), 6), round(float(r['peq'][i]), 6),
                         '%.6g' % float(r['rb_mean'][i]), round(float(r['A'][i]), 6)])
    print('總時間 %.0f 秒' % (time.perf_counter() - t_all))
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'real_cycles.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['batch', 'tau', 'cycle', 'hours', 'npts', 'p_start', 'p_end', 'lambda', 'seed',
                    'rmse', 'kla', 'peq', 'rb_mean', 'A'])
        w.writerows(rows)
    print('-> %s' % path)


if __name__ == '__main__':
    torch.set_num_threads(int(os.environ.get('ML_THREADS', os.cpu_count() or 1)))
    if '--bench' in sys.argv:
        bench()
    elif '--quality' in sys.argv:
        quality()
    elif '--real' in sys.argv:
        real()
    else:
        print(__doc__)
