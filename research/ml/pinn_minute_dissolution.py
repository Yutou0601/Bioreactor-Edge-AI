# -*- coding: utf-8 -*-
"""物理約束神經網路（UDE 形式）：一小時內每分鐘的 CO2／H2 進出與甲烷產量。

2026-10-18。承 cycles/dissolution_per_minute.py（泵週期折疊）：
  · 開泵第 0 分壓力驟降，CO2（pH）只解釋泵開多降的 19–30%
  · 停泵那一分壓力瞬間回升 ~0.009，pH 沒有對應 → 像量測假象
  · 扣掉 CO2 的殘差仍跟著泵 → 假說：菌缺 H2（傳質受限），泵送 H2 進液相時吃得比較快

════════════════════════════════════════════════════════════════════════
為什麼是 UDE，不是經典配點 PINN
  泵一開一關，kLa 是階梯函數。經典 PINN 用平滑網路表示狀態，階梯處擬合很差（要很多配點，
  殘差權重難調）。這裡改成 PINN 家族的「通用微分方程」：質量守恆寫死成 ODE、用可微分的
  數值積分；**只有菌的吃氣速率 r(·) 是神經網路**。物理約束是硬的（每一步都守恆），不是罰項。

模型（壓力當量，kgf/cm²；時間＝分鐘；三批共用設備參數）
  c：液相 CO2 相對平衡的偏差（≤0 為不飽和）   h：液相 H2（≥0，平衡值 Heq）   G：頭空壓力
    dc/dt = k_C(t)·(−c) − r                       CO2 被菌從液相拿走
    dh/dt = k_H(t)·(Heq − h) − 4r                  H2 同上，4:1
    dG/dt = −k_C(t)·(−c) − k_H(t)·(Heq − h) + r − ℓ   溶進液相的離開頭空；CH4 回到頭空；ℓ＝洩漏
    感測器 = G − α·[泵開]                           α＝泵開時的動壓假象（開時讀低、停時回來）
  k_C(t) = k_on 或 k_off（泵開／停）；k_H = 1.6·k_C（穿透理論 √(D_H2/D_CO2)）
  Heq = (V_L/V_G)·H_cc,H2·y_H2·P_abs（同 dissolution_two_channel；V_L/V_G=1.6 未經確認）
  r 的三個版本：
    V1 定速   r = r0（不缺 H2；H2 傳質當作瞬間 = 4r）
    V2 Monod  r = Vmax·h/(K+h)
    V3 神經   r = Vmax·σ(NN(h/Heq, c))  （速率律由網路學，兩批以上共用）
觀測（每批 60 分、兩通道；擬合「每分鐘增量」，誤差權重＝小時間的標準誤）
  頭空壓力增量（感測器）、液相 CO2 增量（pH 換算）。樣本取在每分鐘末（停泵那一分看得到回升）。

嚴謹性檢查（9 月 PINN 的教訓：沒收斂與不可辨識長得一樣）
  · 每個版本多起點；報 χ²/點（≈1 才算擬合到雜訊水準）
  · 洩漏份額剖面：把 ℓ 固定在淨降的 0/25/50/75%，重擬合看 χ² 有沒有差 → 生物與洩漏分不分得開
  · 回收測試：用最佳擬合當真值、加同樣大小的雜訊，重擬合看洩漏份額回不回得來
輸出 -> research/ml/out_pinn_minute/（summary.json、per_minute.csv、png、log.txt）
用法：python pinn_minute_dissolution.py [--quick]（排程頁範本 pinn_minute；只用 CPU，多起點平行）
"""
import json
import os
import sys
import time

import numpy as np
import torch
import torch.nn as nn

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(RESEARCH, 'cycles'))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import dissolution_two_channel as D                                # noqa: E402
import dissolution_per_minute as M                                 # noqa: E402

OUT = os.path.join(HERE, 'out_pinn_minute')
QUICK = '--quick' in sys.argv
torch.set_default_dtype(torch.float64)
DT = 0.25                   # 分鐘（指數積分：鬆弛項精確，步長只影響 r 的顯式項）
SPM = int(round(1 / DT))     # 每分鐘幾步
BURN = 60                   # 先跑一小時；週期性另用罰項壓住
RHO_H = 1.6
LOG = []


def say(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


# ══════════════════════════════════════════════════════════
# 資料：每批每分鐘的增量（平均＋標準誤）
# ══════════════════════════════════════════════════════════
def data():
    C = D.cycles()
    out = []
    for nm, tau, *_ in D.BATCHES:
        cs = [c for c in C if c['batch'] == nm]
        dph, dp = M.fold(cs)
        p_abs = float(np.nanmedian(np.concatenate([c['P'] for c in cs]))) + D.ATM
        k_co2 = -M.VLG * D.H_CC_CO2 * M.Y_CO2 * p_abs * np.log(10)
        dc = k_co2 * dph
        se = lambda X: np.nanstd(X, 0, ddof=1) / np.sqrt(np.isfinite(X).sum(0))
        out.append(dict(name=nm, gap=int(cs[0]['gap']), n=len(dp), p_abs=p_abs,
                        dP=np.nanmean(dp, 0), dP_se=se(dp), dC=np.nanmean(dc, 0), dC_se=se(dc),
                        drop_per_min=-float(np.nanmean(dp)),
                        Heq=M.VLG * D.H_CC_H2 * (1 - M.Y_CO2) * p_abs))
    return out


# ══════════════════════════════════════════════════════════
# 模型
# ══════════════════════════════════════════════════════════
class Kinetics(nn.Module):
    def __init__(self, kind, nb):
        super().__init__()
        self.kind = kind
        self.log_v = nn.Parameter(torch.full((nb,), -6.0))        # Vmax 或 r0（kgf/cm²/分）
        if kind == 'V2':
            self.log_K = nn.Parameter(torch.tensor(-4.0))
        if kind == 'V3':
            self.net = nn.Sequential(nn.Linear(2, 16), nn.Tanh(), nn.Linear(16, 16), nn.Tanh(), nn.Linear(16, 1))

    def forward(self, h, c, Heq):
        v = torch.exp(self.log_v)
        if self.kind == 'V1':
            return v
        if self.kind == 'V2':
            return v * h / (torch.exp(self.log_K) + h)
        x = torch.stack([h / Heq, c * 20.0], -1)
        return v * torch.sigmoid(self.net(x)).squeeze(-1)


class UDE(nn.Module):
    def __init__(self, kind, bat, leak_frac=None):
        super().__init__()
        nb = len(bat)
        self.kind, self.nb = kind, nb
        self.gap = torch.tensor([b['gap'] for b in bat], dtype=torch.float64)
        self.Heq = torch.tensor([b['Heq'] for b in bat])
        self.drop = torch.tensor([b['drop_per_min'] for b in bat])
        self.log_kon = nn.Parameter(torch.tensor(-1.0))
        self.log_koff = nn.Parameter(torch.tensor(-4.0))
        self.log_alpha = nn.Parameter(torch.tensor(-5.0))
        self.leak_frac = leak_frac                                  # None＝自由；數字＝固定為淨降的這個比例
        self.logit_leak = nn.Parameter(torch.zeros(nb))
        self.kin = Kinetics(kind, nb)
        n_steps = (BURN + 60) * SPM
        ph = (np.arange(n_steps) * DT - BURN) % 60.0                       # 每一步開始時的相位
        self.register_buffer('on_steps', torch.tensor((ph[:, None] < np.array([b['gap'] for b in bat])[None, :]).astype(float)))

    def leak(self):
        f = torch.sigmoid(self.logit_leak) if self.leak_frac is None else torch.full((self.nb,), float(self.leak_frac))
        return f * self.drop

    def simulate(self):
        """回傳每分鐘末的 (G, c, h, r, 泵開)，形狀 (nb, 61)，取最後一小時（t=0…60）。"""
        kon = torch.exp(self.log_kon).clamp(max=5.0)
        koff = torch.exp(self.log_koff).clamp(max=5.0)
        ell = self.leak()
        c = torch.zeros(self.nb)
        h = self.Heq * 0.1
        G = torch.zeros(self.nb)
        n_steps = self.on_steps.shape[0]
        first = BURN * SPM
        rec_G, rec_c, rec_h, rec_r = [], [], [], []
        acc_r = torch.zeros(self.nb)
        for i in range(n_steps + 1):
            if i >= first and (i - first) % SPM == 0:              # 每分鐘末記錄
                rec_G.append(G); rec_c.append(c); rec_h.append(h); rec_r.append(acc_r)
                acc_r = torch.zeros(self.nb)
            if i == n_steps:
                break
            on = self.on_steps[i]
            kC = koff + (kon - koff) * on
            kH = RHO_H * kC
            r = self.kin(h, c, self.Heq)
            if self.kind == 'V1':
                eC = 1 - torch.exp(-kC * DT)
                tC = (-c) * eC
                c = c + tC - r * DT
                G = G - tC - 4 * r * DT + r * DT - ell * DT
            else:
                eC, eH = 1 - torch.exp(-kC * DT), 1 - torch.exp(-kH * DT)
                tC, tH = (-c) * eC, (self.Heq - h) * eH
                c = c + tC - r * DT
                h = torch.clamp(h + tH - 4 * r * DT, min=1e-9)
                G = G - tC - tH + r * DT - ell * DT
            acc_r = acc_r + r * DT
        G, c, h, r = (torch.stack(x, 1) for x in (rec_G, rec_c, rec_h, rec_r))
        m = torch.arange(61, dtype=torch.float64)
        on_at = ((m[None, :] - 1) % 60 < self.gap[:, None]).double()     # 第 m−1 分（樣本取在分末）泵是否開
        sensor = G - torch.exp(self.log_alpha) * on_at
        return sensor, c, h, r, on_at

    def predict(self):
        sensor, c, h, r, on = self.simulate()
        return sensor[:, 1:] - sensor[:, :-1], c[:, 1:] - c[:, :-1], c, h, r[:, 1:], on


def loss_fn(model, bat, w_period=10.0):
    dP, dC, c, h, r, _ = model.predict()
    zP = (dP - torch.tensor(np.stack([b['dP'] for b in bat]))) / torch.tensor(np.stack([b['dP_se'] for b in bat]))
    zC = (dC - torch.tensor(np.stack([b['dC'] for b in bat]))) / torch.tensor(np.stack([b['dC_se'] for b in bat]))
    chi2 = (zP ** 2).sum() + (zC ** 2).sum()
    period = ((c[:, -1] - c[:, 0]) ** 2).sum() / 1e-6 + ((h[:, -1] - h[:, 0]) ** 2).sum() / 1e-6
    return chi2 + w_period * period * 1e-4, chi2


def fit(kind, bat, leak_frac=None, seed=0, adam=None, lbfgs=None, init=None):
    torch.manual_seed(seed)
    m = UDE(kind, bat, leak_frac)
    rng = np.random.default_rng(seed)
    with torch.no_grad():
        m.log_kon.fill_(rng.uniform(-2.5, 0.5))
        m.log_koff.fill_(rng.uniform(-6, -2))
        m.log_alpha.fill_(np.log(rng.uniform(0.002, 0.015)))
        m.logit_leak.copy_(torch.tensor(rng.normal(0, 1, len(bat))))
        r_guess = np.array([b['drop_per_min'] for b in bat]) / 4
        m.kin.log_v.copy_(torch.tensor(np.log(r_guess * (1.0 if kind == 'V1' else 2.0))))
        if kind == 'V2':
            m.kin.log_K.fill_(np.log(rng.uniform(0.002, 0.03)))
    if init is not None:
        m.load_state_dict(init, strict=False)
    adam = adam or (60 if QUICK else 200)
    lbfgs = lbfgs or (20 if QUICK else 60)
    opt = torch.optim.Adam(m.parameters(), lr=0.05)
    for it in range(adam):
        opt.zero_grad()
        L, _ = loss_fn(m, bat)
        if not torch.isfinite(L):
            break
        L.backward()
        opt.step()
    opt2 = torch.optim.LBFGS(m.parameters(), lr=0.5, max_iter=lbfgs, line_search_fn='strong_wolfe')

    def closure():
        opt2.zero_grad()
        L, _ = loss_fn(m, bat)
        L.backward()
        return L
    try:
        opt2.step(closure)
    except RuntimeError:
        pass
    with torch.no_grad():
        L, chi2 = loss_fn(m, bat)
    return m, float(chi2), float(L)


def _job(a):
    """一個起點一個行程（小張量，多執行緒沒好處）。回傳可序列化的結果。"""
    kind, bat, leak_frac, seed, tag = a
    torch.set_num_threads(1)
    t0 = time.time()
    m, chi2, L = fit(kind, bat, leak_frac, seed=seed)
    return dict(kind=kind, leak_frac=leak_frac, seed=seed, tag=tag, chi2=chi2, L=L,
                state={k: v.detach().clone() for k, v in m.state_dict().items()}, sec=time.time() - t0)


def run_jobs(jobs):
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=min(max(1, (os.cpu_count() or 2) - 1), len(jobs))) as ex:   # 留一顆給後端
        out = list(ex.map(_job, jobs))
    for r in out:
        say('   %s 起點 %d：χ² %.1f（%.0f 秒）' % (r['tag'], r['seed'], r['chi2'], r['sec']))
    return out


def pick(results, bat, tag):
    """同一個 tag 的多個起點取損失最小的，重建成模型。"""
    rr = [r for r in results if r['tag'] == tag and np.isfinite(r['L'])]
    b = min(rr, key=lambda r: r['L'])
    m = UDE(b['kind'], bat, b['leak_frac'])
    m.load_state_dict(b['state'])
    return m, b['chi2']


def describe(m, bat):
    with torch.no_grad():
        dP, dC, c, h, r, on = m.predict()
        ell = m.leak().numpy()
    out = dict(k_on=float(torch.exp(m.log_kon).clamp(max=5)), k_off=float(torch.exp(m.log_koff).clamp(max=5)),
               alpha=float(torch.exp(m.log_alpha)), batches={})
    if m.kind == 'V2':
        out['K'] = float(torch.exp(m.kin.log_K))
    for i, b in enumerate(bat):
        rr = r[i].numpy()                                             # 每分鐘甲烷（＝CO2 被吃）量
        out['batches'][b['name']] = dict(
            leak=float(ell[i]), leak_frac=float(ell[i] / b['drop_per_min']),
            ch4_per_min_mean=float(rr.mean()), ch4_pump_on=float(rr[:b['gap']].mean()),
            ch4_pump_off=float(rr[b['gap']:].mean()),
            h_sat_mean=float(h[i].mean() / b['Heq']), h_sat_min=float(h[i].min() / b['Heq']),
            bio_share=float(4 * rr.mean() / b['drop_per_min']))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    t_all = time.time()
    bat = data()
    npts = sum(2 * 60 for _ in bat)
    for b in bat:
        say('%s：泵 %d 分、%d 小時、淨降 %.5f /分、Heq %.4f' % (b['name'], b['gap'], b['n'], b['drop_per_min'], b['Heq']))
    res = {}
    NS = 2 if QUICK else 3
    say('\n══ 1. 三種速率律，洩漏自由（各 %d 個起點，平行）══' % NS)
    out1 = run_jobs([(k, bat, None, sd, k) for k in ('V1', 'V2', 'V3') for sd in range(NS)])
    fits = {}
    for kind in ('V1', 'V2', 'V3'):
        m, chi2 = pick(out1, bat, kind)
        k = sum(p.numel() for p in m.parameters() if p.requires_grad)
        fits[kind] = m
        d = describe(m, bat)
        spread = [r['chi2'] for r in out1 if r['tag'] == kind]
        res[kind] = dict(chi2=chi2, chi2_per_pt=chi2 / npts, n_params=k, aic=chi2 + 2 * k, start_chi2=spread, **d)
        say('%s：χ²/點 %.2f、參數 %d、AIC %.1f、k_on %.3f/分、k_off %.4f/分、α %.4f（各起點 χ² %s）'
            % (kind, chi2 / npts, k, chi2 + 2 * k, d['k_on'], d['k_off'], d['alpha'], ' / '.join('%.0f' % x for x in spread)))
        for nm, x in d['batches'].items():
            say('    %-6s 生物份額 %.2f、洩漏 %.2f、CH4 泵開 %.2e／泵停 %.2e /分、液相 H2 平均飽和 %.3f'
                % (nm, x['bio_share'], x['leak_frac'], x['ch4_pump_on'], x['ch4_pump_off'], x['h_sat_mean']))
    best_kind = min(('V2', 'V3'), key=lambda k: res[k]['aic'])

    say('\n══ 2. 洩漏份額剖面（%s）＋回收測試的真值（洩漏 50%%）══' % best_kind)
    FR = (0.0, 0.25, 0.5, 0.75)
    out2 = run_jobs([(best_kind, bat, f, sd, 'leak%.2f' % f) for f in FR for sd in range(2)])
    prof = []
    for f in FR:
        _, chi2 = pick(out2, bat, 'leak%.2f' % f)
        prof.append(dict(leak_frac=f, chi2=chi2))
        say('  洩漏固定 %.0f%%：χ² %.1f（比自由解 %+.1f）' % (100 * f, chi2, chi2 - res[best_kind]['chi2']))
    res['leak_profile'] = prof
    span = max(p['chi2'] for p in prof) - min(p['chi2'] for p in prof)
    say('  → χ² 全距 %.1f（>4 才算有區分力，約等於 2σ）' % span)

    say('\n══ 3. 回收測試：洩漏 50%% 的最佳擬合當真值、加同樣大小的雜訊、洩漏自由重擬合 ══')
    truth, _ = pick(out2, bat, 'leak0.50')
    with torch.no_grad():
        tdP, tdC, *_ = truth.predict()
    fakes = []
    for s_ in range(2):
        rng = np.random.default_rng(100 + s_)
        fakes.append([dict(b, dP=tdP[i].numpy() + rng.normal(0, b['dP_se']), dC=tdC[i].numpy() + rng.normal(0, b['dC_se']))
                      for i, b in enumerate(bat)])
    out3 = run_jobs([(best_kind, fakes[s_], None, sd, 'rec%d' % s_) for s_ in range(2) for sd in range(2)])
    rec = []
    for s_ in range(2):
        m, chi2 = pick(out3, fakes[s_], 'rec%d' % s_)
        lf = [describe(m, fakes[s_])['batches'][b['name']]['leak_frac'] for b in bat]
        rec.append(dict(seed=s_, chi2=chi2, leak_frac=lf))
        say('  雜訊 %d：回收的洩漏份額 %s（真值 0.50）；χ²/點 %.2f' % (s_, ' / '.join('%.2f' % x for x in lf), chi2 / npts))
    res['recovery'] = rec

    # 每分鐘輸出（最佳版本）
    m = fits[best_kind]
    with torch.no_grad():
        dP, dC, c, h, r, on = m.predict()
        alpha = float(torch.exp(m.log_alpha))
    rows = []
    for i, b in enumerate(bat):
        for mm in range(60):
            rows.append(dict(batch=b['name'], minute=mm, pump=int(mm < b['gap']),
                             obs_dP=b['dP'][mm], fit_dP=float(dP[i, mm]), obs_dC=b['dC'][mm], fit_dC=float(dC[i, mm]),
                             ch4=float(r[i, mm]), h_sat=float(h[i, mm + 1] / b['Heq']), c_dev=float(c[i, mm + 1])))
    with open(os.path.join(OUT, 'per_minute.csv'), 'w', encoding='utf-8') as fh:
        ks = list(rows[0])
        fh.write(','.join(ks) + '\n')
        for x in rows:
            fh.write(','.join(('%.6g' % x[k]) if isinstance(x[k], float) else str(x[k]) for k in ks) + '\n')
    res['best_kind'] = best_kind
    res['seconds'] = round(time.time() - t_all, 1)
    json.dump(res, open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
    plot(rows, bat, res, best_kind)
    open(os.path.join(OUT, 'log.txt'), 'w', encoding='utf-8').write('\n'.join(LOG))
    say('\n完成 %.0f 秒 -> %s' % (time.time() - t_all, OUT))


def plot(rows, bat, res, kind):
    import logging
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    logging.getLogger('matplotlib.font_manager').setLevel(logging.ERROR)   # 找不到字型的警告會洗版紀錄
    plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Noto Sans CJK TC', 'Noto Sans CJK JP', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    fig, ax = plt.subplots(3, len(bat), figsize=(5.2 * len(bat), 10), sharex=True)
    for i, b in enumerate(bat):
        r = [x for x in rows if x['batch'] == b['name']]
        m = np.array([x['minute'] for x in r])
        for a in ax[:, i]:
            a.axvspan(-0.5, b['gap'] - 0.5, color='#e8d9a8', alpha=0.5, lw=0)
            a.axhline(0, color='#999', lw=0.7)
            a.spines[['top', 'right']].set_visible(False)
        ax[0, i].errorbar(m, [x['obs_dP'] * 1000 for x in r], yerr=b['dP_se'] * 1000, fmt='o', ms=2.5, color='#555', lw=0.6, label='實測')
        ax[0, i].plot(m, [x['fit_dP'] * 1000 for x in r], color='#d0602f', lw=1.6, label=kind)
        ax[0, i].set_title('%s　頭空壓力每分鐘變化' % b['name'])
        ax[0, i].set_ylabel('×10⁻³ kgf/cm²')
        ax[1, i].errorbar(m, [x['obs_dC'] * 1000 for x in r], yerr=b['dC_se'] * 1000, fmt='o', ms=2.5, color='#555', lw=0.6)
        ax[1, i].plot(m, [x['fit_dC'] * 1000 for x in r], color='#2f6fd0', lw=1.6)
        ax[1, i].set_title('液相 CO2 每分鐘變化（pH）')
        ax[1, i].set_ylabel('×10⁻³ kgf/cm²')
        a2 = ax[2, i]
        a2.plot(m, [x['ch4'] * 1000 * 60 for x in r], color='#2aa876', lw=1.8, label='CH4 產量')
        a2.set_ylabel('CH4 ×10⁻³ kgf/cm²/hr', color='#2aa876')
        tw = a2.twinx()
        tw.plot(m, [x['h_sat'] for x in r], color='#8a5bb0', lw=1.2, ls='--')
        tw.set_ylabel('液相 H2 飽和度', color='#8a5bb0')
        bb = res[kind]['batches'][b['name']]
        a2.set_title('模型推得：每分鐘 CH4 與液相 H2（生物份額 %.2f）' % bb['bio_share'])
        a2.set_xlabel('距開泵（分鐘）')
        if i == 0:
            ax[0, i].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'pinn_minute.png'), dpi=130)


def plot_only():
    """用輸出檔重畫（Jetson 的 matplotlib 找不到中文字型時，在筆電重畫）。"""
    import csv
    bat = data()
    res = json.load(open(os.path.join(OUT, 'summary.json'), encoding='utf-8'))
    rows = []
    for r in csv.DictReader(open(os.path.join(OUT, 'per_minute.csv'), encoding='utf-8')):
        rows.append({k: (v if k == 'batch' else float(v)) for k, v in r.items()})
    plot(rows, bat, res, res['best_kind'])


if __name__ == '__main__':
    plot_only() if '--plot-only' in sys.argv else main()
