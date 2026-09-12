
# -*- coding: utf-8 -*-
"""細部（小時尺度）分析能做到什麼程度——以及做不到什麼。

2026-09-12。會議要「1hr / 2hr / 3hr 各能轉換多少氣體」，本檔回答那條線在
哪裡：哪些量在小時尺度上量得到、哪些不行、要多長的視窗才夠。

════════════════════════════════════════════════════════════════════════
結論摘要（詳細數字見 main() 的輸出）

  1 壓力／消耗：小時尺度**可用**。訊噪比 10.2。
  2 CH4 歸因　：小時尺度**不可用**。逐時波動 SD 0.0895 是每小時產甲烷量
                0.00191 的 47 倍，單小時訊噪比 0.02。最短需約 2 天。
  3 日夜效應　：**沒有證據**。置換檢定 p = 0.110，而且全日極差只有 1.2 個
                量化階。⚠ 用中位數做 Kruskal-Wallis 會得到 p = 0.000，
                那是假象——每小時消耗只有 2~3 個量化階，中位數只能取到
                0.0200／0.0250／0.0300 三個值。**效應量比顯著性重要。**

════════════════════════════════════════════════════════════════════════
⚠ 估計量的選擇（這一段是本檔最值得記住的部分）

要算一段期間「總共產生多少 CH4」，有三種做法，結果差很多：

    單筆端點      +36%          沒有誤差估計，且端點恰好是哪一筆全靠運氣
    兩端各 6 hr   +37% ± 1%     ← 正確做法
    兩端各 24 hr  +29% ± 2%     末端取太寬會把還在上升的曲線拉低
    迴歸 × 時長   +27%          ⚠ 軌跡彎曲時會低估

CH4 軌跡是**飽和曲線**（日增幅 +10.2 → +0.3），不是直線。對彎曲的資料配
直線再乘時長，算的不是總變化量。而「總變化量」正是我們要的——它就是頭空
裡 CH4 存量的變化。

所以用**兩端各取少數幾小時的平均**：夠降雜訊，又不會因為取太寬而咬到曲率。
K = 6 小時是實測的平衡點。
"""
import datetime as dt
import glob
import os
import sys

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # research/
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))

ATM = 1.033
QUANT = 0.01          # 壓力感測器量化階
FOLDER = '0825-0831_氫氣不夠暫停進氣__自動化測試'

PHASES = [
    ('建立期', dt.date(2026, 8, 11), dt.date(2026, 8, 23)),
    ('衰退期', dt.date(2026, 8, 26), dt.date(2026, 8, 30)),
]


def load():
    from core.cycle_store import read_series_full
    d = os.path.join(REPO, 'research', 'Testing_data', FOLDER)
    got = read_series_full(sorted(glob.glob(os.path.join(d, '*.csv'))))
    if got is None:
        raise SystemExit('讀不到資料：%s' % d)
    ts, h, p, temp, co2, ch4 = got
    a = np.array([v if v is not None else 0.0 for v in ch4])
    return ts, np.asarray(h), np.asarray(p), a


def descents(h, p):
    """以補氣為界切出下降段。

    ⚠ 消耗量不可用「所有負的相鄰差加總」——感測器有 ±0.01 抖動，一小時
      累加會得到 0.11，而實測速率只有 0.03。
    """
    segs, valley, start = [], p[0], 0
    for i in range(1, len(p)):
        if h[i] - h[i - 1] > 1.0 or p[i] - valley > 0.03:
            if i - 1 > start:
                segs.append((start, i - 1))
            start, valley = i, p[i]
        elif p[i] < valley:
            valley = p[i]
    segs.append((start, len(p) - 1))
    return [(s, e) for s, e in segs if e > s + 3 and p[s] > p[e]]


def hourly(ts, h, p, a, segs, d0=None, d1=None):
    """逐小時：消耗量與 CH4 分壓（都用小時內的平均／總和，不用單筆）。"""
    hr = np.floor(h).astype(int)
    sel = np.ones(len(ts), bool)
    if d0 is not None:
        sel = np.array([d0 <= t.date() <= d1 for t in ts])
    out = []
    for u in sorted(set(hr[sel])):
        idx = np.flatnonzero((hr == u) & sel)
        if len(idx) < 40:                 # 該小時資料不足，跳過
            continue
        cons = 0.0
        for s, e in segs:
            lo, hi = max(s, idx[0]), min(e, idx[-1])
            if hi > lo + 1 and p[lo] > p[hi]:
                cons += p[lo] - p[hi]
        out.append((u, ts[idx[0]], cons,
                    float((a[idx] / 100.0 * (p[idx] + ATM)).mean())))
    return out


def snr_report(ts, h, p, a):
    print('── 1  各量在小時尺度的訊噪比 ──')
    print('   訊號＝相鄰小時的真實變化；雜訊＝小時內散布 ÷ √n')
    hr = np.floor(h).astype(int)
    print('   %-6s %14s %12s %12s %8s' %
          ('量', '小時均值範圍', '小時間 SD', '小時內雜訊', '訊噪比'))
    for nm, x in (('壓力', p), ('CH4', a)):
        means, within = [], []
        for u in np.unique(hr):
            m = hr == u
            if m.sum() < 30:
                continue
            v = x[m]
            means.append(v.mean())
            within.append(v.std(ddof=1) / np.sqrt(len(v)))
        means = np.array(means)
        between = np.std(np.diff(means), ddof=1) / np.sqrt(2)
        noise = np.median(within)
        print('   %-6s %6.2f~%6.2f %12.4f %12.4f %8.1f'
              % (nm, means.min(), means.max(), between, noise, between / noise))


def ch4_limit(rows):
    """CH4 歸因需要多長的視窗。"""
    x = np.array([r[0] for r in rows], float)
    y = np.array([r[3] for r in rows])
    sl, ic = np.polyfit(x, y, 1)
    sd = (y - (sl * x + ic)).std(ddof=1)
    print('\n── 2  CH4 歸因的最短視窗 ──')
    print('   產甲烷趨勢 %.5f kg/cm²/hr；去趨勢後逐時波動 SD %.5f'
          % (sl, sd))
    print('   單小時訊噪比 %.2f　（波動是訊號的 %.0f 倍）'
          % (abs(sl) / sd, sd / abs(sl)))
    print('   %6s %10s %10s' % ('視窗hr', '兩端相減', '判定'))
    for W in (1, 3, 6, 12, 24, 48, 72, 120):
        snr = abs(sl) * W / (sd * np.sqrt(2))
        print('   %6d %10.2f %10s' % (W, snr, '可用' if snr >= 2 else ''))
    need = 2 * sd * np.sqrt(2) / abs(sl)
    print('   ★ 達訊噪比 2 需 %.0f 小時（%.1f 天）' % (need, need / 24))


def estimators(rows, label):
    """三種估計量的比較。"""
    y = np.array([r[3] for r in rows])
    cons = sum(r[2] for r in rows)
    x = np.array([r[0] for r in rows], float)
    n = len(y)
    print('\n   %s　n=%d 小時　總消耗 %.2f' % (label, n, cons))
    print('   %-16s %20s %12s' % ('估計量', 'CH4 產量', '生物份額'))
    g = y[-1] - y[0]
    print('   %-16s %+20.4f %11.0f%%' % ('單筆端點', g, g / cons / 0.25 * 100))
    for K in (6, 12, 24):
        if n < 3 * K:
            continue
        g = y[-K:].mean() - y[:K].mean()
        se = np.sqrt(y[-K:].var(ddof=1) / K + y[:K].var(ddof=1) / K)
        mark = '  ← 建議' if K == 6 else ''
        print('   %-16s %+13.4f ± %.4f %8.0f%% ± %.0f%%%s'
              % ('兩端各 %d hr' % K, g, se, g / cons / 0.25 * 100,
                 se / cons / 0.25 * 100, mark))
    sl, ic = np.polyfit(x, y, 1)
    g = sl * (x[-1] - x[0])
    print('   %-16s %+20.4f %11.0f%%   ⚠ 軌跡彎曲時低估'
          % ('迴歸 × 時長', g, g / cons / 0.25 * 100))


def diurnal(rows):
    """日夜效應——重點是效應量，不是 p 值。"""
    import collections
    by = collections.defaultdict(list)
    for u, t, c, f in rows:
        by[t.hour].append(c)
    mean = np.array([np.mean(by[k]) for k in range(24)])
    sem = np.array([np.std(by[k], ddof=1) / np.sqrt(len(by[k]))
                    for k in range(24)])
    rng = np.random.default_rng(0)
    allv = np.array([r[2] for r in rows])
    lab = np.array([r[1].hour for r in rows])
    obs = mean.max() - mean.min()
    null = np.array([
        (lambda m: m.max() - m.min())(
            np.array([allv[q == k].mean() for k in range(24)]))
        for q in (rng.permutation(lab) for _ in range(2000))])
    pv = (null >= obs).mean()
    print('\n── 3  日夜效應 ──')
    print('   全日平均範圍 %.4f ~ %.4f，極差 %.4f（＝%.1f 個量化階）'
          % (mean.min(), mean.max(), obs, obs / QUANT))
    print('   各時段標準誤中位 %.4f' % np.median(sem))
    print('   置換檢定 p = %.3f' % pv)
    print('   ★ %s' % ('沒有日夜效應的證據' if pv > 0.05 else
                       '置換顯著，但效應量僅約一個量化階，不宜解讀'))
    print('   ⚠ 用**中位數**做 Kruskal-Wallis 會得到 p = 0.000，那是假象：')
    print('     每小時消耗只有 2~3 個量化階，中位數只能取 0.0200／0.0250／')
    print('     0.0300 三個值。顯著性來自量化而非生理。')


def main():
    ts, h, p, a = load()
    segs = descents(h, p)
    print('讀入 %d 筆　%s ~ %s　切出 %d 個循環'
          % (len(ts), ts[0].date(), ts[-1].date(), len(segs)))
    print()
    snr_report(ts, h, p, a)

    allrows = hourly(ts, h, p, a, segs)
    build = hourly(ts, h, p, a, segs, *PHASES[0][1:])
    ch4_limit(build)

    print('\n── 4  總 CH4 產量的三種估計量 ──')
    for nm, d0, d1 in PHASES:
        estimators(hourly(ts, h, p, a, segs, d0, d1),
                   '%s %s~%s' % (nm, d0.strftime('%m/%d'), d1.strftime('%m/%d')))

    diurnal(allrows)

    print('\n── 5  逐循環（自動化的基本單位）──')
    amp = np.array([p[s] - p[e] for s, e in segs])
    dur = np.array([h[e] - h[s] for s, e in segs])
    print('   %d 個循環' % len(segs))
    for nm, v, f in (('振幅 kg/cm²', amp, '%.3f'),
                     ('時長 hr', dur, '%.2f'),
                     ('速率 kg/cm²/hr', amp / dur, '%.4f')):
        print(('   %-16s 中位 ' + f + '　四分位 ' + f + ' ~ ' + f)
              % (nm, np.median(v), np.percentile(v, 25), np.percentile(v, 75)))


if __name__ == '__main__':
    main()
