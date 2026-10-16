# -*- coding: utf-8 -*-
"""GA（NSGA-II）篩選：哪些現有特徵能把生物從溶解／洩漏裡分出來？

2026-10-16。讀 separation_sim.py 的輸出（Jetson 產生），在這台跑。

════════════════════════════════════════════════════════════════════════
評分：不是一般的交叉驗證
  一般交叉驗證會被「模擬的先驗分布」騙：生物是總壓降的一部分，在先驗裡兩者相關，
  所以只會量總壓降的特徵也能「預測」生物——那是先驗教的，不是資料分得開。
  這裡在先驗 A（參數獨立）訓練，在 **B1、B2**（邊際相同、相關結構相反）測試，
  取兩者較差的 R² 當「穩健預測力」。只靠先驗相關猜中的，在其中一個一定會崩。

搜尋
  · NSGA-II：最大化穩健 R²、最小化特徵數；5 個亂數種子。
  · 另外窮舉全部單一特徵與兩兩組合（GA 的抽查，也是「沒有漏網之魚」的直接證據）。
  · 模型：嶺迴歸（標準化特徵，閉式解，一次評估幾毫秒）；前沿上的組合再用梯度提升樹
    （非線性）重評，確認線性沒有漏掉資訊。

檢核
  · 選擇感知的置換虛無：把訓練標籤打亂、**整個 GA 重跑**，取每種特徵數下最佳穩健 R²
    的分布——GA 會從很多組合裡挑最好的，只對最後一組做置換會低估虛無。
  · 穩定性：5 個種子 × bootstrap 訓練列，統計每個特徵出現在前沿最佳解的頻率。
  · 「超越壓力」：先用全部壓力特徵（非線性）預測生物，再看 pH／ORP 能不能預測殘差。

結果（2026-10-16；穩健 R²＝最不利先驗、沒見過的真實雜訊；線性／非線性；保守雜訊 N2）
                  只用壓力    壓力＋pH    壓力＋ORP   GA 最佳   置換虛無最大
  單一循環        0.16/0.21   0.30/0.41   0.24/0.24   0.34      0.04
  同條件 8 循環   0.21/0.28   0.42/0.51   0.25/0.32   0.51      0.10
  跨條件 8 循環   0.24/0.32   0.54/0.66  −0.05/0.41   0.60      0.11
  · 壓力怎麼組合都卡在 0.2–0.3（跨 τ 也救不了：循環間 P_eq 浮動淹沒跨循環迴歸）。
  · pH 是唯一真槓桿；最有效的組合是「起始降速 s0＋pH 斜率」（窮舉與 GA 5 種子一致）。
  · ORP 無可用資訊：真實循環內 ΔORP 中位 −45 mV，機理只有 ±5 mV；N1 下看似有用是因為
    N1 扣掉了真實 ORP 趨勢（覆蓋檢查抓到：orp_slope 覆蓋 0.31）。分組後 ORP 甚至有害。
  · 以上以機理模型為前提（生物受 H2 質傳限制、pH 由碳酸緩衝決定、γ 0.3–5）。
  圖：docs/analysis_charts_3batch/fig59_separation_ga.png（fig_separation.py）

用法：python separation_ga.py [N1|N2|grp_same_K8_N2|grp_cross_K8_N2|...]
輸出 -> research/ml/out_separation/ga_<noise>_*.csv、log
"""
import csv
import itertools
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'out_separation')
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ALPHA = 1.0
TARGET = 'bio'


NFOLD = 3


def load(noise):
    """回傳 Z[k] = (X 標準化, y, 模板編號)、以及模板→折的對應。

    ⚠ 依模板分組交叉驗證（2026-10-16 修正）：每個模擬循環借用一個真實循環的**固定**
      殘差序列。訓練與測試共用模板時，模型可由 ORP 平均、時長等認出模板、把那段已知
      雜訊「扣掉」——真實的新循環不可能這樣。初版即因此高估 ORP（N2 下「超越壓力」
      殘差 R² 0.18，而機理訊號僅 ±5 mV、雜訊 ±45 mV）。改為：29 個模板依批次分層分
      3 折，在沒見過的模板上測試，三折預測合併後算 R²。
    """
    name = noise if noise.startswith('grp_') else 'sim_%s' % noise
    d = np.load(os.path.join(DATA, name + '.npz'), allow_pickle=True)
    feats = list(d['features'])
    tg = list(d['targets'])
    it = tg.index(TARGET)
    mu = d['trainA_X'].mean(0)
    sd = d['trainA_X'].std(0)
    sd[sd == 0] = 1
    if 'real_id' not in d:
        # 分組資料（separation_sim --group）：每組的模板都來自同一折，直接用組的折號
        Z = {k: ((d[k + '_X'] - mu) / sd, d[k + '_Y'][:, it], d[k + '_fold'])
             for k in ('trainA', 'testA', 'testB1', 'testB2')}
        return Z, feats, d, mu, sd, np.arange(NFOLD)
    Z = {k: ((d[k + '_X'] - mu) / sd, d[k + '_Y'][:, it], d[k + '_tpl'])
         for k in ('trainA', 'testA', 'testB1', 'testB2')}
    # 模板分折：依批次分層、批內輪流分配
    ids = list(d['real_id'])
    fold = np.zeros(len(ids), int)
    for b in ('tau1', 'tau5', 'tau10'):
        mine = [i for i, s in enumerate(ids) if s.startswith(b + '#')]
        for j, i in enumerate(mine):
            fold[i] = j % NFOLD
    return Z, feats, d, mu, sd, fold


def r2(y, p):
    return 1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum()


class Scorer:
    """嶺迴歸的快速評估（依模板分組交叉驗證）：每折預先算好 XᵀX、Xᵀy。"""

    def __init__(self, Z, fold, ytrain=None):
        X, y, tp = Z['trainA']
        y = y if ytrain is None else ytrain
        self.fold = fold
        self.parts = []
        for f in range(NFOLD):
            m = fold[tp] != f
            xm, ym = X[m].mean(0), y[m].mean()
            Xc = X[m] - xm
            self.parts.append((xm, ym, Xc.T @ Xc, Xc.T @ (y[m] - ym)))
        self.tests = {k: Z[k] for k in ('testA', 'testB1', 'testB2')}

    def score(self, idx):
        idx = np.asarray(idx)
        if idx.size == 0:
            return dict(A=0.0, B1=0.0, B2=0.0, robust=0.0)
        betas = []
        for xm, ym, G, b in self.parts:
            betas.append(np.linalg.solve(G[np.ix_(idx, idx)] + ALPHA * np.eye(len(idx)), b[idx]))
        out = {}
        for k, (X, y, tp) in self.tests.items():
            p = np.empty(len(y))
            for f, (xm, ym, _, _) in enumerate(self.parts):
                m = self.fold[tp] == f
                p[m] = ym + (X[m][:, idx] - xm[idx]) @ betas[f]
            out[k.replace('test', '')] = float(r2(y, p))
        out['robust'] = min(out['B1'], out['B2'])
        return out


def cv_predict(Z, fold, idx, make_model, target=None, test_target=None):
    """任意模型的依模板分組交叉驗證預測。target：訓練目標（預設生物真值）。"""
    X, y, tp = Z['trainA']
    y = y if target is None else target
    preds = {k: np.empty(len(Z[k][1])) for k in ('testA', 'testB1', 'testB2')}
    for f in range(NFOLD):
        m = fold[tp] != f
        mdl = make_model()
        mdl.fit(X[m][:, idx], y[m])
        for k in preds:
            Xk, _, tk = Z[k]
            mk = fold[tk] == f
            preds[k][mk] = mdl.predict(Xk[mk][:, idx])
    return preds


def run_nsga(scorer, nf, seed, pop=120, gens=120):
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.core.problem import Problem
    from pymoo.operators.crossover.pntx import TwoPointCrossover
    from pymoo.operators.mutation.bitflip import BitflipMutation
    from pymoo.operators.sampling.rnd import BinaryRandomSampling
    from pymoo.optimize import minimize

    class P(Problem):
        def __init__(self):
            super().__init__(n_var=nf, n_obj=2, n_ieq_constr=1, xl=0, xu=1, vtype=bool)

        def _evaluate(self, X, out, *a, **k):
            F = np.zeros((len(X), 2))
            G = np.zeros((len(X), 1))
            for i, x in enumerate(X):
                idx = np.flatnonzero(x)
                G[i, 0] = 1 - len(idx)                  # 至少一個特徵
                F[i, 0] = -scorer.score(idx)['robust'] if len(idx) else 1.0
                F[i, 1] = len(idx)
            out['F'], out['G'] = F, G

    algo = NSGA2(pop_size=pop, sampling=BinaryRandomSampling(), crossover=TwoPointCrossover(),
                 mutation=BitflipMutation(), eliminate_duplicates=True)
    res = minimize(P(), algo, ('n_gen', gens), seed=seed, verbose=False)
    front = {}
    for x in np.atleast_2d(res.X):
        idx = tuple(np.flatnonzero(x))
        s = scorer.score(idx)['robust']
        if len(idx) not in front or s > front[len(idx)][1]:
            front[len(idx)] = (idx, s)
    return front


def main():
    noise = sys.argv[1] if len(sys.argv) > 1 else 'N1'
    Z, feats, d, mu, sd, fold = load(noise)
    nf = len(feats)
    ORP_IDX = [i for i, f in enumerate(feats) if 'orp' in f]
    PH_IDX = [i for i, f in enumerate(feats) if 'ph' in f and 'orp' not in f]
    P_IDX = [i for i in range(len(feats)) if i not in ORP_IDX and i not in PH_IDX]
    log_lines = []

    def say(s=''):
        print(s)
        log_lines.append(s)

    say('雜訊 %s；目標＝%s（生物造成的壓降速率）；訓練 %d、各測試集 %d；依模板分組 %d 折（在沒見過的真實循環雜訊上測）'
        % (noise, TARGET, len(Z['trainA'][1]), len(Z['testA'][1]), NFOLD))
    sc = Scorer(Z, fold)

    # ── 覆蓋檢查：真實循環的特徵是否落在模擬範圍內 ──
    Xa = d['trainA_X']
    has_real = 'real_X' in d
    if has_real:
        lo, hi = np.percentile(Xa, 1, 0), np.percentile(Xa, 99, 0)
        cover = ((d['real_X'] >= lo) & (d['real_X'] <= hi)).mean(0)
    else:
        cover = np.full(nf, np.nan)
    say('\n== 覆蓋檢查（真實 29 個循環落在模擬 1–99 百分位內的比例；< 0.9 標 ⚠）%s'
        % ('' if has_real else '——分組資料：略過（單循環特徵的覆蓋見單循環的 log）'))
    for i, f in enumerate(feats if has_real else []):
        say('   %-28s %.2f %s   真實中位 %+.4g   模擬中位 %+.4g'
            % (f, cover[i], '⚠' if cover[i] < 0.9 else ' ', np.median(d['real_X'][:, i]),
               np.median(Xa[:, i])))

    # ── 基準 ──
    say('\n== 基準（嶺迴歸；穩健＝B1、B2 較差者）')
    for name, idx in (('全部特徵', list(range(nf))), ('只用壓力', P_IDX),
                      ('壓力＋pH', P_IDX + PH_IDX), ('壓力＋ORP', P_IDX + ORP_IDX),
                      ('只用 pH', PH_IDX), ('只用 ORP', ORP_IDX)):
        s = sc.score(idx)
        say('   %-10s R²  A %+.3f   B1 %+.3f   B2 %+.3f   穩健 %+.3f'
            % (name, s['A'], s['B1'], s['B2'], s['robust']))

    # ── 窮舉單一與兩兩 ──
    say('\n== 窮舉：單一特徵（依穩健 R² 排序，前 10）')
    single = sorted(((sc.score([i]), i) for i in range(nf)), key=lambda z: -z[0]['robust'])
    for s, i in single[:10]:
        say('   %-28s 穩健 %+.3f   A %+.3f   B1 %+.3f   B2 %+.3f'
            % (feats[i], s['robust'], s['A'], s['B1'], s['B2']))
    pairs = sorted(((sc.score(list(p)), p) for p in itertools.combinations(range(nf), 2)),
                   key=lambda z: -z[0]['robust'])
    say('== 窮舉：兩兩組合（%d 種，前 8）' % len(pairs))
    for s, p in pairs[:8]:
        say('   %-48s 穩健 %+.3f   A %+.3f' % (' + '.join(feats[j] for j in p), s['robust'], s['A']))

    # ── NSGA-II，5 個種子 ──
    say('\n== NSGA-II 前沿（5 個種子；每種特徵數下最佳的穩健 R²）')
    t0 = time.perf_counter()
    fronts = [run_nsga(sc, nf, seed) for seed in range(5)]
    sizes = sorted(set().union(*[f.keys() for f in fronts]))
    best = {}
    for k in sizes:
        cands = [f[k] for f in fronts if k in f]
        best[k] = max(cands, key=lambda z: z[1])
        vals = [c[1] for c in cands]
        if k <= 12:
            say('   %2d 個特徵：最佳 %+.3f（5 種子間 %+.3f–%+.3f）  %s'
                % (k, best[k][1], min(vals), max(vals), ', '.join(feats[j] for j in best[k][0])))
    say('   （GA 共 %.0f 秒）' % (time.perf_counter() - t0))

    # ── 選擇感知的置換虛無：打亂訓練標籤、整個 GA 重跑 ──
    say('\n== 選擇感知的置換虛無（訓練標籤打亂、整個 GA 重跑 20 次）')
    rng = np.random.default_rng(0)
    null_best = []
    for r in range(20):
        yperm = rng.permutation(Z['trainA'][1])
        scn = Scorer(Z, fold, ytrain=yperm)
        fr = run_nsga(scn, nf, 100 + r, pop=80, gens=60)
        null_best.append(max(v[1] for v in fr.values()))
    nb = np.array(null_best)
    say('   置換後 GA 能找到的最佳穩健 R²：中位 %+.3f、95 百分位 %+.3f、最大 %+.3f'
        % (np.median(nb), np.percentile(nb, 95), nb.max()))
    top = max(best.values(), key=lambda z: z[1])
    say('   真標籤下 GA 的最佳穩健 R² %+.3f → 置換 p = %.3f'
        % (top[1], (1 + (nb >= top[1]).sum()) / (1 + len(nb))))

    # ── 穩定性：bootstrap 訓練列 × 前沿最佳解的特徵頻率 ──
    say('\n== 穩定性（訓練列 bootstrap 10 次，記錄穩健 R² 最佳解用到的特徵）')
    cnt = np.zeros(nf)
    Xtr, ytr, ttr = Z['trainA']
    for b in range(10):
        ib = rng.integers(0, len(ytr), len(ytr))
        Zb = dict(Z)
        Zb['trainA'] = (Xtr[ib], ytr[ib], ttr[ib])
        scb = Scorer(Zb, fold)
        fr = run_nsga(scb, nf, 200 + b, pop=80, gens=80)
        idx, _ = max(fr.values(), key=lambda z: z[1])
        cnt[list(idx)] += 1
    for i in np.argsort(-cnt)[:12]:
        if cnt[i]:
            say('   %-28s %2d/10' % (feats[i], cnt[i]))

    # ── 非線性重評 ＋ 「超越壓力」──
    from sklearn.ensemble import HistGradientBoostingRegressor
    say('\n== 非線性（梯度提升樹）重評')
    def mk():
        return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, random_state=0)

    def hgb_score(idx):
        pr = cv_predict(Z, fold, idx, mk)
        out = {k.replace('test', ''): float(r2(Z[k][1], pr[k])) for k in pr}
        out['robust'] = min(out['B1'], out['B2'])
        return out, pr
    hg = {}
    for name, idx in (('全部特徵', list(range(nf))), ('只用壓力', P_IDX), ('壓力＋pH', P_IDX + PH_IDX),
                      ('壓力＋ORP', P_IDX + ORP_IDX), ('GA 最佳', list(top[0]))):
        s, pr = hgb_score(idx)
        hg[name] = (s, pr)
        say('   %-10s R²  A %+.3f   B1 %+.3f   B2 %+.3f   穩健 %+.3f'
            % (name, s['A'], s['B1'], s['B2'], s['robust']))

    say('\n== 超越壓力：pH／ORP 能不能預測「壓力解釋不了的生物」？（依模板分組）')
    # 訓練集的壓力殘差也要交叉擬合，否則殘差被過度擬合而偏小
    X, y, tp = Z['trainA']
    res_tr = np.empty(len(y))
    for f in range(NFOLD):
        m = fold[tp] != f
        mdl = mk().fit(X[m][:, P_IDX], y[m])
        res_tr[~m] = y[~m] - mdl.predict(X[~m][:, P_IDX])
    prP = hg['只用壓力'][1]
    for name, idx in (('pH', PH_IDX), ('ORP', ORP_IDX), ('pH＋ORP', PH_IDX + ORP_IDX)):
        pr = cv_predict(Z, fold, idx, mk, target=res_tr)
        line = '   %-8s' % name
        for k in ('testA', 'testB1', 'testB2'):
            res = Z[k][1] - prP[k]
            line += '  %s：殘差 R² %+.3f' % (k.replace('test', ''), r2(res, pr[k]))
        say(line)

    # ── 存檔 ──
    with open(os.path.join(DATA, 'ga_%s_front.csv' % noise), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['n_features', 'robust_r2', 'r2_A', 'r2_B1', 'r2_B2', 'features'])
        for k in sizes:
            idx = best[k][0]
            s = sc.score(idx)
            w.writerow([k, round(s['robust'], 4), round(s['A'], 4), round(s['B1'], 4),
                        round(s['B2'], 4), ';'.join(feats[j] for j in idx)])
    with open(os.path.join(DATA, 'ga_%s_singles.csv' % noise), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['feature', 'robust_r2', 'r2_A', 'r2_B1', 'r2_B2', 'coverage_real'])
        for s, i in single:
            w.writerow([feats[i], round(s['robust'], 4), round(s['A'], 4), round(s['B1'], 4),
                        round(s['B2'], 4), round(float(cover[i]), 3)])
    np.save(os.path.join(DATA, 'ga_%s_null.npy' % noise), nb)
    with open(os.path.join(DATA, 'ga_%s_log.txt' % noise), 'w', encoding='utf-8') as f:
        f.write('\n'.join(log_lines))
    print('-> out_separation/ga_%s_*' % noise)


if __name__ == '__main__':
    main()
