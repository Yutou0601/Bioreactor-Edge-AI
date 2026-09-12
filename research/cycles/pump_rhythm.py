
# -*- coding: utf-8 -*-
"""小時內的節奏：循環泵在壓力資料裡看得見，而且泵運轉時間＝τ。

2026-09-12。做「小時的細微尺度」分析時發現的。

════════════════════════════════════════════════════════════════════════
結論

把 τ 三批的壓力變化依「小時內第幾分鐘」分組疊加，會出現極強的固定節奏：

    批次    驟降尖峰      回升尖峰      間距    宣稱 τ
    tau1    第 50 分      第 51 分      1 分      1
    tau5    第 25 分      第 30 分      5 分      5
    tau10   第 13 分      第 23 分     10 分     10

**間距與各批宣稱的 τ 完全一致**（相關 1.0000、迴歸斜率 1.000、截距 0.000）。
τ 的定義就是「每小時循環幾分鐘」，所以這個訊號確認來自**循環泵**。

⚠ 更重要的是佔比：泵只運轉每小時的 1.7 ~ 17% 時間，卻造成

    tau1   37%
    tau5   85%
    tau10  65%

的總壓降。以 tau10 為例，泵運轉時的下降速率約是停機時的 **9 倍**。

════════════════════════════════════════════════════════════════════════
⚠ 為什麼這件事值得記下來

論文的估計器把每段下降當成平滑的連續弛豫來擬合
（P = P_eq + A·e^{−kt} − r_b·t）。但實際的過程是**每小時一次的脈衝**：
泵一開，氣體被大量帶進液相；泵一停，壓力部分回升。平滑曲線是那串脈衝的
包絡線，不是底層機制。

這不代表擬合是錯的——在遠長於一小時的時間尺度上，包絡線仍然有意義。但它
說明了兩件事：

  1. **小時以下的尺度沒有「生物速率」可言**，那個尺度上看到的全是泵。
     這與 hourly_resolution.py 的結論一致（CH4 歸因最短需約 2 天）。
  2. τ 這個槓桿之所以有效，機制是清楚的：**泵運轉時間直接決定氣液接觸
     時間**，而壓降的六成以上發生在那段時間裡。

⚠ 偵測方式不要用「超過門檻幾倍」的做法。泵開瞬間的尖峰極大（tau10 是
  平均的 23 倍），會把標準差或 MAD 撐大，結果門檻只抓得到尖峰那一分鐘。
  正確做法是找**驟降尖峰與回升尖峰的位置**，兩者間距就是運轉時間。
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

FOLDER = '202607至08最新循環研究'

# 三批的期間與宣稱的 τ（每小時循環幾分鐘）
BATCHES = [
    ('tau1', 1, dt.date(2026, 7, 22), dt.date(2026, 7, 26)),
    ('tau5', 5, dt.date(2026, 7, 27), dt.date(2026, 7, 29)),
    ('tau10', 10, dt.date(2026, 7, 30), dt.date(2026, 8, 3)),
]

REFILL_RISE = 0.03        # 單步跳升超過此值視為補氣，要排除


def load():
    from core.cycle_store import read_series_full
    d = os.path.join(REPO, 'research', 'Testing_data', FOLDER)
    got = read_series_full(sorted(glob.glob(os.path.join(d, '*.csv'))))
    if got is None:
        raise SystemExit('讀不到資料：%s' % d)
    ts, h, p, temp, co2, ch4 = got
    return ts, np.asarray(h), np.asarray(p)


def minute_profile(ts, h, p, d0, d1):
    """依「小時內第幾分鐘」疊加每分鐘的壓降。回傳長度 60 的陣列。"""
    m = np.array([d0 <= t.date() <= d1 for t in ts])
    ix = np.flatnonzero(m)
    by = [[] for _ in range(60)]
    for j in range(1, len(ix)):
        a, b = ix[j - 1], ix[j]
        dtr = h[b] - h[a]
        if not (0.008 < dtr < 0.03):        # 只用間隔約一分鐘的相鄰筆
            continue
        if p[b] - p[a] > REFILL_RISE:       # 補氣不算
            continue
        by[ts[b].minute].append(p[a] - p[b])
    mu = np.array([np.mean(v) if len(v) > 5 else 0.0 for v in by])
    n = np.array([len(v) for v in by])
    se = np.array([np.std(v, ddof=1) / np.sqrt(len(v)) if len(v) > 2 else 0.0
                   for v in by])
    return mu, se, n


def pump_window(mu):
    """泵運轉窗口＝驟降尖峰到回升尖峰。

    ⚠ 不要用門檻法。開泵瞬間的尖峰極大，會把 SD／MAD 撐大，門檻只抓得到
      那一分鐘（實測 tau10 用 4×MAD 只抓到 2 分鐘，實際是 10 分鐘）。
    """
    on = int(np.argmax(mu))
    off = int(np.argmin(mu))
    return on, off, (off - on) % 60


def permutation_p(ts, h, p, d0, d1, n_iter=2000, seed=1):
    """把分鐘標籤打散，看實測的全日極差是否可能來自偶然。"""
    m = np.array([d0 <= t.date() <= d1 for t in ts])
    ix = np.flatnonzero(m)
    vals, labs = [], []
    for j in range(1, len(ix)):
        a, b = ix[j - 1], ix[j]
        dtr = h[b] - h[a]
        if not (0.008 < dtr < 0.03) or p[b] - p[a] > REFILL_RISE:
            continue
        vals.append(p[a] - p[b])
        labs.append(ts[b].minute)
    vals = np.array(vals)
    labs = np.array(labs)
    obs_mu = np.array([vals[labs == i].mean() if (labs == i).sum() else 0.0
                       for i in range(60)])
    obs = obs_mu.max() - obs_mu.min()
    rng = np.random.default_rng(seed)
    hit = 0
    for _ in range(n_iter):
        q = rng.permutation(labs)
        mm = np.array([vals[q == i].mean() if (q == i).sum() else 0.0
                       for i in range(60)])
        if mm.max() - mm.min() >= obs:
            hit += 1
    return obs, hit / n_iter


def main():
    ts, h, p = load()
    print('讀入 %d 筆　%s ~ %s\n' % (len(ts), ts[0].date(), ts[-1].date()))

    print('── 泵運轉窗口 vs 宣稱的 τ ──')
    print('%-7s %6s %14s %14s %7s %6s %14s' %
          ('批次', '宣稱τ', '驟降尖峰', '回升尖峰', '間距', '一致', '泵期間佔壓降'))
    claimed, detected = [], []
    profiles = {}
    for nm, tau, d0, d1 in BATCHES:
        mu, se, n = minute_profile(ts, h, p, d0, d1)
        profiles[nm] = (mu, se, n)
        on, off, gap = pump_window(mu)
        win = [(on + k) % 60 for k in range(gap)]
        tot = mu.sum()
        w = sum(mu[i] for i in win)
        ok = '✓' if abs(gap - tau) <= 1 else '✗'
        print('%-7s %6d  第%2d分 %+.3f  第%2d分 %+.3f %5d分 %6s %10.0f%%'
              % (nm, tau, on, mu[on], off, mu[off], gap, ok,
                 w / tot * 100 if tot else 0))
        claimed.append(tau)
        detected.append(gap)

    x, y = np.array(claimed, float), np.array(detected, float)
    sl, ic = np.polyfit(x, y, 1)
    print('\n   宣稱 %s vs 實測 %s' % (list(map(int, x)), list(map(int, y))))
    print('   相關 %.4f　迴歸斜率 %.3f　截距 %.3f'
          % (np.corrcoef(x, y)[0, 1], sl, ic))

    print('\n── 節奏是真的嗎（置換檢定：打散分鐘標籤）──')
    for nm, tau, d0, d1 in BATCHES:
        obs, pv = permutation_p(ts, h, p, d0, d1)
        print('   %-7s 實測全日極差 %.4f　p = %.4f %s'
              % (nm, obs, pv, '← 顯著' if pv < 0.05 else ''))

    print('\n── tau10 的逐分鐘剖面（最清楚的一批）──')
    mu, se, n = profiles['tau10']
    print('   %4s %10s %9s %6s' % ('分', '平均壓降', '標準誤', 'n'))
    on, off, gap = pump_window(mu)
    for i in range(60):
        mark = ''
        if i == on:
            mark = '  ← 泵開'
        elif i == off:
            mark = '  ← 泵停'
        elif (i - on) % 60 < gap:
            mark = '  ｜'
        if abs(mu[i]) > 0.002 or mark:
            print('   %4d %+10.4f %9.4f %6d%s' % (i, mu[i], se[i], n[i], mark))

    print('\n── 泵開 vs 泵停的速率差 ──')
    for nm, tau, d0, d1 in BATCHES:
        mu, se, n = profiles[nm]
        on, off, gap = pump_window(mu)
        win = [(on + k) % 60 for k in range(gap)]
        rest = [i for i in range(60) if i not in win]
        r_on = sum(mu[i] for i in win) / (gap / 60.0)
        r_off = sum(mu[i] for i in rest) / ((60 - gap) / 60.0)
        print('   %-7s 泵開 %.4f　泵停 %.4f　倍率 %.1f×'
              % (nm, r_on, r_off, r_on / r_off if r_off else float('nan')))


if __name__ == '__main__':
    main()
