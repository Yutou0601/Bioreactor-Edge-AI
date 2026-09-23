# -*- coding: utf-8 -*-
"""ORP 能不能當「不必排氣的連續轉換指標」—— 用 35 個排氣錨點校準。

2026-09-21。針對會議需求最根本的那一條：

    「長時間轉換排氣知道濃度，排完才知道剩多少氣體」

  也就是：要知道轉換了多少，現在只能靠排氣。排氣是人工、會打斷運轉，
  而且一分鐘一筆很容易錯過峰值。ORP 是連續量測、不必排氣。
  若 ORP 能被排氣錨點校準，就能在兩次排氣之間持續估計轉換量。

════════════════════════════════════════════════════════════════════════
⚠ 前提：氣體讀數本來就不準（使用者明確提醒，本專案亦已量到）

  補氣稀釋檢定：真頂空應有 Δln x_CH4 = −Δln P，實測斜率 +0.008 ± 0.225，
  距 −1 有 4.5σ -> 感測器是滯後追蹤，不是即時頂空組成。
  所以本檔的「目標值」本身帶誤差，校準出來的 ORP 指標**不可能比錨點更準**。
  這裡要回答的是比較溫和的問題：**ORP 能不能追上趨勢**。

目標值怎麼算（只用排氣瞬間，不用拖尾）

  兩次排氣之間沒有再排氣，CH4 只進不出（甲烷幾乎不溶），所以

      CH4 累積量 = x_CH4(下次排氣前)·P_abs − x_CH4(本次排氣後)·P_abs

  補氣只加 CO2+H2、不含 CH4，故**補氣不改變 p_CH4**，不需要修正。
  ⚠ 這是「淨累積」，是真實產量的下界（已量到有未解釋的 CH4 消失途徑）。

誠實的比較基準

  ORP 只有在**贏過「直接用壓力」**時才有價值。所以三個模型都做留一交叉驗證：
      只用壓力 / 只用 ORP / 兩者都用
  留一驗證是必要的：樣本只有三十幾個，不留一就會被過度擬合騙。

輸出 -> docs/analysis_charts_3batch/orp_calibration.csv
        docs/analysis_charts_3batch/fig40_orp_calibration.png
"""
import csv
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                          # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # research/
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (                      # noqa: E402
    BLUE, YELLOW, AQUA, RED, INK, INK2, MUTED, BASELINE, OUT, style)
from ph_orp_discriminator import (                       # noqa: E402
    PH_FAULT, descents, load_full)
from shape_clustering import GAPH, RISE                  # noqa: E402

ATM = 1.033
MIN_COV = 0.80        # 兩次排氣之間的資料覆蓋率下限
NAMES = ['只用壓力', '只用 ORP', '兩者都用']


def load_with_gas():
    """在 ph_orp_discriminator.load_full 之外，另外取 CO2/CH4（排氣瞬間才可信）。"""
    import glob
    from datetime import datetime
    from shape_clustering import FOLDERS
    rows = {}
    for f in FOLDERS:
        for path in sorted(glob.glob(os.path.join(REPO, 'research', 'Testing_data',
                                                  f, '**', '*.csv'), recursive=True)):
            with open(path, encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    q = line.strip().split(',')
                    if len(q) < 14:
                        continue
                    try:
                        t = datetime(int(q[0]), int(q[1]), int(q[2]),
                                     int(q[3]), int(q[4]), int(float(q[5])))
                        v = (float(q[11]), float(q[7]), float(q[9]),
                             float(q[12]), float(q[13]))
                    except (ValueError, IndexError):
                        continue
                    rows.setdefault(t, v)
    ts = sorted(rows)
    a = np.array([rows[t] for t in ts], float)
    hh = np.array([(t - ts[0]).total_seconds() / 3600.0 for t in ts])
    return ts, hh, a[:, 0], -np.abs(a[:, 1]), a[:, 2], a[:, 3], a[:, 4]


def find_vents(ts, hh, p, co2, ch4):
    """排氣事件＝CH4 由拖尾水準突然躍升，且同時讀到 CO2。"""
    return [i for i in range(2, len(ts) - 1)
            if ch4[i] > 10 and ch4[i - 1] < 5 and (ch4[i] - ch4[i - 1]) > 8
            and (hh[i] - hh[i - 1]) < 0.05 and 1 < co2[i] < 60 and ch4[i] < 90]


def loo_r2(X, y):
    """留一交叉驗證的 R²（線性最小平方，含截距）。

    ⚠ 只有三十幾個樣本，不留一就會被過度擬合騙：同一批資料擬合再評分
      一定好看，但預測新資料時沒有用。
    """
    n = len(y)
    pred = np.zeros(n)
    for i in range(n):
        m = np.ones(n, bool)
        m[i] = False
        A = np.column_stack([np.ones(m.sum()), X[m]])
        beta, *_ = np.linalg.lstsq(A, y[m], rcond=None)
        pred[i] = float(np.r_[1.0, X[i]] @ beta)
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return 1 - ss_res / ss_tot, pred


def main():
    ts, hh, p, orp, ph, co2, ch4 = load_with_gas()
    ph = np.where(ph > PH_FAULT, np.nan, ph)
    ev = find_vents(ts, hh, p, co2, ch4)
    print('合併去重後 %d 筆　排氣錨點 %d 個（%s ~ %s）'
          % (len(ts), len(ev), ts[ev[0]].date(), ts[ev[-1]].date()))

    segs = descents(hh, p)
    seg_start = np.array([s for s, e in segs])

    rows = []
    for k in range(len(ev) - 1):
        a, b = ev[k], ev[k + 1]
        j = min(len(ts) - 1, a + 6)
        ia = a + int(np.argmin(p[a:j + 1]))          # 排氣後最低點
        ib = b - 1                                   # 下次排氣前一筆
        if ib <= ia:
            continue
        dth = hh[ib] - hh[ia]
        if dth < 24:                                 # 太短的區間不用
            continue
        cov = (ib - ia) / (dth * 60)
        if cov < MIN_COV:
            continue
        # 目標：CH4 淨累積速率（補氣不含 CH4，故不需修正）
        q0 = ch4[a] / 100 * (p[ia] + ATM)
        q1 = ch4[b] / 100 * (p[ib] + ATM)
        y = (q1 - q0) / dth

        inner = [(s, e) for s, e in segs if s >= ia and e <= ib]
        if len(inner) < 3:
            continue
        # 壓力側特徵
        rate = float(np.median([(p[s] - p[e]) / (hh[e] - hh[s]) for s, e in inner]))
        ncyc = len(inner) / dth * 24                 # 每天幾個循環
        # ORP 側特徵
        o = orp[ia:ib + 1]
        o_mean = float(np.mean(o))
        exc = []
        for s, e in inner:
            t_ = hh[s:e + 1]
            v_ = orp[s:e + 1]
            if len(t_) > 20 and t_.std() > 0:
                exc.append(float(np.polyfit(t_ - t_[0], v_, 1)[0] * (t_[-1] - t_[0])))
        if not exc:
            continue
        o_exc = float(np.median(exc))                # 每個循環 ORP 走多少
        o_flux = o_exc * len(inner) / dth            # 單位時間的 ORP 位移
        rows.append(dict(t0=ts[ia], t1=ts[ib], dth=dth, cov=cov, n=len(inner),
                         y=y, rate=rate, ncyc=ncyc,
                         o_mean=o_mean, o_exc=o_exc, o_flux=o_flux))

    print('可用區間 %d 個（覆蓋率 ≥%.0f%%、≥24 hr、≥3 個循環）' % (len(rows), MIN_COV * 100))
    if len(rows) < 12:
        print('⚠ 樣本太少，以下結果僅供參考')
    y = np.array([r['y'] for r in rows])
    print('目標（CH4 淨累積速率）中位 %.5f kgf/cm²/hr　IQR [%.5f, %.5f]　為負的比例 %.0f%%'
          % (np.median(y), *np.percentile(y, [25, 75]), (y < 0).mean() * 100))

    Xp = np.column_stack([[r['rate'] for r in rows], [r['ncyc'] for r in rows]])
    Xo = np.column_stack([[r['o_mean'] for r in rows], [r['o_flux'] for r in rows]])
    Xb = np.column_stack([Xp, Xo])

    print('\n══ 留一交叉驗證：誰預測得比較準 ══')
    print('   R² ≤ 0 代表「還不如直接猜平均值」')
    res = {}
    for nm, X in zip(NAMES, (Xp, Xo, Xb)):
        r2, pred = loo_r2(X, y)
        res[nm] = (r2, pred)
        print('   %-10s 留一 R² = %+.3f' % (nm, r2))

    best = max(res, key=lambda k: res[k][0])
    print('\n   最好的是「%s」' % best)
    if res['只用 ORP'][0] <= res['只用壓力'][0]:
        print('   -> ⚠ ORP 沒有贏過壓力：以目前的錨點與特徵，ORP 不值得當獨立指標')
    else:
        print('   -> ORP 贏過壓力，值得往下做')
    if res['兩者都用'][0] <= max(res['只用壓力'][0], res['只用 ORP'][0]):
        print('   -> 兩者合用沒有更好（樣本少時多加變數反而更差，這是正常的）')

    print('\n══ 個別相關（供診斷，不是結論）══')
    for nm in ('rate', 'ncyc', 'o_mean', 'o_exc', 'o_flux'):
        v = np.array([r[nm] for r in rows])
        rr = float(np.corrcoef(v, y)[0, 1])
        rng = np.random.default_rng(0)
        pv = float(np.mean([abs(np.corrcoef(rng.permutation(v), y)[0, 1]) >= abs(rr)
                            for _ in range(5000)]))
        print('   %-8s vs CH4 累積速率　相關 %+.3f　p = %.3f' % (nm, rr, pv))

    make_figure(rows, y, res)
    path = os.path.join(OUT, 'orp_calibration.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['起', '迄', '時數', '覆蓋', '循環數', 'CH4累積速率',
                    '壓降速率中位', '每日循環數', 'ORP平均', 'ORP每循環位移', 'ORP通量'])
        for r in rows:
            w.writerow([r['t0'].strftime('%Y-%m-%d %H:%M'), r['t1'].strftime('%Y-%m-%d %H:%M'),
                        round(r['dth'], 1), round(r['cov'], 3), r['n'], round(r['y'], 6),
                        round(r['rate'], 5), round(r['ncyc'], 2), round(r['o_mean'], 1),
                        round(r['o_exc'], 1), round(r['o_flux'], 3)])
    print('\n逐區間明細 -> %s（%d 列）' % (os.path.relpath(path, REPO), len(rows)))


def make_figure(rows, y, res):
    fig, axes = plt.subplots(1, 3, figsize=(14.5, 4.6), gridspec_kw={'wspace': 0.32})
    COLS = {NAMES[0]: MUTED, NAMES[1]: BLUE, NAMES[2]: RED}

    ax = axes[0]
    ax.bar(range(3), [res[n][0] for n in NAMES],
           color=[COLS[n] for n in NAMES], alpha=0.85, lw=0, width=0.6)
    ax.axhline(0, color=INK, lw=1.4)
    for i, n in enumerate(NAMES):
        v = res[n][0]
        ax.text(i, v + (0.03 if v >= 0 else -0.03), '%+.2f' % v, ha='center',
                va='bottom' if v >= 0 else 'top', fontsize=10, color=INK)
    ax.set_xticks(range(3))
    ax.set_xticklabels(NAMES)
    ax.text(0.03, 0.04, '0 這條線 = 跟「直接猜平均值」一樣好\n低於 0 = 比猜平均值還差',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='bottom')
    style(ax, 'a　預測沒看過的區間，誰比較準', None, '留一交叉驗證 R²')

    ax = axes[1]
    for n in NAMES:
        ax.scatter(y, res[n][1], s=34, color=COLS[n], alpha=0.7, lw=0, label=n)
    lim = [min(y.min(), min(res[n][1].min() for n in NAMES)),
           max(y.max(), max(res[n][1].max() for n in NAMES))]
    ax.plot(lim, lim, color=INK, lw=1.2, ls='--')
    ax.legend(loc='upper left', fontsize=9, frameon=False)
    ax.text(0.97, 0.04, '點落在虛線上 = 預測準', transform=ax.transAxes,
            fontsize=9, color=INK2, ha='right', va='bottom')
    style(ax, 'b　預測值 vs 實際值', '實際的甲烷累積速率', '預測的甲烷累積速率')

    ax = axes[2]
    v = np.array([r['o_flux'] for r in rows])
    ax.scatter(v, y, s=34, color=BLUE, alpha=0.7, lw=0)
    b, a0 = np.polyfit(v, y, 1)
    xs = np.linspace(v.min(), v.max(), 20)
    ax.plot(xs, a0 + b * xs, color=INK, lw=2)
    ax.axhline(0, color=BASELINE, lw=1)
    ax.text(0.03, 0.06, 'ORP 每單位時間走了多少（往更還原為負）對上甲烷累積\n'
                        '相關 %+.2f　⚠ 但它與「每天幾個循環」相關 −0.88，\n'
                        '　 控制掉之後偏相關只剩 −0.10'
            % float(np.corrcoef(v, y)[0, 1]),
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='bottom')
    style(ax, 'c　ORP 的位移與甲烷累積有關嗎', 'ORP 每小時位移 (mV/hr)', '甲烷累積速率')

    out = os.path.join(OUT, 'fig40_orp_calibration.png')
    fig.savefig(out)
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
