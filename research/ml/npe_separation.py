# -*- coding: utf-8 -*-
"""用 pH＋壓力分離生物／洩漏／溶解：攤銷式神經後驗估計（NPE）＋序列編碼器＋跨循環集合池化。

2026-10-18。承 separation_sim（機理模擬器）與 ph_abc（ABC：溶解通過校準，生物與洩漏失敗）。

════════════════════════════════════════════════════════════════════════
為什麼換架構
  ABC 只用 9 個手工摘要統計量。NPE 讓網路直接讀整條壓力與 pH 序列，自己學摘要：
    · 每循環編碼器：1D-CNN（局部形狀、泵脈衝）→ 雙向 GRU（整段時序）→ 注意力池化
    · 輸出不是點估計，是後驗分布：混合密度網路（6 個全共變異高斯）
    · 階層版：K 個循環（τ=1 與 τ=10 各半）共用生物與洩漏 → DeepSets（平均＋最大池化）
      合成一個組嵌入，估組層級的速率。跨 τ 給「同一個生物、不同的 kLa」對比。

物理上能分到哪裡（先講清楚，網路再新也超不過）
  pH 只看液相 CO2。每單位壓降帶走的 CO2：生物 0.25、整體流洩漏 ≈ 頭空 CO2 比例
  （約 0.15–0.2）、H2 選擇性洩漏（Graham）≈ 0.05。所以 pH 只在洩漏偏 H2 時分得開
  生物與洩漏；整體流洩漏的 pH 響應幾乎與生物相同。模擬器的洩漏選擇性 sel ~ U(0,1)。
  因此同時跑「無雜訊」版本當**物理上限**：無雜訊都分不開，就是資訊不存在。

驗證（與 ph_abc 同一套標準，校準不過就不套用到真實資料）
  · 依模板分 3 折（template_folds）：測試循環的真實殘差，訓練時從沒看過
  · 先驗 A 訓練；A／B1／B2（相關結構相反）測試。80% 區間涵蓋率在 B1、B2 都落在
    0.70–0.90 才算通過
  · 單循環＋真實雜訊跑完 3 折 → 每個真實循環都由「沒看過它的模板」的模型推估
  · 基準：同一批模擬的手工特徵＋梯度提升（只比 R²）

用法（Jetson）：ML_DEVICE=cuda REAL_NPY=out_separation/real_cycles_3ch.npy \
               python3 -u npe_separation.py [--quick]
輸出 -> research/ml/out_npe/（results.json、real_posteriors.csv、log）
"""
import copy
import json
import os
import sys
import time

import numpy as np
import torch
import torch.nn as nn

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
os.environ.setdefault('REAL_NPY', os.path.join(HERE, 'out_separation', 'real_cycles_3ch.npy'))
import separation_sim as S                                         # noqa: E402

DEV = torch.device(os.environ.get('ML_DEVICE', 'cpu'))
OUT = os.path.join(HERE, 'out_npe')
L = 128                       # 每循環重採樣成 128 格（正規化時間）
TARGETS = ['bio', 'leak', 'diss']
SCALE = 0.01                  # 速率以 0.01 kgf/cm²/hr 為單位
LOG = []


def say(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


# ══════════════════════════════════════════════════════════
# 資料
# ══════════════════════════════════════════════════════════
def bin_matrix(t):
    """(L, n) 平均矩陣：把一條時間軸分成 L 格、每格取平均。"""
    tn = (t - t[0]) / (t[-1] - t[0])
    b = np.minimum((tn * L).astype(int), L - 1)
    M = np.zeros((L, len(t)))
    M[b, np.arange(len(t))] = 1.0
    M /= np.maximum(M.sum(1, keepdims=True), 1)
    return M


def featurize(tpl, P, pH):
    """序列 (B, 3, L)：壓力相對起點（/0.1）、pH 相對起點（/0.01）、泵開比例；純量 (B, 4)。"""
    M = bin_matrix(tpl['t'])
    p = (P - P[:, :1]) / 0.1
    h = (pH - pH[:, :1]) / 0.01
    pump = np.broadcast_to(tpl['pump'].astype(float), P.shape)
    seq = np.stack([p @ M.T, h @ M.T, pump @ M.T], 1).astype(np.float32)
    T = float(tpl['t'][-1])
    sc = np.column_stack([np.full(len(P), T / 10), np.full(len(P), tpl['pump'].mean() * 5),
                          P[:, 0], (pH[:, 0] - 7) * 10]).astype(np.float32)
    return seq, sc


def clean_copy(tpls):
    """無雜訊版本：真實殘差歸零（量化另外關掉）。"""
    out = []
    for tp in tpls:
        c = copy.copy(tp)
        c['rP'] = np.zeros_like(tp['rP'])
        c['rpH'] = np.zeros_like(tp['rpH'])
        c['rO'] = np.zeros_like(tp['rO'])
        out.append(c)
    return out


def set_quant(clean):
    S.QP, S.QPH, S.QORP = (1e-9, 1e-9, 1e-9) if clean else (0.01, 0.01, 1.0)


def gen_single(tpls, n, prior, seed, ids):
    rng = np.random.default_rng(seed)
    prm = S.draw_params(n, prior, rng)
    which = rng.choice(ids, n)
    seq = np.zeros((n, 3, L), np.float32)
    sc = np.zeros((n, 4), np.float32)
    Y = np.zeros((n, 3), np.float32)
    for ti in np.unique(which):
        idx = np.flatnonzero(which == ti)
        P, pH, _, truth = S.simulate(tpls[ti], prm, idx, rng)
        seq[idx], sc[idx] = featurize(tpls[ti], P, pH)
        Y[idx] = np.column_stack([truth[k] for k in TARGETS]) / SCALE
    return seq, sc, Y, prm['sel']


def gen_group(tpls, n_groups, K, prior, seed, ids):
    """與 separation_sim.build_groups 相同的共享結構（組內共用生物、洩漏、選擇性、
    補氣偏差、γ、泵開 kLa、f_off；各循環自己的溶解缺口、CH4 比例、模板），
    模板一半 τ=1、一半 τ=10，只從 ids 抽。"""
    rng = np.random.default_rng(seed)
    g = S.draw_params(n_groups, prior, rng)
    kla_on = np.exp(rng.uniform(np.log(0.05), np.log(10.0), n_groups))
    n = n_groups * K
    gi = np.repeat(np.arange(n_groups), K)
    prm = {k: v[gi].copy() for k, v in g.items()}
    prm['deficit'] = np.clip(prm['deficit'] + rng.uniform(-0.1, 0.1, n), 0, 0.5)
    prm['f_ch4'] = rng.uniform(0.05, 0.40, n)
    t1 = [i for i in ids if tpls[i]['batch'] == 'tau1']
    t10 = [i for i in ids if tpls[i]['batch'] == 'tau10']
    which = np.concatenate([np.concatenate([rng.choice(t1, K // 2), rng.choice(t10, K - K // 2)])
                            for _ in range(n_groups)])
    duty = np.array([tpls[w]['pump'].mean() for w in which])
    prm['keff'] = kla_on[gi] * (1 + prm['gamma']) * (duty + prm['f_off'] * (1 - duty))
    seq = np.zeros((n, 3, L), np.float32)
    sc = np.zeros((n, 4), np.float32)
    Yc = np.zeros((n, 3), np.float32)
    for ti in np.unique(which):
        idx = np.flatnonzero(which == ti)
        P, pH, _, truth = S.simulate(tpls[ti], prm, idx, rng)
        seq[idx], sc[idx] = featurize(tpls[ti], P, pH)
        Yc[idx] = np.column_stack([truth[k] for k in TARGETS]) / SCALE
    Y = Yc.reshape(n_groups, K, 3).mean(1)
    return seq.reshape(n_groups, K, 3, L), sc.reshape(n_groups, K, 4), Y, g['sel']


# ══════════════════════════════════════════════════════════
# 模型
# ══════════════════════════════════════════════════════════
class CycleEncoder(nn.Module):
    def __init__(self, emb=64):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(3, 32, 5, padding=2), nn.GELU(),
            nn.Conv1d(32, 64, 5, padding=4, dilation=2), nn.GELU(),
            nn.Conv1d(64, 64, 5, padding=8, dilation=4), nn.GELU())
        self.gru = nn.GRU(64, 48, batch_first=True, bidirectional=True)
        self.att = nn.Linear(96, 1)
        self.mlp = nn.Sequential(nn.Linear(96 + 4, 128), nn.GELU(), nn.Linear(128, emb))

    def forward(self, x, s):                       # x (B,3,L)  s (B,4)
        h = self.conv(x).transpose(1, 2)            # (B,L,64)
        h, _ = self.gru(h)                          # (B,L,96)
        a = torch.softmax(self.att(h), 1)
        z = (a * h).sum(1)
        return self.mlp(torch.cat([z, s], 1))


class MDN(nn.Module):
    """混合密度網路：M 個 D 維全共變異高斯。"""
    def __init__(self, emb, D=3, M=6):
        super().__init__()
        self.D, self.M = D, M
        self.net = nn.Sequential(nn.Linear(emb, 128), nn.GELU(),
                                 nn.Linear(128, M * (1 + D + D * (D + 1) // 2)))
        self.tril = torch.tril_indices(D, D)

    def dist(self, e):
        o = self.net(e)
        B, M, D = len(e), self.M, self.D
        logit = o[:, :M]
        mu = o[:, M:M + M * D].view(B, M, D)
        lt = o[:, M + M * D:].view(B, M, -1)
        Lm = torch.zeros(B, M, D, D, device=e.device, dtype=e.dtype)
        Lm[:, :, self.tril[0], self.tril[1]] = lt
        diag = torch.nn.functional.softplus(torch.diagonal(Lm, dim1=-2, dim2=-1)) + 1e-3
        Lm = Lm.tril(-1) + torch.diag_embed(diag)
        mix = torch.distributions.Categorical(logits=logit)
        comp = torch.distributions.MultivariateNormal(mu, scale_tril=Lm)
        return torch.distributions.MixtureSameFamily(mix, comp)


class NPE(nn.Module):
    def __init__(self, group=False, emb=64):
        super().__init__()
        self.group = group
        self.enc = CycleEncoder(emb)
        self.pool = nn.Sequential(nn.Linear(2 * emb, 128), nn.GELU(), nn.Linear(128, emb)) if group else None
        self.head = MDN(emb)
        self.register_buffer('ymu', torch.zeros(3))      # 目標標準化（訓練時設定），後驗抽樣再換回
        self.register_buffer('ysd', torch.ones(3))

    def embed(self, x, s):
        if not self.group:
            return self.enc(x, s)
        G, K = x.shape[:2]
        e = self.enc(x.reshape(G * K, *x.shape[2:]), s.reshape(G * K, -1)).view(G, K, -1)
        return self.pool(torch.cat([e.mean(1), e.max(1).values], 1))   # DeepSets：與順序無關

    def dist(self, x, s):
        return self.head.dist(self.embed(x, s))


def train(model, X, Sc, Y, max_epochs, patience, bs=512, lr=1e-3, seed=0, tag=''):
    """AdamW＋驗證損失停滯就減半學習率＋早停；回傳 (最佳驗證 NLL（標準化空間）, 實際用掉的輪數)。"""
    torch.manual_seed(seed)
    n = len(X)
    nv = max(min(256, n // 5), n // 10)
    perm = np.random.default_rng(seed).permutation(n)
    va, tr = perm[:nv], perm[nv:]
    tX = lambda a: torch.tensor(a, device=DEV)
    model.ymu.copy_(torch.tensor(Y[tr].mean(0), device=DEV))
    model.ysd.copy_(torch.tensor(Y[tr].std(0) + 1e-6, device=DEV))
    Xt, St = tX(X), tX(Sc)
    Yt = (tX(Y) - model.ymu) / model.ysd
    vt = torch.tensor(va, device=DEV)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.5, patience=max(2, patience // 3))
    best, best_state, bad, used = 1e9, None, 0, 0
    for ep in range(max_epochs):
        model.train()
        g = torch.tensor(np.random.default_rng(seed * 1000 + ep).permutation(tr), device=DEV)
        for i in range(0, len(g), bs):
            b = g[i:i + bs]
            loss = -model.dist(Xt[b], St[b]).log_prob(Yt[b]).mean()
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
        model.eval()
        with torch.no_grad():
            vl = float(np.mean([-model.dist(Xt[vt[i:i + 1024]], St[vt[i:i + 1024]])
                                .log_prob(Yt[vt[i:i + 1024]]).mean().item() for i in range(0, nv, 1024)]))
        sched.step(vl)
        used = ep + 1
        if vl < best - 1e-4:
            best, bad = vl, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
        if used % 5 == 0:
            say('      %s 第 %d 輪  驗證 NLL %.3f（最佳 %.3f）' % (tag, used, vl, best))
        if bad >= patience:
            break
    model.load_state_dict(best_state)
    return best, used


QS = (0.025, 0.10, 0.25, 0.50, 0.75, 0.90, 0.975)


@torch.no_grad()
def posterior(models, X, Sc, ns=2000):
    """集成後驗：每個模型抽 ns/M 個樣本合併（等權混合），回傳各分位數 (len(QS), n, 3)。"""
    for m in models:
        m.eval()
    per = max(200, ns // len(models))
    out = []
    qt = torch.tensor(QS, device=DEV)
    for i in range(0, len(X), 256):
        xb, sb = torch.tensor(X[i:i + 256], device=DEV), torch.tensor(Sc[i:i + 256], device=DEV)
        smp = torch.cat([m.dist(xb, sb).sample((per,)) * m.ysd + m.ymu for m in models], 0)
        out.append(torch.quantile(smp, qt, dim=0).cpu().numpy())
    return np.concatenate(out, 1)


def scores(Y, Q):
    out = {}
    for j, k in enumerate(TARGETS):
        y = Y[:, j]
        med = Q[3, :, j]
        r2 = 1 - np.sum((y - med) ** 2) / np.sum((y - y.mean()) ** 2)
        cov = lambda a, b: float(np.mean((y >= Q[a, :, j]) & (y <= Q[b, :, j])))
        out[k] = dict(r2=round(float(r2), 3), cov50=round(cov(2, 4), 3), cov80=round(cov(1, 5), 3),
                      cov95=round(cov(0, 6), 3), width80=round(float(np.mean(Q[5, :, j] - Q[1, :, j])) * SCALE, 5))
    return out


def sel_bins(Y, Q, sel):
    """依洩漏選擇性分組看分離度：sel 0 整體流（物理上預測分不開）→ 1 Graham（H2 選擇性）。"""
    out = []
    for lo, hi in ((0, 1 / 3), (1 / 3, 2 / 3), (2 / 3, 1.0001)):
        m = (sel >= lo) & (sel < hi)
        if m.sum() < 30:
            continue
        row = dict(sel=f'{lo:.2f}-{min(hi, 1):.2f}', n=int(m.sum()))
        for j, k in enumerate(TARGETS):
            y = Y[m, j]
            row[k] = round(float(1 - np.sum((y - Q[3, m, j]) ** 2) / np.sum((y - y.mean()) ** 2)), 3)
        out.append(row)
    return out


def hand_features(X, Sx):
    p, h, pump = X[:, 0], X[:, 1], X[:, 2]

    def sl(y):
        tt = np.linspace(0, 1, y.shape[1])
        tc = tt - tt.mean()
        return (tc * (y - y.mean(1, keepdims=True))).sum(1) / (tc ** 2).sum()
    third = L // 3
    return np.column_stack([Sx, p[:, -1], sl(p), sl(p[:, :third]), sl(p[:, -third:]),
                            h[:, -8:].mean(1) - h[:, :8].mean(1), sl(h), sl(h[:, -third:]) - sl(h[:, :third]),
                            (np.diff(p, axis=1) * pump[:, 1:]).sum(1), (np.diff(h, axis=1) * pump[:, 1:]).sum(1)])


def gbm_r2(Xtr, Str, Ytr, tests):
    """基準：同一批模擬的手工摘要＋梯度提升，三種先驗都報 R²。"""
    from sklearn.ensemble import HistGradientBoostingRegressor
    Ftr = hand_features(Xtr, Str)
    out = {p: {} for p in tests}
    for j, k in enumerate(TARGETS):
        m = HistGradientBoostingRegressor(max_iter=300, random_state=0).fit(Ftr, Ytr[:, j])
        for p, (Xte, Ste, Yte) in tests.items():
            pr = m.predict(hand_features(Xte, Ste))
            y = Yte[:, j]
            out[p][k] = round(float(1 - np.sum((y - pr) ** 2) / np.sum((y - y.mean()) ** 2)), 3)
    return out


def mask_channels(X, Sc, channels):
    """消融：channels='p' 時把 pH 通道與起始 pH 歸零，只留壓力與泵。"""
    if channels == 'p':
        X = X.copy(); Sc = Sc.copy()
        X[..., 1, :] = 0.0
        Sc[..., 3] = 0.0
    return X, Sc


def passed(res):
    return {k: all(0.70 <= res[p][k]['cov80'] <= 0.90 for p in ('B1', 'B2')) for k in TARGETS}


def run(cfg, tpls_noisy):
    group, clean = cfg['mode'] == 'group', cfg['noise'] == 'clean'
    tpls = clean_copy(tpls_noisy) if clean else tpls_noisy
    set_quant(clean)
    fold_t = S.template_folds(tpls)
    folds, n_seeds = cfg['folds'], cfg['seeds']
    gen = (lambda n, prior, seed, ids: gen_group(tpls, n, cfg['K'], prior, seed, ids)) if group else \
          (lambda n, prior, seed, ids: gen_single(tpls, n, prior, seed, ids))
    allres, real_rows = [], []
    for fi, f in enumerate(folds):
        tr_ids = [i for i in range(len(tpls)) if fold_t[i] != f]
        te_ids = [i for i in range(len(tpls)) if fold_t[i] == f]
        tm = {}
        t0 = time.time()
        Xtr, Str, Ytr, _ = gen(cfg['n_train'], 'A', 100 + f, tr_ids)
        Xtr, Str = mask_channels(Xtr, Str, cfg['channels'])
        tm['simulate_train'] = round(time.time() - t0, 1)
        tests = {}
        t0 = time.time()
        for pi, prior in enumerate(('A', 'B1', 'B2')):
            Xte, Ste, Yte, sel = gen(cfg['n_test'], prior, 200 + 10 * f + pi, te_ids)
            Xte, Ste = mask_channels(Xte, Ste, cfg['channels'])
            tests[prior] = (Xte, Ste, Yte, sel)
        tm['simulate_test'] = round(time.time() - t0, 1)
        models, seed_res, val = [], [], []
        t0 = time.time()
        for s in range(n_seeds):
            say('[進度] 折 %d/%d  種子 %d/%d  訓練中…' % (fi + 1, len(folds), s + 1, n_seeds))
            m = NPE(group=group).to(DEV)
            vl, used = train(m, Xtr, Str, Ytr, cfg['max_epochs'], cfg['patience'], bs=cfg['bs'],
                             seed=1000 * f + s, tag='折%d種子%d' % (f, s))
            models.append(m)
            val.append(dict(seed=s, val_nll=round(vl, 4), epochs=used))
            seed_res.append({p: scores(tests[p][2], posterior([m], tests[p][0], tests[p][1], cfg['ns']))
                             for p in tests})
        tm['train'] = round(time.time() - t0, 1)
        t0 = time.time()
        Qs = {p: posterior(models, tests[p][0], tests[p][1], cfg['ns']) for p in tests}
        ens = {p: scores(tests[p][2], Qs[p]) for p in tests}
        tm['posterior'] = round(time.time() - t0, 1)
        res = dict(fold=f, train_size=len(Xtr), seeds=val, ensemble=ens, per_seed=seed_res,
                   by_selectivity=sel_bins(tests['A'][2], Qs['A'], tests['A'][3]), passed=passed(ens))
        if not group:
            t0 = time.time()
            res['gbm_r2'] = gbm_r2(Xtr, Str, Ytr, {p: tests[p][:3] for p in tests})
            tm['gbm'] = round(time.time() - t0, 1)
        res['seconds'] = tm
        say('[%s] 折 %d  訓練 %d、%d 個種子（輪數 %s）  時間 %s'
            % (cfg['tag'], f, len(Xtr), n_seeds, [v['epochs'] for v in val], tm))
        for p in ('A', 'B1', 'B2'):
            say('   集成 %-3s ' % p + '  '.join('%s R² %+.2f 涵蓋50/80/95 %.2f/%.2f/%.2f' % (
                k, ens[p][k]['r2'], ens[p][k]['cov50'], ens[p][k]['cov80'], ens[p][k]['cov95']) for k in TARGETS))
        if 'gbm_r2' in res:
            say('   GBM（手工特徵）' + '  '.join('%s: %s' % (p, ' '.join('%s %+.2f' % kv for kv in res['gbm_r2'][p].items()))
                                         for p in ('A', 'B1', 'B2')))
        say('   依洩漏選擇性（A）：' + '  '.join('sel %s：bio %+.2f leak %+.2f' % (b['sel'], b['bio'], b['leak'])
                                          for b in res['by_selectivity']))
        say('   校準（B1、B2 的 80% 涵蓋率皆在 0.70–0.90）：' + '  '.join(
            '%s %s' % (k, '通過' if v else '失敗') for k, v in res['passed'].items()))
        allres.append(res)
        if not group and not clean:
            for ti in te_ids:
                tp = tpls_noisy[ti]
                x, s_ = featurize(tp, tp['P'][None, :], tp['pH'][None, :])
                x, s_ = mask_channels(x, s_, cfg['channels'])
                Q = posterior(models, x, s_, 8000)
                real_rows.append(dict(batch=tp['batch'], cycle=tp['cycle'], fold=f,
                                      **{'%s_%s' % (k, nm): round(float(Q[qi, 0, j]) * SCALE, 5)
                                         for j, k in enumerate(TARGETS)
                                         for nm, qi in (('lo80', 1), ('med', 3), ('hi80', 5))},
                                      **{'%s_calibrated' % k: bool(res['passed'][k]) for k in TARGETS}))
    return allres, real_rows


def summarize(allres):
    """跨折平均（集成）：每個先驗、每個目標的 R² 與 80% 涵蓋率。"""
    out = {}
    for p in ('A', 'B1', 'B2'):
        out[p] = {k: dict(r2=round(float(np.mean([r['ensemble'][p][k]['r2'] for r in allres])), 3),
                          r2_sd=round(float(np.std([r['ensemble'][p][k]['r2'] for r in allres])), 3),
                          cov80=round(float(np.mean([r['ensemble'][p][k]['cov80'] for r in allres])), 3))
                  for k in TARGETS}
    out['passed_all_folds'] = {k: all(r['passed'][k] for r in allres) for k in TARGETS}
    return out


def parse_args():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['single', 'group'], default='single')
    ap.add_argument('--noise', choices=['N2', 'clean'], default='N2')
    ap.add_argument('--channels', choices=['p+ph', 'p'], default='p+ph')
    ap.add_argument('--folds', default='0,1,2')
    ap.add_argument('--seeds', type=int, default=3)
    ap.add_argument('--n_train', type=int, default=None)
    ap.add_argument('--n_test', type=int, default=None)
    ap.add_argument('--max_epochs', type=int, default=60)
    ap.add_argument('--patience', type=int, default=8)
    ap.add_argument('--K', type=int, default=8)
    ap.add_argument('--ns', type=int, default=2000)
    ap.add_argument('--bs', type=int, default=None)
    ap.add_argument('--tag', default='')
    ap.add_argument('--quick', action='store_true')
    a = ap.parse_args()
    group = a.mode == 'group'
    cfg = dict(mode=a.mode, noise=a.noise, channels=a.channels,
               folds=[int(x) for x in a.folds.split(',') if x.strip() != ''],
               seeds=max(1, a.seeds), max_epochs=max(1, a.max_epochs), patience=max(1, a.patience),
               K=max(2, a.K), ns=max(200, a.ns), bs=a.bs or (64 if group else 512),
               n_train=a.n_train or ((800 if group else 6000) if a.quick else (8000 if group else 40000)),
               n_test=a.n_test or ((300 if group else 1500) if a.quick else (1500 if group else 6000)))
    if a.quick:
        cfg.update(max_epochs=min(cfg['max_epochs'], 8), seeds=min(cfg['seeds'], 1))
    cfg['tag'] = a.tag or '%s_%s_%s_%s' % (a.mode, a.noise, a.channels.replace('+', ''), time.strftime('%m%d_%H%M'))
    return cfg


def main():
    cfg = parse_args()
    out_dir = os.path.join(OUT, cfg['tag'])
    os.makedirs(out_dir, exist_ok=True)
    tpls = S.load_templates('N2')
    say('設定 %s' % json.dumps(cfg, ensure_ascii=False))
    say('模板 %d 個；%s' % (len(tpls), DEV.type))
    t0 = time.time()
    allres, real = run(cfg, tpls)
    summ = summarize(allres)
    say('\n══ 跨 %d 折平均（%d 個種子的集成）══' % (len(allres), cfg['seeds']))
    for p in ('A', 'B1', 'B2'):
        say('   %-3s ' % p + '  '.join('%s R² %+.2f±%.2f 涵蓋80 %.2f' % (k, summ[p][k]['r2'], summ[p][k]['r2_sd'],
                                                                    summ[p][k]['cov80']) for k in TARGETS))
    say('   每一折都通過校準：' + '  '.join('%s %s' % (k, '是' if v else '否') for k, v in summ['passed_all_folds'].items()))
    with open(os.path.join(out_dir, 'results.json'), 'w', encoding='utf-8') as fh:
        json.dump(dict(cfg=cfg, summary=summ, folds=allres, seconds=round(time.time() - t0, 1)),
                  fh, ensure_ascii=False, indent=1)
    if real:
        keys = list(real[0])
        with open(os.path.join(out_dir, 'real_posteriors.csv'), 'w', encoding='utf-8') as fh:
            fh.write(','.join(keys) + '\n')
            for r in real:
                fh.write(','.join(str(r[k]) for k in keys) + '\n')
        say('\n真實 %d 個循環（每個由沒看過其模板的模型推估；只列校準通過的目標）：' % len(real))
        for k in TARGETS:
            ok = [r for r in real if r['%s_calibrated' % k]]
            if ok:
                say('   %s：中位 %.4f，80%% 區間中位寬 %.4f（%d 個循環）'
                    % (k, np.median([r['%s_med' % k] for r in ok]),
                       np.median([r['%s_hi80' % k] - r['%s_lo80' % k] for r in ok]), len(ok)))
            else:
                say('   %s：沒有一折通過校準 → 不報數字' % k)
    with open(os.path.join(out_dir, 'log.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(LOG))
    say('完成 %.0f 秒 -> %s' % (time.time() - t0, out_dir))


if __name__ == '__main__':
    main()
