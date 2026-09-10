
# -*- coding: utf-8 -*-
"""
抖動式頂空體積量測（Dither Volumetry）
════════════════════════════════════════════════════════════════════════

`headspace_from_refill.py` 想用補氣的**上升速率**當體積訊號，被一分鐘取樣打敗
（補氣只持續 1–3 分鐘 ⇒ 只有 1–3 個點）。本檔換一條路，把量化從敵人變成工具。

**洞見一：量化＋隨機相位＝無偏**
補氣起點與取樣格點的相位是隨機的，真實歷時 τ 會被觀測成 floor(τ) 或 ceil(τ)，
比例由 frac(τ) 決定。故**觀測歷時的平均是 τ 的無偏估計**，
標準誤 ≤ 0.5/√n 分鐘。n=212 ⇒ SE ≈ 2 秒，比量化步階細 30 倍（dithering）。

**洞見二：該迴歸的是歷時對幅度，不是要求兩者獨立**
理想氣體 ＋ 定流量 ṅ：

    ΔP = ṅRT/V · Δt      ⇒      Δt = [V/(ṅRT)] · ΔP

**歷時對幅度的迴歸斜率 ∝ 頂空體積。** 先前把兩者的相關當成失敗，是診斷錯了。

設計：每期依幅度分箱 → 各箱以抖動取平均歷時（次量化精度）
→ 對「平均幅度」做過原點迴歸 → 斜率即體積代理。

輸出 -> docs/analysis_charts_3batch/dither_volumetry.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys
import csv
import datetime as dt

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from trigger_setpoint_tracker import load_events, merge_fragments  # noqa: E402

NBIN = 5
NBOOT = 3000
SAMP_MIN = 1.0      # 取樣間隔（分鐘）

ERAS = [('2025-08→09 調校期', dt.date(2025, 8, 1), dt.date(2025, 10, 1)),
        ('2025-10→12',       dt.date(2025, 10, 1), dt.date(2026, 1, 1)),
        ('2026-01→05',       dt.date(2026, 1, 1), dt.date(2026, 6, 1)),
        ('2026-07→08',       dt.date(2026, 7, 1), dt.date(2026, 9, 1))]


def prep():
    ev = merge_fragments(load_events())
    out = []
    for e in ev:
        dmin = (e['t_end']-e['t']).total_seconds()/60
        # merge_fragments 的 t_end 是最後一個片段的起點；補氣至少跨一個取樣間隔
        dmin = max(dmin, 0.0)+SAMP_MIN
        if e['amp'] <= 0:
            continue
        out.append(dict(t=e['t'], amp=e['amp'], dur=dmin))
    return out


def origin_slope(x, y, w=None):
    """過原點的加權最小平方斜率。"""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if w is None:
        w = np.ones_like(x)
    return float(np.sum(w*x*y)/np.sum(w*x*x))


def main():
    ev = prep()
    T = [e['t'] for e in ev]
    amp = np.array([e['amp'] for e in ev])
    dur = np.array([e['dur'] for e in ev])
    print('══ 抖動式頂空體積量測 ══')
    print(f'   補氣事件 {len(ev)} 個   {T[0].date()} → {T[-1].date()}\n')

    print('── 抖動的前提：觀測歷時是否真的落在相鄰整數上？──')
    frac = dur/SAMP_MIN
    isint = np.mean(np.abs(frac-np.round(frac)) < 1e-6)
    lv, cnt = np.unique(np.round(dur, 3), return_counts=True)
    print(f'   歷時落在整數分鐘的比例 {isint:.1%}')
    print(f'   前 6 個最常見歷時（分鐘）：'
          + '  '.join(f'{v:.0f}×{c}' for v, c in
                      zip(lv[np.argsort(-cnt)][:6], np.sort(cnt)[::-1][:6])))
    print(f'   ⇒ 單次觀測誤差 ≤ {SAMP_MIN/2:.1f} min；'
          f'n 次平均的 SE ≤ {SAMP_MIN/2:.2f}/√n')

    rows = []
    print('\n── 各期：歷時對幅度的迴歸（斜率 ∝ 頂空體積）──')
    rng = np.random.default_rng(89)
    for nm, a, b in ERAS:
        m = np.array([a <= t.date() < b for t in T])
        if m.sum() < 20:
            continue
        A, D = amp[m], dur[m]
        # 依幅度分箱，各箱取抖動平均
        qs = np.quantile(A, np.linspace(0, 1, NBIN+1))
        bx, by, bn, bse = [], [], [], []
        for i in range(NBIN):
            s = (A >= qs[i]) & (A < qs[i+1] if i < NBIN-1 else A <= qs[i+1])
            if s.sum() < 4:
                continue
            bx.append(A[s].mean())
            by.append(D[s].mean())
            bn.append(int(s.sum()))
            bse.append(D[s].std(ddof=1)/np.sqrt(s.sum()))
        if len(bx) < 3:
            continue
        bx, by = np.array(bx), np.array(by)
        w = 1/np.maximum(np.array(bse), 1e-6)**2
        sl = origin_slope(bx, by, w)
        # 自助
        boot = []
        idx = np.where(m)[0]
        for _ in range(NBOOT):
            k = rng.choice(idx, size=len(idx), replace=True)
            Ab, Db = amp[k], dur[k]
            q2 = np.quantile(Ab, np.linspace(0, 1, NBIN+1))
            xs, ys = [], []
            for i in range(NBIN):
                s = (Ab >= q2[i]) & (Ab < q2[i+1] if i < NBIN-1 else Ab <= q2[i+1])
                if s.sum() >= 4:
                    xs.append(Ab[s].mean()); ys.append(Db[s].mean())
            if len(xs) >= 3:
                boot.append(origin_slope(xs, ys))
        ci = np.quantile(boot, [.025, .975]) if boot else (np.nan, np.nan)
        print(f'\n   ▸ {nm}   n = {m.sum()}')
        print(f'     {"幅度箱中心":>12}{"平均歷時(min)":>15}{"n":>6}{"SE(min)":>10}')
        for x, y, nn, s in zip(bx, by, bn, bse):
            print(f'     {x:>12.3f}{y:>15.3f}{nn:>6}{s:>10.3f}')
        print(f'     過原點斜率 = {sl:.2f} min per kg/cm²'
              f'   95% CI [{ci[0]:.2f}, {ci[1]:.2f}]')
        rows.append((nm, m.sum(), sl, ci[0], ci[1]))

    if len(rows) >= 2:
        print('\n── 相對頂空體積（以第一個穩定期為基準）──')
        base = rows[1][2] if len(rows) > 1 else rows[0][2]
        print(f'   {"期間":<20}{"斜率":>9}{"95% CI":>20}{"相對 V":>10}')
        print('   '+'-'*60)
        for nm, nn, sl, lo, hi in rows:
            print(f'   {nm:<20}{sl:>9.2f}'
                  f'{f"[{lo:.2f}, {hi:.2f}]":>20}{sl/base:>10.2f}')
        print('\n   （斜率 = V/(ṅRT)。ṅ、T 不變時，斜率比 ＝ 頂空體積比。）')

        print('\n── 判定 ──')
        st = [r for r in rows if '調校' not in r[0]]
        if len(st) >= 2:
            sep = all(st[i][4] < st[j][3] or st[j][4] < st[i][3]
                      for i in range(len(st)) for j in range(i+1, len(st)))
            print(f'   穩定期之間的 CI {"互不重疊 ✓" if sep else "有重疊 ✘"}')
            if sep:
                print('   ⇒ 各期頂空體積確實不同，特徵可分辨製程狀態。')
            else:
                print('   ⇒ 無法分辨各期體積差異；'
                      '需要補氣期間 10 s 取樣才能提高解析度。')
        print('\n   ⚠ 前提：進氣流量 ṅ 與溫度 T 在期間內固定。'
              '若閥門開度或鋼瓶壓力有變，斜率變化不可歸因於體積。'
              '**此前提尚未經設備方確認。**')

    with open(f'{OUT}/dither_volumetry.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w_ = csv.writer(fh)
        w_.writerow(['era', 'n', 'slope_min_per_kgcm2', 'ci_lo', 'ci_hi'])
        for r in rows:
            w_.writerow([r[0], r[1], f'{r[2]:.4f}',
                         f'{r[3]:.4f}', f'{r[4]:.4f}'])
    print(f'\n輸出 → {OUT}/dither_volumetry.csv')


if __name__ == '__main__':
    main()
