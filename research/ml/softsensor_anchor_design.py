# -*- coding: utf-8 -*-
"""方向 2：少量 CH4 錨點的軟感測器＋主動學習排採樣——先做「設計研究」。

2026-10-16。

════════════════════════════════════════════════════════════════════════
為什麼先做模擬，不直接拿真資料訓練
  真資料只有 35 次帶組成的排氣、可用區間 17 個；orp_calibration.py 已經做過線性版
  （留一 R² 壓力 0.151、ORP 0.110），17 個點訓練任何深度模型都沒有意義。
  瓶頸是錨點密度。所以現在真正要回答的是**實驗協定**的問題：

    要排幾次氣（錨點）、在什麼時候排，軟感測器才夠準？
    「讓模型決定何時排氣」（主動學習）能比「固定每 Δ 小時排一次」省幾次？

  這些答案取決於一個我們不知道的量——**連續訊號裡到底有多少生物資訊**
  （c_bio：ORP/pH 與生物速率的耦合強度）。所以把 c_bio 當旋鈕掃過去，畫成
  「錨點數 → 誤差」的曲線。實驗開始第一週就能從資料估 c_bio，再查這張表。

模擬器（每分鐘；參數取自已量到的數值，見各行註解）
  P：dP/dt = −kLa(t)(P − P_eq) − r_bio(t) − L(t)；低於 0.72 觸發補氣回 1.17。
     kLa 泵開 1.25、泵停 0.05 /h（包絡 k≈0.15，論文中位）；每小時第 25 分起開泵 τ=5 分。
     觀測＝量化 0.01 ＋ AR(1) 雜訊 φ=0.26（simulator_validation_ar1）。
  r_bio：0.010 × exp(OU)，時間尺度 3 天；隨機一天起降為一半（模擬換料）。
  L：非生物定速移除（洩漏／脫氣／補氣比偏差，見 hydrogen_loss_feed_ratio）。
     兩種情境：恆定 0.008，或緩慢漂移。**L 漂移時壓力分不出 r_bio 與 L。**
  ORP：補氣 +37 mV、泵開 +7 mV/分 的操作響應（orp_is_substrate），循環內往負走
     −60 mV（orp_activity_signal 的 −39~−134），＋ c_bio × 12 mV × z(r_bio)，＋慢漂移雜訊。
  pH：補氣酸化 −0.03（2 小時衰減）＋ c_bio × 0.01 × z(r_bio) ＋ 雜訊，量化 0.01。
  錨點：兩次排氣之間 r_bio 的區間平均 ×(1 + 15% 誤差)（氣體感測器滯後追蹤）。
  ⚠ 模擬器的結論只對「這組假設」成立。它回答的是相對問題（策略 A 比 B 省幾次、
    c_bio 要多大才有用），不是反應器的絕對數字。

比較
  編碼器：手工逐小時特徵 vs 自監督 Bi-LSTM（遮罩重建預訓練，不用任何錨點）。
  模型：貝氏線性迴歸（錨點是區間平均 → 設計列是區間內嵌入的平均，仍是線性）。
  策略：固定間隔／隨機／資訊增益（不確定度大就排）／新穎度（狀態沒看過就排）。
  基準：**不用軟感測器**，直接拿錨點分段常數內插——密集排氣時它可能就贏了，要老實比。
  誤差：逐小時 r_bio 的相對 RMSE；分「採樣期」與「之後 20 天不排氣」兩段。

用法（Jetson）：ML_DEVICE=cuda python3 -u softsensor_anchor_design.py [--quick]
"""
import json
import os
import sys
import time

import numpy as np
from scipy.signal import lfilter

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out_softsensor_design')

DAYS, CAMPAIGN_DAYS = 60, 40
DT = 1 / 60.0
P_HI, P_TRIG = 1.17, 0.72
KLA_ON, KLA_OFF, TAU, PUMP_AT = 1.25, 0.05, 5, 25
R0, L0 = 0.010, 0.008
ANCHOR_REL = 0.15
MIN_GAP_H = 3
EMB_DIM = 8


# ══════════════════════════════════════════════════════════
# 模擬
# ══════════════════════════════════════════════════════════
def _ou(rng, sd, T_h, n):
    """平穩 OU（每分鐘離散）：x_i = a x_{i-1} + e_i。"""
    a = np.exp(-DT / T_h)
    e = rng.normal(0, sd * np.sqrt(1 - a * a), n)
    e[0] = rng.normal(0, sd)
    return lfilter([1.0], [1.0, -a], e)


def _ar1(rng, sd, phi, n):
    e = rng.normal(0, sd * np.sqrt(1 - phi * phi), n)
    return lfilter([1.0], [1.0, -phi], e)


def _decay(x, T_min):
    """衝激 → 指數衰減響應。"""
    a = np.exp(-1.0 / T_min)
    return lfilter([1.0], [1.0, -a], x)


def simulate(c_bio, leak_mode, seed):
    rng = np.random.default_rng(seed)
    n = DAYS * 1440
    minute = np.arange(n) % 60
    pump = ((minute - PUMP_AT) % 60) < TAU

    r = R0 * np.exp(_ou(rng, 0.35, 72.0, n))
    step_at = int(rng.uniform(0.3, 0.9) * n)               # 換料：之後降為一半
    r[step_at:] *= 0.5
    L = (np.full(n, L0) if leak_mode == 'const'
         else L0 * np.exp(_ou(rng, 0.4, 120.0, n)))
    peq = 0.60 + _ou(rng, 0.02, 240.0, n)
    kla = np.where(pump, KLA_ON, KLA_OFF)

    P = np.empty(n)
    refill = np.zeros(n, bool)
    P[0] = P_HI
    for i in range(1, n):                                   # 補氣是狀態相依的，只能逐步積分
        p = P[i - 1] - DT * (kla[i] * (P[i - 1] - peq[i]) + r[i] + L[i])
        if p < P_TRIG:
            p = P_HI
            refill[i] = True
        P[i] = p
    P_obs = np.round((P + _ar1(rng, 0.004, 0.26, n)) / 0.01) * 0.01

    # 補氣後經過的分鐘
    last = np.maximum.accumulate(np.where(refill | (np.arange(n) == 0), np.arange(n), 0))
    since = (np.arange(n) - last).astype(float)
    zr = (np.log(r) - np.log(r).mean()) / np.log(r).std()
    orp = (-555.0
           + _decay(37.0 * refill, 60.0)
           + _decay(7.0 * pump, 60.0)
           - 60.0 * np.minimum(since / 480.0, 1.5)
           + c_bio * 12.0 * zr
           + _ar1(rng, 4.0, 0.95, n))
    ph = np.round((7.05 - _decay(0.03 * refill, 120.0) / 1.0
                   + c_bio * 0.01 * zr + _ar1(rng, 0.004, 0.9, n)) / 0.01) * 0.01
    H = n // 60
    return dict(P=P_obs, orp=np.round(orp), ph=ph, pump=pump, refill=refill,
                r_hour=r[:H * 60].reshape(H, 60).mean(1),
                n_refill=int(refill.sum()), step_hour=step_at // 60)


# ══════════════════════════════════════════════════════════
# 編碼器
# ══════════════════════════════════════════════════════════
def hand_features(s):
    """逐小時 8 個特徵，只用觀測得到的量（壓力、ORP、pH、補氣與泵旗標）。"""
    n = len(s['P'])
    H = n // 60
    dP = np.diff(s['P'], prepend=s['P'][0])
    dP[s['refill']] = 0.0
    quiet = ~s['pump'] & ~s['refill']
    rs = lambda x: x[:H * 60].reshape(H, 60)
    q = rs(quiet)
    slope = -(rs(dP) * q).sum(1) / np.maximum(q.sum(1), 1) * 60      # 泵停期每小時降幅
    pdrop = -(rs(dP) * rs(s['pump'])).sum(1)                         # 泵開期降幅
    orp_h = rs(s['orp'])
    ref_h = rs(s['refill']).sum(1)
    ref24 = np.convolve(ref_h, np.ones(24), 'full')[:H]               # 過去 24 小時補氣次數
    last = np.maximum.accumulate(np.where(ref_h > 0, np.arange(H), 0))
    F = np.stack([slope, pdrop, rs(s['P']).mean(1), orp_h.mean(1),
                  orp_h[:, -1] - orp_h[:, 0], rs(s['ph']).mean(1), ref24,
                  np.arange(H) - last], 1)
    return F


def ssl_embeddings(s, device='cpu', epochs=12, seq=360, hid=32, seed=0):
    """自監督 Bi-LSTM：遮掉隨機 10 分鐘片段，重建 ΔP、ORP、pH。完全不用錨點。

    回傳逐小時嵌入（雙向隱藏狀態在該小時的平均，2×hid 維）。
    """
    import torch
    import torch.nn as nn
    torch.manual_seed(seed)
    dev = torch.device(device)
    dP = np.diff(s['P'], prepend=s['P'][0])
    dP[s['refill']] = 0.0
    z = lambda x: (x - x.mean()) / (x.std() + 1e-9)
    X = np.stack([dP / 0.01, z(s['orp']), z(np.diff(s['orp'], prepend=s['orp'][0])),
                  z(s['ph']), s['pump'].astype(float), s['refill'].astype(float)], 1).astype(np.float32)
    TGT = [0, 1, 3]
    C = X.shape[1]

    class Enc(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(C + 1, hid, num_layers=2, batch_first=True, bidirectional=True)
            self.head = nn.Linear(2 * hid, len(TGT))

        def forward(self, x):
            h = self.lstm(x)[0]
            return self.head(h), h

    net = Enc().to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=2e-3)
    starts = np.arange(0, len(X) - seq, 120)
    S = torch.tensor(np.stack([X[a:a + seq] for a in starts]), device=dev)
    g = torch.Generator(device='cpu').manual_seed(seed)
    for ep in range(epochs):
        perm = torch.randperm(len(S), generator=g).to(dev)
        for i in range(0, len(S), 64):
            xb = S[perm[i:i + 64]]
            m = torch.zeros(xb.shape[:2], device=dev)
            for _ in range(4):                               # 每條 4 段、每段 10 分鐘
                a = torch.randint(0, seq - 10, (len(xb),), generator=g).to(dev)
                idx = a[:, None] + torch.arange(10, device=dev)[None]
                m.scatter_(1, idx, 1.0)
            inp = torch.cat([xb * (1 - m[..., None]), m[..., None]], -1)
            pred, _ = net(inp)
            mk = m.bool()
            loss = ((pred - xb[..., TGT]) ** 2)[mk].mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
    # 逐小時嵌入：每小時取以它為中心的 6 小時視窗，平均中間那一小時的隱藏狀態
    H = len(X) // 60
    pad = (seq - 60) // 2
    Xp = np.concatenate([np.zeros((pad, C), np.float32), X, np.zeros((pad + 60, C), np.float32)])
    E = np.zeros((H, 2 * hid))
    net.eval()
    with torch.no_grad():
        for b0 in range(0, H, 128):
            hs = range(b0, min(H, b0 + 128))
            xb = torch.tensor(np.stack([Xp[h * 60:h * 60 + seq] for h in hs]), device=dev)
            inp = torch.cat([xb, torch.zeros(*xb.shape[:2], 1, device=dev)], -1)
            _, hseq = net(inp)
            E[b0:b0 + len(hs)] = hseq[:, pad:pad + 60].mean(1).cpu().numpy()
    return E, float(loss.item())


def smooth24(F):
    """置中 24 小時移動平均（邊界以實際點數正規化）。

    ⚠ 2026-10-16 試跑發現不能省：逐小時特徵幾乎全是量化雜訊（一小時只掉 0~3 個 0.01 階），
      錨點又是區間平均——拿區間平均擬合的權重套回逐小時，雜訊被放大，誤差 >1 且錨點越多越差。
      r_bio 本身的時間尺度是 3 天，所以先平滑到日尺度再談。
    """
    w = np.ones(24)
    num = np.apply_along_axis(lambda x: np.convolve(x, w, 'same'), 0, F)
    den = np.convolve(np.ones(len(F)), w, 'same')[:, None]
    return num / den


def reduce(F, dim=EMB_DIM):
    """24 小時平滑、標準化後 PCA 到 dim 維。用全部小時（無標籤資料本來就隨時拿得到）。"""
    F = smooth24(F)
    Z = (F - F.mean(0)) / (F.std(0) + 1e-9)
    U, s, Vt = np.linalg.svd(Z - Z.mean(0), full_matrices=False)
    E = Z @ Vt[:dim].T
    return E / (E.std(0) + 1e-9)


# ══════════════════════════════════════════════════════════
# 錨點模型與策略
# ══════════════════════════════════════════════════════════
ALPHAS = (0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0)   # 權重先驗精度候選（嵌入已標準化）


def blr(Xr, y, sig2):
    """貝氏線性迴歸；先驗精度以邊際概似（經驗貝氏）從 ALPHAS 挑。

    ⚠ 固定 α=1 時 9 個參數配 16 個錨點會過擬合（試跑：錨點越多誤差反而越大）。
    截距幾乎不懲罰。
    """
    n, d = Xr.shape
    G = Xr.T @ Xr / sig2
    b = Xr.T @ y / sig2
    best = None
    for a in ALPHAS:
        p0 = np.r_[1e-4, np.full(d - 1, a)]
        A = np.diag(p0) + G
        # 邊際概似（Woodbury：只解 d×d，不必解 n×n；常數項省略）
        #   log|C| = n log σ² + log|A| − log|P0|,  yᵀC⁻¹y = yᵀy/σ² − bᵀA⁻¹b
        ll = -0.5 * (np.linalg.slogdet(A)[1] - np.log(p0).sum()
                     + y @ y / sig2 - b @ np.linalg.solve(A, b))
        if best is None or ll > best[0]:
            best = (ll, A)
    S = np.linalg.inv(best[1])
    return S @ b, S


def run_policy(E, r_hour, policy, N, theta, rng):
    """在採樣期（前 CAMPAIGN_DAYS 天）內決定排氣時刻。回傳 (排氣小時列表, 錨點值)。

    錨點值 = 兩次排氣間 r_bio 平均 × (1+15% 誤差)，單位換成 0.01（讓 y 約為 1）。
    """
    Hc = CAMPAIGN_DAYS * 24
    one = lambda a, b: np.r_[1.0, E[a:b].mean(0)]
    noise = lambda a, b: r_hour[a:b].mean() / 0.01 * (1 + ANCHOR_REL * rng.standard_normal())
    if policy in ('fixed', 'random'):
        if policy == 'fixed':
            v = np.linspace(0, Hc, N + 1).round().astype(int)[1:]
        else:
            v = np.sort(rng.choice(np.arange(MIN_GAP_H, Hc + 1), N, replace=False))
        vents = [0] + [int(x) for x in v]
        rows = [one(a, b) for a, b in zip(vents[:-1], vents[1:])]
        ys = [noise(a, b) for a, b in zip(vents[:-1], vents[1:])]
        return vents, np.array(rows), np.array(ys)

    # 線上策略：前兩次照固定間隔熱身，之後每小時判斷「現在排不排」
    warm = max(MIN_GAP_H, Hc // max(N, 1))
    vents, rows, ys = [0], [], []
    m = S = None
    for t in range(1, Hc + 1):
        if len(ys) >= N:
            break
        a = vents[-1]
        if t - a < MIN_GAP_H:
            continue
        x = one(a, t)
        go = False
        if len(ys) < 2:
            go = (t - a) >= warm
        elif policy == 'infogain':
            sig2 = (ANCHOR_REL * np.mean(ys)) ** 2
            go = (x @ S @ x) / sig2 > theta
        elif policy == 'novelty':
            R = np.array(rows)[:, 1:]
            go = np.sqrt(((R - x[1:]) ** 2).mean(1)).min() > theta
        if go:
            rows.append(x)
            ys.append(noise(a, t))
            vents.append(t)
            if len(ys) >= 2:
                sig2 = (ANCHOR_REL * np.mean(ys)) ** 2
                m, S = blr(np.array(rows), np.array(ys), sig2)
    return vents, np.array(rows), np.array(ys)


def tune_theta(E, r_hour, policy, N, seed):
    """二分搜尋門檻：取「仍用得完 N 次預算」的**最嚴**門檻。

    ⚠ 不要取「第一個剛好 N 次」的門檻：那通常是最鬆的，等於一開始每 3 小時排一次、
      預算在前幾天就花光（試跑時資訊增益與新穎度因此給出逐位相同的結果）。
    """
    lo, hi = -9.0, 6.0                                     # log10 θ；lo 端用得完、hi 端用不完
    run = lambda th: run_policy(E, r_hour, policy, N, 10 ** th, np.random.default_rng(seed))
    best = run(lo)
    for _ in range(18):
        mid = (lo + hi) / 2
        got = run(mid)
        if len(got[2]) >= N:
            lo, best = mid, got                            # 還用得完 → 門檻再提高
        else:
            hi = mid
    return best


def evaluate(E, r_hour, vents, R, y):
    """回傳 (軟感測器 採樣期, 軟感測器 之後, 內插 採樣期, 內插 之後) 的相對 RMSE。"""
    Hc = CAMPAIGN_DAYS * 24
    H = len(r_hour)
    sig2 = (ANCHOR_REL * np.mean(y)) ** 2
    m, _ = blr(R, y, sig2)
    pred = (np.c_[np.ones(H), E] @ m) * 0.01
    interp = np.empty(H)
    for (a, b), val in zip(zip(vents[:-1], vents[1:]), y):
        interp[a:b] = val * 0.01
    interp[vents[-1]:] = y[-1] * 0.01                      # 之後沿用最後一個錨點
    # 以「日平均」計分：r_bio 時間尺度 3 天，逐小時的真值變化不是這個問題要解的
    day = lambda x: x[:len(x) // 24 * 24].reshape(-1, 24).mean(1)
    rel = lambda p, sl: float(np.sqrt(np.mean((day(p[sl]) - day(r_hour[sl])) ** 2))
                              / r_hour[sl].mean())
    c, post = slice(0, Hc), slice(Hc, H)
    const = np.full(H, np.mean(y) * 0.01)                  # 最笨的基準：錨點平均當常數
    return (rel(pred, c), rel(pred, post), rel(interp, c), rel(interp, post),
            rel(const, c), rel(const, post))


# ══════════════════════════════════════════════════════════
def main():
    quick = '--quick' in sys.argv
    device = os.environ.get('ML_DEVICE', 'cpu')
    seeds = [0, 1] if quick else [0, 1, 2, 3, 4]
    Ns = [4, 8, 16] if quick else [4, 8, 16, 32, 64, 128, 256]
    scen = [(c, lk) for c in (0.0, 0.5, 1.0) for lk in ('const', 'drift')]
    if quick:
        scen = [(0.0, 'const'), (1.0, 'drift')]
    policies = ['fixed', 'random', 'infogain', 'novelty']
    os.makedirs(OUT, exist_ok=True)
    rows = []
    t0 = time.time()
    for c, lk in scen:
        for sd in seeds:
            s = simulate(c, lk, 1000 + sd)
            encs = {'hand': reduce(hand_features(s))}
            Essl, lss = ssl_embeddings(s, device=device, epochs=4 if quick else 12, seed=sd)
            encs['ssl'] = reduce(Essl)
            print('[%5.0fs] c_bio=%.1f L=%-5s seed=%d　補氣 %d 次　SSL 損失 %.3f'
                  % (time.time() - t0, c, lk, sd, s['n_refill'], lss), flush=True)
            for enc, E in encs.items():
                for pol in policies:
                    for N in Ns:
                        rng = np.random.default_rng(sd * 7919 + N)
                        if pol in ('fixed', 'random'):
                            v, R, y = run_policy(E, s['r_hour'], pol, N, None, rng)
                        else:
                            v, R, y = tune_theta(E, s['r_hour'], pol, N, sd * 7919 + N)
                        if len(y) < 2:
                            continue
                        e = evaluate(E, s['r_hour'], v, R, y)
                        rows.append(dict(c_bio=c, leak=lk, seed=sd, enc=enc, policy=pol,
                                         N=N, n_used=len(y), soft_c=e[0], soft_post=e[1],
                                         interp_c=e[2], interp_post=e[3],
                                         const_c=e[4], const_post=e[5]))
    with open(os.path.join(OUT, 'results.json'), 'w', encoding='utf-8') as f:
        json.dump(dict(device=device, days=DAYS, campaign_days=CAMPAIGN_DAYS,
                       anchor_rel=ANCHOR_REL, rows=rows), f, ensure_ascii=False, indent=1)
    report(rows, Ns)
    print('\n完成 %.0f 秒 -> %s' % (time.time() - t0, OUT))


def report(rows, Ns):
    import collections
    g = collections.defaultdict(list)
    for r in rows:
        g[(r['c_bio'], r['leak'], r['enc'], r['policy'], r['N'])].append(r)
    for c, lk in sorted({(r['c_bio'], r['leak']) for r in rows}):
        print('\n══ c_bio=%.1f　L=%s　（日平均 r_bio 相對 RMSE，採樣期 / 之後 20 天；種子平均；[實際用掉的錨點]）══' % (c, lk))
        print('%-6s %-10s' % ('編碼', '策略') + ''.join('%18s' % ('N=%d' % N) for N in Ns))
        cell = lambda v, a, b: ('%.2f/%.2f [%d]' % (np.mean([x[a] for x in v]), np.mean([x[b] for x in v]),
                                                    round(np.mean([x['n_used'] for x in v])))) if v else '—'
        for enc in ('hand', 'ssl'):
            for pol in ('fixed', 'random', 'infogain', 'novelty'):
                print('%-6s %-10s' % (enc, pol) +
                      ''.join('%18s' % cell(g.get((c, lk, enc, pol, N)), 'soft_c', 'soft_post') for N in Ns))
        for nm, a, b in (('內插(固定)', 'interp_c', 'interp_post'), ('常數(固定)', 'const_c', 'const_post')):
            print('%-6s %-10s' % ('—', nm) +
                  ''.join('%18s' % cell(g.get((c, lk, 'hand', 'fixed', N)), a, b) for N in Ns))


if __name__ == '__main__':
    main()
