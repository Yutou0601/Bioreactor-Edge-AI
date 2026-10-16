# -*- coding: utf-8 -*-
"""分離可行性的機理模擬：壓力＋pH＋ORP，答案已知、雜訊取自真實循環。

2026-10-16。給 separation_ga.py 用（GA 篩「哪些現有特徵能分離」）。

════════════════════════════════════════════════════════════════════════
為什麼要機理模型（不只壓力）
  單看壓力，常數移除與「平衡壓力低一點」是恆等式級的簡併（pinn_batched、
  design_identifiability 已證）。pH 與 ORP 觀測的是**另外的隱藏狀態**：
    · pH 反映液相溶解 CO2（緩衝下 pH ≈ 常數 − log10[CO2aq]）
        溶解 → 液相 CO2 增加 → pH 下降；生物吃掉液相 CO2 → pH 上升
    · ORP（氫電極的 Nernst）＝ −61.1·pH − 30.6·log10(p_H2) mV（35 °C）
        三條途徑對氣體組成的影響不同（溶解帶走 CO2；生物 4:1；洩漏可能偏 H2）
  原理上可能打開簡併——這支要量的是**在真實雜訊下**還剩多少。

模型（每個循環；分壓單位 kg/cm² 絕對壓，1 atm = 1.033）
  狀態：h（H2）、c（CO2 氣相）、m（CH4）、n（惰性）、L（液相 CO2 存量，以氣相壓力當量計）
    x = L/γ                         液相 CO2 所平衡的分壓（γ＝液相容量比）
    F = kLa(t)·γ·(c − x)            氣→液的 CO2 傳質（kLa 隨泵開關變）
    R = kb·h·x/(x + Kx)             生物 CO2 消耗率（H2 質傳限制，CO2 耗盡時停）
    洩漏：每種氣體 λ·w_i·p_i（w_i 介於整體流與 Graham 擴散 1/√M 之間）
    dh = −4R − 漏_h；dc = −F − 漏_c；dm = +R − 漏_m；dn = −漏_n；dL = F − R
  總壓降 ＝ (F − R) + 4R + 漏 ＝ 溶解（液相存量淨增）＋ 生物 ＋ 洩漏 —— 三者恰好相加。
  量測：P＝h+c+m+n−1.033；pH＝pH0 − log10(x/x0)；ORP＝O0 − 61.1(pH−pH0) − 30.6·log10(h/h0)

雜訊（關鍵：不是白雜訊）
  每個模擬循環借一個真實循環當模板：沿用其時間軸、泵開關、起始壓力／pH／ORP，
  並加上該循環**同一時段**的三通道真實殘差（保留泵鋸齒、自相關、通道間相關），
  再量化（P 0.01、pH 0.01、ORP 1 mV）。殘差兩種取法：
    N1 中度：壓力扣指數擬合、pH／ORP 扣線性趨勢
    N2 保守：pH／ORP 只扣平均（真實循環內的趨勢全當雜訊——若那些趨勢其實是機理
       訊號，N2 會低估可分離性；兩者都報）

先驗（三種，邊際分布相同、相關結構不同）
  A   各機理參數彼此獨立（訓練用）
  B1  生物與溶解缺口正相關 +0.8、生物與洩漏負相關 −0.8
  B2  相反（−0.8／+0.8）
  只靠「先驗相關」猜中的特徵在 B1／B2 會崩；真的帶資訊的不會。

用法（Jetson）：ML_DEVICE=cuda python3 separation_sim.py [--noise N1|N2] [--n 6000]
輸出 -> research/ml/out_separation/sim_<noise>.npz（特徵、真值、真實循環的特徵）
"""
import math
import os
import sys
import time

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out_separation')
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
DEVICE = torch.device(os.environ.get('ML_DEVICE', 'cpu'))
DT = torch.float64
ATM = 1.033
NERNST_PH, NERNST_H2 = 61.1, 30.6          # mV（35 °C）
QP, QPH, QORP = 0.01, 0.01, 1.0
# pH 計情境（--ph_res R --ph_sigma S）：None＝照舊（真實殘差原樣、量化 0.01）。
# 設定時：真實 pH 殘差先做 15 分鐘移動平均（去掉現有 0.01 量化的跳動、保留慢速漂移——
# 換 pH 計也消不掉的那部分），再加新 pH 計的白雜訊 S，以解析度 R 量化。
PH_RES = float(sys.argv[sys.argv.index('--ph_res') + 1]) if '--ph_res' in sys.argv else None
PH_SIGMA = float(sys.argv[sys.argv.index('--ph_sigma') + 1]) if '--ph_sigma' in sys.argv else 0.0

sys.path.insert(0, HERE)
from design_identifiability import fit_cycles             # noqa: E402

FEATURES = [
    # 壓力（repo 既有的每循環特徵 ＋ 泵開／泵停速率、殘差自相關）
    'hours', 'p0', 'drop', 'drop_rate', 'k_single', 'A_single', 'r2_single', 's0',
    'slope_early', 'slope_late', 'curv', 'rate_pump_on', 'rate_pump_off', 'resid_ac1',
    # pH
    'ph_mean', 'dph', 'ph_slope', 'ph_slope_late_minus_early', 'ph_on_minus_off', 'corr_ph_p',
    # ORP
    'orp_mean', 'dorp', 'orp_slope', 'orp_on_minus_off', 'corr_orp_p', 'dorp_h2part',
]
TARGETS = ['bio', 'diss', 'leak', 'total']


# ── 特徵（真實與模擬共用同一個函式）─────────────────────────────────────
def _slope(t, y):
    t = t - t.mean()
    return float((t * (y - y.mean())).sum() / (t * t).sum())


def cycle_features(t, P, pH, ORP, pump, k_hat, A_hat):
    n = len(t)
    T = float(t[-1])
    third = max(5, n // 3)
    w = max(5, min(30, n // 10))
    fit = A_hat + (P[0] - A_hat) * np.exp(-k_hat * t)
    res = P - fit
    ac1 = float(np.corrcoef(res[:-1], res[1:])[0, 1]) if res.std() > 0 else 0.0
    dP = np.diff(P) / np.diff(t)
    dph = np.diff(pH) / np.diff(t)
    dorp = np.diff(ORP) / np.diff(t)
    on = pump[1:]
    def onoff(d):
        if on.any() and (~on).any():
            return float(d[on].mean() - d[~on].mean())
        return 0.0
    tc = (t - t.mean()) / (T + 1e-9)
    curv = float(np.polyfit(tc, P, 2)[0])
    d_ph = float(pH[-w:].mean() - pH[:w].mean())
    d_orp = float(ORP[-w:].mean() - ORP[:w].mean())
    return [
        T, float(P[0]), float(P[0] - P[-1]), float((P[0] - P[-1]) / T), float(k_hat), float(A_hat),
        float(1 - ((P - fit) ** 2).sum() / max(((P - P.mean()) ** 2).sum(), 1e-12)),
        float(k_hat * (P[0] - A_hat)),
        -_slope(t[:third], P[:third]), -_slope(t[-third:], P[-third:]), curv,
        float(-dP[on].mean()) if on.any() else 0.0, float(-dP[~on].mean()) if (~on).any() else 0.0,
        ac1,
        float(pH.mean()), d_ph, _slope(t, pH),
        _slope(t[-third:], pH[-third:]) - _slope(t[:third], pH[:third]), onoff(dph),
        float(np.corrcoef(pH, P)[0, 1]) if pH.std() > 0 else 0.0,
        float(ORP.mean()), d_orp, _slope(t, ORP), onoff(dorp),
        float(np.corrcoef(ORP, P)[0, 1]) if ORP.std() > 0 else 0.0,
        d_orp + NERNST_PH * d_ph,
    ]


# ── 真實循環（模板與殘差庫）──────────────────────────────────────────────
def load_templates(noise):
    raw = np.load(os.path.join(os.environ.get('REAL_NPY', '/tmp/pb/real_cycles_3ch.npy')),
                  allow_pickle=True)
    tpl = []
    for c in raw:
        t = np.asarray(c['t'], float)
        P, pH, O = (np.asarray(c[k], float) for k in ('P', 'pH', 'ORP'))
        tt = torch.tensor(t, dtype=DT, device=DEVICE)
        kh, Ah, _ = fit_cycles(torch.tensor(P, dtype=DT, device=DEVICE)[None, :], tt)
        kh, Ah = float(kh), float(Ah)
        rP = P - (Ah + (P[0] - Ah) * np.exp(-kh * t))
        if noise == 'N1':
            rpH = pH - np.polyval(np.polyfit(t, pH, 1), t)
            rO = O - np.polyval(np.polyfit(t, O, 1), t)
        else:
            rpH, rO = pH - pH.mean(), O - O.mean()
        if PH_RES is not None:
            w = 15
            rpH = np.convolve(np.pad(rpH, (w // 2, w - 1 - w // 2), mode='edge'),
                              np.ones(w) / w, mode='valid')
        tpl.append(dict(batch=c['batch'], cycle=int(c['cycle']), t=t, P=P, pH=pH, ORP=O,
                        pump=np.asarray(c['pump'], bool), k=kh, A=Ah,
                        rP=rP, rpH=rpH, rO=rO,
                        feat=cycle_features(t, P, pH, O, np.asarray(c['pump'], bool), kh, Ah)))
    return tpl


# ── 先驗 ────────────────────────────────────────────────────────────────
def draw_params(n, prior, rng):
    """回傳 dict of arrays。邊際分布三種先驗相同，只有相關結構不同（高斯 copula）。"""
    C = np.eye(3)
    if prior == 'B1':
        C = np.array([[1, 0.8, -0.8], [0.8, 1, -0.64], [-0.8, -0.64, 1]])
    elif prior == 'B2':
        C = np.array([[1, -0.8, 0.8], [-0.8, 1, -0.64], [0.8, -0.64, 1]])
    z = rng.multivariate_normal(np.zeros(3), C, size=n)
    u = 0.5 * (1 + np.vectorize(math.erf)(z / math.sqrt(2)))          # 均勻邊際
    bio0 = 0.04 * u[:, 0]                       # 生物在循環起點造成的壓降速率 0–0.04 /hr
    deficit = 0.5 * u[:, 1]                     # 液相未飽和度 0–0.5（x0 = c0·(1−deficit)）
    leak0 = 0.04 * u[:, 2]                      # 洩漏造成的起始壓降速率 0–0.04 /hr
    return dict(
        bio0=bio0, deficit=deficit, leak0=leak0,
        keff=np.exp(rng.uniform(np.log(0.02), np.log(1.0), n)),      # 溶解的有效速率常數
        gamma=np.exp(rng.uniform(np.log(0.3), np.log(5.0), n)),   # 液相 CO2 容量比（液／頭空體積未知 → 放寬；越大 pH 訊號越小＝保守）
        f_off=rng.uniform(0.02, 0.3, n),          # 泵停時 kLa 剩幾成
        f_ch4=rng.uniform(0.05, 0.40, n), f_inert=rng.uniform(0.0, 0.05, n),
        feed_dev=rng.uniform(-0.05, 0.05, n),     # 補氣 H2 比例偏離 4:1
        sel=rng.uniform(0, 1, n),                 # 洩漏選擇性：0 整體流、1 Graham 擴散
    )


def simulate(tpl, prm, idx_tpl, rng, substeps=6):
    """同一模板（同一時間軸）的一批循環一起積分。回傳 P、pH、ORP（已加殘差、已量化）與真值。"""
    t = tpl['t']
    n = len(t)
    B = len(idx_tpl)
    g = lambda a: torch.tensor(a, dtype=DT, device=DEVICE)
    P0 = tpl['P'][0] + ATM
    fm, fn = g(prm['f_ch4'][idx_tpl]), g(prm['f_inert'][idx_tpl])
    share_h = 0.8 * (1 + g(prm['feed_dev'][idx_tpl]))
    rest = P0 * (1 - fm - fn)
    h, c = rest * share_h, rest * (1 - share_h)
    m, nn = P0 * fm, P0 * fn
    gam = g(prm['gamma'][idx_tpl])
    x = c * (1 - g(prm['deficit'][idx_tpl]))
    L = gam * x
    duty = float(tpl['pump'].mean())
    f_off = g(prm['f_off'][idx_tpl])
    kla_on = g(prm['keff'][idx_tpl]) / ((1 + gam) * (duty + f_off * (1 - duty)))
    Kx = 0.02
    kb = g(prm['bio0'][idx_tpl]) / (3 * h * x / (x + Kx))         # 起點生物壓降速率 = 3R0
    # 洩漏：每種氣體 λ w_i p_i；w 介於整體流（1）與 Graham（√(2/M)）
    sel = g(prm['sel'][idx_tpl])
    w = {k: (1 - sel) + sel * math.sqrt(2.0 / M) for k, M in (('h', 2), ('c', 44), ('m', 16), ('n', 28))}
    lam = g(prm['leak0'][idx_tpl]) / (w['h'] * h + w['c'] * c + w['m'] * m + w['n'] * nn)
    h0, x0 = h.clone(), x.clone()
    Ps, xs, hs = [torch.zeros(B, n, dtype=DT, device=DEVICE) for _ in range(3)]
    acc = {k: torch.zeros(B, dtype=DT, device=DEVICE) for k in ('bio', 'diss', 'leak')}
    pump = torch.tensor(tpl['pump'], device=DEVICE)
    Ps[:, 0], xs[:, 0], hs[:, 0] = h + c + m + nn - ATM, x, h
    for j in range(1, n):
        dt_h = float(t[j] - t[j - 1]) / substeps
        kla = torch.where(pump[j], kla_on, kla_on * f_off)
        for _ in range(substeps):
            xx = L / gam
            F = kla * gam * (c - xx)
            R = kb * h * xx.clamp_min(0) / (xx.clamp_min(0) + Kx)
            lh, lc, lm, ln = (lam * w['h'] * h, lam * w['c'] * c, lam * w['m'] * m,
                              lam * w['n'] * nn)
            h = h + dt_h * (-4 * R - lh)
            c = c + dt_h * (-F - lc)
            m = m + dt_h * (R - lm)
            nn = nn + dt_h * (-ln)
            L = L + dt_h * (F - R)
            acc['bio'] += dt_h * 4 * R
            acc['diss'] += dt_h * (F - R)
            acc['leak'] += dt_h * (lh + lc + lm + ln)
        Ps[:, j], xs[:, j], hs[:, j] = h + c + m + nn - ATM, L / gam, h
    T = float(t[-1])
    truth = {k: (v / T).cpu().numpy() for k, v in acc.items()}
    truth['total'] = truth['bio'] + truth['diss'] + truth['leak']
    pH0, O0 = tpl['pH'][0], tpl['ORP'][0]
    pH = pH0 - torch.log10(xs.clamp_min(1e-9) / x0[:, None])
    ORP = O0 - NERNST_PH * (pH - pH0) - NERNST_H2 * torch.log10(hs / h0[:, None])
    P = Ps.cpu().numpy() + tpl['rP'][None, :]
    pH = pH.cpu().numpy() + tpl['rpH'][None, :]
    ORP = ORP.cpu().numpy() + tpl['rO'][None, :]
    P = np.round(P / QP) * QP
    if PH_RES is not None:
        pH = pH + PH_SIGMA * rng.standard_normal(pH.shape)
        pH = np.round(pH / PH_RES) * PH_RES
    else:
        pH = np.round(pH / QPH) * QPH
    ORP = np.round(ORP / QORP) * QORP
    return P, pH, ORP, truth


def build(tpls, n, prior, seed):
    rng = np.random.default_rng(seed)
    prm = draw_params(n, prior, rng)
    which = rng.integers(0, len(tpls), n)
    X = np.zeros((n, len(FEATURES)))
    Y = np.zeros((n, len(TARGETS)))
    for ti, tpl in enumerate(tpls):
        idx = np.flatnonzero(which == ti)
        if not len(idx):
            continue
        P, pH, ORP, truth = simulate(tpl, prm, idx, rng)
        tt = torch.tensor(tpl['t'], dtype=DT, device=DEVICE)
        kh, Ah, _ = fit_cycles(torch.tensor(P, dtype=DT, device=DEVICE), tt)
        kh, Ah = kh.cpu().numpy(), Ah.cpu().numpy()
        for r, i in enumerate(idx):
            X[i] = cycle_features(tpl['t'], P[r], pH[r], ORP[r], tpl['pump'], kh[r], Ah[r])
            Y[i] = [truth[k][r] for k in TARGETS]
    P_meta = np.column_stack([prm[k] for k in ('bio0', 'deficit', 'leak0', 'keff', 'gamma',
                                               'f_off', 'f_ch4', 'feed_dev', 'sel')])
    return X, Y, which, P_meta


# ── 多循環／跨條件：K 個循環共用生物與洩漏 ───────────────────────────────
def template_folds(tpls, nfold=3):
    """與 separation_ga.load() 同一規則：依批次分層、批內輪流分配。"""
    fold = np.zeros(len(tpls), int)
    for b in ('tau1', 'tau5', 'tau10'):
        mine = [i for i, tp in enumerate(tpls) if tp['batch'] == b]
        for j, i in enumerate(mine):
            fold[i] = j % nfold
    return fold


GROUP_EXTRA = ['grp_rb_from_A_vs_invk', 'grp_Peq_from_A_vs_invk', 'grp_dph_vs_drop_slope',
               'grp_k_contrast', 'grp_corr_A_invk']


def build_groups(tpls, n_groups, K, prior, seed, mode):
    """n_groups 組、每組 K 個循環。組內共用：生物、洩漏（速率與選擇性）、補氣偏差、γ、
    泵開時的 kLa、f_off；每循環各自：溶解缺口（組平均 ± 0.1）、CH4 比例、模板。

    mode='same'：模板任意；mode='cross'：一半 τ=1、一半 τ=10 模板（同一 kLa、不同泵開
    比例 → 真實的 k 對比）。每組的模板只從同一折抽（給依模板分組交叉驗證用）。
    回傳 X（組特徵＝單循環特徵的組平均＋跨循環特徵）、Y（組平均真值）、fold。
    """
    rng = np.random.default_rng(seed)
    fold_t = template_folds(tpls)
    g = draw_params(n_groups, prior, rng)                       # 組層級（先驗作用在這裡）
    kla_on = np.exp(rng.uniform(np.log(0.05), np.log(10.0), n_groups))
    n = n_groups * K
    gi = np.repeat(np.arange(n_groups), K)
    prm = {k: v[gi].copy() for k, v in g.items()}
    prm['deficit'] = np.clip(prm['deficit'] + rng.uniform(-0.1, 0.1, n), 0, 0.5)
    prm['f_ch4'] = rng.uniform(0.05, 0.40, n)
    gfold = rng.integers(0, 3, n_groups)
    which = np.zeros(n, int)
    for grp in range(n_groups):
        pool = np.flatnonzero(fold_t == gfold[grp])
        if mode == 'cross':
            t1 = [i for i in pool if tpls[i]['batch'] == 'tau1']
            t10 = [i for i in pool if tpls[i]['batch'] == 'tau10']
            pick = list(rng.choice(t1, K // 2)) + list(rng.choice(t10, K - K // 2))
        else:
            pick = list(rng.choice(pool, K))
        which[grp * K:(grp + 1) * K] = pick
    # keff 由共用的 kLa 與各模板的泵開比例決定（simulate 會反推回同一個 kla_on）
    duty = np.array([tpls[w]['pump'].mean() for w in which])
    prm['keff'] = kla_on[gi] * (1 + prm['gamma']) * (duty + prm['f_off'] * (1 - duty))
    Xc = np.zeros((n, len(FEATURES)))
    Yc = np.zeros((n, len(TARGETS)))
    for ti, tpl in enumerate(tpls):
        idx = np.flatnonzero(which == ti)
        if not len(idx):
            continue
        P, pH, ORP, truth = simulate(tpl, prm, idx, rng)
        tt = torch.tensor(tpl['t'], dtype=DT, device=DEVICE)
        kh, Ah, _ = fit_cycles(torch.tensor(P, dtype=DT, device=DEVICE), tt)
        kh, Ah = kh.cpu().numpy(), Ah.cpu().numpy()
        for r, i in enumerate(idx):
            Xc[i] = cycle_features(tpl['t'], P[r], pH[r], ORP[r], tpl['pump'], kh[r], Ah[r])
            Yc[i] = [truth[k][r] for k in TARGETS]
    return group_features(Xc, gi, n_groups), \
        np.array([Yc[gi == q].mean(0) for q in range(n_groups)]), gfold


def group_features(Xc, gi, n_groups):
    fi = {f: i for i, f in enumerate(FEATURES)}
    out = []
    for q in range(n_groups):
        X = Xc[gi == q]
        A, invk = X[:, fi['A_single']], 1.0 / np.maximum(X[:, fi['k_single']], 1e-4)
        if np.ptp(invk) > 0:
            sl, ic = np.polyfit(invk, A, 1)
            cA = float(np.corrcoef(invk, A)[0, 1])
        else:
            sl, ic, cA = 0.0, float(A.mean()), 0.0
        dr, dp = X[:, fi['drop_rate']], X[:, fi['dph']]
        s2 = float(np.polyfit(dr, dp, 1)[0]) if np.ptp(dr) > 0 else 0.0
        kc = float(np.log(X[:, fi['k_single']].max() / max(X[:, fi['k_single']].min(), 1e-4)))
        out.append(list(X.mean(0)) + [-sl, ic, s2, kc, cA])
    return np.array(out)


def main_groups(K, mode, noise, n_groups):
    t0 = time.perf_counter()
    tpls = load_templates(noise)
    print('分組模擬：每組 %d 個循環、%s；雜訊 %s；%s' % (K, mode, noise, DEVICE.type))
    out = {}
    for name, prior, seed, size in (('trainA', 'A', 11, n_groups), ('testA', 'A', 12, n_groups // 2),
                                    ('testB1', 'B1', 13, n_groups // 2), ('testB2', 'B2', 14, n_groups // 2)):
        X, Y, gf = build_groups(tpls, size, K, prior, seed, mode)
        out[name + '_X'], out[name + '_Y'], out[name + '_fold'] = X, Y, gf
        print('  %-7s %5d 組  %.0f 秒' % (name, size, time.perf_counter() - t0))
    out['features'] = np.array(FEATURES + GROUP_EXTRA)
    out['targets'] = np.array(TARGETS)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'grp_%s_K%d_%s.npz' % (mode, K, noise))
    np.savez_compressed(path, **out)
    print('-> %s' % path)


def main():
    noise = 'N2' if '--noise' in sys.argv and sys.argv[sys.argv.index('--noise') + 1] == 'N2' else 'N1'
    if '--group' in sys.argv:
        K = int(sys.argv[sys.argv.index('--group') + 1])
        mode = 'cross' if '--cross' in sys.argv else 'same'
        ng = int(sys.argv[sys.argv.index('--n') + 1]) if '--n' in sys.argv else 1500
        return main_groups(K, mode, noise, ng)
    n = int(sys.argv[sys.argv.index('--n') + 1]) if '--n' in sys.argv else 6000
    t0 = time.perf_counter()
    tpls = load_templates(noise)
    print('模板（真實循環）%d 個；雜訊 %s；%s' % (len(tpls), noise, DEVICE.type))
    out = {}
    for name, prior, seed, size in (('trainA', 'A', 1, n), ('testA', 'A', 2, n // 2),
                                    ('testB1', 'B1', 3, n // 2), ('testB2', 'B2', 4, n // 2)):
        X, Y, which, meta = build(tpls, size, prior, seed)
        out[name + '_X'], out[name + '_Y'], out[name + '_tpl'], out[name + '_meta'] = X, Y, which, meta
        print('  %-7s %5d 個循環  %.0f 秒' % (name, size, time.perf_counter() - t0))
    out['real_X'] = np.array([tp['feat'] for tp in tpls])
    out['real_id'] = np.array(['%s#%d' % (tp['batch'], tp['cycle']) for tp in tpls])
    out['features'] = np.array(FEATURES)
    out['targets'] = np.array(TARGETS)
    os.makedirs(OUT, exist_ok=True)
    tag = noise if PH_RES is None else '%s_ph%g' % (noise, PH_RES)
    path = os.path.join(OUT, 'sim_%s.npz' % tag)
    np.savez_compressed(path, **out)
    print('-> %s' % path)


if __name__ == '__main__':
    main()
