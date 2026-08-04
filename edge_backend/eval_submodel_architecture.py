# -*- coding: utf-8 -*-
"""子模型->主模型架構的嚴格評估：留一 campaign 交叉驗證。

結論（2026-08-03）：在跨 campaign 的嚴格檢驗下，沒有任何 tau 模型能打贏
「取全體平均」的平凡基準。原因是同一 tau 的不同 campaign 之間差異
（tau=10 的兩段相差 62%）與 tau 效應本身（0->10 約 2 倍）同量級。
tau 模型僅在「同一段連續菌況」之內有預測力。

campaign = 一段固定循環時間、連續運轉的期間（共 6 段，橫跨 2026-03 ~ 08）。
留一 campaign 表示：模型完全沒看過該段的任何循環，也沒看過該菌況。
"""
import glob, os, sys
import numpy as np, pandas as pd
from scipy import optimize
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'c:/Users/lkkyb/OneDrive/Desktop/MIRDC/Bioreactor-Edge-AI/edge_backend')
os.chdir(r'c:/Users/lkkyb/OneDrive/Desktop/MIRDC/Bioreactor-Edge-AI/edge_backend')

from analyze_three_batches import BATCHES, load_all, load_txt, find_cycles

TD = 'Testing_data'
HIST = [('無循環', f'{TD}/0301-0416_無循環與有循環_5mins', 0.0, None, '2026-04-07'),
        ('歷史5min', f'{TD}/0301-0416_無循環與有循環_5mins', 5.0, '2026-04-07', None),
        ('歷史10min', f'{TD}/0417-0427_有循環_10mins_74%', 10.0, None, None)]


def folder(f):
    d = pd.concat([load_txt(p) for p in sorted(glob.glob(f'{f}/*.txt'))], ignore_index=True)
    return d.sort_values('ts').drop_duplicates('ts').reset_index(drop=True)


rows = []
for lab, f, tau, t0, t1 in HIST:
    d = folder(f)
    if t0: d = d[d.ts >= t0]
    if t1: d = d[d.ts < t1]
    for cyc, _ in find_cycles(d.reset_index(drop=True)):
        hrs = (cyc.ts.iloc[-1] - cyc.ts.iloc[0]).total_seconds() / 3600
        drop = cyc.p_reactor.iloc[0] - cyc.p_reactor.iloc[-1]
        if hrs >= 2 and 0.15 <= drop <= 0.90:
            rows.append(dict(camp=lab, tau=tau, start=cyc.ts.iloc[0], rate=drop / hrs))

new = load_all()
for name, (a, b, tau) in BATCHES.items():
    s = new[(new.ts >= a) & (new.ts <= b)].reset_index(drop=True)
    cy = find_cycles(s)
    for i, (cyc, _) in enumerate(cy):
        hrs = (cyc.ts.iloc[-1] - cyc.ts.iloc[0]).total_seconds() / 3600
        drop = cyc.p_reactor.iloc[0] - cyc.p_reactor.iloc[-1]
        if i != len(cy) - 1 and 0.15 <= drop <= 0.35 and hrs >= 2:
            rows.append(dict(camp=name, tau=tau, start=cyc.ts.iloc[0], rate=drop / hrs))

D = pd.DataFrame(rows)
D['day'] = D.groupby('camp').start.transform(lambda s: (s - s.min()).dt.total_seconds() / 86400)
print('資料總覽（6 個 campaign）：')
print(D.groupby(['camp', 'tau']).agg(n=('rate', 'size'), 天數=('day', 'max'),
                                     速率=('rate', 'mean')).round(3).to_string())
print(f'\n總循環數 n={len(D)}   全體 sd={D.rate.std():.4f}\n')

tau, day, y = D.tau.values, D.day.values, D.rate.values


def M0(p, t, d): return np.full_like(t, p[0])
def M1(p, t, d): return p[0] + p[1] * t / (p[2] + t)                    # 飽和 tau
def M2(p, t, d): return (p[0] + p[1] * t / (p[2] + t)) * np.exp(-p[3] * d)  # 飽和 x 衰減
def M3(p, t, d): return p[0] + p[1] / np.maximum(t, 0.5)               # 舊 1/tau


MODELS = {'M0 常數（平凡基準）': (M0, [0.02]),
          'M3 舊式 1/τ': (M3, [0.04, -0.02]),
          'M1 飽和型 τ': (M1, [0.02, 0.02, 3.0]),
          'M2 飽和型 τ × 菌況衰減': (M2, [0.02, 0.03, 3.0, 0.05])}


def fit(fn, p0, t, d, yy):
    r = optimize.least_squares(lambda p: fn(p, t, d) - yy, p0, max_nfev=20000)
    return r.x


print('留一 campaign 交叉驗證（模型完全沒看過該段的 τ 與菌況）：')
camps = D.camp.unique()
hdr = f'{"模型":26s}' + ''.join(f'{c[:9]:>11s}' for c in camps) + f'{"整體RMSE":>11s}'
print(hdr)
for name, (fn, p0) in MODELS.items():
    errs, per = [], []
    for c in camps:
        m = D.camp.values != c
        try:
            p = fit(fn, p0, tau[m], day[m], y[m])
            e = fn(p, tau[~m], day[~m]) - y[~m]
        except Exception:
            e = np.full((~m).sum(), np.nan)
        per.append(np.sqrt(np.nanmean(e ** 2)))
        errs.append(e)
    tot = np.sqrt(np.nanmean(np.concatenate(errs) ** 2))
    print(f'{name:26s}' + ''.join(f'{v:>11.4f}' for v in per) + f'{tot:>11.4f}')

print('\n各模型用全部資料擬合的參數與 in-sample R²：')
for name, (fn, p0) in MODELS.items():
    p = fit(fn, p0, tau, day, y)
    r2 = 1 - np.var(fn(p, tau, day) - y) / np.var(y)
    print(f'  {name:26s} R²={r2:.3f}  參數={np.round(p, 4)}')
