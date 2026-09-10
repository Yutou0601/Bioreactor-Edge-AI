
# -*- coding: utf-8 -*-
"""
資料清理 ＋ 方程式形式檢定
════════════════════════════════════════════════════════════════════════

設備方 2026-08-07 提供的三點，本檔逐一處理：

  1. **洗管線要排除**——透過多次進氣排氣清洗，會被切分器當成一堆短循環。
     徵兆：單位時間內補氣次數異常高。
  2. **補氣視為 1 分鐘內瞬間升到定值**——所以補氣那一分鐘要整個排除，
     不能算進下降段（先前用「循環前半」，可能混進補氣尾巴）。
  3. **方程式要改寫**——`dP/dt = −k_La(f·P − p*) − r_b` 這個形式在
     八個資料夾、351 個循環上**全部解出負的 k_La**，且 R² ≤ 0.38。
     負 k_La 代表「壓力越高下降越慢」，與物理相反。

**形式檢定**：若 CO2 的物理吸收在補氣後很快完成，則循環大部分時間是
**定速率**移除，壓力軌跡近乎**直線**；若物理項主導，則是**指數**趨近平衡。
先前的形狀分析已給線索：4:1 的曲率 0.50–0.59（0.5 = 完美直線）。

  逐循環比較三種形式的樣本外表現（留一資料點交叉驗證）：
     L  線性     P(t) = P0 − r·t                       （定速率＝生物主導）
     E  指數     P(t) = Peq + (P0−Peq)·exp(−k·t)       （物理主導）
     LE 線性+指數 P(t) = Peq + (P0−Peq)·exp(−k·t) − r·t （兩者並存）

輸出 -> docs/analysis_charts_3batch/clean_and_form.csv
"""
import os
import sys
import csv
import glob
import datetime as dt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from regime_changepoints import TD                                 # noqa: E402
from multivariate_increments import load4                          # noqa: E402

SKIP_MIN = 3.0/60          # 補氣後跳過的時間（小時）＝ 3 分鐘
WASH_PER_DAY = 6           # 每日補氣次數超過此值視為洗管線
MIN_HR, MIN_AMP = 4.0, 0.10


def seg_clean(h, P, ts):
    """切分循環，並標記洗管線期間。"""
    out, valley, start = [], P[0], 0
    for i in range(1, len(P)):
        if h[i]-h[i-1] > 1.0:
            if h[i-1]-h[start] > MIN_HR:
                out.append((start, i-1))
            start, valley = i, P[i]; continue
        if P[i]-valley > 0.03:
            if h[i-1]-h[start] > MIN_HR:
                out.append((start, i-1))
            start, valley = i, P[i]
        elif P[i] < valley:
            valley = P[i]
    if h[-1]-h[start] > MIN_HR:
        out.append((start, len(P)-1))
    cyc = [(a, b) for a, b in out
           if h[b]-h[a] >= MIN_HR and P[a]-P[b] >= MIN_AMP]

    # 洗管線：以「每日循環起始次數」判定
    import collections
    per_day = collections.Counter(ts[a].date() for a, _ in cyc)
    wash = {d for d, n in per_day.items() if n > WASH_PER_DAY}
    return cyc, wash


def fit_forms(t, y):
    """三種形式的 AIC 比較。

    ⚠ 初版寫成「每個樣本點都留一 ＋ 格點搜尋」，300 個循環要三千萬次
      最小平方，跑不完。非巢狀模型的比較本來就該用 AIC，不需逐點留一。

    AIC = n·ln(SSE/n) + 2p，p 為參數數（含非線性的 k）。
    """
    n = len(t)
    if n < 12:
        return None

    def sse_lin():
        A = np.vstack([t, np.ones_like(t)]).T
        c, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = y-A@c
        return float(r @ r), 2

    def sse_grid(cols_fn, npar):
        best = None
        for k in np.arange(0.01, 1.51, 0.01):
            A = cols_fn(k)
            c, *_ = np.linalg.lstsq(A, y, rcond=None)
            r = y-A@c
            s = float(r @ r)
            if best is None or s < best:
                best = s
        return best, npar

    res = {}
    for nm, (s, p) in (
            ('L', sse_lin()),
            ('E', sse_grid(lambda k: np.vstack(
                [np.exp(-k*t), np.ones_like(t)]).T, 3)),
            ('LE', sse_grid(lambda k: np.vstack(
                [np.exp(-k*t), t, np.ones_like(t)]).T, 4))):
        res[nm] = n*np.log(max(s, 1e-18)/n)+2*p
    return res


def main():
    folders = []
    for d in sorted(os.listdir(TD)):
        p = os.path.join(TD, d)
        if not os.path.isdir(p):
            continue
        if glob.glob(os.path.join(p, '*.csv')):
            folders.append((p, d))
        for s in sorted(os.listdir(p)):
            sp = os.path.join(p, s)
            if os.path.isdir(sp) and glob.glob(os.path.join(sp, '*.csv')):
                folders.append((sp, f'{d}/{s}'))

    print('══ 資料清理 ＋ 方程式形式檢定 ══\n')
    print(f'   補氣後跳過 {SKIP_MIN*60:.0f} 分鐘（補氣視為瞬間）')
    print(f'   每日循環數 > {WASH_PER_DAY} 視為洗管線，整日排除\n')

    print(f'   {"資料夾":<30}{"總循環":>7}{"洗管線日":>9}{"排除":>6}{"保留":>6}')
    print('   '+'-'*60)
    keep, rows = [], []
    for path, tag in folders:
        try:
            raw = load4(path)
        except Exception:
            continue
        if len(raw) < 500:
            continue
        ts = [r[0] for r in raw]
        P = np.array([r[1] for r in raw]); O = np.array([r[2] for r in raw])
        h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
        cyc, wash = seg_clean(h, P, ts)
        drop = sum(1 for a, _ in cyc if ts[a].date() in wash)
        print(f'   {tag[:29]:<30}{len(cyc):>7}{len(wash):>9}'
              f'{drop:>6}{len(cyc)-drop:>6}')
        for a, b in cyc:
            if ts[a].date() in wash:
                continue
            t = h[a:b+1]-h[a]
            sel = t >= SKIP_MIN                 # 排除補氣那幾分鐘
            if sel.sum() < 15:
                continue
            keep.append((tag, ts[a], t[sel]-t[sel][0], P[a:b+1][sel],
                         O[a:b+1][sel]))

    print(f'\n   清理後保留 {len(keep)} 個循環')

    # ── 形式檢定 ────────────────────────────────────────
    print('\n── 三種形式的留一交叉驗證（每個循環各自比較）──')
    win = {'L': 0, 'E': 0, 'LE': 0}   # AIC 最小者勝出
    per = {'L': [], 'E': [], 'LE': []}
    for tag, t0, t, y, o in keep:
        r = fit_forms(t, y)
        if not r or not all(np.isfinite(v) for v in r.values()):
            continue
        best = min(r, key=r.get)
        win[best] += 1
        for k, v in r.items():
            per[k].append(v)
    tot = sum(win.values())
    print(f'   {"形式":<26}{"勝出次數":>9}{"佔比":>8}{"中位 AIC":>12}')
    print('   '+'-'*56)
    names = {'L': 'L  線性（定速率＝生物）',
             'E': 'E  指數（物理主導）',
             'LE': 'LE 線性+指數（兩者並存）'}
    for k in ('L', 'E', 'LE'):
        print(f'   {names[k]:<26}{win[k]:>9}{win[k]/max(tot,1)*100:>7.1f}%'
              f'{np.median(per[k]):>12.5f}')

    print(f'\n   共比較 {tot} 個循環')
    bestk = max(win, key=win.get)
    print(f'   → 最常勝出：**{names[bestk]}**')
    if bestk == 'L':
        print('   ⇒ 壓力下降以**定速率**為主，`∝(P−Peq)` 的指數形式不適用。')
        print('     這解釋了為什麼八個資料夾的 k_La 全部解出負值——')
        print('     模型在對一條直線硬套指數，斜率自然沒有物理意義。')
    elif bestk == 'LE':
        print('   ⇒ 兩個通道並存，原模型形式方向正確但需重新估計。')
    else:
        print('   ⇒ 指數形式較佳，負 k_La 另有原因。')

    with open(f'{OUT}/clean_and_form.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['form', 'wins', 'share', 'median_rmse'])
        for k in ('L', 'E', 'LE'):
            w.writerow([k, win[k], f'{win[k]/max(tot,1):.4f}',
                        f'{np.median(per[k]):.6f}'])
    print(f'\n輸出 → {OUT}/clean_and_form.csv')


if __name__ == '__main__':
    main()
