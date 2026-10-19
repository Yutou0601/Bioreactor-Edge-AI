# -*- coding: utf-8 -*-
"""甲烷產量的持續預測＋逐次更新（前一次的排氣量測推進下一次的訓練）。

2026-10-18。使用者需求：「ORP 的 H2 看能不能反推甲烷產量，要一個模型持續預測，
並將前一次的實驗推到下一次的訓練」。

════════════════════════════════════════════════════════════════════════
先講清楚 ORP 這條路為什麼不能直接走
  ORP → 溶解 H2 → 甲烷，第一步就斷了（cycles/dissolution_two_channel.py）：Nernst 換出
  液相 H2 是頭空平衡的 2.4 倍、循環內變 10¹⁰ 倍，而且泵開時 ORP 往正（H2 溶入應往負）。
  9/21 orp_calibration.py 用 ORP 對排氣錨點校準也輸給壓力（留一 R² 0.110 vs 0.151）。
  所以這裡**不假設** ORP 有用：把它當候選特徵，跟壓力、pH 一起用「逐次前推」驗證，
  贏過基準才採用。

模型（物理骨架＋要學的只有一個份額）
  甲烷 ＝ s × (壓降消耗 × 化學計量上限)            （CO2 + 4H2 → CH4，descent_report）
  s ＝ 壓降裡真正來自產甲烷的份額。其餘是洩漏／氫氣流失（設備方 10/16 確認有洩漏）。
  s 會隨時間變（洩漏程度、菌況），修好洩漏後應往 1 走 → 用**會遺忘的序列模型**：
    M0  過去平均            （最笨的「前一次推到下一次」）
    M1  卡爾曼隨機漫步      s_k = s_{k−1} + w；新排氣到了就更新，q／r 只用過去資料挑
    M2  貝氏線性回歸＋遺忘  s ~ 特徵（ORP、pH、壓力），每次只用過去資料、舊樣本權重 λ^age
  評估：時間順序前推——第 k 個排氣區間只用 1…k−1 訓練去預測，絕不偷看未來。

標籤
  docs/analysis_charts_3batch/bio_activity_vents.csv（bio_activity_timeline.py 產生）裡
  status = ok 的區間（化學計量檢查通過）。⚠ 氣體感測器是滯後追蹤，標籤本身有雜訊。

用法
  python ch4_sequential.py            前推驗證＋寫出目前狀態（state.json）
  python ch4_sequential.py --update   只重算狀態（有新的排氣區間後跑；排程頁可排）
輸出 -> research/ml/out_ch4_seq/（walkforward.csv、summary.json、state.json、png）
"""
import csv
import datetime as dt
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
REPO = os.path.dirname(RESEARCH)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from core.descent_report import CH4_PER_CONSUMED_MAX                # noqa: E402

TD = os.path.join(RESEARCH, 'Testing_data')
LABELS = os.path.join(REPO, 'docs', 'analysis_charts_3batch', 'bio_activity_vents.csv')
OUT = os.path.join(HERE, 'out_ch4_seq')
I_ORP, I_PH, I_P = 7, 9, 11
ORP_SIGN = -1.0                       # 原始只存絕對值，真值為負（multivariate_increments）
WARM = 4                              # 前 4 個區間只拿來暖身，不評分
FEATS = ['orp_mean', 'orp_slope', 'ph_mean', 'ph_slope', 'cons_rate', 'cyc_per_day']
FEAT_NAME = {'orp_mean': 'ORP 平均', 'orp_slope': 'ORP 趨勢', 'ph_mean': 'pH 平均',
             'ph_slope': 'pH 趨勢', 'cons_rate': '壓降消耗速率', 'cyc_per_day': '每日循環數'}


def load_series():
    """全部 CSV 依時間戳去重；回傳時間、壓力、ORP（真值）、pH。"""
    rows = {}
    for path in sorted(glob.glob(os.path.join(TD, '**', '*.csv'), recursive=True)):
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                q = line.strip().split(',')
                if len(q) < 14:
                    continue
                try:
                    t = dt.datetime(int(q[0]), int(q[1]), int(q[2]), int(q[3]), int(q[4]), int(float(q[5])))
                    v = (float(q[I_P]), ORP_SIGN * float(q[I_ORP]), float(q[I_PH]))
                except (ValueError, IndexError):
                    continue
                rows.setdefault(t, v)
    ts = sorted(rows)
    a = np.array([rows[t] for t in ts], float)
    return np.array(ts), a[:, 0], a[:, 1], a[:, 2]


def labels():
    out = []
    with open(LABELS, encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            if r['status'] != 'ok':
                continue
            cons = float(r['consumed'])
            s = float(r['bio_share'])
            out.append(dict(start=dt.datetime.strptime(r['start'], '%Y-%m-%d %H:%M'),
                            end=dt.datetime.strptime(r['end'], '%Y-%m-%d %H:%M'),
                            hours=float(r['hours']), n_desc=int(r['n_descents']), consumed=cons,
                            share=s, ch4=s * CH4_PER_CONSUMED_MAX * cons))
    return sorted(out, key=lambda r: r['start'])


def features(lab, ts, P, orp, ph):
    for r in lab:
        m = (ts >= r['start']) & (ts <= r['end'])
        h = np.array([(x - r['start']).total_seconds() / 3600 for x in ts[m]])
        o, p = orp[m], ph[m]
        okp = (p > 5) & (p < 9)                                # 14.00 等故障值
        oko = np.isfinite(o) & (o < 0)
        r['orp_mean'] = float(np.mean(o[oko])) if oko.sum() > 60 else np.nan
        r['orp_slope'] = float(np.polyfit(h[oko], o[oko], 1)[0] * 24) if oko.sum() > 60 else np.nan   # mV/天
        r['ph_mean'] = float(np.mean(p[okp])) if okp.sum() > 60 else np.nan
        r['ph_slope'] = float(np.polyfit(h[okp], p[okp], 1)[0] * 24) if okp.sum() > 60 else np.nan     # /天
        r['cons_rate'] = r['consumed'] / r['hours']
        r['cyc_per_day'] = r['n_desc'] / r['hours'] * 24
        r['coverage'] = float(m.sum() / 60 / r['hours'])      # 一分鐘一筆：資料覆蓋比例
    return lab


# ══════════════════════════════════════════════════════════
# 序列模型（都只吃「過去」）
# ══════════════════════════════════════════════════════════
def m0_mean(past):
    s = np.array([r['share'] for r in past])
    sd = s.std(ddof=1) if len(s) > 1 else 0.3
    return float(s.mean()), float(sd * np.sqrt(1 + 1 / len(s)))


def kalman(series, q, r, m0=0.5, v0=0.25):
    """隨機漫步局部水準。回傳每一步的一步前推 (均值, 變異) 與對數概似和，以及最後的後驗。"""
    m, v, ll, pred = m0, v0, 0.0, []
    for y in series:
        vp = v + q
        pred.append((m, vp + r))
        S = vp + r
        ll += -0.5 * (np.log(2 * np.pi * S) + (y - m) ** 2 / S)
        K = vp / S
        m, v = m + K * (y - m), (1 - K) * vp
    return pred, ll, (m, v)


QS = [1e-4, 1e-3, 3e-3, 1e-2, 3e-2]
RS = [0.01, 0.02, 0.04, 0.08]


def m1_kalman(past):
    """q（漂移）與 r（標籤雜訊）用過去資料的邊際概似挑，再給下一步預測。"""
    s = [x['share'] for x in past]
    best = max(((kalman(s, q, r)[1], q, r) for q in QS for r in RS))
    _, q, r = best
    _, _, (m, v) = kalman(s, q, r)
    return float(m), float(np.sqrt(v + q + r)), dict(q=q, r=r)


LAMS = [1.0, 0.95, 0.85]


def blr(Xp, yp, x_new, lam, alpha=1.0):
    """貝氏線性回歸（截距＋特徵），舊樣本權重 lam^age；雜訊變異用加權殘差估。"""
    n = len(yp)
    w = lam ** np.arange(n - 1, -1, -1)
    A = np.column_stack([np.ones(n), Xp])
    W = np.diag(w)
    prec = A.T @ W @ A + alpha * np.diag([1e-6] + [1.0] * Xp.shape[1])
    cov = np.linalg.inv(prec)
    beta = cov @ A.T @ W @ yp
    res = yp - A @ beta
    s2 = float((w * res ** 2).sum() / max(w.sum() - A.shape[1], 1.0))
    a = np.concatenate([[1.0], x_new])
    return float(a @ beta), float(np.sqrt(s2 * (1 + a @ cov @ a)))


def m2_reg(past, new, feats):
    """特徵只用過去資料標準化；遺忘係數 λ 用過去資料的逐次前推誤差挑。"""
    X = np.array([[r[f] for f in feats] for r in past])
    y = np.array([r['share'] for r in past])
    ok = np.isfinite(X).all(1)
    xn = np.array([new[f] for f in feats])
    if ok.sum() < 3 or not np.isfinite(xn).all():
        return np.nan, np.nan, None
    X, y = X[ok], y[ok]
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z, zn = (X - mu) / sd, (xn - mu) / sd
    best = None
    for lam in LAMS:                                  # 在過去資料內部再做一次前推來挑 λ
        err = [abs(blr(Z[:k], y[:k], Z[k], lam)[0] - y[k]) for k in range(3, len(y))]
        e = np.mean(err) if err else 0.0
        if best is None or e < best[0]:
            best = (e, lam)
    lam = best[1]
    mean, sdv = blr(Z, y, zn, lam)
    return float(np.clip(mean, 0, 1.2)), sdv, dict(lam=lam)


MODELS = [('M0 過去平均', lambda p, n: m0_mean(p) + (None,)),
          ('M1 卡爾曼漂移', lambda p, n: m1_kalman(p))] + \
         [('M2 回歸：%s' % FEAT_NAME[f], (lambda f: lambda p, n: m2_reg(p, n, [f]))(f)) for f in FEATS] + \
         [('M2 回歸：ORP 兩項', lambda p, n: m2_reg(p, n, ['orp_mean', 'orp_slope'])),
          ('M2 回歸：壓力兩項', lambda p, n: m2_reg(p, n, ['cons_rate', 'cyc_per_day']))]


def walk_forward(lab):
    rows = []
    for k in range(WARM, len(lab)):
        past, new = lab[:k], lab[k]
        for name, fn in MODELS:
            mean, sd, info = fn(past, new)
            if not np.isfinite(mean):
                continue
            rows.append(dict(k=k, start=new['start'].strftime('%Y-%m-%d'), model=name,
                             share_true=new['share'], share_pred=mean, share_sd=sd,
                             ch4_true=new['ch4'], ch4_pred=mean * CH4_PER_CONSUMED_MAX * new['consumed'],
                             covered80=abs(new['share'] - mean) <= 1.2816 * sd))
    return rows


def score(rows):
    out = {}
    base = {r['k']: r for r in rows if r['model'] == 'M0 過去平均'}
    for name, _ in MODELS:
        rr = [r for r in rows if r['model'] == name]
        if not rr:
            continue
        e = np.array([abs(r['share_pred'] - r['share_true']) for r in rr])
        ech4 = np.array([abs(r['ch4_pred'] - r['ch4_true']) for r in rr])
        # 與 M0 成對比較（同一批 k）：贏幾次、平均差多少
        d = np.array([abs(r['share_pred'] - r['share_true']) - abs(base[r['k']]['share_pred'] - r['share_true'])
                      for r in rr if r['k'] in base])
        rng = np.random.default_rng(0)
        bs = [np.mean(rng.choice(d, len(d))) for _ in range(4000)] if len(d) else [np.nan]
        out[name] = dict(n=len(rr), mae_share=float(e.mean()), mae_ch4=float(ech4.mean()),
                         cov80=float(np.mean([r['covered80'] for r in rr])),
                         vs_m0=float(d.mean()) if len(d) else np.nan,
                         vs_m0_ci=[float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
                         wins=int((d < 0).sum()), losses=int((d > 0).sum()))
    return out


def current_state(lab):
    """用全部已知排氣區間更新後的「下一次」預測：給前端／即時估計用。"""
    m, sd, info = m1_kalman(lab)
    return dict(updated=dt.datetime.now().isoformat(timespec='seconds'), n_labels=len(lab),
                last_label_end=lab[-1]['end'].isoformat(sep=' '), model='M1 卡爾曼漂移',
                share_mean=m, share_sd=sd, share_80=[m - 1.2816 * sd, m + 1.2816 * sd], **(info or {}),
                ch4_per_consumed=CH4_PER_CONSUMED_MAX,
                how_to_use='甲烷（kgf/cm² 分壓）≈ share_mean × ch4_per_consumed × 上次排氣以來各下降段壓降總和')


def main():
    os.makedirs(OUT, exist_ok=True)
    lab = labels()
    print('排氣標籤（化學計量檢查通過）%d 個：%s ~ %s' % (len(lab), lab[0]['start'].date(), lab[-1]['end'].date()))
    if '--update' in sys.argv:
        st = current_state(lab)
        json.dump(st, open(os.path.join(OUT, 'state.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('狀態已更新：下一次份額 %.2f [%.2f, %.2f]' % (st['share_mean'], *st['share_80']))
        return
    ts, P, orp, ph = load_series()
    print('原始資料 %d 筆（去重）' % len(ts))
    lab = features(lab, ts, P, orp, ph)
    print('\n %-11s %6s %5s %6s %7s %7s %6s %7s %5s' % ('起', '時數', '份額', '覆蓋', 'ORP均', 'ORP趨勢', 'pH均', 'pH趨勢', '循/天'))
    for r in lab:
        print(' %-11s %6.0f %5.2f %6.2f %7.0f %+7.1f %6.2f %+7.3f %5.1f'
              % (r['start'].strftime('%Y-%m-%d'), r['hours'], r['share'], r['coverage'], r['orp_mean'],
                 r['orp_slope'], r['ph_mean'], r['ph_slope'], r['cyc_per_day']))
    rows = walk_forward(lab)
    sc = score(rows)
    print('\n══ 逐次前推（第 %d～%d 個區間，各只用之前的資料）══' % (WARM + 1, len(lab)))
    print(' %-20s %3s %9s %11s %7s %14s %s' % ('模型', 'n', '份額 MAE', '甲烷 MAE', '80%涵蓋', '比 M0（負＝好）', '勝/負'))
    for name, s in sc.items():
        print(' %-20s %3d %9.3f %11.5f %7.2f %+7.3f [%+.3f,%+.3f] %2d/%-2d'
              % (name, s['n'], s['mae_share'], s['mae_ch4'], s['cov80'], s['vs_m0'], *s['vs_m0_ci'], s['wins'], s['losses']))
    st = current_state(lab)
    print('\n目前狀態（全部 %d 個標籤更新後）：下一次份額 %.2f，80%% 區間 [%.2f, %.2f]（q=%g、r=%g）'
          % (st['n_labels'], st['share_mean'], *st['share_80'], st['q'], st['r']))
    with open(os.path.join(OUT, 'walkforward.csv'), 'w', encoding='utf-8') as fh:
        ks = list(rows[0])
        fh.write(','.join(ks) + '\n')
        for r in rows:
            fh.write(','.join(str(round(r[k], 6)) if isinstance(r[k], float) else str(r[k]) for k in ks) + '\n')
    feats_out = [{k: (v.isoformat(sep=' ') if isinstance(v, dt.datetime) else v) for k, v in r.items()} for r in lab]
    json.dump(dict(labels=feats_out, scores=sc, state=st), open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)
    json.dump(st, open(os.path.join(OUT, 'state.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    plot(lab, rows)
    print('-> %s' % OUT)


def plot(lab, rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Noto Sans CJK TC', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    fig, ax = plt.subplots(1, 2, figsize=(14, 4.6))
    x = [r['start'] for r in lab]
    ax[0].plot(x, [r['share'] for r in lab], 'o-', color='#333', label='實測（排氣 CH4）')
    for name, col in (('M0 過去平均', '#999999'), ('M1 卡爾曼漂移', '#2f6fd0'), ('M2 回歸：ORP 兩項', '#d0602f')):
        rr = [r for r in rows if r['model'] == name]
        xs = [lab[r['k']]['start'] for r in rr]
        m = np.array([r['share_pred'] for r in rr])
        s = np.array([r['share_sd'] for r in rr])
        ax[0].plot(xs, m, 's--', color=col, ms=4, label=name)
        if name == 'M1 卡爾曼漂移':
            ax[0].fill_between(xs, m - 1.2816 * s, m + 1.2816 * s, color=col, alpha=0.12, lw=0)
    ax[0].set_ylabel('壓降中來自產甲烷的份額')
    ax[0].set_title('a　逐次前推：每個點只用之前的排氣訓練')
    ax[0].legend(frameon=False, fontsize=8)
    names = [n for n, _ in MODELS]
    sc = score(rows)
    vals = [sc[n]['mae_share'] for n in names if n in sc]
    ax[1].barh(range(len(vals)), vals, color=['#999' if 'M0' in n else '#2f6fd0' if 'M1' in n else '#d0602f'
                                               if 'ORP' in n else '#7aa37a' for n in names if n in sc])
    ax[1].set_yticks(range(len(vals)), [n for n in names if n in sc], fontsize=8)
    ax[1].invert_yaxis()
    ax[1].set_xlabel('份額 MAE（越小越好）')
    ax[1].set_title('b　各模型前推誤差')
    for a in ax:
        a.spines[['top', 'right']].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'ch4_sequential.png'), dpi=130)


if __name__ == '__main__':
    main()
