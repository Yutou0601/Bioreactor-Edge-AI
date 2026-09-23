# -*- coding: utf-8 -*-
"""用「曲線彎不彎」把所有下降週期分群 —— 彎曲是物理溶解的指紋。

2026-09-21。使用者建議：用彎曲程度做進一步的分群。

════════════════════════════════════════════════════════════════════════
為什麼彎曲程度是對的切入點

  論文的壓降模型是兩項相加：

      P(t) = P_eq + A·e^(−kt)  −  r_b·t
                    ╰────┬───╯     ╰──┬──╯
                   氣體溶入液體      定速移除
                   會「彎」          完全不彎（直線）

  指數項隨時間變慢，畫出來是**向下凸的彎曲**；定速移除項畫出來是**直線**。
  所以一條下降曲線彎得越厲害，代表溶解佔得越多；越直，代表定速移除佔得越多。
  **彎曲程度是可以直接看的物理/生物指紋，不需要擬合任何參數。**

  ⚠ 但要注意方向：只有「先快後慢」（向下凸）才是溶解的形狀。
    若量到「先慢後快」（向上凹），那兩項都解釋不了，是模型之外的東西。

做法（刻意不用抽象特徵，讓圖能直接看）

  1. 每條下降曲線在時間上拉成 0~1、在壓力上正規化成 1~0
     -> 完全的直線會變成 s(u) = 1 − u，與快慢和深淺無關，只剩「形狀」
  2. 直接對形狀向量分群（k-means），每群畫出自己的平均形狀
  3. 看各群是什麼時候、什麼條件下出現的

輸出 -> docs/analysis_charts_3batch/shape_clustering.csv
        docs/analysis_charts_3batch/fig36_shape_clusters.png
"""
import csv
import glob
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

ATM = 1.033
RISE = 0.03
GAPH = 0.05
NGRID = 40          # 形狀向量的長度
FOLDERS = ['old data', '0109-0123_H2_1CO2_1', '0301-0416_無循環與有循環_5mins',
           '0417-0427_有循環_10mins_74%', 'data', '20260727_1min_data',
           '202607至08最新循環研究', '0825-0831_氫氣不夠暫停進氣__自動化測試']


def load_all():
    """整個archive 合併；read_series_full 內部依時間戳去重（重複副本的教訓）。"""
    from core.cycle_store import read_series_full
    paths = []
    for f in FOLDERS:
        paths += sorted(glob.glob(os.path.join(REPO, 'research', 'Testing_data',
                                               f, '**', '*.csv'), recursive=True))
    ts, hh, p, temp, co2, ch4 = read_series_full(paths)
    g = lambda v: np.array([x if x is not None else 0.0 for x in v], float)
    return ts, np.asarray(hh, float), np.asarray(p, float), g(co2), g(ch4)


def descents(hh, p):
    segs, start, valley = [], 0, p[0]
    for i in range(1, len(p)):
        if hh[i] - hh[i - 1] > GAPH or p[i] - valley > RISE:
            if i - 1 > start:
                segs.append((start, i - 1))
            start, valley = i, p[i]
        elif p[i] < valley:
            valley = p[i]
    segs.append((start, len(p) - 1))
    # 排除撐不起形狀的段：太短、太淺、點太少
    return [(s, e) for s, e in segs
            if e - s >= 40 and p[s] - p[e] >= 0.10 and hh[e] - hh[s] >= 2.0]


def shape(hh, p, s, e, n=NGRID):
    """正規化形狀：時間拉成 0~1，壓力拉成 1~0。純直線 -> 1−u。"""
    t = hh[s:e + 1] - hh[s]
    y = p[s:e + 1]
    u = t / t[-1]
    v = (y - y[-1]) / (y[0] - y[-1])
    grid = np.linspace(0, 1, n)
    return np.interp(grid, u, v), grid


def bow(sv, grid):
    """彎曲量＝形狀與直線的平均落差。正 = 先快後慢（溶解的形狀）。"""
    return float(np.mean((1 - grid) - sv))


def kmeans(Z, k, seed=0, n_init=40):
    rng = np.random.default_rng(seed)
    best, best_sse = None, np.inf
    for _ in range(n_init):
        ctr = Z[rng.choice(len(Z), k, replace=False)]
        for _ in range(200):
            d = ((Z[:, None, :] - ctr[None, :, :]) ** 2).sum(2)
            lab = d.argmin(1)
            if len(set(lab)) < k:
                break
            new = np.array([Z[lab == j].mean(0) for j in range(k)])
            if np.allclose(new, ctr):
                break
            ctr = new
        d = ((Z[:, None, :] - ctr[None, :, :]) ** 2).sum(2)
        lab, sse = d.argmin(1), d.min(1).sum()
        if sse < best_sse:
            best, best_sse, bctr = lab, sse, ctr
    return best, bctr, best_sse


def main():
    ts, hh, p, c, m = load_all()
    segs = descents(hh, p)
    S, meta = [], []
    for s, e in segs:
        sv, grid = shape(hh, p, s, e)
        if not np.all(np.isfinite(sv)):
            continue
        S.append(sv)
        meta.append(dict(t0=ts[s], dur=hh[e] - hh[s], drop=p[s] - p[e],
                         rate=(p[s] - p[e]) / (hh[e] - hh[s]), p0=p[s],
                         bow=bow(sv, grid), co2=float(np.median(c[s:e + 1]))))
    S = np.array(S)
    grid = np.linspace(0, 1, NGRID)
    print('全archive 去重後可用下降週期 %d 條（%s ~ %s）'
          % (len(S), meta[0]['t0'].date(), meta[-1]['t0'].date()))

    bows = np.array([x['bow'] for x in meta])
    print('\n彎曲量（正 = 先快後慢，溶解的形狀；0 = 完全直線；負 = 先慢後快）')
    print('   中位 %+.4f　IQR [%+.4f, %+.4f]　為正的比例 %.0f%%'
          % (np.median(bows), *np.percentile(bows, [25, 75]), (bows > 0).mean() * 100))

    # ── 把彎曲量換算成「溶解佔多少」──
    #   兩項模型正規化後：s(u) = β·指數形狀(u) + (1−β)·(1−u)
    #   兩邊都減 (1−u) 再取平均 ->  彎曲量 = β × 純指數的彎曲量(kT)
    #   所以 β = 彎曲量 / 純指數彎曲量(kT)。⚠ 需要先知道 kT，這就是既有的簡併：
    #   同一個彎曲量，kT 取小 -> β 要很大；kT 取大 -> β 很小。故只能給對照表。
    def bow_exp(kT):
        e = (np.exp(-kT * grid) - np.exp(-kT)) / (1 - np.exp(-kT))
        return float(np.mean((1 - grid) - e))
    print('\n── 彎曲量換算成「溶解佔總壓降的比例」（對照表，因為需要先知道 kT）──')
    print('   %6s %14s %14s %14s' % ('kT', '純指數的彎曲量', '中位彎曲量對應', '第75百分位對應'))
    med, q75 = float(np.median(bows)), float(np.percentile(bows, 75))
    for kT in (0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0):
        be = bow_exp(kT)
        f = lambda b: ('%.0f%%' % (b / be * 100)) if b / be <= 1.2 else '>100%(不可能)'
        print('   %6.1f %14.4f %14s %14s' % (kT, be, f(med), f(q75)))
    print('   論文 k 中位 0.15 /hr、週期中位 10.2 hr -> kT ≈ 1.5')
    print('   -> 中位彎曲量 %+.4f 對應溶解僅佔 %.0f%%，其餘是定速移除'
          % (med, med / bow_exp(1.5) * 100))

    # ── 分群：直接對形狀向量 ──
    print('\n── 直接對「形狀」分群（不給任何標籤）──')
    for k in (2, 3, 4):
        lab, ctr, sse = kmeans(S, k)
        sizes = [int((lab == j).sum()) for j in range(k)]
        bw = [bow(ctr[j], grid) for j in range(k)]
        print('   k=%d　SSE %7.2f　各群 %s　平均彎曲量 %s'
              % (k, sse, sizes, ' '.join('%+.3f' % b for b in bw)))
    K = 3
    lab, ctr, _ = kmeans(S, K)
    order = np.argsort([bow(ctr[j], grid) for j in range(K)])[::-1]
    remap = {old: new for new, old in enumerate(order)}
    lab = np.array([remap[x] for x in lab])
    ctr = ctr[order]

    NAMES = ['最彎（先快後慢）', '接近直線', '反向彎（先慢後快）']
    print('\n── 三群各自是什麼 ──')
    print('   %-18s %5s %9s %9s %9s %9s'
          % ('群', '條數', '彎曲量', '速率中位', '時長中位', '起壓中位'))
    for j in range(K):
        ix = lab == j
        print('   %-18s %5d %+9.4f %9.4f %9.2f %9.2f'
              % (NAMES[j], ix.sum(), bow(ctr[j], grid),
                 np.median([meta[i]['rate'] for i in np.flatnonzero(ix)]),
                 np.median([meta[i]['dur'] for i in np.flatnonzero(ix)]),
                 np.median([meta[i]['p0'] for i in np.flatnonzero(ix)])))

    print('\n── 各群出現的年份（看是不是某個時期特有）──')
    years = sorted({x['t0'].strftime('%Y-%m') for x in meta})
    print('   %-18s %s' % ('群', '　'.join(y[2:] for y in years)))
    for j in range(K):
        row = []
        for y in years:
            tot = sum(1 for x in meta if x['t0'].strftime('%Y-%m') == y)
            n = sum(1 for i, x in enumerate(meta)
                    if x['t0'].strftime('%Y-%m') == y and lab[i] == j)
            row.append('%3.0f%%' % (n / tot * 100) if tot else '  -')
        print('   %-18s %s' % (NAMES[j], ' '.join(row)))

    make_figure(S, grid, lab, ctr, meta, NAMES, K)

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'shape_clustering.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['起始時刻', '群', '彎曲量', '時長hr', '降幅', '速率', '起壓', 'CO2中位'])
        for i, x in enumerate(meta):
            w.writerow([x['t0'].strftime('%Y-%m-%d %H:%M'), NAMES[lab[i]],
                        round(x['bow'], 5), round(x['dur'], 2), round(x['drop'], 3),
                        round(x['rate'], 5), round(x['p0'], 2), round(x['co2'], 2)])
    print('\n逐週期明細 -> %s（%d 列）' % (os.path.relpath(path, REPO), len(meta)))


def make_figure(S, grid, lab, ctr, meta, NAMES, K):
    COLS = [BLUE, MUTED, RED]
    fig = plt.figure(figsize=(13, 8.6))
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1], hspace=0.42, wspace=0.26)

    # (a) 三群的平均形狀
    ax = fig.add_subplot(gs[0, 0])
    ax.plot(grid, 1 - grid, color=INK, lw=1.4, ls='--', zorder=5)
    ax.text(0.30, 0.64, '完全的直線', color=INK, fontsize=9, ha='left', va='bottom')
    for j in range(K):
        ix = np.flatnonzero(lab == j)
        for i in ix[:70]:
            ax.plot(grid, S[i], color=COLS[j], lw=0.5, alpha=0.10)
        ax.plot(grid, ctr[j], color=COLS[j], lw=2.6,
                label='%s（%d 條）' % (NAMES[j], len(ix)))
    ax.legend(loc='upper right', fontsize=9, frameon=False)
    style(ax, 'a　把每條下降曲線拉成同樣大小後，形狀分成三群',
          '一個週期走完的進度', '壓力剩下多少（1 = 剛補完氣）')
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.03, 1.03)

    # (b) 與直線的落差（放大看）
    ax = fig.add_subplot(gs[0, 1])
    ax.axhline(0, color=INK, lw=1.4, ls='--')
    ax.text(0.99, 0.004, '完全的直線', color=INK, fontsize=9, ha='right', va='bottom')
    for j in range(K):
        d = ctr[j] - (1 - grid)
        ax.plot(grid, d, color=COLS[j], lw=2.6)
        ax.fill_between(grid, 0, d, color=COLS[j], alpha=0.16)
        k = int(NGRID * 0.62)
        # 標籤要離開曲線本身，否則字會壓在線上
        ax.text(grid[k], d[k] + (0.045 if d[k] >= 0 else -0.045), NAMES[j],
                color=COLS[j], fontsize=9, ha='center',
                va='bottom' if d[k] >= 0 else 'top')
    # ⚠ 方向不要寫反：落差 = 曲線 − 直線。落差為負 = 曲線在直線下方
    #   = 壓力比直線掉得更多 = 前段快後段慢 = 溶解的形狀。
    ax.text(0.02, 0.03, '在直線下方 = 前段掉得快、後段慢下來\n（氣體溶進液體會是這個樣子）',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='bottom')
    ax.text(0.02, 0.97, '在直線上方 = 前段慢、後段反而加快\n（兩項都解釋不了）',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='top')
    style(ax, 'b　把「彎多少」放大來看', '一個週期走完的進度', '與直線的落差')
    ax.set_xlim(0, 1)
    _lo, _hi = ax.get_ylim()                    # 上下各留給兩段說明文字
    ax.set_ylim(_lo - (_hi - _lo) * 0.30, _hi + (_hi - _lo) * 0.26)

    # (c) 彎曲量的分布
    ax = fig.add_subplot(gs[1, 0])
    bows = np.array([x['bow'] for x in meta])
    bins = np.linspace(np.percentile(bows, 1), np.percentile(bows, 99), 34)
    bot = np.zeros(len(bins) - 1)
    for j in range(K):
        h, _ = np.histogram(bows[lab == j], bins=bins)
        ax.bar(bins[:-1], h, width=np.diff(bins), bottom=bot, align='edge',
               color=COLS[j], alpha=0.85, lw=0)
        bot += h
    ax.axvline(0, color=INK, lw=1.4, ls='--')
    ax.set_ylim(0, ax.get_ylim()[1] * 1.32)     # ⚠ 先定軸再放字，順序反了字會掉進圖內
    # 靠左排，才不會撞到右上角的統計數字
    ax.text(-0.006, ax.get_ylim()[1] * 0.99, '完全的直線 ', color=INK, fontsize=9,
            ha='right', va='top')
    ax.text(0.98, 0.96,
            '像溶解的形狀 %.0f%%　反向的 %.0f%%\n中位 %+.3f：離直線很近'
            % ((bows > 0).mean() * 100, (bows <= 0).mean() * 100, np.median(bows)),
            transform=ax.transAxes, fontsize=9.5, color=INK2, ha='right', va='top')
    style(ax, 'c　每條曲線彎多少（共 %d 條）' % len(bows), '彎曲量', '週期數')

    # (d) 彎曲量隨時間
    ax = fig.add_subplot(gs[1, 1])
    tt = [x['t0'] for x in meta]
    for j in range(K):
        ix = np.flatnonzero(lab == j)
        ax.scatter([tt[i] for i in ix], bows[ix], s=14, color=COLS[j], alpha=0.65, lw=0)
    ax.axhline(0, color=INK, lw=1.2, ls='--')
    # 三個月滾動中位
    o = np.argsort(tt)
    w = max(9, len(o) // 20)
    roll = [np.median(bows[o[max(0, i - w):i + w]]) for i in range(len(o))]
    ax.plot([tt[i] for i in o], roll, color=INK, lw=2)
    days = np.array([(x['t0'] - meta[0]['t0']).total_seconds() / 86400 for x in meta])
    sl = float(np.polyfit(days, bows, 1)[0])
    rng = np.random.default_rng(3)
    pv = float(np.mean([abs(np.polyfit(days, rng.permutation(bows), 1)[0]) >= abs(sl)
                        for _ in range(2000)]))
    ax.text(0.02, 0.97, '黑線 = 滾動中位數\n一年來的趨勢 %+.1e /天，p = %.2f%s'
            % (sl, pv, '' if pv < 0.05 else '（看不出趨勢）'),
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='top')
    style(ax, 'd　彎曲量隨時間：一整年都貼著直線', None, '彎曲量')
    # ⚠ 不可用 fig.autofmt_xdate()：它會把**所有**子圖的 x 刻度標籤藏起來，
    #   (a)(b) 的 0~1 進度軸會整排消失。只動這一個軸。
    import matplotlib.dates as mdates
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    for t in ax.get_xticklabels():
        t.set_rotation(0)
        t.set_ha('center')

    out = os.path.join(OUT, 'fig36_shape_clusters.png')
    fig.savefig(out)
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
