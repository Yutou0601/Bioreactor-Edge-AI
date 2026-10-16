# -*- coding: utf-8 -*-
"""用 pH＋壓力推估真實循環裡生物／溶解／洩漏各佔多少（近似貝氏計算 ABC），先驗證再套用。

2026-10-17。承 separation_ga（pH 是唯一能分出生物的現有訊號）。

方法
  · 參考表：separation_sim 先驗 A 的模擬循環（答案已知），只用壓力與 pH 特徵當摘要統計量
    （ORP 已證實無資訊，不用）。
  · 對每個要推估的循環：距離（以參考表的 MAD 標準化）最近的 q 比例被接受，再做局部線性
    迴歸校正（Beaumont 2002，Epanechnikov 權重）→ 後驗中位數與 80% 可信區間。
  · ⚠ 留一模板：推估真實循環 j 時，排除以 j 為模板的模擬——那些模擬帶著與 j 完全相同的
    真實殘差，比對會假性精確。
  · 校準檢查（必須先過）：拿先驗 B1／B2 的模擬當「假的真實資料」，看 80% 區間是否約 80%
    包含答案。先驗不同還準，區間才可信；不準就不套用到真實資料。

結果（2026-10-17，N2）
  · 校準：溶解通過（B1 78%、B2 75%；區間寬 0.0045）；生物、洩漏在 B1 失敗（66%、62%）——
    pH 鎖定溶解，但分不開生物與洩漏（pH 與洩漏的相關 0.01）。
  · 真實 29 個循環：溶解中位 −0.0005 kg/cm²/hr，80% 區間都貼著 0（逐循環最壞情況約佔總降速
    13%，中位）。接受比例 1–6% 結論不變；拿掉 pH 區間寬 0.0076 → 有 pH 0.0044（窄 40%）。
    ⟹ 壓降幾乎全是「生物＋洩漏」。ABC 給的生物：洩漏 ≈ 1:1 是先驗決定的（校準失敗），不可引用。
  · 圖：docs/analysis_charts_3batch/fig60_ph_analysis.png（fig_ph_analysis.py）

用法：python ph_abc.py [sim 檔標籤，預設 N2]
輸出 -> research/ml/out_separation/abc_<tag>_real.csv、abc_<tag>_log.txt
"""
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'out_separation')
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

STATS = ['s0', 'drop_rate', 'slope_early', 'slope_late', 'curv',
         'ph_slope', 'dph', 'ph_slope_late_minus_early', 'corr_ph_p']
PARAMS = ['bio', 'diss', 'leak']
Q = 0.03


def abc_one(s_obs, S, TH, mad, q=Q):
    """回傳每個參數的（中位、10%、90%）。S：(n, d) 參考統計量；TH：(n, p) 參數。"""
    dist = np.sqrt((((S - s_obs) / mad) ** 2).sum(1))
    k = max(30, int(q * len(S)))
    idx = np.argpartition(dist, k)[:k]
    h = dist[idx].max() + 1e-12
    w = 1 - (dist[idx] / h) ** 2
    X = (S[idx] - s_obs) / mad
    A = np.column_stack([np.ones(k), X])
    W = np.sqrt(w)[:, None]
    out = []
    for j in range(TH.shape[1]):
        beta, *_ = np.linalg.lstsq(A * W, TH[idx, j] * W[:, 0], rcond=None)
        adj = TH[idx, j] - X @ beta[1:]                   # 迴歸校正到 s_obs
        o = np.argsort(adj)
        cw = np.cumsum(w[o]) / w.sum()
        q10, q50, q90 = (adj[o][np.searchsorted(cw, p)] for p in (0.1, 0.5, 0.9))
        out.append((q50, q10, q90))
    return out


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else 'N2'
    d = np.load(os.path.join(DATA, 'sim_%s.npz' % tag), allow_pickle=True)
    F, T = list(d['features']), list(d['targets'])
    si = [F.index(s) for s in STATS]
    pi = [T.index(p) for p in PARAMS]
    S = np.vstack([d['trainA_X'], d['testA_X']])[:, si]
    TH = np.vstack([d['trainA_Y'], d['testA_Y']])[:, pi]
    tpl = np.concatenate([d['trainA_tpl'], d['testA_tpl']])
    mad = np.median(np.abs(S - np.median(S, 0)), 0) * 1.4826
    mad[mad == 0] = 1
    lines = []

    def say(s=''):
        print(s)
        lines.append(s)

    say('ABC：參考表 %d 個先驗 A 模擬循環；摘要統計量 %d 個（壓力＋pH）；接受最近 %.0f%%；%s'
        % (len(S), len(STATS), Q * 100, tag))

    # ── 校準檢查：B1／B2 的模擬當假的真實資料 ──
    say('\n== 校準檢查（假的真實資料來自相關結構不同的先驗 B1／B2；每組 300 個；留一模板）')
    rng = np.random.default_rng(0)
    ok_all = True
    for key in ('testB1', 'testB2'):
        Xs, Ys, ts = d[key + '_X'][:, si], d[key + '_Y'][:, pi], d[key + '_tpl']
        pick = rng.choice(len(Xs), 300, replace=False)
        hit = np.zeros(len(PARAMS))
        width = np.zeros(len(PARAMS))
        err = np.zeros(len(PARAMS))
        for i in pick:
            m = tpl != ts[i]
            post = abc_one(Xs[i], S[m], TH[m], mad)
            for j, (q50, q10, q90) in enumerate(post):
                hit[j] += q10 <= Ys[i, j] <= q90
                width[j] += q90 - q10
                err[j] += abs(q50 - Ys[i, j])
        sdv = Ys[pick].std(0)
        for j, p in enumerate(PARAMS):
            cov = hit[j] / len(pick)
            ok = 0.70 <= cov <= 0.90
            ok_all &= ok
            say('   %-6s %-5s 80%% 區間實際命中 %.0f%% %s  區間平均寬 %.4f（真值 SD %.4f）  中位絕對誤差 %.4f'
                % (key.replace('test', ''), p, cov * 100, '✓' if ok else '✗', width[j] / len(pick), sdv[j],
                   err[j] / len(pick)))
    say('   → %s' % ('校準通過，可套用到真實資料' if ok_all else
                     '⚠ 校準未全部通過：真實資料的結果只能當參考，區間不可照字面解讀'))

    # ── 真實 29 個循環 ──
    R = d['real_X'][:, si]
    ids = list(d['real_id'])
    say('\n== 真實循環（留一模板；kg/cm²/hr；括號為 80% 可信區間）')
    say('%-9s %-28s %-28s %-28s %s' % ('循環', '生物', '溶解', '洩漏', '量到的總降速'))
    rows = []
    tot_i = F.index('drop_rate')
    for j in range(len(R)):
        m = tpl != j
        post = abc_one(R[j], S[m], TH[m], mad)
        cells = ['%+.4f [%+.4f, %+.4f]' % p for p in post]
        say('%-9s %-28s %-28s %-28s %.4f' % (ids[j], *cells, d['real_X'][j, tot_i]))
        rows.append([ids[j]] + [round(v, 5) for p in post for v in p] + [round(d['real_X'][j, tot_i], 5)])
    arr = np.array([[r[1], r[4], r[7]] for r in rows])
    say('\n各批中位數（生物／溶解／洩漏）：')
    for b in ('tau1', 'tau5', 'tau10'):
        m = np.array([i.startswith(b + '#') for i in ids])
        say('   %-5s n=%2d  %+.4f / %+.4f / %+.4f' % (b, m.sum(), *np.median(arr[m], 0)))
    say('   全部     %+.4f / %+.4f / %+.4f   （論文 r_b 0.0125；平均總降速 %.4f）'
        % (*np.median(arr, 0), np.median(d['real_X'][:, tot_i])))

    with open(os.path.join(DATA, 'abc_%s_real.csv' % tag), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['cycle'] + ['%s_%s' % (p, s) for p in PARAMS for s in ('med', 'q10', 'q90')]
                   + ['drop_rate'])
        w.writerows(rows)
    with open(os.path.join(DATA, 'abc_%s_log.txt' % tag), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


if __name__ == '__main__':
    main()
